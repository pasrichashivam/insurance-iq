"""Tests for the deterministic insurance tools (they run against backend/data/cardinal_ridge.db)."""
import json

from agent import tools


def call(tool, arg):
    return json.loads(tool.invoke(arg))


def test_ring_shop_claim_is_high_fraud():
    result = call(tools.score_fraud_indicators, "CLM-DEMO-01")
    assert result["risk_band"] == "HIGH" and result["fraud_score"] >= 50


def test_clean_glass_claim_is_covered_and_low_risk():
    assert call(tools.check_coverage, "CLM-DEMO-03")["coverage_verdict"] == "COVERED"
    assert call(tools.score_fraud_indicators, "CLM-DEMO-03")["risk_band"] == "LOW"


def test_flood_without_endorsement_is_not_covered():
    assert call(tools.check_coverage, "CLM-DEMO-02")["coverage_verdict"] == "NOT COVERED"


def test_cancelled_policy_is_not_covered():
    assert call(tools.check_coverage, "CLM-DEMO-06")["coverage_verdict"] == "NOT COVERED"


def test_florida_decision_clock_is_breached():
    result = call(tools.check_state_compliance, "CLM-DEMO-02")
    assert result["overall"] == "NON-COMPLIANT"


def test_large_commercial_loss_needs_escalation_and_reinsurance_notice():
    result = call(tools.check_settlement_authority, "CLM-DEMO-04")
    assert result["escalation_needed"] is True
    assert result["reinsurance"]["notice_required"] is True


def test_unknown_claim_is_reported_not_found():
    assert tools.get_claim_details.invoke("CLM-NOPE").startswith("NOT FOUND")


def test_sql_tool_allows_select_and_rejects_writes():
    assert call(tools.run_sql_query, "SELECT COUNT(*) AS n FROM claims")["rows"][0]["n"] > 1000
    assert tools.run_sql_query.invoke("DELETE FROM claims").startswith("REJECTED")
    assert tools.run_sql_query.invoke("SELECT 1; DROP TABLE claims").startswith("REJECTED")
