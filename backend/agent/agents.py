"""
1. Multi-agent claims review + single-agent insurance assistant.

    claim id
        |
        +--> Coverage agent   --+
        +--> Fraud/SIU agent  --+--> Claims Director synthesis (one LLM call) --> decision memo
        +--> Compliance agent --+

Each specialist is a LangChain v1 agent (create_agent) with its own prompt, deterministic DB-backed tools and
the shared middleware stack (agent/middleware.py). The ClaimsReviewSupervisor runs them in order and hands
their reports to the Claims Director prompt. The Assistant is one agent with all tools (incl. guarded SQL).

2. Single-agent insurance assistant.

3. Referral agent and underwriter synthesis.
    Submission id
        |
        +--> application_agent [Application & Risk]   --+
        +--> claim history agent --+--> Underwriter synthesis (one LLM call) --> decision memo
        +--> Referral agent --+
        
Each specialist is a LangChain v1 agent (create_agent) with its own prompt, deterministic DB-backed tools and
the shared middleware stack (agent/middleware.py). The UnderwriterSupervisor runs them in order and hands
their reports to the Underwriter synthesis prompt.

request = request_text.strip()
        log.info("Underwriting phase", phase="1 - Application & Risk", submission=submission_id)
        application_result = _text(self.application_agent.invoke({"messages": [{"role": "user", "content": request}]}))
        log.info("Underwriting phase", phase="2 - Loss History", submission=submission_id)
        loss_history_result = _text(self.history_agent.invoke({"messages": [{"role": "user", "content": request}]}))

        log.info("Underwriting phase", phase="3 - Referral Desk (HITL)", submission=submission_id)
"""
import re
import threading
import uuid
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from agent import insurance_db
from agent.middleware import build_agent_middleware
from agent.prompts import (
    ASSISTANT_PROMPT,
    COMPLIANCE_AGENT_PROMPT,
    COVERAGE_AGENT_PROMPT,
    FRAUD_AGENT_PROMPT,
    SYNTHESIS_PROMPT_TEMPLATE,
    APPLICATION_RISK_PROMPT,
    LOSS_HISTORY_PROMPT,
    REFERRAL_AGENT_PROMPT,
    UNDERWRITER_MEMO_TEMPLATE,
)
from agent.tools import (
    check_coverage,
    check_settlement_authority,
    check_state_compliance,
    get_claim_details,
    lookup_vendor_history,
    run_sql_query,
    score_fraud_indicators,
    search_company_guidelines,
    UW_LEVELS,
    assess_submission,
    assess_submission_risk,
    get_applicant_loss_history,
    get_submission,
    request_manual_review,
    search_company_guidelines,
)
from logger import GLOBAL_LOGGER as log
from rag.llm import get_llm


REVIEW_TOOL = "request_manual_review"
_SUB_ID = re.compile(r"SUB-[A-Z0-9]+(?:-[A-Z0-9]+)*", re.I)


def create_specialized_agent(tools, system_prompt):
    """An agent = the LLM + a set of tools + a system prompt (+ middleware around the loop)."""
    return create_agent(
        model=get_llm(),
        tools=tools,
        system_prompt=system_prompt,
        middleware=build_agent_middleware(),
    )


def _final_text(agent, message: str) -> str:
    result = agent.invoke({"messages": [{"role": "user", "content": message}]})
    return result["messages"][-1].text  # .text joins Gemini's content blocks

def extract_submission_id(text: str) -> str | None:
    match = _SUB_ID.search(text or "")
    return match.group(0).upper() if match else None


def _text(agent_result) -> str:
    return agent_result["messages"][-1].text


def _called_review_tool(agent_result) -> bool:
    return any(getattr(m, "name", None) == REVIEW_TOOL for m in agent_result["messages"])

def ask_assistant(question: str) -> str:
    """Single-agent insurance assistant: SQL analytics + claim tools + RAG over the policy PDFs."""
    agent = create_specialized_agent(
        [run_sql_query, get_claim_details, check_coverage, score_fraud_indicators,
         check_state_compliance, lookup_vendor_history, search_company_guidelines],
        ASSISTANT_PROMPT,
    )
    return _final_text(agent, question)

