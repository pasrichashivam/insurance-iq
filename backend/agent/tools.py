"""Tools the insurance agents can call.

Every tool is DETERMINISTIC: it reads the Cardinal Ridge database (read-only) and applies the
company rules in plain Python. The LLM decides WHICH tool to call and explains the result,
but it never invents the numbers. Two tools are different on purpose:
    search_company_guidelines  -> RAG over the indexed PDFs (company + state policy documents)
    run_sql_query              -> guarded, read-only SELECT for portfolio analytics

Time travel: policyholders, policies, policy_coverages and claims are EFFECTIVE-DATED (one row per change).
Every record tool takes an optional `as_of_date` (YYYY-MM-DD). Leave it empty and the tool answers with the
LATEST information; give a date and it answers with the version that was in force on that date.

Business rules mirrored here (and written up in sample_docs/):
    * Settlement authority ladder          -> cardinal_ridge_claims_authority_and_reserving_guidelines.pdf
    * Fraud red flags                      -> cardinal_ridge_siu_fraud_detection_guidelines.pdf
    * State prompt-payment clocks          -> state_*_claims_regulations_summary.pdf (+ state_regulations table)
"""
import json
import re
from datetime import timedelta
import uuid
from langchain_core.tools import tool

from agent import insurance_db as db
from agent.doc_rules import DOC_LABELS, required_documents
from logger import GLOBAL_LOGGER as log

AUTHORITY_LADDER = [("JUNIOR", 10_000), ("SENIOR", 50_000), ("MANAGER", 250_000), ("DIRECTOR", 1_000_000)]
LEVEL_RANK = {name: i for i, (name, _) in enumerate(AUTHORITY_LADDER)}


def _json(data) -> str:
    return json.dumps(data, indent=2, default=str)


def _asof(as_of_date: str | None):
    """-> (iso_or_None, error_message_or_None)"""
    try:
        return db.parse_as_of(as_of_date), None
    except ValueError:
        return None, f"INVALID as_of_date '{as_of_date}': use YYYY-MM-DD (or leave empty for the latest information)."


def _load_claim(claim_id: str, as_of: str | None = None) -> dict | None:
    return db.version_one("claims", "claim_id = ?", (claim_id.strip().upper(),), as_of)


def _not_found(claim_id: str, as_of: str | None = None) -> str:
    if as_of and db.one("SELECT 1 AS x FROM claims WHERE claim_id = ?", (claim_id.strip().upper(),)):
        return f"NOT FOUND AS OF {as_of}: claim {claim_id} had not been reported yet on that date."
    return f"NOT FOUND: no claim with id '{claim_id}'. Claim ids look like CLM-2026-000123 or CLM-DEMO-01."


def _policy(policy_id: str, as_of: str | None):
    return db.version_one("policies", "policy_id = ?", (policy_id,), as_of) or db.version_one("policies", "policy_id = ?", (policy_id,), None)


def _coverage(policy_id: str, code: str, as_of: str | None):
    return db.version_one("policy_coverages", "policy_id = ? AND coverage_code = ?", (policy_id, code), as_of) or \
        db.version_one("policy_coverages", "policy_id = ? AND coverage_code = ?", (policy_id, code), None)


def _holder(customer_id: str, as_of: str | None):
    return db.version_one("policyholders", "customer_id = ?", (customer_id,), as_of) or \
        db.version_one("policyholders", "customer_id = ?", (customer_id,), None)


def _notes(claim_id: str, as_of: str | None) -> list[dict]:
    cutoff = as_of or db.as_of_date().isoformat()
    return db.query("SELECT * FROM claim_notes WHERE claim_id = ? AND effective_date <= ? ORDER BY note_seq",
                    (claim_id, cutoff))


def statement_conflicts(claim_id: str, as_of: str | None = None) -> list[str]:
    """Contradictions between what was reported in different claim notes (date, location city, injuries)."""
    claim = _load_claim(claim_id, as_of)
    notes = _notes(claim_id, as_of)
    out: list[str] = []
    dates: dict = {}
    for n in notes:
        if n["when_occurred"]:
            dates.setdefault(n["when_occurred"][:10], n)
    if claim and claim["loss_date"]:
        dates.setdefault(claim["loss_date"], None)
    if len(dates) > 1:
        detail = ", ".join(d + (f" ({n['note_type']} note {n['effective_date']})" if n else " (claim record)") for d, n in dates.items())
        out.append(f"Loss date differs between sources: {detail}.")
    cities: dict = {}
    for n in notes:
        if n["where_occurred"]:
            parts = [p.strip() for p in n["where_occurred"].split(",")]
            if len(parts) >= 2:
                cities.setdefault(f"{parts[-2]}, {parts[-1]}", n)
    if len(cities) > 1:
        out.append("Loss location differs: " + "; ".join(f"{k} ({v['note_type']} note {v['effective_date']})" for k, v in cities.items()) + ".")
    inj = {n["injuries_reported"] for n in notes if n["injuries_reported"] is not None}
    if len(inj) > 1:
        out.append("Injury reporting is inconsistent: some notes say no injuries, others report injuries.")
    return out


def duplicate_invoices(claim_id: str) -> list[dict]:
    mine = db.query("SELECT doc_id, invoice_number, invoice_amount FROM claim_documents WHERE claim_id = ? AND invoice_number IS NOT NULL",
                    (claim_id,))
    hits = []
    for d in mine:
        for o in db.query("SELECT claim_id, vendor_id, invoice_amount, doc_date FROM claim_documents "
                          "WHERE invoice_number = ? AND claim_id != ?", (d["invoice_number"], claim_id)):
            hits.append({"invoice_number": d["invoice_number"], "also_billed_on_claim": o["claim_id"], "vendor_id": o["vendor_id"],
                         "other_invoice_amount": o["invoice_amount"], "this_invoice_amount": d["invoice_amount"]})
    return hits


