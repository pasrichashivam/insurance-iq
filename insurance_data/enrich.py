"""History, notes and document builders for generate_data.py.

Everything here uses its OWN random generator (rng2) so the base data produced by generate_data.py stays
byte-for-byte identical to the original single-version dataset: the CURRENT version of every policyholder,
policy, coverage and claim equals the original row. This module only adds the earlier versions (transaction
history with effective dates), the claim_notes table and the claim_documents table.

Versioned tables carry six extra trailing columns:
    version_no, valid_from, valid_to (exclusive, NULL = still current), is_current, change_type, change_note
A record is "in force as of date D" when valid_from <= D and (valid_to IS NULL or D < valid_to).
"""
import random
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from agent.doc_rules import required_documents  # noqa: E402

rng2 = random.Random(77_031)

VERSION_COLS = ["version_no", "valid_from", "valid_to", "is_current", "change_type", "change_note"]


def _versions(snapshots):
    """snapshots: [(date, row_list, change_type, note)] -> rows with the six version columns appended."""
    snapshots = sorted(snapshots, key=lambda s: s[0])
    merged = []
    for d, row, ct, note in snapshots:
        if merged and merged[-1][0] == d:
            _, _, pct, pnote = merged[-1]
            merged[-1] = (d, row, pct if ct in pct.split("+") else f"{pct}+{ct}", f"{pnote} {note}")
        else:
            merged.append((d, row, ct, note))
    out = []
    for i, (d, row, ct, note) in enumerate(merged):
        nxt = merged[i + 1][0] if i + 1 < len(merged) else None
        out.append(list(row) + [i + 1, d.isoformat(), nxt.isoformat() if nxt else None, int(nxt is None), ct, note])
    return out


# ------------------------------------------------------------------------------------------------
# Policyholders
# ------------------------------------------------------------------------------------------------

def holder_versions(holders, policies, cities, as_of):
    """holders: [id,name,type,state,city,zip,email,phone,since,credit_tier,address_changes_12m]"""
    first_eff = {}
    for p in policies:
        first_eff[p[1]] = min(first_eff.get(p[1], date.fromisoformat(p[4])), date.fromisoformat(p[4]))
    rows = []
    for h in holders:
        join = min(date(h[8], 1, 1), first_eff.get(h[0], date(h[8], 1, 1)))
        n_addr = h[10]
        events = []  # (date, change_type)
        if n_addr:
            lo = max(join + timedelta(days=1), as_of - timedelta(days=365))
            span = max((as_of - timedelta(days=1) - lo).days, 1)
            for off in sorted(rng2.sample(range(span + 1), min(n_addr, span + 1))):
                events.append((lo + timedelta(days=off), "ADDRESS_CHANGE"))
        old_tier = h[9]
        if rng2.random() < 0.15:
            old_tier = rng2.choice([t for t in "ABCD" if t != h[9]])
            events.append((join + timedelta(days=rng2.randint(30, max((as_of - join).days - 1, 31))), "CREDIT_TIER_CHANGE"))
        events.sort(key=lambda e: e[0])
        n_changes = sum(1 for e in events if e[1] == "ADDRESS_CHANGE")
        cur = list(h)
        cur[9] = old_tier
        if n_changes:
            city, z3 = rng2.choice(cities[h[3]])
            cur[4], cur[5] = city, f"{z3}{rng2.randint(10, 99)}"
        snaps = [(join, list(cur), "CUSTOMER_ONBOARDED", "Customer record created.")]
        seen_addr = 0
        for d, ct in events:
            if ct == "ADDRESS_CHANGE":
                seen_addr += 1
                if seen_addr == n_changes:
                    cur[4], cur[5] = h[4], h[5]
                else:
                    city, z3 = rng2.choice(cities[h[3]])
                    cur[4], cur[5] = city, f"{z3}{rng2.randint(10, 99)}"
                note = f"Address updated to {cur[4]}, {h[3]} {cur[5]}."
            else:
                cur[9] = h[9]
                note = f"Credit tier re-scored from {old_tier} to {h[9]}."
            snaps.append((d, list(cur), ct, note))
        snaps[-1] = (snaps[-1][0], list(h), snaps[-1][2], snaps[-1][3])
        rows += _versions(snaps)
    return rows


