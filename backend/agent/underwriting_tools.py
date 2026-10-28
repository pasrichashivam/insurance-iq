"""Tools for the Underwriter Navigator agents (new business and renewals).

Same principle as agent/tools.py: the risk score, the indicated premium and the required authority are computed by
plain Python rules (mirroring cardinal_ridge_underwriting_guidelines.pdf). The LLM selects tools and writes the memo;
it never invents numbers. `request_manual_review` is the only tool with a side effect (it files a referral), so it is the
one that is gated by the Human-in-the-Loop middleware (see agent/underwriter.py).
"""
import json
import re
import uuid

from langchain_core.tools import tool

from agent import insurance_db as db
from agent.tools import _json, search_company_guidelines  # noqa: F401  (re-exported for the agents)

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