def documents_status(claim: dict) -> dict:
    """Required vs received documents (database side). Reused by the claims-processing and customer agents."""
    have = db.query("SELECT doc_type, doc_date, received_date, invoice_number, invoice_amount, file_name "
                    "FROM claim_documents WHERE claim_id = ? ORDER BY doc_type", (claim["claim_id"],))
    need = required_documents(claim["line"], claim["cause_of_loss"], claim["claimed_amount"], bool(claim["vendor_id"]))
    have_types = {d["doc_type"] for d in have}
    return {"claim_id": claim["claim_id"], "required": need, "received": have,
            "missing": [{"doc_type": t, "description": DOC_LABELS.get(t, t)} for t in need if t not in have_types]}


# ==========================================
# RAG tool: company + state policy documents
# ==========================================

@tool
def search_company_guidelines(query: str) -> str:
    """Search Cardinal Ridge's indexed policy documents (claims guidelines, SIU fraud guidelines,
    underwriting guidelines, state regulation summaries, policy forms) and return the most relevant passages."""
    try:
        from rag.vector_store import get_vector_store

        docs = get_vector_store().similarity_search(query, k=4)
    except Exception as exc:  # no index yet, no API key, ...
        return f"GUIDELINE SEARCH UNAVAILABLE: {exc}. Index the sample_docs PDFs first (Index Documents tab)."
    if not docs:
        return "No matching passages found. Make sure the sample_docs PDFs are indexed."
    return "\n\n".join(f"[{d.metadata.get('source', '?')}]\n{d.page_content}" for d in docs)


# ==========================================
# Claim / policy / coverage tools
# ==========================================

@tool
def get_claim_details(claim_id: str, as_of_date: str = "") -> str:
    """Return the full claim file: claim facts, policyholder, policy, adjuster and vendor, for a claim id like CLM-DEMO-01.
    as_of_date: optional YYYY-MM-DD to see the file as it stood on that date; leave empty for the latest information."""
    as_of, err = _asof(as_of_date)
    if err:
        return err
    claim = _load_claim(claim_id, as_of)
    if not claim:
        return _not_found(claim_id, as_of)
    policy = _policy(claim["policy_id"], as_of)
    holder = _holder(claim["customer_id"], as_of)
    if holder:
        holder = {k: holder[k] for k in ("customer_id", "name", "type", "state", "city", "customer_since", "credit_tier", "address_changes_12m")}
    adjuster = db.one("SELECT adjuster_id, name, level, authority_limit, open_claims FROM adjusters WHERE adjuster_id = ?",
                      (claim["adjuster_id"],))
    vendor = db.one("SELECT vendor_id, name, type, state, years_in_network FROM vendors WHERE vendor_id = ?",
                    (claim["vendor_id"],)) if claim["vendor_id"] else None
    return _json({"claim": claim, "policyholder": holder, "policy": policy, "adjuster": adjuster, "vendor": vendor,
                  "viewing": f"as of {as_of}" if as_of else "latest information", "as_of_date": as_of or db.as_of_date()})


@tool
def get_claim_history(claim_id: str) -> str:
    """List every recorded change to a claim (FNOL, acknowledgement, supplement, SIU referral, decision, payment ...)
    with its effective date, status, claimed amount, reserve and paid amount."""
    rows = db.query("SELECT version_no, valid_from, valid_to, change_type, change_note, status, claimed_amount, reserve_amount, "
                    "paid_amount, adjuster_id, siu_referred FROM claims WHERE claim_id = ? ORDER BY version_no", (claim_id.strip().upper(),))
    return _json({"claim_id": claim_id.strip().upper(), "versions": rows}) if rows else _not_found(claim_id)


@tool
def get_policy_history(policy_id: str) -> str:
    """List every recorded change to a policy and its coverages (issue, endorsement, cancellation, expiry) with effective dates."""
    pid = policy_id.strip().upper()
    pol = db.query("SELECT version_no, valid_from, valid_to, status, annual_premium, cancel_date, cancel_reason, change_type, change_note "
                   "FROM policies WHERE policy_id = ? ORDER BY version_no", (pid,))
    if not pol:
        return f"NOT FOUND: no policy '{policy_id}'."
    cov = db.query("SELECT coverage_code, version_no, valid_from, valid_to, limit_amount, deductible, change_type "
                   "FROM policy_coverages WHERE policy_id = ? ORDER BY coverage_code, version_no", (pid,))
    return _json({"policy_id": pid, "policy_versions": pol, "coverage_versions": cov})


@tool
def get_claim_notes(claim_id: str, as_of_date: str = "") -> str:
    """Return the adjuster notes for a claim: what happened, where, when, how, parties involved, exposures and damages.
    Notes accumulate over time as more facts arrive; each has an effective date. Also returns the consolidated
    'latest known' picture. as_of_date: optional YYYY-MM-DD (notes known on that date); empty = all notes."""
    as_of, err = _asof(as_of_date)
    if err:
        return err
    cid = claim_id.strip().upper()
    if not db.one("SELECT 1 AS x FROM claims WHERE claim_id = ?", (cid,)):
        return _not_found(claim_id)
    notes = _notes(cid, as_of)
    latest: dict = {}
    for n in notes:
        for k in ("what_happened", "where_occurred", "when_occurred", "how_occurred", "parties_involved", "exposures", "damages",
                  "injuries_reported", "underwriting_insights"):
            if n[k] is not None:
                latest[k] = n[k]
    return _json({"claim_id": cid, "note_count": len(notes), "consolidated_latest_known": latest,
                  "conflicts_between_notes": statement_conflicts(cid, as_of), "notes": notes})