# ------------------------------------------------------------------------------------------------
# Policies + coverages
# ------------------------------------------------------------------------------------------------

def policy_versions(policies, coverages, as_of):
    """policies: (id,cust,line,state,eff,exp,status,cancel,reason,premium,producer); coverages: (pid,code,limit,ded)"""
    covs_by_pol = {}
    for c in coverages:
        covs_by_pol.setdefault(c[0], []).append(c)
    pol_rows, cov_rows = [], []
    for p in policies:
        pid = p[0]
        eff = date.fromisoformat(p[4])
        exp = date.fromisoformat(p[5])
        cancel = date.fromisoformat(p[7]) if p[7] else None
        end = min(exp, cancel or exp, as_of)
        endorse = None
        if "DEMO" not in pid and rng2.random() < 0.3 and (end - eff).days > 40:
            endorse = eff + timedelta(days=rng2.randint(20, (end - eff).days - 10))
        issued = list(p)
        issued[6], issued[7], issued[8] = "ACTIVE", None, None
        snaps = [(eff, issued, "POLICY_ISSUED", f"Policy issued, term {p[4]} to {p[5]}.")]
        if endorse:
            issued[9] = round(p[9] * rng2.uniform(0.90, 0.97), 2)
            mid = list(issued)
            mid[9] = p[9]
            snaps.append((endorse, mid, "ENDORSEMENT", "Mid-term endorsement: coverage terms and premium adjusted."))
        if cancel:
            snaps.append((cancel, list(p), "CANCELLATION", f"Policy cancelled ({p[8]})."))
        if p[6] == "EXPIRED":
            snaps.append((exp, list(p), "EXPIRATION", "Policy term ended without renewal."))
        snaps = [(d, list(p) if i == len(snaps) - 1 else r, ct, n) for i, (d, r, ct, n) in enumerate(snaps)]
        # keep the premium the policy had at that point; the last snapshot is the current row
        pol_rows += _versions(snaps)
        for c in covs_by_pol.get(pid, []):
            csnaps = []
            if endorse and c[3] > 0 and rng2.random() < 0.7:
                old = c[3] * 2 if c[3] <= 2500 else c[3] // 2
                csnaps.append((eff, [c[0], c[1], c[2], old], "POLICY_ISSUED", "Original deductible."))
                csnaps.append((endorse, list(c), "DEDUCTIBLE_CHANGE", f"Deductible changed from {old} to {c[3]:g}."))
            else:
                csnaps.append((eff, list(c), "POLICY_ISSUED", "Coverage attached at issue."))
            cov_rows += _versions(csnaps)
    return pol_rows, cov_rows


# ------------------------------------------------------------------------------------------------
# Claims
# ------------------------------------------------------------------------------------------------

