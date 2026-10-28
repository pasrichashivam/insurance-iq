# Insurance-IQ (Cardinal Ridge Insurance Group)

An AI claims-intelligence POC for a **fictional US property & casualty insurer**, *Cardinal Ridge Insurance Group* (Columbus, Ohio).
It writes **Auto, Homeowners, Commercial Property, General Liability and Workers' Comp** in **OH, TX, FL, CA, NY and IL**.

> Everything here is synthetic. The company, customers, vendors and numbers do not exist. State regulation summaries are
> **simplified, fictionalised demo values — not legal advice**.

## 1. What the app does

| Tab | What it is | How it works |
|---|---|---|
| **Policy Q&A (RAG)** | Ask plain-English questions about company and state policy documents | PDFs → chunks → embeddings (Chroma/Vertex) → Gemini answers only from retrieved text |
| **Insurance Assistant** | One agent that answers portfolio and claim questions | Tools: guarded read-only **SQL** over the claims DB, claim/coverage/fraud/compliance tools, and RAG over the PDFs |
| **Data Explorer** | Type a question in plain English **or** a SQL SELECT → the **top 50 rows in a scrollable table** plus the **exact SQL that was executed**; "No information available for the query" when nothing matches | `agent/data_explorer.py`: LLM writes the SQL from the live schema (one retry on error), read-only guard, 50-row cap. See section 6b |
| **Claims Review** | Type a claim id → a **team of 3 specialist agents + a Claims Director** produce a decision memo | Coverage · Fraud/SIU · Compliance & Authority agents (each with deterministic tools) → Director synthesis |
| **Underwriter Navigator** | Type a submission id (new business or renewal) → **risk assessment, pricing recommendation, loss-history review, a human-in-the-loop referral gate and an Underwriters Memo** | Application & Risk · Loss History · Referral Desk (HITL middleware) agents on a deterministic risk/pricing engine → memo. See section 6a |
| **Index Documents** | Upload PDFs or index everything in `sample_docs/` | Feeds the Q&A and the agents' `search_company_guidelines` tool |
| **System Status** | Mode, models, storage, vector store | — |

**Design principle — the LLM never invents numbers.** Dates, deadlines, deductibles, fraud scores, authority levels and
reinsurance thresholds are computed by plain Python tools reading the database (opened **read-only**). The LLM chooses which tool to
call and explains the result. The existing middleware (PII redaction, call limits, retries, tool logging) wraps every agent.

```
claim id ─► Coverage agent   (get_claim_details, check_coverage, search_company_guidelines)  ─┐
         ─► Fraud/SIU agent  (score_fraud_indicators, lookup_vendor_history, guidelines)    ─┼─► Claims Director memo
         ─► Compliance agent (check_state_compliance, check_settlement_authority, guidelines)─┘   APPROVE / ESCALATE / HOLD & SIU / DENY
```

```
submission id ─► Application & Risk agent (get_submission, assess_submission_risk, guidelines)      ─┐
              ─► Loss History agent       (get_applicant_loss_history, claim-note insights)         ─┼─► Underwriters Memo
              ─► Referral Desk agent      (request_manual_review ⏸ HITL: approve / edit / reject)  ─┘   QUOTE / CONDITIONS / REFER / DECLINE
```

API: `POST /api/agent/audit {"request_text": "Review claim CLM-DEMO-01"}` · `POST /api/agent/underwriting {"request_text": "Underwrite submission SUB-DEMO-03"}` ·
`POST /api/agent/underwriting/review {"thread_id": "...", "decision": "approve"}` · `GET /api/agent/underwriting/submissions` ·
`POST /api/agent/assistant {"question": "..."}` ·
`POST /api/rag/ask` · `POST /api/rag/ingest` · `GET /api/status` (Swagger at `/docs`).

## 2. The synthetic data (what was generated)

Generated deterministically (seed 20261001) by [`insurance_data/generate_data.py`](insurance_data/generate_data.py). "Today" in the dataset is **2026-10-01**
(`meta.as_of_date`), so deadline maths is reproducible.

| Table | Rows | Purpose |
|---|---|---|
| policyholders | 1,206 | Individuals and businesses (credit tier, address changes) |
| policies / policy_coverages | 2,752 / 11,413 | Policy periods, cancellations, limits, deductibles |
| claims | 1,616 | Status OPEN / UNDER_INVESTIGATION / APPROVED / PAID / DENIED; ~2 years of losses |
| claim_payments | 1,570 | Payment ledger |
| adjusters | 30 | Levels JUNIOR $10k · SENIOR $50k · MANAGER $250k · DIRECTOR $1M |
| vendors | 63 | Body shops, contractors, clinics |
| siu_cases | 59 | Special-investigation history |
| underwriting_submissions | 165 | New-business and renewal applications (`customer_id` links existing customers; `application_notes` = supporting-document text). Demo ids `SUB-DEMO-01..05` |
| catastrophe_events | 3 | `CAT-2025-HURR-FL`, `CAT-2025-HURR-TX`, `CAT-2026-HAIL-TX` |
| reinsurance_treaties | 3 | Property CAT XOL, Auto Quota Share, Casualty XOL |
| state_regulations | 6 | Simplified claim clocks per state |

Also exported as CSV in `insurance_data/csv/`; the SQLite file used by the app is `backend/data/cardinal_ridge.db` (committed so Docker works).