@tool
def get_claim_documents(claim_id: str) -> str:
    """List the documents received for a claim and which required documents are still missing."""
    claim = _load_claim(claim_id)
    if not claim:
        return _not_found(claim_id)
    return _json(documents_status(claim))


@tool
def check_coverage(claim_id: str, as_of_date: str = "") -> str:
    """Decide whether the claim is covered: policy in force on the loss date, coverage present, exclusions,
    deductible, limit and an estimated payable amount. as_of_date: optional YYYY-MM-DD to evaluate with the policy
    and claim data known on that date; leave empty for the latest information."""
    as_of, err = _asof(as_of_date)
    if err:
        return err
    claim = _load_claim(claim_id, as_of)
    if not claim:
        return _not_found(claim_id, as_of)
    policy = _policy(claim["policy_id"], as_of)
    cov = _coverage(claim["policy_id"], claim["coverage_code"], as_of)
    loss = db.to_date(claim["loss_date"])
    issues, notes = [], []

    if not (db.to_date(policy["effective_date"]) <= loss <= db.to_date(policy["expiry_date"])):
        issues.append(f"Loss date {loss} is OUTSIDE the policy period {policy['effective_date']} to {policy['expiry_date']}.")
    if policy["cancel_date"] and loss >= db.to_date(policy["cancel_date"]):
        issues.append(f"Policy was CANCELLED on {policy['cancel_date']} ({policy['cancel_reason']}) before the loss on {loss}. No coverage.")
    elif policy["cancel_date"]:
        notes.append(f"Policy was cancelled on {policy['cancel_date']} but was in force on the loss date.")
    if not cov:
        issues.append(f"Policy has no {claim['coverage_code']} coverage.")
    if claim["cause_of_loss"] == "FLOOD" and claim["coverage_code"] != "FLOOD":
        has_flood = db.one("SELECT 1 AS x FROM policy_coverages WHERE policy_id = ? AND coverage_code = 'FLOOD'", (claim["policy_id"],))
        if not has_flood:
            issues.append("Flood/surface-water damage is EXCLUDED under the homeowners form and no FLOOD endorsement is on this policy.")

    deductible = (cov or {}).get("deductible") or 0.0
    limit = (cov or {}).get("limit_amount") or 0.0
    cat = claim["catastrophe_code"] or ""
    if cov and claim["line"] == "HOME" and "HURR" in cat and policy["state"] in ("FL", "TX"):
        hurricane = 0.02 * limit
        if hurricane > deductible:
            notes.append(f"Hurricane percentage deductible applies: 2% of dwelling limit = ${hurricane:,.2f}.")
            deductible = hurricane
    payable = 0.0 if issues else max(0.0, min(claim["claimed_amount"] - deductible, limit))
    if limit and claim["claimed_amount"] >= 0.9 * limit:
        notes.append(f"Claimed amount is {claim['claimed_amount'] / limit:.0%} of the coverage limit.")

    return _json({
        "claim_id": claim["claim_id"], "policy_id": policy["policy_id"], "line": claim["line"], "state": claim["state"],
        "viewing": f"as of {as_of}" if as_of else "latest information",
        "policy_status": policy["status"], "loss_date": claim["loss_date"], "cause_of_loss": claim["cause_of_loss"],
        "coverage_code": claim["coverage_code"], "coverage_limit": limit, "deductible_applied": deductible,
        "claimed_amount": claim["claimed_amount"], "estimated_payable": round(payable, 2),
        "coverage_verdict": "NOT COVERED" if issues else "COVERED", "issues": issues, "notes": notes,
    })


# ==========================================
# Fraud / SIU tools
# ==========================================

