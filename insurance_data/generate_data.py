"""Generate the structured data for Cardinal Ridge Insurance Group (a FICTIONAL US insurer).

    python insurance_data/generate_data.py

Writes (deterministic - same seed, same data every run):
    backend/data/cardinal_ridge.db   SQLite database the agents query (read-only)
    insurance_data/csv/*.csv         the same tables as CSV, for Excel / BI / inspection

Everything is made up: names, addresses, phone numbers and e-mails (example.com) are random.
Fraud patterns are PLANTED on purpose so the Fraud/SIU agent has something real to find:
    * three "ring" vendors with many claims just under the $10,000 adjuster authority limit
    * repeat claimants (3+ claims in 24 months)
    * losses shortly after policy inception, late reporting, lapsed-policy losses
Six hand-built DEMO claims (CLM-DEMO-01 ... 06) cover the classic scenarios; see the README.
"""
import csv
import random
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import enrich  # noqa: E402  (history, claim notes, claim documents)

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / "backend" / "data" / "cardinal_ridge.db"
CSV_DIR = Path(__file__).resolve().parent / "csv"

AS_OF = date(2026, 10, 1)  # "today" inside the dataset; all deadline maths uses this
rng = random.Random(20261001)

STATES = {"OH": 24, "TX": 22, "FL": 16, "CA": 16, "NY": 12, "IL": 10}
CITIES = {
    "OH": [("Columbus", "432"), ("Cleveland", "441"), ("Cincinnati", "452"), ("Toledo", "436")],
    "TX": [("Houston", "770"), ("Dallas", "752"), ("Austin", "787"), ("San Antonio", "782")],
    "FL": [("Miami", "331"), ("Tampa", "336"), ("Orlando", "328"), ("Jacksonville", "322")],
    "CA": [("Los Angeles", "900"), ("San Diego", "921"), ("Sacramento", "958"), ("Fresno", "937")],
    "NY": [("New York", "100"), ("Buffalo", "142"), ("Albany", "122"), ("Rochester", "146")],
    "IL": [("Chicago", "606"), ("Springfield", "627"), ("Naperville", "605"), ("Peoria", "616")],
}
FIRST = ["James", "Mary", "Robert", "Patricia", "John", "Jennifer", "Michael", "Linda", "David", "Elizabeth",
         "William", "Barbara", "Richard", "Susan", "Joseph", "Jessica", "Thomas", "Sarah", "Daniel", "Karen",
         "Carlos", "Maria", "Wei", "Priya", "Omar", "Aisha", "Luis", "Ana", "Kevin", "Nicole", "Brandon", "Tiffany"]
LAST = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez",
        "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin",
        "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson",
        "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Patel"]
BUSINESS = ["Bakery", "Dental Group", "Logistics", "Roofing", "Machine Shop", "Restaurant Group", "Landscaping",
            "Auto Repair", "Medical Billing", "Construction", "Print Shop", "Fitness Studio", "Warehouse Co",
            "Plumbing", "Electric", "Packaging"]

# line -> list of (cause_of_loss, coverage_code, weight, (min_amt, max_amt))
CAUSES = {
    "AUTO": [("COLLISION", "COLLISION", 45, (1200, 16000)), ("HAIL", "COMPREHENSIVE", 12, (900, 9000)),
             ("THEFT", "COMPREHENSIVE", 8, (4000, 32000)), ("GLASS", "COMPREHENSIVE", 12, (250, 1400)),
             ("VANDALISM", "COMPREHENSIVE", 5, (500, 5000)), ("LIABILITY_PD", "PD_LIABILITY", 12, (1500, 30000)),
             ("LIABILITY_BI", "BI_LIABILITY", 6, (6000, 90000))],
    "HOME": [("WATER_DAMAGE", "DWELLING", 28, (2500, 38000)), ("WIND_HAIL", "DWELLING", 24, (3000, 45000)),
             ("FIRE", "DWELLING", 8, (15000, 260000)), ("THEFT", "PERSONAL_PROPERTY", 14, (800, 12000)),
             ("LIGHTNING", "DWELLING", 6, (1500, 20000)), ("FLOOD", "DWELLING", 8, (8000, 90000)),
             ("LIABILITY", "HOME_LIABILITY", 12, (2000, 60000))],
    "COMM_PROPERTY": [("FIRE", "BUILDING", 20, (40000, 700000)), ("WATER_DAMAGE", "BUILDING", 30, (8000, 120000)),
                      ("THEFT", "BPP", 20, (3000, 60000)), ("WIND_HAIL", "BUILDING", 20, (10000, 200000)),
                      ("BUSINESS_INTERRUPTION", "BUSINESS_INCOME", 10, (15000, 180000))],
    "GL": [("SLIP_FALL", "GL_OCCURRENCE", 50, (8000, 250000)), ("PROPERTY_DAMAGE_3P", "GL_OCCURRENCE", 30, (3000, 90000)),
           ("PRODUCT_LIABILITY", "GL_OCCURRENCE", 20, (15000, 400000))],
    "WC": [("STRAIN", "WC_STATUTORY", 40, (4000, 70000)), ("SLIP_FALL", "WC_STATUTORY", 30, (6000, 110000)),
           ("MACHINERY", "WC_STATUTORY", 15, (20000, 260000)), ("REPETITIVE_MOTION", "WC_STATUTORY", 15, (5000, 60000))],
}