def claim_versions(claims, siu_opened, adjuster_ids, as_of):
    """claims: final rows. siu_opened: {claim_id: date}. Returns (version rows, {claim_id: initial claimed amount})."""
    rows, initial = [], {}
    for c in claims:
        cid, rep = c[0], date.fromisoformat(c[6])
        ack = date.fromisoformat(c[17]) if c[17] else None
        dec = date.fromisoformat(c[18]) if c[18] else None
        pay = date.fromisoformat(c[19]) if c[19] else None
        final_claimed = c[11]
        supplement = cid in ("CLM-DEMO-01", "CLM-DEMO-04") or (rng2.random() < 0.2 and not cid.startswith("CLM-DEMO"))
        init_claimed = round(final_claimed * (0.56 if cid == "CLM-DEMO-04" else rng2.uniform(0.55, 0.85)), 2) if supplement else final_claimed
        if cid == "CLM-DEMO-01":
            init_claimed = 7400.00
        initial[cid] = init_claimed
        init_adj = c[14]
        reassigned = rng2.random() < 0.1 and not cid.startswith("CLM-DEMO")
        if reassigned:
            init_adj = rng2.choice([a for a in adjuster_ids if a != c[14]])
        first = list(c)
        first[10], first[11], first[12], first[13], first[14] = "OPEN", init_claimed, round(init_claimed * 0.6, 2), 0.0, init_adj
        first[17] = first[18] = first[19] = first[20] = None
        first[21] = 0
        horizon = dec or pay or as_of
        ev = []  # (date, priority, change_type, note, {column: value})
        if reassigned:
            ev.append((min(rep + timedelta(days=rng2.randint(1, 10)), horizon), 1, "ADJUSTER_REASSIGNED",
                       f"Claim reassigned from {init_adj} to {c[14]}.", {14: c[14]}))
        if ack:
            ev.append((ack, 2, "ACKNOWLEDGED", "Claim acknowledged to the insured; reserve reviewed.",
                       {17: c[17], 12: round(init_claimed * 0.85, 2)}))
            if c[10] == "UNDER_INVESTIGATION" and cid not in siu_opened:
                ev.append((min(ack + timedelta(days=rng2.randint(1, 5)), as_of), 3, "INVESTIGATION_OPENED",
                           "Claim moved to investigation.", {10: "UNDER_INVESTIGATION"}))
        if supplement:
            top = dec - timedelta(days=1) if dec and dec > rep + timedelta(days=3) else (ack or rep) + timedelta(days=10)
            d = min(max(rep + timedelta(days=rng2.randint(3, 25)), rep + timedelta(days=1)), top, as_of)
            ev.append((d, 4, "CLAIM_SUPPLEMENT",
                       f"Claimed amount revised from {init_claimed:,.2f} to {final_claimed:,.2f} after estimate/inspection.",
                       {11: final_claimed, 12: round(final_claimed * 0.8, 2)}))
        if cid in siu_opened:
            d = siu_opened[cid]
            chg = {21: 1}
            if not dec or d < dec:
                chg[10] = "UNDER_INVESTIGATION"
            ev.append((d, 5, "SIU_REFERRAL", "Claim referred to the Special Investigations Unit.", chg))
        if dec:
            ev.append((dec, 6, "DECISION", "Claim denied in writing." if c[10] == "DENIED" else "Coverage decision issued.",
                       {18: c[18], 20: c[20], 10: "DENIED" if c[10] == "DENIED" else "APPROVED",
                        12: 0.0 if c[10] == "DENIED" else c[12]}))
        if pay:
            ev.append((pay, 7, "PAYMENT", "Claim payment issued.", {19: c[19], 13: c[13], 10: c[10], 12: c[12]}))
        cur = list(first)
        snaps = [(rep, list(first), "FNOL", "First notice of loss recorded; initial reserve set.")]
        for d, _, ct, note, chg in sorted((e for e in ev if e[0] <= as_of), key=lambda e: (e[0], e[1])):
            for k, v in chg.items():
                cur[k] = v
            snaps.append((d, list(cur), ct, note))
        snaps[-1] = (snaps[-1][0], list(c), snaps[-1][2], snaps[-1][3])
        rows += _versions(snaps)
    return rows, initial


def claimed_at(version_rows_for_claim, d):
    """claimed_amount (column 11) of the claim version in force on date d."""
    chosen = version_rows_for_claim[0]
    for v in version_rows_for_claim:
        if date.fromisoformat(v[-5]) <= d:
            chosen = v
    return chosen[11]


# ------------------------------------------------------------------------------------------------
# Claim notes  (what / where / when / how / parties / exposures / damages, added over time)
# ------------------------------------------------------------------------------------------------

_STREETS = ["Main St", "Oak Ave", "Maple Dr", "Elm St", "Industrial Pkwy", "Lakeview Rd", "Commerce Blvd", "Highland Ave", "Park Ln"]
_FIRST = ["Alex", "Jordan", "Taylor", "Morgan", "Casey", "Riley", "Devon", "Jamie", "Chris", "Pat"]
_LAST = ["Brooks", "Foster", "Nguyen", "Patel", "Reed", "Sullivan", "Ortiz", "Bennett", "Hayes", "Kim"]
_DEPT = {"OH": "Franklin County Sheriff", "TX": "Harris County Sheriff", "FL": "Miami-Dade Police", "CA": "LAPD",
         "NY": "NYPD", "IL": "Chicago PD"}


_CITIES = {"TX": ["Houston", "Dallas"], "OH": ["Columbus", "Cleveland"], "FL": ["Miami", "Tampa"],
           "CA": ["Los Angeles", "San Diego"], "NY": ["New York", "Buffalo"], "IL": ["Chicago", "Springfield"]}