def compute_fraud_score(claim_id: str, as_of: str | None = None) -> dict | None:
    """The scoring engine behind `score_fraud_indicators` (also called directly by the fraud agent pipeline)."""
    claim = _load_claim(claim_id, as_of)
    if not claim:
        return None
    policy = _policy(claim["policy_id"], as_of)
    holder = _holder(claim["customer_id"], as_of)
    cov = _coverage(claim["policy_id"], claim["coverage_code"], as_of)
    loss, rep = db.to_date(claim["loss_date"]), db.to_date(claim["reported_date"])
    flt, fparams = db.version_filter(as_of)
    flags: list[tuple[int, str]] = []

    since_inception = (loss - db.to_date(policy["effective_date"])).days
    if 0 <= since_inception <= 30:
        flags.append((20, f"Loss only {since_inception} days after policy inception (<=30 days)"))
    elif 31 <= since_inception <= 60:
        flags.append((10, f"Loss {since_inception} days after policy inception (<=60 days)"))

    lag = (rep - loss).days
    if lag > 30:
        flags.append((15, f"Reported {lag} days after the loss (>30 days)"))
    elif lag > 14:
        flags.append((8, f"Reported {lag} days after the loss (>14 days)"))

    amount = claim["claimed_amount"]
    for _, limit in AUTHORITY_LADDER[:3]:
        if 0.95 * limit <= amount < limit:
            flags.append((15, f"Amount ${amount:,.2f} sits just under the ${limit:,.0f} settlement-authority threshold"))
            break
    if cov and cov["limit_amount"] and amount >= 0.9 * cov["limit_amount"]:
        flags.append((10, "Claimed amount is >=90% of the coverage limit"))
    if amount >= 5000 and amount % 1000 == 0:
        flags.append((5, "Round-dollar claim amount"))

    prior = db.one(f"SELECT COUNT(*) AS n FROM claims WHERE {flt} AND customer_id = ? AND claim_id != ? AND loss_date >= ? AND loss_date <= ?",
                   (*fparams, claim["customer_id"], claim["claim_id"], str(loss - timedelta(days=730)), claim["loss_date"]))["n"]
    if prior >= 3:
        flags.append((20, f"{prior} other claims by this customer in the 24 months before the loss"))
    elif prior == 2:
        flags.append((10, "2 other claims by this customer in the 24 months before the loss"))

    if claim["vendor_id"]:
        cutoff = as_of or "9999-12-31"
        v_siu = db.one("SELECT COUNT(*) AS n FROM siu_cases WHERE vendor_id = ? AND opened_date <= ?", (claim["vendor_id"], cutoff))["n"]
        vname = (db.one("SELECT name FROM vendors WHERE vendor_id = ?", (claim["vendor_id"],)) or {}).get("name", claim["vendor_id"])
        if v_siu >= 3:
            flags.append((20, f"Vendor {vname} appears in {v_siu} SIU cases"))
        elif v_siu >= 1:
            flags.append((10, f"Vendor {vname} appears in {v_siu} SIU case(s)"))

    if holder["address_changes_12m"] >= 2:
        flags.append((8, f"{holder['address_changes_12m']} address changes in the last 12 months"))
    if policy["cancel_date"] and 0 <= (db.to_date(policy["cancel_date"]) - loss).days <= 30:
        flags.append((10, "Policy cancelled within 30 days after the loss"))
    if re.search(r"no witness|unwitnessed|no police report", claim["description"], re.I):
        flags.append((8, "Narrative says no witnesses / no police report"))

    dups = duplicate_invoices(claim["claim_id"])
    if dups:
        flags.append((20, f"Invoice number(s) {sorted({d['invoice_number'] for d in dups})} also billed on "
                          f"{len(dups)} other claim(s) (duplicate invoice)"))
    conflicts = statement_conflicts(claim["claim_id"], as_of)
    if conflicts:
        flags.append((15, "Inconsistent statements in the claim notes: " + " ".join(conflicts)))

    score = min(100, sum(p for p, _ in flags))
    band = "HIGH" if score >= 50 else "MEDIUM" if score >= 25 else "LOW"
    action = {"HIGH": "REFER TO SIU before any payment", "MEDIUM": "Supervisor review; request additional documentation",
              "LOW": "No SIU action; handle in the normal workflow"}[band]
    return {"claim_id": claim["claim_id"], "viewing": f"as of {as_of}" if as_of else "latest information",
            "fraud_score": score, "risk_band": band, "recommended_action": action,
            "flags": [{"points": p, "flag": f} for p, f in flags], "already_in_siu": bool(claim["siu_referred"])}


@tool
def score_fraud_indicators(claim_id: str, as_of_date: str = "") -> str:
    """Score a claim 0-100 against Cardinal Ridge's SIU red-flag rules and list every flag that fired (includes duplicate
    invoices and inconsistent statements). as_of_date: optional YYYY-MM-DD; leave empty for the latest information."""
    as_of, err = _asof(as_of_date)
    if err:
        return err
    result = compute_fraud_score(claim_id, as_of)
    return _json(result) if result else _not_found(claim_id, as_of)


def vendor_profile(vendor_id: str, as_of: str | None = None) -> dict | None:
    flt, fparams = db.version_filter(as_of)
    vendor = db.one("SELECT * FROM vendors WHERE vendor_id = ?", (vendor_id.strip().upper(),))
    if not vendor:
        return None
    stats = db.one(f"SELECT COUNT(*) AS claims, ROUND(AVG(claimed_amount),2) AS avg_amount, "
                   f"SUM(CASE WHEN claimed_amount BETWEEN 9500 AND 9999.99 THEN 1 ELSE 0 END) AS just_under_10k, "
                   f"SUM(CASE WHEN julianday(reported_date) - julianday(loss_date) <= 1 THEN 1 ELSE 0 END) AS reported_within_1_day "
                   f"FROM claims WHERE {flt} AND vendor_id = ?", (*fparams, vendor["vendor_id"]))
    peers = db.one(f"SELECT ROUND(AVG(c),1) AS avg_claims_per_vendor, ROUND(AVG(a),2) AS avg_amount FROM (SELECT COUNT(*) AS c, AVG(claimed_amount) AS a "
                   f"FROM claims WHERE {flt} AND vendor_id IS NOT NULL GROUP BY vendor_id)", fparams)
    cutoff = as_of or "9999-12-31"
    siu = db.query("SELECT outcome, COUNT(*) AS n FROM siu_cases WHERE vendor_id = ? AND opened_date <= ? GROUP BY outcome",
                   (vendor["vendor_id"], cutoff))
    dup = db.one("SELECT COUNT(*) AS n FROM claim_documents d WHERE d.vendor_id = ? AND d.invoice_number IN "
                 "(SELECT invoice_number FROM claim_documents WHERE invoice_number IS NOT NULL GROUP BY invoice_number HAVING COUNT(*) > 1)",
                 (vendor["vendor_id"],))["n"]
    return {"vendor": vendor, "claim_stats": stats, "peer_average_claims_per_vendor": peers["avg_claims_per_vendor"],
            "peer_average_claim_amount": peers["avg_amount"], "invoices_with_duplicate_numbers": dup, "siu_cases_by_outcome": siu}