# state -> (ack days, decision days, payment days, unit, statute, late interest, notes).
# Simplified for DEMO use - always verify against the current statute / regulation.
STATE_RULES = {
    "TX": (15, 15, 5, "business", "Tex. Ins. Code ch. 542 (Prompt Payment of Claims Act)", 0.18,
           "Penalty interest 18%/yr plus attorney fees for late payment."),
    "FL": (7, 60, 60, "calendar", "Fla. Stat. 627.70131 / 626.9541", 0.12,
           "Pay or deny within 60 days of notice; statutory interest on late payment."),
    "CA": (15, 40, 30, "calendar", "Cal. Code Regs. tit. 10, 2695.5 and 2695.7", 0.10,
           "Accept/deny within 40 days of proof of claim; pay within 30 days of acceptance."),
    "NY": (15, 15, 5, "business", "N.Y. Comp. Codes R. & Regs. tit. 11, part 216 (Reg. 64)", 0.09,
           "Decision within 15 business days of proof of loss; 9% statutory interest."),
    "OH": (15, 21, 10, "calendar", "Ohio Adm. Code 3901-1-54", 0.05,
           "Decision within 21 days of proof of loss; payment within 10 days of settlement."),
    "IL": (10, 30, 30, "business", "215 ILCS 5/154.6 and 50 Ill. Adm. Code 919", 0.09,
           "Acknowledge within 10 working days; 9% interest plus penalties for vexatious delay."),
}
VENDOR_TYPES = ["BODY_SHOP", "CONTRACTOR", "MEDICAL_CLINIC", "ATTORNEY", "TOW_STORAGE", "PUBLIC_ADJUSTER"]


def pick_state():
    return rng.choices(list(STATES), weights=list(STATES.values()))[0]


def add_days(d, n, business=False):
    if not business:
        return d + timedelta(days=n)
    while n > 0:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


SCHEMA = """
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE state_regulations (
  state TEXT PRIMARY KEY, ack_days INTEGER, decision_days INTEGER, payment_days INTEGER,
  day_unit TEXT, statute TEXT, late_interest_rate REAL, notes TEXT);
CREATE TABLE adjusters (
  adjuster_id TEXT PRIMARY KEY, name TEXT, state TEXT, level TEXT, authority_limit INTEGER,
  specialty TEXT, open_claims INTEGER);
CREATE TABLE policyholders (
  customer_id TEXT, name TEXT, type TEXT, state TEXT, city TEXT, zip TEXT,
  email TEXT, phone TEXT, customer_since INTEGER, credit_tier TEXT, address_changes_12m INTEGER,
  version_no INTEGER, valid_from TEXT, valid_to TEXT, is_current INTEGER, change_type TEXT, change_note TEXT, PRIMARY KEY (customer_id, version_no));
CREATE TABLE policies (
  policy_id TEXT, customer_id TEXT, line TEXT, state TEXT, effective_date TEXT,
  expiry_date TEXT, status TEXT, cancel_date TEXT, cancel_reason TEXT, annual_premium REAL,
  producer TEXT, version_no INTEGER, valid_from TEXT, valid_to TEXT, is_current INTEGER, change_type TEXT, change_note TEXT, PRIMARY KEY (policy_id, version_no));
CREATE TABLE policy_coverages (
  policy_id TEXT, coverage_code TEXT, limit_amount REAL, deductible REAL,
  version_no INTEGER, valid_from TEXT, valid_to TEXT, is_current INTEGER, change_type TEXT, change_note TEXT, PRIMARY KEY (policy_id, coverage_code, version_no));
CREATE TABLE vendors (
  vendor_id TEXT PRIMARY KEY, name TEXT, type TEXT, state TEXT, city TEXT, tax_id TEXT,
  years_in_network INTEGER, preferred INTEGER);
CREATE TABLE claims (
  claim_id TEXT, policy_id TEXT, customer_id TEXT, line TEXT, state TEXT,
  loss_date TEXT, reported_date TEXT, cause_of_loss TEXT, coverage_code TEXT, description TEXT,
  status TEXT, claimed_amount REAL, reserve_amount REAL, paid_amount REAL, adjuster_id TEXT,
  vendor_id TEXT, catastrophe_code TEXT, acknowledged_date TEXT, decision_date TEXT,
  payment_date TEXT, denial_reason TEXT, siu_referred INTEGER,
  version_no INTEGER, valid_from TEXT, valid_to TEXT, is_current INTEGER, change_type TEXT, change_note TEXT, PRIMARY KEY (claim_id, version_no));
CREATE TABLE claim_payments (
  payment_id TEXT PRIMARY KEY, claim_id TEXT, payee TEXT, payment_type TEXT, amount REAL, payment_date TEXT);
CREATE TABLE siu_cases (
  case_id TEXT PRIMARY KEY, claim_id TEXT, vendor_id TEXT, opened_date TEXT, status TEXT,
  outcome TEXT, indicators TEXT);
CREATE TABLE underwriting_submissions (
  submission_id TEXT PRIMARY KEY, applicant TEXT, line TEXT, state TEXT, industry TEXT,
  total_insured_value REAL, loss_ratio_3yr REAL, claims_3yr INTEGER, protection_class INTEGER,
  roof_age_years INTEGER, submitted_date TEXT, status TEXT, referral_reason TEXT,
  customer_id TEXT, application_notes TEXT);
CREATE TABLE claim_notes (
  note_id TEXT PRIMARY KEY, claim_id TEXT, note_seq INTEGER, effective_date TEXT, note_type TEXT, author_role TEXT,
  what_happened TEXT, where_occurred TEXT, when_occurred TEXT, how_occurred TEXT, parties_involved TEXT,
  exposures TEXT, damages TEXT, injuries_reported INTEGER, underwriting_insights TEXT, note_text TEXT);
CREATE TABLE claim_documents (
  doc_id TEXT PRIMARY KEY, claim_id TEXT, doc_type TEXT, doc_date TEXT, received_date TEXT, vendor_id TEXT,
  invoice_number TEXT, invoice_amount REAL, file_name TEXT);
CREATE TABLE catastrophe_events (
  cat_code TEXT PRIMARY KEY, name TEXT, peril TEXT, state TEXT, event_date TEXT, claim_count INTEGER,
  incurred_estimate REAL);
CREATE TABLE reinsurance_treaties (
  treaty_id TEXT PRIMARY KEY, name TEXT, type TEXT, line TEXT, retention REAL, limit_amount REAL,
  cession_pct REAL, notice_threshold REAL, term_year INTEGER);
-- "current" views: the latest version of each record. Use these for portfolio questions.
CREATE VIEW policyholders_current AS SELECT * FROM policyholders WHERE is_current = 1;
CREATE VIEW policies_current AS SELECT * FROM policies WHERE is_current = 1;
CREATE VIEW policy_coverages_current AS SELECT * FROM policy_coverages WHERE is_current = 1;
CREATE VIEW claims_current AS SELECT * FROM claims WHERE is_current = 1;
"""