def _name():
    return f"{rng2.choice(_FIRST)} {rng2.choice(_LAST)}"


def _place(line, cause, city, st):
    s = f"{rng2.randint(100, 9800)} {rng2.choice(_STREETS)}"
    if line == "AUTO":
        if cause in ("THEFT", "VANDALISM", "GLASS"):
            return rng2.choice([f"insured's driveway at {s}", f"parking lot at {s}", f"street parking near {s}"]) + f", {city}, {st}"
        return rng2.choice([f"intersection of {s} and {rng2.choice(_STREETS)}", f"I-{rng2.choice([70, 71, 75, 95, 10])} near exit {rng2.randint(1, 60)}",
                            f"retail parking lot at {s}"]) + f", {city}, {st}"
    if line == "HOME":
        return f"insured dwelling, {s}" + f", {city}, {st}"
    if line in ("COMM_PROPERTY", "GL"):
        return f"insured premises, {s}" + f", {city}, {st}"
    return f"job site / workplace, {s}" + f", {city}, {st}"


_EXPOSURES = {
    "COLLISION": "First-party collision (vehicle). Possible third-party property damage and bodily injury if another vehicle was involved.",
    "HAIL": "First-party comprehensive (hail). Possible total-loss evaluation if repair exceeds 75% of ACV.",
    "THEFT": "First-party theft. Recovery / salvage and subrogation potential if recovered.",
    "GLASS": "First-party glass. Single-component repair or replacement.",
    "VANDALISM": "First-party vandalism. Police report required; possible subrogation if offender identified.",
    "LIABILITY_PD": "Third-party property damage liability. Possible rental / loss-of-use claim by the third party.",
    "LIABILITY_BI": "Third-party bodily injury liability. Treatment ongoing; possible attorney involvement and policy-limit demand.",
    "WATER_DAMAGE": "Dwelling / contents water damage. Mold remediation and additional living expense (ALE) exposure if the home is uninhabitable.",
    "WIND_HAIL": "Roof and exterior damage. Possible interior water intrusion; roof age affects settlement basis (RCV vs ACV).",
    "FIRE": "Structure and contents fire loss. Smoke and water (suppression) damage, debris removal, ALE / business-income exposure.",
    "LIGHTNING": "Electrical system and appliance damage. Possible fire follow-on damage.",
    "FLOOD": "Surface-water / flood damage to ground floor. Flood is excluded unless a flood endorsement is on the policy.",
    "LIABILITY": "Third-party liability (premises). Medical-payments and bodily-injury exposure.",
    "BUSINESS_INTERRUPTION": "Business-income and extra-expense exposure for the period of restoration.",
    "SLIP_FALL": "Bodily injury / medical expense exposure; possible litigation. Premises maintenance and incident logs requested.",
    "PROPERTY_DAMAGE_3P": "Third-party property damage caused by insured operations; possible contractual indemnity.",
    "PRODUCT_LIABILITY": "Products liability: bodily injury and recall exposure; product lot traceability requested.",
    "STRAIN": "Workers' comp medical and indemnity (lost time) exposure; possible permanent partial disability rating.",
    "MACHINERY": "Workers' comp: traumatic injury, surgery likely; possible OSHA reporting and third-party (machine maker) subrogation.",
    "REPETITIVE_MOTION": "Workers' comp: cumulative-trauma claim; possible surgery and extended lost time.",
}
_DAMAGE = {
    "COLLISION": "Front-end damage: bumper, hood, radiator support, headlamp assembly; airbag deployment not reported.",
    "HAIL": "Hood, roof and trunk dents (approx. {n} impacts) and cracked windshield.",
    "THEFT": "Loss of stolen property; forced-entry damage to locks and ignition where applicable.",
    "GLASS": "Cracked windshield; chip repair not feasible.",
    "VANDALISM": "Keyed panels on both sides, broken side mirror.",
    "LIABILITY_PD": "Third-party vehicle rear bumper and tail-light damage.",
    "LIABILITY_BI": "Claimant reports neck and back soft-tissue injury; no fractures confirmed.",
    "WATER_DAMAGE": "Saturated drywall, flooring and cabinetry; moisture readings elevated in adjacent rooms.",
    "WIND_HAIL": "Missing and creased shingles, damaged gutters / downspouts; granule loss across roof slopes.",
    "FIRE": "Fire, smoke and water damage to structure and contents; origin area heavily charred.",
    "LIGHTNING": "Burned electrical panel, damaged appliances and HVAC control board.",
    "FLOOD": "Water line approx. {n} inches on ground floor; flooring, drywall and cabinets affected.",
    "LIABILITY": "Guest sustained injury (sprain/fracture reported); medical bills submitted.",
    "BUSINESS_INTERRUPTION": "Operations suspended; lost revenue documented for the restoration period.",
    "SLIP_FALL": "Claimant reports lower-back and wrist injury; treated at urgent care.",
    "PROPERTY_DAMAGE_3P": "Damage to third-party fixtures / equipment at customer location.",
    "PRODUCT_LIABILITY": "Claimant alleges injury from defective product; product retained for inspection.",
    "STRAIN": "Lower-back strain; off work per physician restrictions.",
    "MACHINERY": "Hand / finger laceration and crush injury; surgical repair performed.",
    "REPETITIVE_MOTION": "Carpal tunnel symptoms in both wrists; nerve-conduction study ordered.",
}
_INSIGHT = {
    "WATER_DAMAGE": "Water-loss history: check plumbing age, shut-off valve and water-leak sensors at renewal.",
    "WIND_HAIL": "Roof condition: verify roof age / material; consider ACV roof settlement or higher wind-hail deductible.",
    "FIRE": "Severity loss: review electrical / heating inspections, sprinkler status and protection class at renewal.",
    "THEFT": "Theft exposure: consider security-system requirement or higher theft deductible.",
    "FLOOD": "Flood exposure in the area: offer flood endorsement or NFIP referral to avoid coverage gaps.",
    "COLLISION": "Driver history: review MVR and annual mileage; prior at-fault frequency affects rating tier.",
    "LIABILITY_BI": "Liability severity: review limits adequacy and driver-risk tier.",
    "SLIP_FALL": "Premises risk: require housekeeping / inspection log and slip-resistant flooring at renewal.",
    "STRAIN": "Workers' comp frequency: check safety program, lifting training and experience-mod trend.",
    "MACHINERY": "Machine guarding and lock-out/tag-out compliance should be verified before renewal.",
}