@tool
def lookup_vendor_history(vendor_id: str, as_of_date: str = "") -> str:
    """Profile a repair shop / contractor / clinic (unusual provider behaviour): claim volume, average amount, share of claims
    just under $10,000, same-or-next-day reporting, duplicate invoice numbers and every SIU case that involved the vendor.
    Use ids like VND-901. as_of_date: optional YYYY-MM-DD; leave empty for the latest information."""
    as_of, err = _asof(as_of_date)
    if err:
        return err
    profile = vendor_profile(vendor_id, as_of)
    return _json(profile) if profile else f"NOT FOUND: no vendor '{vendor_id}'."


@tool
def detect_duplicate_invoices(claim_id: str) -> str:
    """Find invoice numbers on this claim that were also billed on other claims (duplicate / recycled invoices)."""
    cid = claim_id.strip().upper()
    if not _load_claim(cid):
        return _not_found(claim_id)
    hits = duplicate_invoices(cid)
    return _json({"claim_id": cid, "duplicate_invoice_found": bool(hits), "matches": hits})


def related_claims(claim: dict, as_of: str | None = None) -> dict:
    flt, fparams = db.version_filter(as_of)
    cols = "claim_id, customer_id, loss_date, cause_of_loss, claimed_amount, status, vendor_id, state"
    same_customer = db.query(f"SELECT {cols} FROM claims WHERE {flt} AND customer_id = ? AND claim_id != ? ORDER BY loss_date DESC LIMIT 10",
                             (*fparams, claim["customer_id"], claim["claim_id"]))
    same_vendor = []
    if claim["vendor_id"]:
        same_vendor = db.query(
            f"SELECT {cols} FROM claims WHERE {flt} AND vendor_id = ? AND claim_id != ? AND ABS(julianday(loss_date) - julianday(?)) <= 90 "
            f"AND ABS(claimed_amount - ?) <= 0.05 * ? ORDER BY loss_date LIMIT 10",
            (*fparams, claim["vendor_id"], claim["claim_id"], claim["loss_date"], claim["claimed_amount"], claim["claimed_amount"]))
    same_day = []
    if not claim["catastrophe_code"]:
        same_day = db.query(f"SELECT {cols} FROM claims WHERE {flt} AND loss_date = ? AND state = ? AND cause_of_loss = ? AND claim_id != ? "
                            f"AND catastrophe_code IS NULL LIMIT 10", (*fparams, claim["loss_date"], claim["state"], claim["cause_of_loss"], claim["claim_id"]))
    shared_invoice = sorted({h["also_billed_on_claim"] for h in duplicate_invoices(claim["claim_id"])})
    return {"claim_id": claim["claim_id"], "same_customer": same_customer, "same_vendor_similar_amount_90d": same_vendor,
            "same_day_state_cause": same_day, "claims_sharing_an_invoice_number": shared_invoice,
            "summary": {"same_customer": len(same_customer), "same_vendor_cluster": len(same_vendor),
                        "same_day_cluster": len(same_day), "shared_invoice": len(shared_invoice)}}


@tool
def find_related_claims(claim_id: str, as_of_date: str = "") -> str:
    """Find potentially related claims: same customer, same vendor with similar amounts in a 90-day window, same loss
    date/state/cause cluster, and claims sharing an invoice number. as_of_date: optional YYYY-MM-DD."""
    as_of, err = _asof(as_of_date)
    if err:
        return err
    claim = _load_claim(claim_id, as_of)
    if not claim:
        return _not_found(claim_id, as_of)
    return _json(related_claims(claim, as_of))


@tool
def compare_claim_statements(claim_id: str, as_of_date: str = "") -> str:
    """Compare what was said in each dated claim note (FNOL, inspection, recorded statement ...) and report contradictions in
    loss date, location and injuries. as_of_date: optional YYYY-MM-DD."""
    as_of, err = _asof(as_of_date)
    if err:
        return err
    cid = claim_id.strip().upper()
    if not _load_claim(cid, as_of):
        return _not_found(claim_id, as_of)
    conflicts = statement_conflicts(cid, as_of)
    return _json({"claim_id": cid, "consistent": not conflicts, "conflicts": conflicts,
                  "notes_reviewed": [{"effective_date": n["effective_date"], "type": n["note_type"], "when": n["when_occurred"],
                                      "where": n["where_occurred"]} for n in _notes(cid, as_of)]})


# ==========================================
# Compliance / authority tools
# ==========================================