class ClaimsReviewSupervisor:
    def __init__(self):
        self.llm = get_llm()
        self.coverage_agent = create_specialized_agent(
            [get_claim_details, check_coverage, search_company_guidelines], COVERAGE_AGENT_PROMPT
        )
        self.fraud_agent = create_specialized_agent(
            [get_claim_details, score_fraud_indicators, lookup_vendor_history, search_company_guidelines],
            FRAUD_AGENT_PROMPT,
        )
        self.compliance_agent = create_specialized_agent(
            [check_state_compliance, check_settlement_authority, search_company_guidelines],
            COMPLIANCE_AGENT_PROMPT,
        )

    @staticmethod
    def _invoke_agent(agent, request: str) -> str:
        return _final_text(agent, request)

    def run_audit(self, request: str) -> dict:
        log.info("Starting review phase", phase="1 - Coverage")
        coverage_result = self._invoke_agent(self.coverage_agent, request)
        log.info("Starting review phase", phase="2 - Fraud / SIU")
        fraud_result = self._invoke_agent(self.fraud_agent, request)
        log.info("Starting review phase", phase="3 - Compliance & Authority")
        compliance_result = self._invoke_agent(self.compliance_agent, request)

        synthesis_prompt = SYNTHESIS_PROMPT_TEMPLATE.format(
            as_of_date=insurance_db.as_of_date().isoformat(),
            coverage_result=coverage_result,
            fraud_result=fraud_result,
            compliance_result=compliance_result,
        )
        log.info("Starting review phase", phase="4 - Claims Director Synthesis")
        director_memo = self.llm.invoke(synthesis_prompt).text

        return {
            "coverage_result": coverage_result,
            "fraud_result": fraud_result,
            "compliance_result": compliance_result,
            "director_memo": director_memo,
        }