DESC = {
    "COLLISION": "Insured vehicle struck {x} at an intersection; damage to the front end.",
    "HAIL": "Hail storm damaged hood, roof and windshield of the insured vehicle.",
    "THEFT": "Reported theft of insured property; police report filed.",
    "GLASS": "Cracked windshield from road debris.",
    "VANDALISM": "Vehicle keyed and mirror broken while parked overnight.",
    "LIABILITY_PD": "Insured backed into a third-party vehicle in a parking lot.",
    "LIABILITY_BI": "Third party alleges neck and back injury after rear-end collision.",
    "WATER_DAMAGE": "Burst pipe caused water damage to {y}.",
    "WIND_HAIL": "Wind and hail damaged roof shingles and gutters.",
    "FIRE": "Fire originating in {y}; fire department responded.",
    "LIGHTNING": "Lightning strike damaged electrical panel and appliances.",
    "FLOOD": "Rising surface water entered the structure after heavy rain.",
    "LIABILITY": "Guest injured on the insured premises; medical bills submitted.",
    "BUSINESS_INTERRUPTION": "Operations suspended for repairs following covered loss.",
    "SLIP_FALL": "Customer or employee slipped on wet floor and was injured.",
    "PROPERTY_DAMAGE_3P": "Third-party property damaged by insured's operations.",
    "PRODUCT_LIABILITY": "Product sold by the insured allegedly caused injury.",
    "STRAIN": "Employee lifting injury to lower back.",
    "MACHINERY": "Employee hand injury while operating machinery.",
    "REPETITIVE_MOTION": "Employee reports carpal tunnel syndrome from repetitive work.",
}


def describe(cause):
    return DESC.get(cause, "Loss reported by the insured.").format(
        x=rng.choice(["a parked car", "a guardrail", "a utility pole", "another vehicle"]),
        y=rng.choice(["the kitchen", "the basement", "the attic", "the garage", "the warehouse"]))