@tool
def check_state_compliance(claim_id: str, as_of_date: str = "") -> str:
    """Check the claim against its state's prompt-payment rules (acknowledgement, decision and payment deadlines)
    and estimate late-payment interest exposure. Evaluated as of today's date in the system, or as of as_of_date
    (YYYY-MM-DD) using the claim data known on that date."""
    as_of, err = _asof(as_of_date)
    if err:
        return err
    claim = _load_claim(claim_id, as_of)
    if not claim:
        return _not_found(claim_id, as_of)
    rule = db.one("SELECT * FROM state_regulations WHERE state = ?", (claim["state"],))
    today = db.to_date(as_of) if as_of else db.as_of_date()
    biz = rule["day_unit"] == "business"
    rep = db.to_date(claim["reported_date"])
    ack, dec, pay = (db.to_date(claim[k]) for k in ("acknowledged_date", "decision_date", "payment_date"))
    unit = rule["day_unit"]
    overdue_days: list[int] = []  # calendar days late on decision / payment, for the interest estimate

    def milestone(name, deadline, done, counts_for_interest):
        if done:
            late = db.days_between(deadline, done, biz)
            if late > 0 and counts_for_interest:
                overdue_days.append((done - deadline).days)
            return {"milestone": name, "deadline": deadline, "completed": done,
                    "status": "MET" if late <= 0 else f"BREACHED (completed {late} {unit} days late)"}
        left = db.days_between(today, deadline, biz)
        if left < 0:
            if counts_for_interest:
                overdue_days.append((today - deadline).days)
            status = f"BREACHED - OVERDUE by {-left} {unit} days"
        else:
            status = f"DUE SOON ({left} {unit} days left)" if left <= 3 else f"PENDING ({left} {unit} days left)"
        return {"milestone": name, "deadline": deadline, "completed": None, "status": status}

    milestones = [milestone("Acknowledge claim", db.add_days(rep, rule["ack_days"], biz), ack, False),
                  milestone("Accept / deny decision", db.add_days(rep, rule["decision_days"], biz), dec, True)]
    if dec and claim["status"] in ("APPROVED", "PAID"):
        milestones.append(milestone("Pay claim", db.add_days(dec, rule["payment_days"], biz), pay, True))

    breached = any(m["status"].startswith("BREACHED") for m in milestones)
    interest = None
    if overdue_days:
        base = claim["reserve_amount"] or claim["claimed_amount"]
        interest = round(base * rule["late_interest_rate"] * max(overdue_days) / 365, 2)
    return _json({"claim_id": claim["claim_id"], "state": claim["state"], "statute": rule["statute"],
                  "rule": f"ack {rule['ack_days']}, decision {rule['decision_days']}, payment {rule['payment_days']} {unit} days",
                  "reported_date": claim["reported_date"], "as_of_date": today, "milestones": milestones,
                  "overall": "NON-COMPLIANT" if breached else "COMPLIANT",
                  "estimated_late_interest_exposure_usd": interest, "state_notes": rule["notes"]})


@tool
def check_settlement_authority(claim_id: str, as_of_date: str = "") -> str:
    """Check who must approve the claim amount (delegation-of-authority ladder), whether the assigned adjuster has
    enough authority, and whether reinsurers must be notified. as_of_date: optional YYYY-MM-DD; empty = latest."""
    as_of, err = _asof(as_of_date)
    if err:
        return err
    claim = _load_claim(claim_id, as_of)
    if not claim:
        return _not_found(claim_id, as_of)
    adjuster = db.one("SELECT * FROM adjusters WHERE adjuster_id = ?", (claim["adjuster_id"],))
    amount = max(claim["claimed_amount"], claim["reserve_amount"] or 0)
    required = next((n for n, lim in AUTHORITY_LADDER if amount <= lim), "CLAIMS VP + BOARD NOTIFICATION")
    ok = required in LEVEL_RANK and LEVEL_RANK[adjuster["level"]] >= LEVEL_RANK[required]
    treaty = db.one("SELECT * FROM reinsurance_treaties WHERE ',' || line || ',' LIKE '%,' || ? || ',%'", (claim["line"],))
    return _json({
        "claim_id": claim["claim_id"], "amount_assessed": amount, "required_approval_level": required,
        "assigned_adjuster": {"id": adjuster["adjuster_id"], "name": adjuster["name"], "level": adjuster["level"],
                              "authority_limit": adjuster["authority_limit"]},
        "adjuster_has_authority": ok, "escalation_needed": not ok,
        "reinsurance": {"treaty": treaty["name"] if treaty else None,
                        "notice_threshold": treaty["notice_threshold"] if treaty else None,
                        "notice_required": bool(treaty and amount >= treaty["notice_threshold"])},
        "ladder": dict(AUTHORITY_LADDER),
    })


# ==========================================
# Analytics tool (assistant only)
# ==========================================

_FORBIDDEN = re.compile(r"\b(insert|update|delete|drop|alter|create|attach|detach|pragma|replace|vacuum)\b", re.I)


@tool
def run_sql_query(sql: str) -> str:
    """Run ONE read-only SQLite SELECT against the insurance database and return up to 50 rows as JSON.
    Tables: policyholders, policies, policy_coverages, claims (these four are effective-dated: one row per change, so
    prefer the views policyholders_current, policies_current, policy_coverages_current, claims_current for 'latest'
    answers), claim_notes, claim_documents, claim_payments, adjusters, vendors, siu_cases, underwriting_submissions,
    catastrophe_events, reinsurance_treaties, state_regulations, meta.
    Use this for portfolio questions (counts, totals, loss ratios, trends)."""
    statement = sql.strip().rstrip(";")
    if ";" in statement or not re.match(r"^(select|with)\b", statement, re.I) or _FORBIDDEN.search(statement):
        return "REJECTED: only a single read-only SELECT statement is allowed."
    try:
        rows = db.query(statement)
    except Exception as exc:
        return f"SQL ERROR: {exc}. Check table and column names."
    log.info("run_sql_query", rows=len(rows))
    return _json({"row_count": len(rows), "rows": rows[:50], "truncated": len(rows) > 50})

### Tools for Underwriting Navigator

UW_LEVELS = ["UNDERWRITER", "SENIOR UNDERWRITER", "CHIEF UNDERWRITER"]
# (max annual premium, max TIV, max claims in 3 years) per level; the Chief UW has no ceiling
UW_AUTHORITY = [(25_000, 2_000_000, 2), (100_000, 10_000_000, 4)]
BASE_RATE = {"COMM_PROPERTY": 0.006, "GL": 0.009}  # share of total insured value / exposure base
STATE_FACTOR = {"FL": 1.35, "TX": 1.15, "LA": 1.30, "NY": 1.10, "CA": 1.10}
CAT_STATES = {"FL", "TX", "LA"}
HIGH_HAZARD = ("restaurant", "roofing", "woodwork", "machine shop", "chemical", "demolition", "bar")
TIERS = [(25, "PREFERRED", 0.90), (45, "STANDARD", 1.00), (65, "ELEVATED", 1.25), (101, "HIGH", 1.60)]