def build_notes(claims, claim_vers, siu_opened, vendor_names, as_of):
    """Returns note rows. claims: final rows; claim_vers: all claim version rows."""
    vers_by_claim = {}
    for v in claim_vers:
        vers_by_claim.setdefault(v[0], []).append(v)
    out = []
    n_id = 0

    def add(cid, d, ntype, role, what=None, where=None, when=None, how=None, parties=None, expo=None, dmg=None, inj=None, uw=None, text=""):
        nonlocal n_id
        if d > as_of:
            return
        n_id += 1
        out.append([f"NOTE-{n_id:07d}", cid, 0, d.isoformat(), ntype, role, what, where, when, how, parties, expo, dmg, inj, uw, text])

    for c in claims:
        cid, line, st, cause = c[0], c[3], c[4], c[7]
        loss, rep = date.fromisoformat(c[5]), date.fromisoformat(c[6])
        ack = date.fromisoformat(c[17]) if c[17] else None
        dec = date.fromisoformat(c[18]) if c[18] else None
        pay = date.fromisoformat(c[19]) if c[19] else None
        city = _CITIES[st][0]
        vers = vers_by_claim[cid]
        vendor = vendor_names.get(c[15])
        place = _place(line, cause, city, st)
        t_loss = f"{loss.isoformat()} {rng2.randint(0, 23):02d}:{rng2.choice(['00', '15', '30', '45'])}"
        insured = "Insured"
        is_injury = cause in ("LIABILITY_BI", "SLIP_FALL", "STRAIN", "MACHINERY", "REPETITIVE_MOTION", "LIABILITY")
        init_amt = vers[0][11]
        add(cid, rep, "FNOL", "Intake Specialist",
            what=c[9], where=f"location to be confirmed, {city}, {st}", when=t_loss.split(" ")[0],
            how="As reported by the insured by phone / online; details to be confirmed.",
            parties=f"{insured} (policyholder)", expo="Initial exposure: first-party loss as described by the insured.",
            dmg=f"Insured's initial estimate ${init_amt:,.2f} (unverified).", inj=None,
            text=f"FNOL taken {rep}. Loss reported {(rep - loss).days} day(s) after the loss date.")
        insp = None
        if ack:
            insp = min(max(ack + timedelta(days=rng2.randint(1, 5)), rep), as_of)
            parties = [f"{insured} (policyholder)"]
            if cause in ("COLLISION", "LIABILITY_PD", "LIABILITY_BI"):
                parties.append(f"Other driver: {_name()}")
            if line in ("GL", "WC") or cause in ("SLIP_FALL",):
                parties.append(f"Claimant: {_name()}")
            if rng2.random() < 0.5 and cause not in ("GLASS", "STRAIN", "REPETITIVE_MOTION"):
                parties.append(f"Witness: {_name()}")
            if vendor:
                parties.append(f"Repair / service vendor: {vendor} ({c[15]})")
            amt_n = claimed_at(vers, insp)
            inj = 1 if is_injury else 0
            add(cid, insp, "INSPECTION", "Field Adjuster",
                what=c[9], where=place, when=t_loss,
                how=f"Adjuster inspection and recorded statement: {c[9]} Cause confirmed as {cause.replace('_', ' ').lower()}.",
                parties="; ".join(parties), expo=_EXPOSURES.get(cause, "First-party exposure."),
                dmg=_DAMAGE.get(cause, "Damage under evaluation.").format(n=rng2.randint(8, 40)) + f" Adjuster estimate ${amt_n:,.2f}.",
                inj=inj, text="Inspection completed; scope and estimate documented.")
        upd = None
        if insp and (dec or as_of) > insp + timedelta(days=4) and cause not in ("GLASS",):
            upd = min(insp + timedelta(days=rng2.randint(3, 20)), (dec or as_of) - timedelta(days=1))
            if upd > insp:
                extra, uw_expo = [], None
                if cause in ("COLLISION", "LIABILITY_PD", "LIABILITY_BI", "THEFT", "VANDALISM") and "no police report" not in c[9].lower():
                    extra.append(f"Police: {_DEPT[st]} report #PR-{rng2.randint(100000, 999999)}")
                if is_injury:
                    extra.append(f"Treating provider: {rng2.choice(['Mercy Urgent Care', 'Summit Orthopedics', 'Riverside Chiropractic'])}")
                    uw_expo = " Medical specials to date approx. ${:,.0f}; claimant has retained counsel: {}.".format(
                        claimed_at(vers, upd) * 0.35, "yes" if rng2.random() < 0.4 else "no")
                elif line in ("HOME", "COMM_PROPERTY"):
                    uw_expo = " Mitigation / emergency services completed; additional living expense under review."
                amt_u = claimed_at(vers, upd)
                add(cid, upd, "COVERAGE_UPDATE", "Field Adjuster",
                    what=None, where=None, when=None, how=None,
                    parties=("; ".join(extra) if extra else None),
                    expo=(_EXPOSURES.get(cause, "") + (uw_expo or "")),
                    dmg=f"Updated documented damages ${amt_u:,.2f} after receipt of reports / estimates.",
                    inj=1 if is_injury else None, uw=_INSIGHT.get(cause),
                    text="New information received after the initial inspection.")
        if c[0] in siu_opened and siu_opened[c[0]] <= as_of:
            add(cid, siu_opened[c[0]], "SIU", "SIU Analyst",
                text="Referred to SIU after red-flag review. Investigation details are held in the SIU case file.")
        if dec:
            if c[10] == "DENIED":
                add(cid, dec, "DECISION", "Claims Examiner", text=f"Claim denied: {c[20] or 'coverage position letter issued'}.",
                    uw="Denied claim: record the exclusion / coverage gap for underwriting follow-up with the insured.")
            else:
                add(cid, dec, "DECISION", "Claims Examiner", text=f"Coverage accepted. Settlement authorised at ${c[11]:,.2f} claimed less deductible.",
                    uw=_INSIGHT.get(cause))
        if pay:
            add(cid, pay, "CLOSING", "Claims Payments", text=f"Payment of ${c[13]:,.2f} issued; file closed subject to subrogation / salvage review.")

        # planted: inconsistent statements (later statement contradicts the first report)
        planted = cid in ("CLM-DEMO-01", "CLM-DEMO-05") or (not cid.startswith("CLM-DEMO") and insp and rng2.random() < 0.05)
        if planted and insp:
            sd = min((upd or insp) + timedelta(days=rng2.randint(1, 4)), as_of)
            if sd > date.fromisoformat(out[-1][3]) or True:
                other_city = _CITIES[st][1]
                add(cid, sd, "RECORDED_STATEMENT", "Field Adjuster",
                    what=None, where=f"{rng2.choice(_STREETS)}, {other_city}, {st}",
                    when=(loss + timedelta(days=rng2.randint(2, 9))).isoformat() + " 18:30",
                    how="In the recorded statement the insured described a different time and location than in the first notice of loss.",
                    inj=(1 if not is_injury else None),
                    text="Statement differs from FNOL on date/location. Flag for SIU consideration.")
    # numbering per claim
    out.sort(key=lambda r: (r[1], r[3], r[0]))
    seq = {}
    for r in out:
        seq[r[1]] = seq.get(r[1], 0) + 1
        r[2] = seq[r[1]]
    return out