def build():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    CSV_DIR.mkdir(parents=True, exist_ok=True)
    if DB_PATH.exists():
        DB_PATH.unlink()
    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)

    def ins(table, rows):
        if rows:
            con.executemany(f"INSERT INTO {table} VALUES ({','.join('?' * len(rows[0]))})", rows)

    ins("meta", [("company", "Cardinal Ridge Insurance Group (fictional)"), ("as_of_date", AS_OF.isoformat()),
                 ("note", "All data is synthetic. Generated by insurance_data/generate_data.py")])
    ins("state_regulations", [(s, *v[:3], v[3], v[4], v[5], v[6]) for s, v in STATE_RULES.items()])

    # ---- adjusters -------------------------------------------------------------
    levels = [("JUNIOR", 10_000), ("SENIOR", 50_000), ("MANAGER", 250_000), ("DIRECTOR", 1_000_000)]
    adjusters = []
    for i in range(1, 31):
        lvl, lim = rng.choices(levels, weights=[40, 35, 18, 7])[0]
        adjusters.append([f"ADJ-{i:03d}", f"{rng.choice(FIRST)} {rng.choice(LAST)}", pick_state(), lvl, lim,
                          rng.choice(["AUTO", "HOME", "COMM_PROPERTY", "GL", "WC"]), 0])
    adjusters[0] = ["ADJ-001", "Rachel Moore", "TX", "JUNIOR", 10_000, "AUTO", 0]
    adjusters[3] = ["ADJ-004", "Greg Hollis", "IL", "SENIOR", 50_000, "COMM_PROPERTY", 0]
    ins("adjusters", adjusters)
    adj_by_state = {s: [a for a in adjusters if a[2] == s and a[3] != "DIRECTOR"] or adjusters[:5] for s in STATES}

    # ---- vendors (3 ring vendors are planted) -----------------------------------
    vendors, ring = [], []
    for i in range(1, 61):
        st = pick_state()
        vendors.append([f"VND-{i:03d}", f"{rng.choice(LAST)} {rng.choice(['Collision', 'Restoration', 'Medical', 'Legal', 'Towing', 'Claims Services'])}",
                        rng.choice(VENDOR_TYPES), st, rng.choice(CITIES[st])[0],
                        f"{rng.randint(10, 99)}-{rng.randint(1000000, 9999999)}", rng.randint(1, 15), int(rng.random() < 0.5)])
    for vid, nm, vt, st in [("VND-901", "QuickFix Collision Center", "BODY_SHOP", "TX"),
                            ("VND-902", "Sunshine Storm Restoration LLC", "CONTRACTOR", "FL"),
                            ("VND-903", "Premier Injury & Rehab Clinic", "MEDICAL_CLINIC", "NY")]:
        vendors.append([vid, nm, vt, st, rng.choice(CITIES[st])[0], f"{rng.randint(10, 99)}-{rng.randint(1000000, 9999999)}", 1, 0])
        ring.append(vid)
    ins("vendors", vendors)

    def vendors_of(vtype, state):
        return [v[0] for v in vendors if v[2] == vtype and v[3] == state and v[0] not in ring]

    # ---- policyholders ----------------------------------------------------------
    holders = []
    for i in range(1, 1201):
        st = pick_state()
        city, z3 = rng.choice(CITIES[st])
        commercial = rng.random() < 0.14
        nm = f"{rng.choice(LAST)} {rng.choice(BUSINESS)}" if commercial else f"{rng.choice(FIRST)} {rng.choice(LAST)}"
        holders.append([f"CUS-{i:05d}", nm, "COMMERCIAL" if commercial else "PERSONAL", st, city, f"{z3}{rng.randint(10, 99)}",
                        f"customer{i}@example.com", f"555-01{rng.randint(0, 99):02d}", rng.randint(2005, 2026),
                        rng.choices(["A", "B", "C", "D"], weights=[35, 40, 20, 5])[0],
                        rng.choices([0, 1, 2, 3], weights=[85, 10, 4, 1])[0]])

    # ---- policies + coverages ---------------------------------------------------
    policies, coverages = [], []
    cov_index = {}  # (policy_id, coverage_code) -> deductible
    pol_meta = {}   # policy_id -> (customer, line, effective, expiry, cancel_date)
    pol_n = 0

    def make_policy(cust, line, eff, status="ACTIVE", cancel=None, reason=None, pid=None, ded=None):
        nonlocal pol_n
        pol_n += 1
        st = cust[3]
        pid = pid or f"POL-{line[:3]}-{pol_n:06d}"
        exp = eff.replace(year=eff.year + 1, day=28) if (eff.month == 2 and eff.day == 29) else eff.replace(year=eff.year + 1)
        if status == "ACTIVE" and exp < AS_OF:
            status = "EXPIRED"
        if line == "AUTO":
            ded = ded or rng.choice([250, 500, 1000])
            prem = rng.uniform(900, 3200)
            covs = [("BI_LIABILITY", rng.choice([50000, 100000, 250000]), 0), ("PD_LIABILITY", rng.choice([25000, 50000, 100000]), 0),
                    ("COLLISION", rng.choice([25000, 40000, 60000]), ded), ("COMPREHENSIVE", rng.choice([25000, 40000, 60000]), ded),
                    ("MEDPAY", 5000, 0)]
        elif line == "HOME":
            dwell = rng.choice([180000, 240000, 320000, 450000, 650000])
            ded = ded or rng.choice([1000, 2500, 5000])
            prem = dwell * rng.uniform(0.0045, 0.012) * (1.9 if st in ("FL", "TX") else 1)
            covs = [("DWELLING", dwell, ded), ("PERSONAL_PROPERTY", dwell * 0.5, ded), ("HOME_LIABILITY", 300000, 0),
                    ("ADDITIONAL_LIVING", dwell * 0.2, 0)]
            if rng.random() < 0.08 and pid.find("DEMO") < 0:
                covs.append(("FLOOD", min(dwell, 250000), 2500))
        elif line == "COMM_PROPERTY":
            bld = rng.choice([500000, 900000, 1500000, 3000000])
            ded = ded or rng.choice([5000, 10000, 25000])
            prem = bld * rng.uniform(0.004, 0.009)
            covs = [("BUILDING", bld, ded), ("BPP", bld * 0.4, ded), ("BUSINESS_INCOME", bld * 0.3, 0)]
        elif line == "GL":
            prem = rng.uniform(2500, 18000)
            covs = [("GL_OCCURRENCE", 1000000, ded or 2500)]
        else:
            prem = rng.uniform(4000, 60000)
            covs = [("WC_STATUTORY", 1000000, 0)]
        if pid == "POL-COM-DEMO04":
            covs[0] = ("BUILDING", 1500000, ded)
        policies.append((pid, cust[0], line, st, eff.isoformat(), exp.isoformat(), status,
                         cancel.isoformat() if cancel else None, reason, round(prem, 2),
                         rng.choice(["Buckeye Agency Group", "Lone Star Insurance Partners", "Gulf Coast Brokers", "Pacific Risk Advisors",
                                     "Empire Insurance Services", "Prairie State Agency", "Direct (Online)"])))
        for c, lim, d in covs:
            coverages.append((pid, c, round(lim, 2), d))
            cov_index[(pid, c)] = d
        pol_meta[pid] = (cust, line, eff, exp, cancel)
        return pid

    for cust in holders:
        lines = ["COMM_PROPERTY", "GL", "WC"] if cust[2] == "COMMERCIAL" else ["AUTO", "HOME"]
        for line in lines:
            if line in ("AUTO", "HOME") and rng.random() < (0.25 if line == "HOME" else 0.05):
                continue
            if cust[2] == "COMMERCIAL" and rng.random() < 0.4:
                continue
            for _ in range(rng.choice([1, 1, 2])):  # a renewal creates a second term
                eff = date(2024, 10, 1) + timedelta(days=rng.randint(0, 725))
                if eff > AS_OF - timedelta(days=5):
                    eff = AS_OF - timedelta(days=rng.randint(10, 300))
                status, cancel, reason = "ACTIVE", None, None
                if rng.random() < 0.045:
                    status, reason = "CANCELLED", "NON_PAYMENT"
                    cancel = min(eff + timedelta(days=rng.randint(60, 240)), AS_OF - timedelta(days=rng.randint(1, 20)))
                make_policy(cust, line, eff, status, cancel, reason)

    # ---- claims ------------------------------------------------------------------
    claims, payments = [], []
    clm_n = 0

    def cat_for(state, cause, loss):
        if cause in ("WIND_HAIL", "WATER_DAMAGE", "FLOOD", "LIGHTNING") and state in ("FL", "TX") and \
                date(2025, 8, 15) <= loss <= date(2025, 10, 30):
            return "CAT-2025-HURR-" + state
        if cause == "HAIL" and state == "TX" and date(2026, 4, 1) <= loss <= date(2026, 5, 20):
            return "CAT-2026-HAIL-TX"
        return None

    def lifecycle(rep, state, amount, denial):
        """Realistic claim timeline; ~9% of claims blow a regulatory deadline."""
        ackd, decd, payd, unit = STATE_RULES[state][:4]
        biz = unit == "business"
        late = rng.random() < 0.09
        ack = add_days(rep, rng.randint(0, ackd) + (rng.randint(2, 9) if late else 0), biz)
        if ack > AS_OF:
            return "OPEN", None, None, None, round(amount * 0.8, 2)
        decision = add_days(ack, rng.randint(2, decd) + (rng.randint(5, 25) if late else 0), biz)
        if decision > AS_OF:
            return ("UNDER_INVESTIGATION" if rng.random() < 0.25 else "OPEN"), ack, None, None, round(amount * 0.85, 2)
        if denial:
            return "DENIED", ack, decision, None, 0.0
        pay = add_days(decision, rng.randint(1, payd), biz)
        if pay > AS_OF:
            return "APPROVED", ack, decision, None, round(amount * 0.9, 2)
        return "PAID", ack, decision, pay, 0.0

    def add_claim(cid, pol, cause, cov, amount, loss, rep, desc, vendor=None, adj=None, denial=None, demo=None):
        """demo = (status, ack_date) forces a hand-built open/in-flight state."""
        cust, line, _, _, _ = pol_meta[pol]
        st = cust[3]
        if demo:
            status, ack, dec, pay, reserve = demo[0], demo[1], None, None, round(amount * 0.9, 2)
        else:
            status, ack, dec, pay, reserve = lifecycle(rep, st, amount, denial)
        paid = 0.0
        if status == "PAID":
            paid = round(max(amount - cov_index.get((pol, cov), 0), 0) * rng.uniform(0.82, 1.0), 2)
        claims.append([cid, pol, cust[0], line, st, loss.isoformat(), rep.isoformat(), cause, cov, desc, status,
                       round(amount, 2), reserve, paid, adj or rng.choice(adj_by_state[st])[0], vendor,
                       cat_for(st, cause, loss), ack.isoformat() if ack else None, dec.isoformat() if dec else None,
                       pay.isoformat() if pay else None, denial if status == "DENIED" else None, 0])
        if paid and pay:
            n = min(max(1, round(paid / 25000)), 3)
            for k in range(n):
                payments.append([f"PAY-{len(payments) + 1:07d}", cid, "Policyholder" if k == 0 else (vendor or "Vendor"),
                                 "INDEMNITY" if k == 0 else "EXPENSE", round(paid / n, 2), (pay + timedelta(days=k * 3)).isoformat()])

    def window(pid):
        cust, line, eff, exp, cancel = pol_meta[pid]
        return eff, min(exp, cancel or exp, AS_OF)

    pol_ids = list(pol_meta)
    while len(claims) < 1500:
        pid = rng.choice(pol_ids)
        cust, line = pol_meta[pid][:2]
        eff, end = window(pid)
        if end <= eff + timedelta(days=3):
            continue
        cause, cov, _, (lo, hi) = rng.choices(CAUSES[line], weights=[c[2] for c in CAUSES[line]])[0]
        if (pid, cov) not in cov_index:
            continue
        loss = eff + timedelta(days=rng.randint(1, (end - eff).days))
        # cluster catastrophe losses
        if cause == "HAIL" and cust[3] == "TX" and rng.random() < 0.5:
            loss = date(2026, 4, 1) + timedelta(days=rng.randint(0, 48))
        elif line == "HOME" and cust[3] in ("FL", "TX") and cause in ("WIND_HAIL", "WATER_DAMAGE", "FLOOD") and rng.random() < 0.45:
            loss = date(2025, 9, 10) + timedelta(days=rng.randint(0, 10))
        if not (eff <= loss <= end):
            continue
        lag = rng.choices([0, 1, 2, 3, 5, 10, 21, 45, 90], weights=[30, 25, 15, 10, 8, 5, 4, 2, 1])[0]
        rep = min(loss + timedelta(days=lag), AS_OF)
        amount = round(rng.uniform(lo, hi), 2) if rng.random() < 0.85 else float(round(rng.uniform(lo, hi), -3))
        denial = None
        if cause == "FLOOD":
            if (pid, "FLOOD") in cov_index:
                cov = "FLOOD"
            else:
                denial = "Flood is excluded under the HO-3 form; no flood endorsement on policy."
        vendor = None
        if line == "AUTO" and cause in ("COLLISION", "HAIL") and rng.random() < 0.6:
            vendor = rng.choice(vendors_of("BODY_SHOP", cust[3]) or [None])
        if line in ("HOME", "COMM_PROPERTY") and rng.random() < 0.5:
            vendor = rng.choice(vendors_of("CONTRACTOR", cust[3]) or [None])
        clm_n += 1
        add_claim(f"CLM-{rep.year}-{clm_n:06d}", pid, cause, cov, amount, loss, rep, describe(cause), vendor, denial=denial)

    # planted: repeat claimants (3-5 claims on one policy)
    for cid in rng.sample([h[0] for h in holders if h[2] == "PERSONAL"], 14):
        mine = [p for p, m in pol_meta.items() if m[0][0] == cid and m[1] in ("AUTO", "HOME") and m[4] is None]
        if not mine:
            continue
        pid = mine[0]
        line = pol_meta[pid][1]
        eff, end = window(pid)
        if end <= eff + timedelta(days=60):
            continue
        for _ in range(rng.randint(3, 5)):
            cause, cov, _w, (lo, hi) = rng.choice(CAUSES[line])
            if (pid, cov) not in cov_index or cause == "FLOOD":
                continue
            loss = eff + timedelta(days=rng.randint(5, (end - eff).days))
            clm_n += 1
            add_claim(f"CLM-{loss.year}-{clm_n:06d}", pid, cause, cov, rng.uniform(lo, hi), loss,
                      min(loss + timedelta(days=rng.randint(0, 3)), AS_OF), describe(cause))

    # planted: ring vendors - many claims just under the $10k authority limit
    for vid, line, options in [("VND-901", "AUTO", [("COLLISION", "COLLISION")]),
                               ("VND-902", "HOME", [("WIND_HAIL", "DWELLING"), ("WATER_DAMAGE", "DWELLING")]),
                               ("VND-903", "AUTO", [("LIABILITY_BI", "BI_LIABILITY")])]:
        vstate = next(v[3] for v in vendors if v[0] == vid)
        cands = [p for p, m in pol_meta.items() if m[1] == line and m[0][3] == vstate and m[4] is None]
        for pid in rng.sample(cands, min(22, len(cands))):
            eff, end = window(pid)
            if end <= eff + timedelta(days=20):
                continue
            cause, cov = rng.choice(options)
            loss = eff + timedelta(days=rng.randint(10, (end - eff).days))
            clm_n += 1
            add_claim(f"CLM-{loss.year}-{clm_n:06d}", pid, cause, cov, round(rng.uniform(9200, 9980), 2), loss,
                      min(loss + timedelta(days=rng.randint(0, 2)), AS_OF), describe(cause), vendor=vid)

    # ---- hand-built DEMO claims ---------------------------------------------------
    def new_customer(name, state, kind="PERSONAL", since=2026, changes=0):
        city, z3 = rng.choice(CITIES[state])
        n = len(holders) + 1
        rec = [f"CUS-{n:05d}", name, kind, state, city, f"{z3}{rng.randint(10, 99)}", f"customer{n}@example.com",
               "555-0199", since, "C", changes]
        holders.append(rec)
        return rec

    # D01 Auto TX - loss 12 days after inception, ring body shop, $150 under authority, reported 38 days late
    pid = make_policy(new_customer("Dwayne Kessler", "TX", changes=2), "AUTO", date(2026, 6, 1), pid="POL-AUT-DEMO01", ded=500)
    add_claim("CLM-DEMO-01", pid, "COLLISION", "COLLISION", 9850.00, date(2026, 6, 13), date(2026, 7, 21),
              "Single-vehicle collision with a pole; vehicle towed to QuickFix Collision Center. No witnesses, no police report.",
              vendor="VND-901", adj="ADJ-001", demo=("UNDER_INVESTIGATION", date(2026, 7, 23)))
    # D02 Home FL - flood, no flood endorsement, decision overdue (FL: 60 days)
    pid = make_policy(new_customer("Marisol & Hector Alvarez", "FL", since=2019), "HOME", date(2025, 11, 1), pid="POL-HOM-DEMO02", ded=5000)
    add_claim("CLM-DEMO-02", pid, "FLOOD", "DWELLING", 74500.00, date(2026, 7, 14), date(2026, 7, 18),
              "Storm surge and rising water entered the ground floor during a tropical storm; flooring, drywall and cabinets damaged.",
              vendor="VND-902", adj="ADJ-002", denial=None, demo=("OPEN", date(2026, 7, 20)))
    # D03 Auto CA - clean small glass claim
    pid = make_policy(new_customer("Priya Raman", "CA", since=2016), "AUTO", date(2026, 2, 1), pid="POL-AUT-DEMO03", ded=500)
    add_claim("CLM-DEMO-03", pid, "GLASS", "COMPREHENSIVE", 640.00, date(2026, 9, 20), date(2026, 9, 21),
              "Windshield cracked by gravel on Interstate 5; photos and repair estimate attached.", adj="ADJ-003",
              demo=("OPEN", date(2026, 9, 22)))
    # D04 Commercial property IL - $620k fire: authority escalation + reinsurance notice
    pid = make_policy(new_customer("Prairie Ridge Packaging Co", "IL", kind="COMMERCIAL", since=2012), "COMM_PROPERTY",
                      date(2026, 1, 15), pid="POL-COM-DEMO04", ded=25000)
    add_claim("CLM-DEMO-04", pid, "FIRE", "BUILDING", 620000.00, date(2026, 9, 3), date(2026, 9, 3),
              "Electrical fire in the production hall; sprinklers activated; fire marshal report pending. Building and equipment partially destroyed.",
              adj="ADJ-004", demo=("OPEN", date(2026, 9, 4)))
    # D05 WC NY - late reported, unwitnessed, ring clinic, repeat claimant
    pid = make_policy(new_customer("Hudson Valley Roofing", "NY", kind="COMMERCIAL", since=2021), "WC", date(2026, 3, 1), pid="POL-WC-DEMO05")
    add_claim("CLM-DEMO-05", pid, "SLIP_FALL", "WC_STATUTORY", 58000.00, date(2026, 7, 10), date(2026, 8, 20),
              "Roofer reports fall from ladder with shoulder injury; treated at Premier Injury & Rehab Clinic. Incident was unwitnessed.",
              vendor="VND-903", adj="ADJ-005", demo=("OPEN", date(2026, 8, 25)))
    for k in (1, 2):
        clm_n += 1
        add_claim(f"CLM-2026-{clm_n:06d}", pid, "STRAIN", "WC_STATUTORY", 12000 + k * 900, date(2026, 3, 20 + k),
                  date(2026, 3, 22 + k), "Employee back strain.", vendor="VND-903")
    # D06 Auto OH - policy cancelled for non-payment BEFORE the loss
    pid = make_policy(new_customer("Terrence Boyd", "OH"), "AUTO", date(2026, 1, 10), "CANCELLED", date(2026, 6, 1),
                      "NON_PAYMENT", pid="POL-AUT-DEMO06", ded=1000)
    add_claim("CLM-DEMO-06", pid, "COLLISION", "COLLISION", 14200.00, date(2026, 7, 4), date(2026, 7, 6),
              "Rear-end collision on I-71; insured vehicle has front and rear damage.", adj="ADJ-006",
              demo=("OPEN", date(2026, 7, 8)))

    ins("claim_payments", payments)

    # ---- SIU cases: ring-vendor claims + a sample of others (demo claims stay undiscovered) --------
    pool = [c for c in claims if not c[0].startswith("CLM-DEMO")]
    sus = [c for c in pool if c[15] in ring and rng.random() < 0.55] + rng.sample([c for c in pool if c[15] not in ring], 25)
    siu = []
    for i, c in enumerate(sus, 1):
        outcome = rng.choice(["REFERRED_TO_STATE_DOI", "CLAIM_DENIED_MISREPRESENTATION", "UNFOUNDED", "OPEN", "OPEN"]) if c[15] in ring \
            else rng.choice(["UNFOUNDED", "OPEN", "CLAIM_REDUCED", "CLAIM_DENIED_MISREPRESENTATION"])
        indicators = rng.sample(["Inflated repair estimate", "Loss shortly after inception", "Late reporting", "Prior similar claims",
                                 "Inconsistent statements", "No police report", "Staged-accident pattern", "Duplicate invoice"], 3)
        opened = min(date.fromisoformat(c[6]) + timedelta(days=rng.randint(3, 20)), AS_OF)
        siu.append((f"SIU-{i:04d}", c[0], c[15], opened.isoformat(), "OPEN" if outcome == "OPEN" else "CLOSED", outcome, "; ".join(indicators)))
    ins("siu_cases", siu)
    siu_claims = {s[1] for s in siu}
    for c in claims:
        if c[0] in siu_claims:
            c[21] = 1

    # ---- effective-dated history (transactions) for customers, policies, coverages and claims ----------------
    siu_opened = {s[1]: date.fromisoformat(s[3]) for s in siu}
    ins("policyholders", enrich.holder_versions(holders, policies, CITIES, AS_OF))
    pol_rows, cov_rows = enrich.policy_versions(policies, coverages, AS_OF)
    ins("policies", pol_rows)
    ins("policy_coverages", cov_rows)
    claim_rows, _initial = enrich.claim_versions(claims, siu_opened, [a[0] for a in adjusters], AS_OF)
    ins("claims", claim_rows)
    vendor_names = {v[0]: v[1] for v in vendors}
    ins("claim_notes", enrich.build_notes(claims, claim_rows, siu_opened, vendor_names, AS_OF))
    ins("claim_documents", enrich.build_documents(claims, ring, AS_OF))

    # ---- underwriting submissions ---------------------------------------------------------
    subs = []
    industries = ["Restaurant", "Roofing contractor", "Warehouse", "Medical office", "Retail", "Machine shop", "Apartment building", "Auto dealership"]
    for i in range(1, 161):
        st = pick_state()
        tiv = rng.choice([450000, 900000, 1800000, 4500000, 9000000, 18000000])
        lr = round(rng.uniform(0.1, 1.6), 2)
        roof, pc = rng.randint(1, 32), rng.randint(1, 10)
        reasons = []
        if tiv > 10_000_000:
            reasons.append("TIV exceeds $10M underwriter authority")
        if lr > 0.75:
            reasons.append("3-year loss ratio above 75%")
        if st in ("FL", "TX") and roof > 20:
            reasons.append("Roof older than 20 years in wind-exposed state")
        if pc >= 9:
            reasons.append("Poor fire protection class (9-10)")
        subs.append((f"SUB-{i:05d}", f"{rng.choice(LAST)} {rng.choice(['Holdings', 'Group', 'Properties', 'Enterprises'])}",
                     "COMM_PROPERTY" if rng.random() < 0.7 else "GL", st, rng.choice(industries), tiv, lr,
                     rng.choices([0, 1, 2, 4, 7], weights=[30, 30, 20, 13, 7])[0], pc, roof,
                     (AS_OF - timedelta(days=rng.randint(1, 120))).isoformat(),
                     "REFER_TO_SENIOR_UW" if reasons else rng.choice(["QUOTED", "BOUND", "PENDING_INFO"]), "; ".join(reasons) or None))
    commercial = [h for h in holders if h[2] == "COMMERCIAL"]
    notes_pool = ["Sprinklered building; central-station alarm.", "No sprinklers; older wiring updated in 2019.", "Prior carrier non-renewed after two water losses.",
                  "Applicant owns the building and has 12 years in business.", "Part of the premises is leased to a third-party tenant.",
                  "Loss runs attached and dated within 60 days.", "Loss runs requested but not yet received.", "Applicant reports recent roof replacement.",
                  "Seasonal operation with reduced staffing in winter.", "Vacancy of one unit for about 30 days."]
    linked = []
    for s_ in subs:
        row = list(s_)
        cust_id = None
        if enrich.rng2.random() < 0.35:
            h = enrich.rng2.choice(commercial)
            row[1], row[3], cust_id = h[1], h[3], h[0]
        linked.append(row + [cust_id, " ".join(enrich.rng2.sample(notes_pool, 2))])
    hv = next(h for h in holders if h[1] == "Hudson Valley Roofing")
    pr = next(h for h in holders if h[1] == "Prairie Ridge Packaging Co")
    sub_date = (AS_OF - timedelta(days=6)).isoformat()
    linked += [
        ["SUB-DEMO-01", "Maple Street Retail LLC", "COMM_PROPERTY", "OH", "Retail", 900000, 0.25, 0, 3, 6, sub_date, "PENDING_REVIEW", None, None,
         "Fully sprinklered brick building, monitored alarm, new roof in 2020, owner-occupied for 14 years. Loss runs attached and clean."],
        ["SUB-DEMO-02", "Gulfview Seafood Restaurant Group", "COMM_PROPERTY", "FL", "Restaurant", 4_500_000, 1.15, 4, 8, 24, sub_date, "PENDING_REVIEW", None, None,
         "Three kitchen fires/water losses in 3 years, roof is 24 years old, coastal location, prior carrier non-renewed. Applicant requests replacement-cost coverage."],
        ["SUB-DEMO-03", "Hudson Valley Roofing", "GL", "NY", "Roofing contractor", 1_800_000, 0.80, 3, 5, 12, sub_date, "PENDING_REVIEW", None, hv[0],
         "Existing Cardinal Ridge workers' comp customer requesting general liability. Uses subcontractors without written safety program on file."],
        ["SUB-DEMO-04", "Lone Star Distribution Warehouse", "COMM_PROPERTY", "TX", "Warehouse", 18_000_000, 0.30, 0, 4, 8, sub_date, "PENDING_REVIEW", None, None,
         "Excellent loss record; ESFR sprinklers; tilt-up concrete; single-site total insured value above the Senior UW authority."],
        ["SUB-DEMO-05", "Prairie Ridge Packaging Co", "COMM_PROPERTY", "IL", "Machine shop", 3_000_000, 0.55, 1, 4, 10, sub_date, "PENDING_REVIEW", None, pr[0],
         "Existing customer renewing and increasing building limit after the recent production-hall fire (open claim CLM-DEMO-04)."],
    ]
    ins("underwriting_submissions", linked)

    # ---- catastrophe events + reinsurance ----------------------------------------------------
    cats = []
    for code, name, peril, st, ev in [("CAT-2025-HURR-FL", "Hurricane Marisol (FL)", "HURRICANE", "FL", "2025-09-12"),
                                      ("CAT-2025-HURR-TX", "Hurricane Marisol (TX)", "HURRICANE", "TX", "2025-09-14"),
                                      ("CAT-2026-HAIL-TX", "Spring Hail Outbreak (TX)", "HAIL", "TX", "2026-04-18")]:
        n, tot = con.execute("SELECT COUNT(*), COALESCE(SUM(claimed_amount),0) FROM claims WHERE is_current=1 AND catastrophe_code=?", (code,)).fetchone()
        cats.append((code, name, peril, st, ev, n, round(tot, 2)))
    ins("catastrophe_events", cats)
    ins("reinsurance_treaties", [
        ("RI-2026-PROP-XOL", "Property Catastrophe Excess of Loss", "XOL", "HOME,COMM_PROPERTY", 5_000_000, 100_000_000, 1.0, 500_000, 2026),
        ("RI-2026-AUTO-QS", "Auto Quota Share", "QUOTA_SHARE", "AUTO", 0, 0, 0.20, 1_000_000, 2026),
        ("RI-2026-CASUALTY-XOL", "Casualty Excess of Loss (GL/WC)", "XOL", "GL,WC", 1_000_000, 24_000_000, 1.0, 500_000, 2026)])

    con.execute("UPDATE adjusters SET open_claims=(SELECT COUNT(*) FROM claims c WHERE c.is_current=1 AND c.adjuster_id=adjusters.adjuster_id "
                "AND c.status IN ('OPEN','UNDER_INVESTIGATION','APPROVED'))")
    con.commit()

    tables = [t for (t,) in con.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    for table in tables:
        cur = con.execute(f"SELECT * FROM {table}")
        with open(CSV_DIR / f"{table}.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow([d[0] for d in cur.description])
            w.writerows(cur.fetchall())
    print("Database:", DB_PATH)
    for t in tables:
        print(f"  {t:28s} {con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:6d}")
    con.close()


if __name__ == "__main__":
    build()