def load_submission(submission_id: str) -> dict | None:
    return db.one("SELECT * FROM underwriting_submissions WHERE submission_id = ?", (submission_id.strip().upper(),))


def applicant_history(customer_id: str | None) -> dict:
    """What the database knows about an existing customer: policies, claims (latest versions), notes insights."""
    if not customer_id:
        return {"existing_customer": False}
    holder = db.one("SELECT customer_id, name, type, state, customer_since, credit_tier FROM policyholders_current WHERE customer_id = ?",
                    (customer_id,))
    if not holder:
        return {"existing_customer": False}
    policies = db.query("SELECT policy_id, line, status, annual_premium, effective_date, expiry_date FROM policies_current "
                        "WHERE customer_id = ?", (customer_id,))
    claims = db.query("SELECT claim_id, line, loss_date, cause_of_loss, status, claimed_amount, reserve_amount, paid_amount, "
                      "siu_referred FROM claims_current WHERE customer_id = ? ORDER BY loss_date DESC", (customer_id,))
    for c in claims:
        note = db.one("SELECT underwriting_insights, what_happened, damages FROM claim_notes WHERE claim_id = ? "
                      "AND underwriting_insights IS NOT NULL ORDER BY note_seq DESC LIMIT 1", (c["claim_id"],))
        c["underwriting_insight"] = note["underwriting_insights"] if note else None
        c["damages"] = note["damages"] if note else None
    premium = sum(p["annual_premium"] for p in policies if p["status"] == "ACTIVE")
    paid = sum(c["paid_amount"] or 0 for c in claims)
    open_claims = [c for c in claims if c["status"] not in ("PAID", "DENIED", "CLOSED")]
    return {"existing_customer": True, "customer": holder, "policies": policies, "active_annual_premium": premium,
            "claim_count": len(claims), "total_paid": paid, "open_claims": len(open_claims),
            "open_incurred_reserve": sum(c["reserve_amount"] or 0 for c in open_claims),
            "siu_referred_claims": sum(1 for c in claims if c["siu_referred"]), "claims": claims[:10]}


