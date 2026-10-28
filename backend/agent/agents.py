"""Multi-agent claims review + single-agent insurance assistant.

    claim id
        |
        +--> Coverage agent   --+
        +--> Fraud/SIU agent  --+--> Claims Director synthesis (one LLM call) --> decision memo
        +--> Compliance agent --+

Each specialist is a LangChain v1 agent (create_agent) with its own prompt, deterministic DB-backed tools and
the shared middleware stack (agent/middleware.py). The ClaimsReviewSupervisor runs them in order and hands
their reports to the Claims Director prompt. The Assistant is one agent with all tools (incl. guarded SQL).
"""
from langchain.agents import create_agent

from agent import insurance_db
from agent.middleware import build_agent_middleware
from agent.prompts import (
    ASSISTANT_PROMPT,
    COMPLIANCE_AGENT_PROMPT,
    COVERAGE_AGENT_PROMPT,
    FRAUD_AGENT_PROMPT,
    SYNTHESIS_PROMPT_TEMPLATE,
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
)
from logger import GLOBAL_LOGGER as log
from rag.llm import get_llm


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


def ask_assistant(question: str) -> str:
    """Single-agent insurance assistant: SQL analytics + claim tools + RAG over the policy PDFs."""
    agent = create_specialized_agent(
        [run_sql_query, get_claim_details, check_coverage, score_fraud_indicators,
         check_state_compliance, lookup_vendor_history, search_company_guidelines],
        ASSISTANT_PROMPT,
    )
    return _final_text(agent, question)


# Quick test:  python -m agent.agents   (from the backend/ folder)
if __name__ == "__main__":
    print(ClaimsReviewSupervisor().run_audit("Review claim CLM-DEMO-01")["director_memo"])
