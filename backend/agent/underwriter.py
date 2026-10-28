"""Underwriter Navigator: multi-agent underwriting review with a Human-in-the-Loop referral gate.

    submission id (new business or renewal)
        |
        +--> Application & Risk analyst  (application, risk score, pricing)  --+
        +--> Loss History analyst        (claims, claim-note insights)       --+
        +--> Referral Desk agent  ---- request_manual_review ---- PAUSE for a human (HITL) ----+
                                                                                              |
    Underwriters Memo (one LLM call) <-- approve / edit / reject by the human reviewer <------+

The referral agent runs with LangChain's HumanInTheLoopMiddleware and a checkpointer. When it wants to file a
referral the graph is interrupted, `run()` returns status PENDING_REVIEW and the UI shows the proposed action.
`resume()` continues the same thread with the reviewer's decision, then the memo is written.
"""
import re
import threading
import uuid

from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent import insurance_db
from agent.agents import create_specialized_agent
from agent.middleware import build_agent_middleware
from agent.underwriting_prompts import (
    APPLICATION_RISK_PROMPT,
    LOSS_HISTORY_PROMPT,
    REFERRAL_AGENT_PROMPT,
    UNDERWRITER_MEMO_TEMPLATE,
)
from agent.underwriting_tools import (
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


def extract_submission_id(text: str) -> str | None:
    match = _SUB_ID.search(text or "")
    return match.group(0).upper() if match else None


def _text(agent_result) -> str:
    return agent_result["messages"][-1].text


def _called_review_tool(agent_result) -> bool:
    return any(getattr(m, "name", None) == REVIEW_TOOL for m in agent_result["messages"])


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

    # ---- public API -------------------------------------------------------------------------

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