def assess_submission(submission_id: str) -> dict | None:
    """Risk score (0-100), tier, indicated premium, required authority, referral decision and subjectivities."""
    sub = load_submission(submission_id)
    if not sub:
        return None
    hist = applicant_history(sub["customer_id"])
    notes = (sub["application_notes"] or "").lower()
    industry = (sub["industry"] or "").lower()
    drivers: list[tuple[int, str]] = []
    hard: list[str] = []           # reasons that force a manual referral regardless of the score
    conditions: list[str] = []

    lr = sub["loss_ratio_3yr"] or 0
    if lr > 1.0:
        drivers.append((25, f"3-year loss ratio {lr:.0%} is above 100%"))
    elif lr > 0.7:
        drivers.append((15, f"3-year loss ratio {lr:.0%} is above 70%"))
    elif lr > 0.5:
        drivers.append((8, f"3-year loss ratio {lr:.0%} is above 50%"))
    n = sub["claims_3yr"] or 0
    if n >= 5:
        drivers.append((20, f"{n} claims in 3 years"))
    elif n >= 3:
        drivers.append((12, f"{n} claims in 3 years"))
    elif n == 2:
        drivers.append((5, "2 claims in 3 years"))
    roof = sub["roof_age_years"] or 0
    if sub["line"] == "COMM_PROPERTY":
        if roof > 20:
            drivers.append((10, f"Roof is {roof} years old (>20)"))
            conditions.append("Wind/hail on actual-cash-value basis for the roof (roof older than 20 years).")
        elif roof > 15:
            drivers.append((5, f"Roof is {roof} years old (>15)"))
        if sub["state"] in CAT_STATES:
            drivers.append((10, f"{sub['state']} coastal catastrophe exposure"))
            conditions.append("Named-storm / hurricane deductible of 2% of the building limit applies.")
    pc = sub["protection_class"] or 0
    if pc >= 8:
        drivers.append((10, f"Protection class {pc} (poor fire protection)"))
    elif pc >= 6:
        drivers.append((5, f"Protection class {pc}"))
    if any(h in industry for h in HIGH_HAZARD):
        drivers.append((10, f"High-hazard class: {sub['industry']}"))
    if "non-renew" in notes:
        drivers.append((10, "Prior carrier non-renewed"))
        hard.append("Prior carrier non-renewed the risk")
    if "without written safety" in notes or "no written safety" in notes:
        drivers.append((10, "No written safety program with subcontractors"))
        conditions.append("Written safety program and certificates of insurance for all subcontractors before binding.")
    if "vacant" in notes:
        hard.append("Possible vacancy: vacant buildings over 60 days are ineligible")
    if re.search(r"misrepresent|undisclosed", notes):
        hard.append("Possible material misrepresentation on the application")
    if hist["existing_customer"]:
        if hist["siu_referred_claims"]:
            drivers.append((10, f"{hist['siu_referred_claims']} existing claim(s) referred to SIU"))
            hard.append("Existing customer has claims referred to SIU")
        if hist["open_claims"]:
            drivers.append((5, f"{hist['open_claims']} open claim(s), reserve ${hist['open_incurred_reserve']:,.0f}"))
            conditions.append("Confirm the open claim outcome and any required repairs before renewing/increasing limits.")

    score = min(100, sum(p for p, _ in drivers))
    tier, tier_factor = next((t, f) for lim, t, f in TIERS if score < lim)

    tiv = sub["total_insured_value"] or 0
    base = tiv * BASE_RATE.get(sub["line"], 0.006)
    state_f = STATE_FACTOR.get(sub["state"], 1.0)
    loss_mod = max(0.9, min(1.4, 1 + (lr - 0.6) * 0.25))
    premium = round(base * state_f * tier_factor * loss_mod, 2)

    # Authority: the highest level triggered by premium, TIV or claim count
    level = 0
    for i, (max_prem, max_tiv, max_claims) in enumerate(UW_AUTHORITY):
        if premium > max_prem or tiv > max_tiv or n > max_claims:
            level = i + 1
    authority = UW_LEVELS[level]

    # Underwriting guideline: single risks above $10M exceed treaty capacity and must be notified to Reinsurance
    treaty = db.one("SELECT name FROM reinsurance_treaties WHERE ',' || line || ',' LIKE '%,' || ? || ',%'", (sub["line"],))
    reinsurance = bool(treaty and tiv > UW_AUTHORITY[-1][1])
    if reinsurance:
        conditions.append(f"Notify Reinsurance ({treaty['name']}): insured value ${tiv:,.0f} is above $10,000,000 treaty capacity.")
        hard.append("Risk above treaty capacity")
    if sub["line"] == "GL" and "roofing" in industry:
        conditions.append("Exclude work above 3 storeys unless a written fall-protection program is on file.")

    referral_reasons = list(hard)
    if level > 0:
        referral_reasons.append(f"Exceeds Underwriter authority (needs {authority})")
    if score >= 45:
        referral_reasons.append(f"Risk score {score} is ELEVATED or higher")
    referral = bool(referral_reasons)

    if score >= 75 or any("ineligible" in r for r in hard):
        recommendation = "DECLINE"
    elif referral:
        recommendation = "REFER TO " + authority
    elif conditions:
        recommendation = "QUOTE WITH CONDITIONS"
    else:
        recommendation = "QUOTE"
    return {
        "submission_id": sub["submission_id"], "applicant": sub["applicant"], "line": sub["line"], "state": sub["state"],
        "business_type": "RENEWAL / EXISTING CUSTOMER" if hist["existing_customer"] else "NEW BUSINESS",
        "risk_score": score, "risk_tier": tier, "risk_drivers": [{"points": p, "driver": d} for p, d in drivers],
        "pricing": {"total_insured_value": tiv, "base_rate_pct": BASE_RATE.get(sub["line"], 0.006) * 100,
                    "base_premium": round(base, 2), "state_factor": state_f, "tier_factor": tier_factor,
                    "loss_experience_factor": round(loss_mod, 3), "indicated_annual_premium": premium,
                    "suggested_range": [round(premium * 0.95, 2), round(premium * 1.10, 2)]},
        "required_authority": authority, "referral_required": referral, "referral_reasons": referral_reasons,
        "recommendation": recommendation, "conditions": conditions, "reinsurance_notice_required": reinsurance,
        "applicant_history": {k: v for k, v in hist.items() if k not in ("claims", "policies")},
    }


@tool
def get_submission(submission_id: str) -> str:
    """Return the underwriting application: applicant, line, state, industry, insured value, loss history, roof age,
    protection class, application notes and any linked existing customer id. Ids look like SUB-DEMO-01."""
    sub = load_submission(submission_id)
    return _json(sub) if sub else f"NOT FOUND: no submission '{submission_id}'. Ids look like SUB-DEMO-01."


@tool
def assess_submission_risk(submission_id: str) -> str:
    """Deterministic underwriting engine: risk score 0-100, tier, every risk driver, indicated annual premium and
    pricing factors, required underwriting authority, whether manual referral is required (and why), recommendation,
    conditions/subjectivities and reinsurance notice. Always use this for numbers; never compute pricing yourself."""
    result = assess_submission(submission_id)
    return _json(result) if result else f"NOT FOUND: no submission '{submission_id}'."


@tool
def get_applicant_loss_history(submission_id: str) -> str:
    """For an applicant that is already a Cardinal Ridge customer (renewal / cross-sell): policies, every claim with its
    latest status, amounts, SIU flag and the underwriting insights from the claim notes. New business returns the
    prior-carrier loss figures stated on the application."""
    sub = load_submission(submission_id)
    if not sub:
        return f"NOT FOUND: no submission '{submission_id}'."
    hist = applicant_history(sub["customer_id"])
    stated = {"claims_3yr": sub["claims_3yr"], "loss_ratio_3yr": sub["loss_ratio_3yr"]}
    return _json({"submission_id": sub["submission_id"], "stated_on_application": stated,
                  "internal_history": hist if hist["existing_customer"] else "No internal history: new business."})


@tool
def request_manual_review(submission_id: str, referral_authority: str, reason: str) -> str:
    """File a referral to a senior underwriter for manual review. SIDE EFFECT: a human reviewer must approve this call
    (Human-in-the-Loop). referral_authority is one of: SENIOR UNDERWRITER, CHIEF UNDERWRITER."""
    ref = "REF-" + uuid.uuid4().hex[:8].upper()
    return json.dumps({"referral_id": ref, "submission_id": submission_id.upper(), "queue": referral_authority,
                       "reason": reason, "status": "FILED"})