class UnderwriterNavigator:
    def __init__(self):
        self.llm = get_llm()
        self.application_agent = create_specialized_agent(
            [get_submission, assess_submission_risk, search_company_guidelines], APPLICATION_RISK_PROMPT)
        self.history_agent = create_specialized_agent(
            [get_applicant_loss_history, get_submission, search_company_guidelines], LOSS_HISTORY_PROMPT)
        self.checkpointer = InMemorySaver()
        # Human-in-the-Loop: the only tool with a side effect needs a human decision before it runs
        self.referral_agent = create_agent(
            model=self.llm,
            tools=[assess_submission_risk, request_manual_review],
            system_prompt=REFERRAL_AGENT_PROMPT,
            middleware=[
                *build_agent_middleware(),
                HumanInTheLoopMiddleware(
                    interrupt_on={REVIEW_TOOL: {"allowed_decisions": ["approve", "edit", "reject"]}},
                    description_prefix="Underwriting referral awaiting human review",
                ),
            ],
            checkpointer=self.checkpointer,
        )
        self._pending: dict[str, dict] = {}
        self._lock = threading.Lock()

    def run(self, request_text: str) -> dict:
        submission_id = extract_submission_id(request_text)
        if not submission_id:
            raise ValueError("No submission id found. Include an id such as SUB-DEMO-01 in the request.")
        assessment = assess_submission(submission_id)
        if not assessment:
            raise ValueError(f"Submission '{submission_id}' was not found.")

        request = request_text.strip()
        log.info("Underwriting phase", phase="1 - Application & Risk", submission=submission_id)
        application_result = _text(self.application_agent.invoke({"messages": [{"role": "user", "content": request}]}))
        log.info("Underwriting phase", phase="2 - Loss History", submission=submission_id)
        loss_history_result = _text(self.history_agent.invoke({"messages": [{"role": "user", "content": request}]}))

        log.info("Underwriting phase", phase="3 - Referral Desk (HITL)", submission=submission_id)
        thread_id = uuid.uuid4().hex
        config = {"configurable": {"thread_id": thread_id}}
        message = f"Decide on referral for submission {submission_id}."
        result = self.referral_agent.invoke({"messages": [{"role": "user", "content": message}]}, config)
        if assessment["referral_required"] and "__interrupt__" not in result and not _called_review_tool(result):
            result = self.referral_agent.invoke(
                {"messages": [{"role": "user", "content": "Referral IS required. Call request_manual_review now."}]}, config)

        ctx = {"submission_id": submission_id, "assessment": assessment, "application_result": application_result,
               "loss_history_result": loss_history_result}
        if "__interrupt__" in result:
            action = result["__interrupt__"][0].value["action_requests"][0]
            with self._lock:
                self._pending[thread_id] = ctx
            log.info("Underwriting paused for human review", thread_id=thread_id, submission=submission_id)
            return {**self._payload(ctx, thread_id), "status": "PENDING_REVIEW", "referral_result": None,
                    "underwriter_memo": None, "human_review": None,
                    "pending_review": {"tool": action["name"], "args": action["args"], "description": action["description"],
                                       "allowed_decisions": ["approve", "edit", "reject"], "authority_options": UW_LEVELS[1:]}}
        return self._finish(ctx, thread_id, _text(result), "No human review was needed for this submission.")

    def resume(self, thread_id: str, decision: str, reviewer_comment: str = "",
               edited_authority: str | None = None, edited_reason: str | None = None) -> dict:
        with self._lock:
            ctx = self._pending.pop(thread_id, None)
        if not ctx:
            raise ValueError("Unknown or already completed review thread.")
        config = {"configurable": {"thread_id": thread_id}}
        if decision == "approve":
            payload = {"type": "approve"}
        elif decision == "reject":
            payload = {"type": "reject", "message": reviewer_comment or "Reviewer rejected the referral."}
        elif decision == "edit":
            state = self.referral_agent.get_state(config)
            args = dict(state.tasks[0].interrupts[0].value["action_requests"][0]["args"])
            if edited_authority:
                args["referral_authority"] = edited_authority
            if edited_reason:
                args["reason"] = edited_reason
            payload = {"type": "edit", "edited_action": {"name": REVIEW_TOOL, "args": args}}
        else:
            raise ValueError("decision must be approve, edit or reject.")
        log.info("Underwriting resumed", thread_id=thread_id, decision=decision)
        result = self.referral_agent.invoke(Command(resume={"decisions": [payload]}), config)
        human = f"Reviewer decision: {decision.upper()}." + (f" Comment: {reviewer_comment}" if reviewer_comment else "")
        if decision == "edit":
            human += f" Edited referral: {payload['edited_action']['args']}"
        return self._finish(ctx, thread_id, _text(result), human)

    # ---- helpers ----------------------------------------------------------------------------

    @staticmethod
    def _payload(ctx: dict, thread_id: str) -> dict:
        return {"submission_id": ctx["submission_id"], "thread_id": thread_id, "assessment": ctx["assessment"],
                "application_result": ctx["application_result"], "loss_history_result": ctx["loss_history_result"]}

    def _finish(self, ctx: dict, thread_id: str, referral_result: str, human_review: str) -> dict:
        import json
        log.info("Underwriting phase", phase="4 - Underwriters Memo", submission=ctx["submission_id"])
        memo = self.llm.invoke(UNDERWRITER_MEMO_TEMPLATE.format(
            as_of_date=insurance_db.as_of_date().isoformat(),
            assessment_json=json.dumps(ctx["assessment"], indent=1, default=str),
            application_result=ctx["application_result"], loss_history_result=ctx["loss_history_result"],
            referral_result=referral_result, human_review=human_review)).text
        return {**self._payload(ctx, thread_id), "status": "COMPLETED", "referral_result": referral_result,
                "underwriter_memo": memo, "human_review": human_review, "pending_review": None}


# Quick test:  python -m agent.agents   (from the backend/ folder)
if __name__ == "__main__":
    print(ClaimsReviewSupervisor().run_audit("Review claim CLM-DEMO-01")["director_memo"])
