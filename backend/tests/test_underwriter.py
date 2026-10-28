"""Underwriter Navigator: deterministic engine + the Human-in-the-Loop flow (scripted fake LLM, no API key needed)."""
import itertools

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

from agent import underwriter as uw
from agent import agents
from agent.underwriting_tools import assess_submission  # noqa: E402


class FakeChat(GenericFakeChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


def _model(*messages):
    return FakeChat(messages=iter(messages))


def _text_model():
    return FakeChat(messages=itertools.cycle([AIMessage(content="analysis text")]))


def _tool_call(sub_id):
    return AIMessage(content="", tool_calls=[{"name": "request_manual_review", "id": "c1", "args": {
        "submission_id": sub_id, "referral_authority": "SENIOR UNDERWRITER", "reason": "Exceeds authority"}}])


@pytest.fixture
def navigator(monkeypatch):
    def build(*main_messages):
        main = _model(*main_messages)
        monkeypatch.setattr(uw, "get_llm", lambda: main)
        monkeypatch.setattr(agents, "get_llm", _text_model)
        return uw.UnderwriterNavigator()
    return build


def test_engine_demo_submissions():
    clean = assess_submission("SUB-DEMO-01")
    assert clean["risk_tier"] == "PREFERRED" and not clean["referral_required"] and clean["recommendation"] == "QUOTE"
    risky = assess_submission("SUB-DEMO-02")
    assert risky["recommendation"] == "DECLINE" and risky["risk_score"] >= 75
    renewal = assess_submission("SUB-DEMO-03")
    assert renewal["business_type"].startswith("RENEWAL") and renewal["required_authority"] == "SENIOR UNDERWRITER"
    big = assess_submission("SUB-DEMO-04")
    assert big["required_authority"] == "CHIEF UNDERWRITER" and big["reinsurance_notice_required"]
    assert assess_submission("SUB-NOPE") is None


def test_no_referral_completes_without_human(navigator):
    nav = navigator(AIMessage(content="No referral filed."), AIMessage(content="MEMO CLEAN"))
    out = nav.run("Underwrite SUB-DEMO-01")
    assert out["status"] == "COMPLETED" and out["underwriter_memo"] == "MEMO CLEAN"


def test_hitl_pause_and_approve(navigator):
    nav = navigator(_tool_call("SUB-DEMO-04"), AIMessage(content="Referral filed."), AIMessage(content="MEMO OK"))
    out = nav.run("Underwrite SUB-DEMO-04")
    assert out["status"] == "PENDING_REVIEW" and out["underwriter_memo"] is None
    assert out["pending_review"]["tool"] == "request_manual_review"
    done = nav.resume(out["thread_id"], "approve")
    assert done["status"] == "COMPLETED" and done["underwriter_memo"] == "MEMO OK"
    assert "APPROVE" in done["human_review"]
    with pytest.raises(ValueError):
        nav.resume(out["thread_id"], "approve")  # a thread can be resumed only once


def test_hitl_reject(navigator):
    nav = navigator(_tool_call("SUB-DEMO-03"), AIMessage(content="Referral not filed."), AIMessage(content="MEMO R"))
    out = nav.run("Underwrite SUB-DEMO-03")
    done = nav.resume(out["thread_id"], "reject", reviewer_comment="I will handle it")
    assert done["status"] == "COMPLETED" and "REJECT" in done["human_review"] and "I will handle it" in done["human_review"]


def test_hitl_edit(navigator):
    nav = navigator(_tool_call("SUB-DEMO-04"), AIMessage(content="Filed to chief."), AIMessage(content="MEMO E"))
    out = nav.run("Underwrite SUB-DEMO-04")
    done = nav.resume(out["thread_id"], "edit", edited_authority="CHIEF UNDERWRITER")
    assert "CHIEF UNDERWRITER" in done["human_review"]


def test_missing_submission_id(navigator):
    nav = navigator()
    with pytest.raises(ValueError):
        nav.run("underwrite something")


def test_api_endpoints(monkeypatch, navigator):
    from api import endpoints
    from api.main import app

    nav = navigator(_tool_call("SUB-DEMO-04"), AIMessage(content="Filed."), AIMessage(content="MEMO API"))
    monkeypatch.setattr(endpoints, "get_underwriter", lambda: nav)
    client = TestClient(app)
    first = client.post("/api/agent/underwriting", json={"request_text": "Underwrite SUB-DEMO-04"}).json()
    assert first["status"] == "PENDING_REVIEW"
    second = client.post("/api/agent/underwriting/review", json={"thread_id": first["thread_id"], "decision": "approve"}).json()
    assert second["underwriter_memo"] == "MEMO API"
    assert client.post("/api/agent/underwriting", json={"request_text": "no id"}).status_code == 400
