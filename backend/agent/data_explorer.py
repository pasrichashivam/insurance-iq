"""Data Explorer: natural-language question or SQL in -> the executed query and the top 50 rows out.

* A SQL statement (starts with SELECT / WITH) is validated and run as written.
* Anything else is treated as a question; the LLM writes ONE SQLite SELECT from the live database schema.
  If the query fails it gets one retry with the error message.
* No rows (or a question the data cannot answer) -> status "no_data" with the fixed message below.
The database is opened read-only, so even a missed guard cannot change data.
"""
import re
import time

from agent import insurance_db as db
from agent.tools import _FORBIDDEN
from logger import GLOBAL_LOGGER as log
from rag.llm import get_llm

MAX_ROWS = 50
TIMEOUT_SECONDS = 10
NO_DATA_MESSAGE = "No information available for the query"

_SQL_START = re.compile(r"^\s*(select|with|insert|update|delete|drop|alter|create|attach|detach|pragma|replace|vacuum)\b", re.I)

SQL_WRITER_PROMPT = """You translate questions into ONE read-only SQLite SELECT for the Cardinal Ridge insurance database.

SCHEMA (tables and views):
{schema}

RULES:
- policyholders, policies, policy_coverages and claims keep one row per change (valid_from / valid_to / is_current). \
For the latest information use the views policyholders_current, policies_current, policy_coverages_current, claims_current. \
For "as of <date>" use valid_from <= date AND (valid_to IS NULL OR date < valid_to) on the base table.
- "Today" in this dataset is {today}.
- Claim status values: OPEN, UNDER_INVESTIGATION, APPROVED, PAID, DENIED. Lines: AUTO, HOME, COMM_PROPERTY, GL, WC. Dates are ISO text.
- Select only the columns that answer the question; never invent tables or columns.
- Output ONLY the SQL statement: no markdown, no explanation, no semicolon.
- If the question cannot be answered from these tables (for example weather, stock prices, general knowledge, \
or data this schema does not hold), output exactly: NO_DATA
{retry}
QUESTION: {question}
"""


def looks_like_sql(text: str) -> bool:
    return bool(_SQL_START.match(text))


def validate_sql(sql: str) -> str | None:
    """Return a reason if the statement is not allowed, else None."""
    if ";" in sql:
        return "Only a single statement is allowed."
    if not re.match(r"^\s*(select|with)\b", sql, re.I):
        return "Only SELECT statements are allowed."
    if _FORBIDDEN.search(sql):
        return "Only read-only queries are allowed (no INSERT/UPDATE/DELETE/DDL/PRAGMA)."
    return None


def schema_text() -> str:
    """Compact 'table(col, col, ...)' listing read from the live database."""
    lines = []
    with db.connect() as con:
        objects = con.execute(
            "SELECT name, type FROM sqlite_master WHERE type IN ('table','view') AND name NOT LIKE 'sqlite_%' ORDER BY type, name"
        ).fetchall()
        for name, kind in objects:
            cols = [c[1] for c in con.execute(f'PRAGMA table_info("{name}")')]
            lines.append(f"{name}{' [view]' if kind == 'view' else ''}({', '.join(cols)})")
    return "\n".join(lines)


def execute_select(sql: str) -> tuple[list[str], list[list], bool]:
    """Run a validated SELECT; return (columns, up to 50 rows, truncated)."""
    with db.connect() as con:
        deadline = time.monotonic() + TIMEOUT_SECONDS
        con.set_progress_handler(lambda: 1 if time.monotonic() > deadline else 0, 100000)
        cur = con.execute(sql)
        columns = [d[0] for d in cur.description or []]
        fetched = cur.fetchmany(MAX_ROWS + 1)
    rows = [list(r) for r in fetched[:MAX_ROWS]]
    return columns, rows, len(fetched) > MAX_ROWS


def _clean_sql(text) -> str:
    if isinstance(text, list):
        text = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in text)
    text = str(text).strip()
    text = re.sub(r"^```(?:sql)?|```$", "", text, flags=re.I | re.M).strip()
    return text.rstrip(";").strip()


def _generate_sql(question: str, schema: str, error: str = "") -> str:
    retry = f"\nYour previous query failed with: {error}\nFix it.\n" if error else ""
    prompt = SQL_WRITER_PROMPT.format(
        schema=schema, today=db.as_of_date().isoformat(), retry=retry, question=question
    )
    return _clean_sql(get_llm().invoke(prompt).content)


def _result(status: str, mode: str, sql: str = "", columns=None, rows=None, truncated=False, message="", detail=""):
    rows = rows or []
    return {
        "status": status,
        "mode": mode,
        "message": message,
        "sql": sql,
        "columns": columns or [],
        "rows": rows,
        "row_count": len(rows),
        "truncated": truncated,
        "detail": detail,
    }


def _no_data(mode: str, sql: str = "", detail: str = ""):
    return _result("no_data", mode, sql=sql, message=NO_DATA_MESSAGE, detail=detail)


def explore(text: str) -> dict:
    text = (text or "").strip()
    if looks_like_sql(text):
        text = text.rstrip(";").strip()
    if not text:
        raise ValueError("Enter a question or a SQL query.")

    if looks_like_sql(text):
        problem = validate_sql(text)
        if problem:
            return _result("rejected", "sql", sql=text, message=problem)
        try:
            columns, rows, truncated = execute_select(text)
        except Exception as exc:
            return _no_data("sql", sql=text, detail=f"SQL error: {exc}")
        if not rows:
            return _no_data("sql", sql=text)
        log.info("data_explorer", mode="sql", rows=len(rows))
        return _result("ok", "sql", sql=text, columns=columns, rows=rows, truncated=truncated)

    schema = schema_text()
    sql, error = "", ""
    for _ in range(2):
        sql = _generate_sql(text, schema, error)
        if sql.upper().startswith("NO_DATA"):
            return _no_data("nl")
        problem = validate_sql(sql)
        if problem:
            return _result("rejected", "nl", sql=sql, message=problem)
        try:
            columns, rows, truncated = execute_select(sql)
        except Exception as exc:
            error = str(exc)
            continue
        if not rows:
            return _no_data("nl", sql=sql)
        log.info("data_explorer", mode="nl", rows=len(rows))
        return _result("ok", "nl", sql=sql, columns=columns, rows=rows, truncated=truncated)
    return _no_data("nl", sql=sql, detail=f"SQL error: {error}")
