from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from agent import data_explorer as de
from api.main import app


def fake_llm(*replies):
    queue = list(replies)
    return lambda: SimpleNamespace(invoke=lambda prompt: SimpleNamespace(content=queue.pop(0)))


def test_sql_mode_runs_as_written_and_caps_rows():
    r = de.explore("SELECT claim_id, status FROM claims_current")
    assert r["status"] == "ok" and r["mode"] == "sql"
    assert r["columns"] == ["claim_id", "status"]
    assert r["row_count"] == 50 and r["truncated"] is True
    assert r["sql"].startswith("SELECT claim_id")


def test_sql_mode_no_rows_gives_fixed_message():
    r = de.explore("SELECT * FROM claims_current WHERE claim_id='NOPE'")
    assert r["status"] == "no_data" and r["message"] == "No information available for the query"


def test_unknown_table_is_no_data_with_detail():
    r = de.explore("SELECT * FROM weather")
    assert r["status"] == "no_data" and "no such table" in r["detail"]


@pytest.mark.parametrize("sql", ["DELETE FROM claims", "SELECT 1; DROP TABLE claims", "SELECT * FROM claims WHERE 1=1 UNION SELECT 1 /*", "WITH x AS (SELECT 1) DELETE FROM claims"])
def test_writes_are_rejected(sql):
    r = de.explore(sql)
    assert r["status"] in ("rejected", "no_data") and r["rows"] == []


def test_natural_language_generates_and_runs_sql(monkeypatch):
    monkeypatch.setattr(de, "get_llm", fake_llm("```sql\nSELECT state, COUNT(*) AS n FROM claims_current GROUP BY state;\n```"))
    r = de.explore("How many claims per state?")
    assert r["status"] == "ok" and r["mode"] == "nl" and r["columns"] == ["state", "n"]
    assert r["sql"].startswith("SELECT state")


def test_natural_language_retries_once_after_sql_error(monkeypatch):
    monkeypatch.setattr(de, "get_llm", fake_llm("SELECT * FROM claimz", "SELECT claim_id FROM claims_current LIMIT 3"))
    r = de.explore("show some claims")
    assert r["status"] == "ok" and r["row_count"] == 3


def test_unanswerable_question_returns_no_information(monkeypatch):
    monkeypatch.setattr(de, "get_llm", fake_llm("NO_DATA"))
    r = de.explore("What is the weather in Columbus?")
    assert r["status"] == "no_data" and r["message"] == de.NO_DATA_MESSAGE and r["sql"] == ""


def test_endpoint(monkeypatch):
    client = TestClient(app)
    ok = client.post("/api/agent/data-explorer", json={"query": "SELECT 1 AS one"})
    assert ok.status_code == 200 and ok.json()["rows"] == [[1]]
    assert client.post("/api/agent/data-explorer", json={"query": "  "}).status_code == 400