**Planted patterns for the AI to discover:** three *vendor rings* (VND-901 QuickFix Collision Center TX, VND-902 Sunshine Storm
Restoration FL, VND-903 Premier Injury & Rehab NY) each with ~22 claims of $9,200–$9,980 just under the $10k junior authority limit;
14 repeat claimants; hurricane/hail CAT claims; late-reported and early-in-policy losses.

**Six demo claims** (use them in *Claims Review*):

| Claim | Scenario | Expected outcome |
|---|---|---|
| `CLM-DEMO-01` | Auto, TX, $9,850; loss 12 days after inception; reported late; ring shop VND-901; no police report | Covered, fraud **HIGH (100)** → **hold & refer to SIU**; TX clock breached |
| `CLM-DEMO-02` | Home, FL, $74,500 flood; no flood endorsement | **NOT COVERED** → deny; FL 60-day decision clock **breached** |
| `CLM-DEMO-03` | Auto, CA, $640 glass | Clean → **approve** (payable $140 after deductible) |
| `CLM-DEMO-04` | Commercial property, IL, $620k fire | Covered; assigned adjuster only SENIOR → **escalate to Director**; **reinsurance notice** required |
| `CLM-DEMO-05` | Workers' comp, NY, $58k; late-reported, unwitnessed, ring clinic | Fraud **HIGH**; escalation to Manager; NY clock breached |
| `CLM-DEMO-06` | Auto, OH, $14,200; policy cancelled for non-payment before the loss | **NOT COVERED** → deny |

### Policy documents (`sample_docs/`, 15 PDFs generated by [`insurance_data/generate_pdfs.py`](insurance_data/generate_pdfs.py))

Company: Claims Handling, Authority & Reserving Guidelines · SIU Fraud Detection Guidelines · Underwriting Guidelines · Homeowners HO-3 Form ·
Personal Auto Form · Catastrophe Response Plan · Reinsurance Treaty Summary · Privacy & Data Protection (GLBA, AI use) ·
Commercial Property & Workers' Comp Claims Guidelines.
State: Claims-regulation summaries for **TX, FL, CA, NY, OH, IL** (acknowledge / decide / pay clocks, business vs calendar days).
The numbers in the PDFs match the database tables, so RAG answers and tool results agree.

## 3. Run it