# ------------------------------------------------------------------------------------------------
# Claim documents (+ planted duplicate invoices)
# ------------------------------------------------------------------------------------------------

def build_documents(claims, ring, as_of):
    """claim_documents: doc_id, claim_id, doc_type, doc_date, received_date, vendor_id, invoice_number, invoice_amount, file_name"""
    rows, n = [], 0
    ring_invoices = {v: [] for v in ring}
    missing_demo = {"CLM-DEMO-01": {"POLICE_REPORT"}, "CLM-DEMO-04": {"FIRE_REPORT", "PROOF_OF_LOSS"},
                    "CLM-DEMO-05": {"WITNESS_STATEMENT", "WAGE_STATEMENT"}}
    for c in claims:
        cid, line, cause, vendor = c[0], c[3], c[7], c[15]
        rep = date.fromisoformat(c[6])
        need = required_documents(line, cause, c[11], bool(vendor))
        p_have = {"PAID": 0.97, "APPROVED": 0.96, "DENIED": 0.9}.get(c[10], 0.8)
        for doc in need:
            if cid in missing_demo:
                present = doc not in missing_demo[cid]
            elif cid.startswith("CLM-DEMO"):
                present = True
            else:
                present = rng2.random() < p_have
            if not present:
                continue
            n += 1
            d = min(rep + timedelta(days=rng2.randint(0, 6)), as_of)
            inv_no = inv_amt = None
            if doc in ("INVOICE", "REPAIR_ESTIMATE", "CONTRACTOR_ESTIMATE"):
                inv_amt = round(c[11] * (rng2.uniform(0.97, 1.0) if vendor in ring else rng2.uniform(0.9, 1.05)), 2)
                if doc == "INVOICE":
                    inv_no = f"INV-{(vendor or 'GEN')[-3:]}-{rng2.randint(10000, 99999)}"
                    if vendor in ring:
                        if ring_invoices[vendor] and rng2.random() < 0.3:
                            inv_no = rng2.choice(ring_invoices[vendor])  # planted: the same invoice number reused on another claim
                        ring_invoices[vendor].append(inv_no)
            rows.append([f"DOC-{n:07d}", cid, doc, d.isoformat(), min(d + timedelta(days=rng2.randint(0, 3)), as_of).isoformat(),
                         vendor if doc in ("INVOICE", "REPAIR_ESTIMATE", "CONTRACTOR_ESTIMATE") else None, inv_no, inv_amt,
                         f"{cid}_{doc.lower()}.pdf"])
    # the demo claim DEMO-01 reuses an invoice number already billed on another ring claim
    reused = next((r[6] for r in rows if r[5] == "VND-901" and r[6] and r[1] != "CLM-DEMO-01"), None)
    if reused:
        for r in rows:
            if r[1] == "CLM-DEMO-01" and r[2] == "INVOICE":
                r[6] = reused
    return rows