Prerequisites: Python 3.12+, Node 18+ (for the UI), a free Gemini API key (https://aistudio.google.com/apikey).

```powershell
# 1. Python environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt          # includes reportlab for the PDF generator

# 2. Settings
copy .env.example .env                        # then set GOOGLE_API_KEY=...  (keep APP_MODE=local)

# 3. (Optional) regenerate the data and PDFs — they are already committed
python insurance_data/generate_data.py        # -> backend/data/cardinal_ridge.db + insurance_data/csv/
python insurance_data/generate_pdfs.py        # -> sample_docs/*.pdf

# 4. Backend  (http://localhost:8080/docs)
uvicorn api.main:app --app-dir backend --reload --port 8080

# 5. Frontend, in a second terminal  (http://localhost:5173)
cd frontend; npm install; npm run dev
```

**First-run step:** open **Index Documents** and click *Index Stored Documents* after copying the PDFs from `sample_docs/` into the upload folder (or just upload them with the drag-and-drop box; `curl -X POST http://localhost:8080/api/rag/ingest` re-indexes the stored folder).
This embeds the 15 PDFs so Q&A and the agents' guideline search work. The SQL, coverage, fraud and compliance tools work without it.

## 4. Test it

**Automated (no API key or network needed):**

```powershell
python -m pytest -q          # 44 tests: tools vs. demo claims, SQL guard, API, middleware, RAG plumbing, underwriter + HITL, data explorer
```

`backend/tests/test_underwriter.py` drives the Underwriter Navigator with a scripted fake LLM: engine outcomes for SUB-DEMO-01..04,
no-referral path, pause + approve / reject / edit, and the review endpoints.

`backend/tests/test_insurance_tools.py` asserts the demo outcomes (e.g. DEMO-01 fraud HIGH, DEMO-02/06 NOT COVERED, DEMO-04 escalation + reinsurance
notice, `DELETE`/stacked SQL rejected).

**Manual, end to end (needs `GOOGLE_API_KEY`):**

1. *Claims Review* → run `Review claim CLM-DEMO-01` → expect **HOLD & REFER TO SIU**. Repeat for DEMO-02…06 using the table above.
2. *Insurance Assistant* → ask a SQL question from section 6; the answer should quote table results.
3. *Policy Q&A* → ask "What are the Florida claim deadlines?" → answer cites the FL summary (7 / 60 / 60 calendar days).
4. API: `curl -X POST localhost:8080/api/agent/audit -H "Content-Type: application/json" -d "{\"request_text\":\"Review claim CLM-DEMO-02\"}"`.
5. *Underwriter Navigator* → click chip `SUB-DEMO-03` → Run Underwriting → pipeline pauses at **Referral Desk**; Approve / Edit / Reject → memo appears.
   Try `SUB-DEMO-01` (no pause) and `SUB-DEMO-04` (Chief UW). API: `curl -X POST localhost:8080/api/agent/underwriting -H "Content-Type: application/json" -d "{\"request_text\":\"Underwrite submission SUB-DEMO-04\"}"` then post the returned `thread_id` to `/api/agent/underwriting/review`.
6. Safety: ask the assistant to "delete all claims" — it must refuse (the SQL tool only allows one SELECT, on a read-only connection).

CLI shortcut: `cd backend; python -m agent.agents` runs a review of CLM-DEMO-01.

## 5. Insurance problems this solves

| Pain point | How the app helps |
|---|---|
| **Claims leakage** (overpaying, missed deductibles/limits) | `check_coverage` computes policy status, exclusions, deductible (incl. 2% hurricane) and payable amount |
| **Fraud triage / SIU backlog** | Transparent 0–100 red-flag score with reasons; HIGH → SIU referral before payment |
| **Organised vendor rings** | `lookup_vendor_history` + SQL expose shops/clinics with clusters just under authority limits |
| **Regulatory prompt-payment compliance** | Per-state acknowledge / decide / pay clocks (business vs calendar days), breach detection, late-interest estimate |
| **Coverage disputes & bad-faith risk** | Cites policy period, cancellation and exclusions (flood, non-payment); produces denial rationale |
| **Authority & governance** | Delegation-of-authority ladder; flags claims that exceed the adjuster's limit |
| **Reinsurance notice failures** | Flags claims crossing treaty notice thresholds |
| **Catastrophe surge management** | CAT-code analytics, percentage deductibles, response-plan Q&A |
| **Handler productivity / knowledge search** | Natural-language answers from guidelines, forms and state rules, with sources |
| **Portfolio analytics for managers** | Ad-hoc SQL via plain English (loss ratios, severity, aging, adjuster workload) |
| **Slow, inconsistent underwriting** | Underwriter Navigator: repeatable risk score, indicated premium and required authority in seconds, with an Underwriters Memo |
| **High-risk risks bound without senior eyes** | Referral Desk pauses for a human (approve / edit / reject) before any referral is filed |
| **Ignoring what claims already know** | Renewals pull latest claim versions, SIU flags and `claim_notes` underwriting insights |

## 6. Sample questions — and how to check the AI's answer

**How to validate (three helpers, all offline except the retriever trace):**

| Need | Helper |
|---|---|
| Re-run a database check | `python insurance_data/run_sql.py "<SQL>"` (read-only; run from the project root) |
| Re-run the exact agent tool and see its raw JSON | `cd backend; python -c "from agent.tools import check_coverage as t; print(t.invoke({'claim_id':'CLM-DEMO-06'}))"` (swap in `score_fraud_indicators`, `check_state_compliance`, `check_settlement_authority`, `lookup_vendor_history`, `get_claim_notes`, `get_claim_history`) |
| Find the source text of a RAG answer | `python insurance_data/find_in_pdfs.py <word> [<word>...] [--file <part of file name>]` (offline keyword search: prints PDF name, page, line) |
| See the chunks the retriever actually gave the LLM | `cd backend; python -m rag.trace_sources "<question>" [similarity\|multiquery\|contextual]` (prints source file, page, text; needs the PDFs indexed and `GOOGLE_API_KEY`) |

Notes for the SQL checks: the four versioned tables hold one row per change, so use the `*_current` views for "latest" answers
(add `valid_from <= 'YYYY-MM-DD' AND (valid_to IS NULL OR 'YYYY-MM-DD' < valid_to)` on the base table for a point in time). "Today" in the data is `2026-10-01`.
Every agent tool is also logged: the backend log shows `Tool call started/finished` with the arguments, so you can see which tools the answer is based on.

### Policy Q&A (RAG over PDFs)

**Backtracking to the source.** The Q&A tab returns only the answer text. The answer is built from the top-3 chunks (`similarity`; `multiquery` merges four searches; `contextual` trims 10 chunks). Each chunk carries `source` (file) and `page` metadata, so:
1. run `python -m rag.trace_sources "<same question>" <same retriever>` to see the chunks the LLM was given (file, page, text);
2. confirm the wording in the original with `python insurance_data/find_in_pdfs.py ...`, or open the PDF in `sample_docs/` at that page;
3. if the answer says something not in those chunks, treat it as unsupported. The prompt tells the model to say "I don't know" when the context lacks the answer.
Tables in the PDFs are extracted cell by cell, so search with a single keyword rather than a whole phrase.

| Question | Validate with | Expected evidence |
|---|---|---|
| What are the settlement authority limits for each adjuster level? | `find_in_pdfs.py junior --file authority` · `run_sql.py "SELECT level, MAX(authority_limit) FROM adjusters GROUP BY level"` | `cardinal_ridge_claims_authority_and_reserving_guidelines.pdf`; JUNIOR $10k · SENIOR $50k · MANAGER $250k · DIRECTOR $1M. The DB must match the PDF |
| How many days does Florida allow to accept or deny a claim, and are they calendar or business days? | `find_in_pdfs.py calendar --file state_fl` · `run_sql.py "SELECT state, ack_days, decision_days, payment_days, day_unit FROM state_regulations WHERE state='FL'"` | `state_fl_claims_regulations_summary.pdf` p.1: acknowledge 7, decide 60, pay 60, **calendar** days |
| Which red flags raise a fraud score and what score triggers an SIU referral? | `find_in_pdfs.py refer --file siu` · `find_in_pdfs.py bands --file siu` | `cardinal_ridge_siu_fraud_detection_guidelines.pdf` p.1: HIGH ≥ 50 = refer before any payment; 25–49 MEDIUM; flag list in section 2/3. Cross-check against the flags in `score_fraud_indicators` output |
| Is flood damage covered by the HO-3 form? What is the hurricane deductible? | `find_in_pdfs.py flood --file ho3` · `find_in_pdfs.py hurricane --file ho3` | `cardinal_ridge_homeowners_ho3_policy_form.pdf`: flood excluded (endorsement available); FL/TX named-hurricane deductible = percentage of the dwelling limit (2%) |
| When must reinsurers be notified of a large claim? | `find_in_pdfs.py notice --file reinsurance` · `run_sql.py "SELECT name, line, notice_threshold FROM reinsurance_treaties"` | `cardinal_ridge_reinsurance_treaty_summary.pdf` p.1: report within 5 business days once the claim reaches the treaty notice threshold (property/casualty XOL $500k, auto $1M) |
| What are Texas's prompt-payment deadlines? | `find_in_pdfs.py days --file state_tx` · `run_sql.py "SELECT * FROM state_regulations WHERE state='TX'"` | `state_tx_claims_regulations_summary.pdf`: acknowledge 15, decide 15, pay 5 — all **business** days; the DB row (TX, 15, 15, 5, business) must agree |
| What does the privacy policy say about using AI in claim decisions? | `find_in_pdfs.py "ai" --file privacy` | `cardinal_ridge_privacy_and_data_protection_policy.pdf` §2 "Use of AI": decision support only, a licensed human decides coverage, denial and fraud referral; outputs must be explainable |
| What are the underwriting referral limits for a Senior Underwriter? | `find_in_pdfs.py senior --file underwriting` · `find_in_pdfs.py "100,000" --file underwriting` | `cardinal_ridge_underwriting_guidelines.pdf` §1 table: Senior UW up to $100k premium, $10M TIV, 4 claims in 3 years. Same numbers are coded in `agent/underwriting_tools.py` (`UW_AUTHORITY`) |

### Claims Review (agents)

**Validate every claim review** by re-running its tools and comparing with the memo (the memo may never change a tool figure):
`cd backend; python -c "from agent.tools import *; [print(t.invoke({'claim_id':'CLM-DEMO-01'})) for t in (check_coverage, score_fraud_indicators, check_state_compliance, check_settlement_authority)]"`

| Question | Validate with | Expected |
|---|---|---|
| `Review claim CLM-DEMO-01` | `run_sql.py "SELECT julianday(c.loss_date)-julianday(p.effective_date) AS days_since_inception, julianday(c.reported_date)-julianday(c.loss_date) AS report_lag, c.claimed_amount, c.vendor_id FROM claims_current c JOIN policies_current p ON p.policy_id=c.policy_id WHERE c.claim_id='CLM-DEMO-01'"` | Score **100 (HIGH)**, flags: 12 days after inception (+20), reported 38 days after loss (+15), $9,850 just under $10k (+15), VND-901 in 12 SIU cases (+20), 2 address changes (+8), no police report (+8), duplicate invoice INV-901-44540 on 5 other claims (+20), inconsistent statements in the notes (+15) → hold & refer to SIU; TX clock NON-COMPLIANT |
| `Review claim CLM-DEMO-02` | `run_sql.py "SELECT c.cause_of_loss, (SELECT COUNT(*) FROM policy_coverages_current pc WHERE pc.policy_id=c.policy_id AND pc.coverage_code='FLOOD') AS flood_cov FROM claims_current c WHERE c.claim_id='CLM-DEMO-02'"` | cause FLOOD, `flood_cov = 0` → NOT COVERED, deny; FL 60-day clock breached (see `check_state_compliance`) |
| `Review claim CLM-DEMO-03` | `run_sql.py "SELECT claimed_amount, status, cause_of_loss FROM claims_current WHERE claim_id='CLM-DEMO-03'"` and `check_coverage` | $640 glass, covered, payable = $640 − $500 deductible = **$140**, fraud LOW |
| `Review claim CLM-DEMO-04` | `run_sql.py "SELECT c.claimed_amount, a.level FROM claims_current c JOIN adjusters a ON a.adjuster_id=c.adjuster_id WHERE c.claim_id='CLM-DEMO-04'"` · `run_sql.py "SELECT notice_threshold FROM reinsurance_treaties WHERE line LIKE '%COMM_PROPERTY%'"` | $620,000 > MANAGER $250k → required level DIRECTOR; assigned adjuster only SENIOR (`adjuster_has_authority: false`) → escalation; $620k ≥ $500k → reinsurance notice |
| `Review claim CLM-DEMO-05` | `run_sql.py "SELECT c.vendor_id, julianday(c.reported_date)-julianday(c.loss_date) AS lag, (SELECT COUNT(*) FROM siu_cases s WHERE s.vendor_id=c.vendor_id) AS vendor_siu FROM claims_current c WHERE c.claim_id='CLM-DEMO-05'"` | Score **73 (HIGH)**: reported 41 days after loss (+15), round-dollar amount (+5), 2 other claims by the customer (+10), VND-903 in 11 SIU cases (+20), no witnesses (+8), inconsistent statements (+15); $58,000 → MANAGER; NY clock NON-COMPLIANT. `get_claim_notes` shows the contradicting recorded statement |
| `Review claim CLM-DEMO-06` | `run_sql.py "SELECT c.loss_date, p.status, p.cancel_date, p.cancel_reason FROM claims_current c JOIN policies_current p ON p.policy_id=c.policy_id WHERE c.claim_id='CLM-DEMO-06'"` | loss 2026-07-04 is after the 2026-06-01 NON_PAYMENT cancellation → NOT COVERED |
| `Review claim CLM-2026-000123` (any real id) | `run_sql.py "SELECT * FROM claims_current WHERE claim_id='CLM-2026-000123'"` and `get_claim_history` | The memo's amounts, status and dates must equal that row; history shows each dated change |

### Insurance Assistant (SQL + tools + docs)

Ask the assistant to **show the SQL it ran** (it must use `run_sql_query`); then run the query below yourself and compare. Numbers are expected to match exactly.

| Question | Validation query (`run_sql.py "..."`) | Expected on this dataset |
|---|---|---|
| How many claims are open or under investigation by state and line? | `SELECT state, line, status, COUNT(*) n FROM claims_current WHERE status IN ('OPEN','UNDER_INVESTIGATION') GROUP BY state, line, status ORDER BY n DESC` | Top rows: FL/HOME OPEN 21, TX/AUTO OPEN 21, IL/AUTO OPEN 16. Wrong if it counted `claims` (all versions) instead of `claims_current` |
| Which five vendors have the most claims between $9,000 and $9,999, and how many SIU cases does each have? | `SELECT v.vendor_id, v.name, COUNT(*) claims_9k, (SELECT COUNT(*) FROM siu_cases s WHERE s.vendor_id=v.vendor_id) siu FROM claims_current c JOIN vendors v ON v.vendor_id=c.vendor_id WHERE c.claimed_amount BETWEEN 9000 AND 9999.99 GROUP BY v.vendor_id ORDER BY claims_9k DESC LIMIT 5` | VND-901 (23 / 12 SIU), VND-903 (22 / 11), VND-902 (22 / 11), then VND-013, VND-052 |
| List open claims that are past their state decision deadline. | `SELECT c.claim_id, c.state, c.reported_date, r.decision_days, r.day_unit FROM claims_current c JOIN state_regulations r ON r.state=c.state WHERE c.status IN ('OPEN','UNDER_INVESTIGATION') AND c.decision_date IS NULL AND julianday('2026-10-01')-julianday(c.reported_date) > CASE r.day_unit WHEN 'business' THEN r.decision_days*7.0/5 ELSE r.decision_days END` | 20 rows. The business-day conversion is approximate, so borderline claims may differ by a few days: confirm one with `check_state_compliance` |
| Total claimed vs paid for CAT-2025-HURR-FL, split by status. | `SELECT status, COUNT(*) n, ROUND(SUM(claimed_amount),2) claimed, ROUND(SUM(paid_amount),2) paid FROM claims_current WHERE catastrophe_code='CAT-2025-HURR-FL' GROUP BY status` | DENIED 4 · $194,664.07 claimed · $0 paid; PAID 17 · $348,386.06 claimed · $277,157.63 paid |
| Which adjusters are working claims above their authority limit? | `SELECT a.adjuster_id, a.name, a.level, a.authority_limit, COUNT(*) n FROM claims_current c JOIN adjusters a ON a.adjuster_id=c.adjuster_id WHERE c.status IN ('OPEN','UNDER_INVESTIGATION') AND MAX(c.claimed_amount, COALESCE(c.reserve_amount,0)) > a.authority_limit GROUP BY a.adjuster_id ORDER BY n DESC` | Top: ADJ-026 Daniel Jackson (JUNIOR, 11), ADJ-015 Priya Lewis (9), ADJ-019 Priya Hill (7) |
| Average days from loss to report by line; which line is slowest? | `SELECT line, ROUND(AVG(julianday(reported_date)-julianday(loss_date)),1) avg_days FROM claims_current GROUP BY line ORDER BY avg_days DESC` | GL 5.8 (slowest), WC 4.7, COMM_PROPERTY 4.3, HOME 3.9, AUTO 3.8 |
| Which customers have 3+ claims in the last 24 months? | `SELECT customer_id, COUNT(*) n FROM claims_current WHERE loss_date >= date('2026-10-01','-24 months') GROUP BY customer_id HAVING n >= 3 ORDER BY n DESC` | Top: CUS-00724 (8), CUS-00516 (7), CUS-00403 (7). "Last 24 months" is measured from 2026-10-01, not the real today |
| Show denied claims and the top denial reasons. | `SELECT denial_reason, COUNT(*) n FROM claims_current WHERE status='DENIED' GROUP BY denial_reason ORDER BY n DESC` | Top reason: "Flood is excluded under the HO-3 form; no flood endorsement on policy." (37). Compare the full list with the AI's list |
| Is CLM-DEMO-06 covered? Why or why not? | `SELECT p.status, p.cancel_date, p.cancel_reason, c.loss_date FROM claims_current c JOIN policies_current p ON p.policy_id=c.policy_id WHERE c.claim_id='CLM-DEMO-06'` | Policy CANCELLED 2026-06-01 (NON_PAYMENT) before the 2026-07-04 loss → NOT COVERED |
| Score CLM-DEMO-05 for fraud and tell me what to investigate next. | Tool re-run: `score_fraud_indicators` for CLM-DEMO-05 · `run_sql.py "SELECT claim_id, vendor_id, claimed_amount FROM claims_current WHERE vendor_id='VND-903' AND claimed_amount BETWEEN 9000 AND 9999.99 LIMIT 5"` | Score is the sum of the listed flags (check the arithmetic), band HIGH if ≥ 50; flags must each be explained by the DB facts (late report 41 days, VND-903 SIU cases, no witnesses) |
| What does our SIU guideline say about reserving rights during an investigation? | `find_in_pdfs.py reserv --file siu` | `cardinal_ridge_siu_fraud_detection_guidelines.pdf` p.1: ... reservation-of-rights letter. Also run `python -m rag.trace_sources "reserving rights during an investigation"` |

### Underwriter Navigator (type into the tab; each needs a submission id)

**Validate every underwriting run** by printing the deterministic engine output (the memo may never change its numbers) and the source row:
`cd backend; python -c "import json; from agent.underwriting_tools import assess_submission as a; print(json.dumps(a('SUB-DEMO-03'), indent=1, default=str))"`
`python insurance_data/run_sql.py "SELECT * FROM underwriting_submissions WHERE submission_id='SUB-DEMO-03'"`
Premium check: `TIV × base rate (0.6% property / 0.9% GL) × state factor × tier factor × loss-experience factor` (the factors are printed in `pricing`).

| Query | Expected (engine) | Extra validation |
|---|---|---|
| `Underwrite submission SUB-DEMO-01` | Score 0, PREFERRED, premium ≈ $4,435, QUOTE, no referral, no human pause | $900k TIV × 0.6% = $5,400 base × state 1.0 × tier 0.9 × loss factor 0.912 = $4,434.75; range $4,213–$4,878; authority Underwriter (under $25k / $2M / 2 claims) |
| `Underwrite submission SUB-DEMO-02. Applicant requests replacement-cost coverage.` | Score 87, HIGH, DECLINE, referral to Senior UW pauses for review | Row shows loss ratio 115%, 4 claims, roof 24 yrs, "prior carrier non-renewed", FL coastal; guideline: roof > 20 yrs → ACV only (`find_in_pdfs.py roof --file underwriting`) |
| `Underwrite submission SUB-DEMO-03` | RENEWAL / existing customer, score 62, ELEVATED, REFER TO SENIOR UNDERWRITER, safety-program condition | `customer_id` CUS-… is set; `run_sql.py "SELECT claim_id, status, siu_referred FROM claims_current WHERE customer_id=(SELECT customer_id FROM underwriting_submissions WHERE submission_id='SUB-DEMO-03')"` shows the SIU-referred claim CLM-2026-001609 (the referral reason) and the open claim CLM-DEMO-05 (reserve $52,200); guideline "contractor risks require certificates of insurance and a written safety program" |
| `Underwrite submission SUB-DEMO-04 and tell me if reinsurance must be notified.` | Score 10, premium ≈ $103k, CHIEF UNDERWRITER, reinsurance notice | $18M TIV > $10M Senior limit and premium > $100k; `run_sql.py "SELECT total_insured_value FROM underwriting_submissions WHERE submission_id='SUB-DEMO-04'"` |
| `Renew and increase the building limit for SUB-DEMO-05. How does the open fire claim affect it?` | RENEWAL, score 23, Senior UW (TIV $3M > $2M), open-claim condition | `run_sql.py "SELECT claim_id, status, claimed_amount, reserve_amount FROM claims_current WHERE claim_id='CLM-DEMO-04'"` and `get_claim_notes` for CLM-DEMO-04 → the quoted insight ("Severity loss: review electrical / heating inspections, sprinkler status and protection class at renewal.") must come from `claim_notes.underwriting_insights` |
| `Underwrite submission SUB-DEMO-03 — what price range would you quote and who must approve it?` | Range = `pricing.suggested_range` (95%–110% of indicated premium); approver = `required_authority` | Compare both numbers with the engine output above. HITL check: on a paused run, Approve / Edit / Reject must change the "HUMAN REVIEW" line in the memo, and a second review of the same `thread_id` returns 400 |

### Queries that trigger the Human-in-the-Loop pause

The Referral Desk agent calls `request_manual_review` only when the engine says a referral is required; `HumanInTheLoopMiddleware` then pauses the run and the tab shows **Approve / Edit / Reject**.

| # | Query | Why it pauses | What to do and expect |
|---|---|---|---|
| 1 | `Underwrite submission SUB-DEMO-03 and refer it if needed.` | Score 62 (ELEVATED), SIU-referred claim CLM-2026-001609 → hard referral reason; required authority Senior Underwriter | **Approve** → memo "HUMAN REVIEW: approved", premium unchanged ($23,388.75). **Edit** (change authority to Chief Underwriter, add a reason) → memo shows your edited authority/reason. **Reject** → memo records the referral as rejected and keeps the engine recommendation. Re-submitting the same `thread_id` returns 400 |
| 2 | `Underwrite submission SUB-DEMO-04 and tell me if reinsurance must be notified. Escalate to the right authority.` | $18M TIV > $10M → reinsurance/Chief Underwriter referral | The pause shows authority CHIEF UNDERWRITER and the reinsurance reason; after Approve the memo carries the reinsurance notice and the ≈ $103k premium |

Control (must **not** pause): `Underwrite submission SUB-DEMO-01` → score 0, QUOTE, no referral. Validate the trigger with the engine output: `referral_required` and `referral_reasons` in `assess_submission('SUB-DEMO-0x')`.

### Insurance Assistant questions an underwriter can also ask

| Question | Validation query (`run_sql.py "..."`) | Expected |
|---|---|---|
| Which commercial property submissions in FL are pending review, and what is their total insured value? | `SELECT COUNT(*), SUM(total_insured_value) FROM underwriting_submissions WHERE line='COMM_PROPERTY' AND state='FL' AND status='PENDING_REVIEW'` | 1 submission (SUB-DEMO-02), $4,500,000 |
| Show all claims for Prairie Ridge Packaging Co with the latest underwriting insight from the claim notes. | `SELECT cl.claim_id, cl.status, cl.claimed_amount, (SELECT n.underwriting_insights FROM claim_notes n WHERE n.claim_id=cl.claim_id AND n.underwriting_insights IS NOT NULL ORDER BY n.note_seq DESC LIMIT 1) insight FROM claims_current cl JOIN policyholders_current h ON h.customer_id=cl.customer_id WHERE h.name LIKE 'Prairie Ridge%'` | CLM-DEMO-04, OPEN, $620,000, "Severity loss: review electrical / heating inspections, sprinkler status and protection class at renewal." |
| What is the average 3-year loss ratio of submissions in REFER_TO_SENIOR_UW status by state? | `SELECT state, ROUND(AVG(loss_ratio_3yr),2) avg_lr, COUNT(*) n FROM underwriting_submissions WHERE status='REFER_TO_SENIOR_UW' GROUP BY state` | CA 0.82 (19), FL 0.85 (29), IL 0.95 (9), NY 0.95 (18), OH 1.04 (26), TX 0.89 (32) |
| What does the underwriting guideline say about roof age above 20 years and contractor risks? | `find_in_pdfs.py roof --file underwriting` · `find_in_pdfs.py contractor --file underwriting` | `cardinal_ridge_underwriting_guidelines.pdf`: roof > 20 yrs → ACV for wind/hail; contractors need subcontractor certificates and a written safety program. Use `rag.trace_sources` to see the chunk |
| Which existing customers have claims referred to SIU? | `SELECT DISTINCT h.customer_id, h.name FROM claims_current c JOIN policyholders_current h ON h.customer_id=c.customer_id WHERE c.siu_referred=1` | First rows: CUS-00860 Robert Harris, CUS-00078 Carlos Young, CUS-00956 Aisha Brown (the full list must match) |

**Red flags that an answer is wrong:** numbers that differ from the validation query; counts taken from `claims` instead of `claims_current`; a date
"today" other than 2026-10-01; a rule or number that is not in the retrieved chunks; a memo figure that differs from the tool/engine JSON.

## 6a. Underwriter Navigator (new tab, below Claims Review)

A separate multi-agent flow for underwriting **new business and renewals** (`POST /api/agent/underwriting`, code in
[`backend/agent/underwriter.py`](backend/agent/underwriter.py) and
[`underwriting_tools.py`](backend/agent/underwriting_tools.py)).

| Step | Agent | What it does |
|---|---|---|
| 1 | Application & Risk | Reads the application + notes, calls the deterministic risk engine (score 0-100, tier, indicated premium, required authority, conditions), cites the guidelines |
| 2 | Loss History | Existing customers: policies, latest claim versions, SIU flags and the underwriting insights from `claim_notes` |
| 3 | Referral Desk (**HITL**) | If a referral is required it calls `request_manual_review`; LangChain's `HumanInTheLoopMiddleware` pauses the run until a human **approves, edits or rejects** it |
| 4 | Underwriters Memo | One LLM call writes the memo (recommendation, risk, pricing, authority, conditions, next steps) |

Endpoints: `GET /api/agent/underwriting/submissions` (demo picks), `POST /api/agent/underwriting` (returns `COMPLETED` or
`PENDING_REVIEW` + `thread_id`), `POST /api/agent/underwriting/review` (`decision`: approve / edit / reject, then the memo).
Pricing = TIV x base rate (0.6% property, 0.9% GL) x state factor x tier factor x loss-experience factor. Authority:
Underwriter up to $25k premium / $2M TIV / 2 claims, Senior up to $100k / $10M / 4 claims, otherwise Chief.

| Try | Expected |
|---|---|
| `Underwrite submission SUB-DEMO-01` | Score 0, PREFERRED, ~$4.4k, **QUOTE**, no human review, memo straight away |
| `SUB-DEMO-02` (FL restaurant) | Score 87, HIGH, **DECLINE**, referral to Senior UW pauses for review |
| `SUB-DEMO-03` (existing WC customer wants GL) | RENEWAL, score 62, ELEVATED, **REFER TO SENIOR UNDERWRITER**, safety-program condition |
| `SUB-DEMO-04` ($18M warehouse) | Score 10, **REFER TO CHIEF UNDERWRITER**, reinsurance notice condition |
| `SUB-DEMO-05` (renewal after fire claim) | RENEWAL, Senior UW (TIV > $2M), open-claim condition |
| Approve / Edit / Reject on a paused run | Memo states the reviewer decision; Reject = referral not filed, comment recorded |

Tests: `backend/tests/test_underwriter.py` (scripted fake LLM, no API key needed).

## 6b. Data Explorer (new tab, below Insurance Assistant)

Type a **question or a SQL query** and press Run (or Ctrl+Enter). The tab shows (1) the **Executed query** box and (2) a **Results** table, scrollable
vertically and horizontally, with at most **50 rows** (a "top 50 shown" badge appears when there were more).

How it decides (`POST /api/agent/data-explorer {"query": "..."}`):
- Starts with `SELECT` / `WITH` → your SQL is validated and executed as written (`mode: sql`).
- Anything else → the LLM writes one SQLite SELECT from the live schema (`mode: nl`); if it errors, the agent retries once with the error message.
- No rows, an unknown table/column, or a question the data cannot answer (the LLM answers `NO_DATA`) → **"No information available for the query"**
  (`status: no_data`; an optional `detail` shows the SQL error).
- Writes/DDL, `PRAGMA` or multiple statements are refused (`status: rejected`); the database is also opened read-only and queries stop after 10 s.
- Response: `status, mode, message, sql, columns, rows, row_count, truncated, detail`. Use the `*_current` views for "latest"; "today" is 2026-10-01.

| # | Input | Type | Expected result |
|---|---|---|---|
| 1 | `SELECT state, COUNT(*) AS open_claims FROM claims_current WHERE status='OPEN' GROUP BY state ORDER BY open_claims DESC` | SQL | 6 rows: TX 45, FL 37, OH 34, IL 32, CA 27, NY 20. Executed query = your text |
| 2 | `Top 10 customers by total claimed amount` | NL | 10 rows from `claims_current` joined/grouped by customer, sorted by the sum descending; the SQL box shows the generated query. Validate by pasting that SQL back as input #1-style SQL or with `run_sql.py` |
| 3 | `Which vendors are linked to the most SIU-referred claims?` | NL | Generated query over `claims_current.siu_referred=1` grouped by `vendor_id`; the top named vendors are VND-901 (12) and VND-903 (11) (a NULL vendor group of 18 may also appear) |
| 4 | `SELECT submission_id, status, total_insured_value FROM underwriting_submissions WHERE submission_id LIKE 'SUB-DEMO%'` | SQL | 5 rows SUB-DEMO-01..05, all PENDING_REVIEW, TIV 900k / 4.5M / 1.8M / 18M / 3M |
| 5 | `List the Director-level adjusters with their state and authority limit` | NL | Rows from `adjusters` where `level='DIRECTOR'` (e.g. Priya Young TX $1,000,000; Nicole Miller FL $1,000,000) |
| 6 | `What is the weather in Columbus today?` | NL | Table empty, message **No information available for the query**, nothing executed |
| 7 | `SELECT * FROM weather` | SQL | Same message, `detail: SQL error: no such table: weather` |
| 8 | `DELETE FROM claims` | SQL | Refused: "Only read-only queries are allowed…" — no change to the database |

Validate any result by running the shown SQL yourself: `python insurance_data/run_sql.py "<the executed query>"` and comparing rows/counts. For NL
answers, check that the generated query matches the question (tables, filters, `_current` view, sort/limit). Tests: `backend/tests/test_data_explorer.py`
(scripted fake LLM; no API key needed).

## 7. Project map

| Path | Role |
|---|---|
| `insurance_data/generate_data.py`, `generate_pdfs.py` | Reproducible synthetic data + PDFs |
| `insurance_data/run_sql.py`, `find_in_pdfs.py`, `backend/rag/trace_sources.py` | Validation helpers: read-only SQL, offline PDF search, retrieved-chunk trace (section 6) |
| `backend/data/cardinal_ridge.db` | SQLite database (read-only at runtime) |
| `backend/agent/insurance_db.py` | Read-only DB helpers, business-day maths |
| `backend/agent/tools.py` | Deterministic insurance tools (+ guarded SQL, + RAG search) |
| `backend/agent/prompts.py` | Coverage / Fraud / Compliance / Director / Assistant prompts |
| `backend/agent/agents.py` | `ClaimsReviewSupervisor`, `ask_assistant` |
| `backend/agent/underwriter.py` | `UnderwriterNavigator`: 3 agents + HITL (`HumanInTheLoopMiddleware`, checkpointer) + memo |
| `backend/agent/underwriting_tools.py` | Risk/pricing engine and underwriting tools (`assess_submission_risk`, `request_manual_review` ...) |
| `backend/agent/data_explorer.py` | Data Explorer: NL→SQL (or your SQL) → guard → top-50 rows (`POST /api/agent/data-explorer`); UI in `frontend/src/components/DataExplorerTab.tsx`; tests in `backend/tests/test_data_explorer.py` |
| `backend/agent/underwriting_prompts.py` | Underwriting agent prompts and the Underwriters Memo template |
| `backend/api/` | FastAPI endpoints (`/api/agent/audit`, `/api/agent/assistant`, `/api/rag/*`) |
| `frontend/src/components/` | `AuditTab` (Claims Review), `UnderwriterTab` (Underwriter Navigator), `AssistantTab`, `RagQATab`, `DocumentUploadTab` |
| `backend/tests/` | Pytest suite incl. `test_insurance_tools.py` |

## 8. Limits & disclaimers

- Synthetic data and fictional company; simplified state rules — verify real law before any production use.
- AI output is decision support. A licensed human must decide coverage, denial and fraud referrals.
- Fraud score weights are illustrative heuristics, not a validated model; check for fairness/bias before real use.
- The original procurement-audit write-up in `README.md` / `docs/` describes the base architecture this edition builds on.

Get information for claim CLM-DEMO-05 I need to get below information.
1. Claim id, policy_id, customer_id, policy inception date, loss_date, reported_date, vendor id, vendor name (separate columns)
2. Number of days between policy inception and loss occurred.
2. Number of days between loss occurred and loss reported.
3. Claim amount
4. Count of SIU referred for a vendor associated with this claim
5. Description
6. How many more claims the customer of this claim is linked to in last 24 months.

Claim Review:
Review claim CLM-2026-001610
Review claim CLM-DEMO-04

Underwriter Navigator:

HITL: Underwrite submission SUB-DEMO-04 and tell me if reinsurance must be notified. Escalate to the right authority.
