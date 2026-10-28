"""Generate the Cardinal Ridge company + state policy PDFs into sample_docs/.

Run from the project root:   python insurance_data/generate_pdfs.py
Needs reportlab (pip install reportlab). Everything is FICTIONAL; state summaries are SIMPLIFIED demo values,
not legal advice, and must match the state_regulations table produced by generate_data.py.
"""
from pathlib import Path

from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib import colors

OUT = Path(__file__).resolve().parent.parent / "sample_docs"
OUT.mkdir(exist_ok=True)
CO = "Cardinal Ridge Insurance Group"
DISCLAIMER = ("FICTIONAL DOCUMENT - created for a software demonstration. Cardinal Ridge Insurance Group does not exist. "
              "Legal and regulatory content is simplified and is NOT legal advice.")

ss = getSampleStyleSheet()
H1 = ParagraphStyle("H1", parent=ss["Heading1"], fontSize=18, spaceAfter=10)
H2 = ParagraphStyle("H2", parent=ss["Heading2"], fontSize=13, spaceBefore=10, spaceAfter=4)
BODY = ParagraphStyle("B", parent=ss["BodyText"], fontSize=10, leading=14, alignment=TA_LEFT)
SMALL = ParagraphStyle("S", parent=BODY, fontSize=8, textColor=colors.grey)


def build(filename: str, title: str, doc_no: str, sections: list) -> None:
    """sections: list of (heading, [paragraph | ('bullets', [..]) | ('table', [[..]])])"""
    story = [Paragraph(title, H1), Paragraph(f"{CO} | Document {doc_no} | Effective 2026-01-01 | Version 3.1", SMALL),
             Spacer(1, 4), Paragraph(DISCLAIMER, SMALL), Spacer(1, 8)]
    for heading, items in sections:
        story.append(Paragraph(heading, H2))
        for it in items:
            if isinstance(it, str):
                story.append(Paragraph(it, BODY))
                story.append(Spacer(1, 4))
            elif it[0] == "bullets":
                for b in it[1]:
                    story.append(Paragraph("&bull; " + b, BODY))
                story.append(Spacer(1, 4))
            elif it[0] == "table":
                t = Table(it[1], hAlign="LEFT", repeatRows=1)
                t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8edf3")),
                                       ("FONTSIZE", (0, 0), (-1, -1), 8.5), ("VALIGN", (0, 0), (-1, -1), "TOP")]))
                story += [t, Spacer(1, 6)]
    SimpleDocTemplate(str(OUT / filename), pagesize=letter, leftMargin=0.9 * inch, rightMargin=0.9 * inch,
                      topMargin=0.8 * inch, bottomMargin=0.8 * inch, title=title, author=CO).build(story)
    print("wrote", filename)


# ----------------------------------------------------------------------------------------------
# Company documents
# ----------------------------------------------------------------------------------------------

def claims_guidelines():
    build("cardinal_ridge_claims_authority_and_reserving_guidelines.pdf",
          "Claims Handling, Settlement Authority & Reserving Guidelines", "CRIG-CLM-001", [
        ("1. Purpose and scope", [
            "These guidelines govern how Cardinal Ridge Insurance Group (CRIG) handles first-party and third-party claims in Auto (AUTO), "
            "Homeowners (HOME), Commercial Property (COMM_PROPERTY), General Liability (GL) and Workers' Compensation (WC) in Ohio, Texas, "
            "Florida, California, New York and Illinois. They apply to every adjuster, supervisor, vendor manager and third-party administrator."]),
        ("2. Claim lifecycle", [
            ("table", [["Stage", "Standard", "Owner"],
                       ["First notice of loss (FNOL)", "Log within 1 business day; assign adjuster same day", "Intake"],
                       ["Acknowledgement", "Within the state clock (see state summaries); company standard 2 business days", "Adjuster"],
                       ["Coverage review", "Confirm policy in force on loss date, coverage, exclusions, deductible", "Adjuster / Coverage counsel"],
                       ["Investigation", "Statements, photos, estimates, police/fire reports as relevant", "Adjuster"],
                       ["Decision", "Accept or deny in writing inside the state decision clock", "Adjuster / authority holder"],
                       ["Payment", "Within the state payment clock after acceptance", "Claims payments"]])]),
        ("3. Delegation of settlement authority", [
            "No one may approve a payment above their personal authority. The assessed amount is the HIGHER of the claimed amount and the "
            "current reserve. Authority is per claim, per occurrence.",
            ("table", [["Level", "Authority limit (USD)", "Notes"],
                       ["Claims Adjuster (JUNIOR)", "10,000", "Auto physical damage, small property"],
                       ["Senior Adjuster (SENIOR)", "50,000", "Includes small bodily injury"],
                       ["Claims Manager (MANAGER)", "250,000", "Requires file review before approval"],
                       ["Claims Director (DIRECTOR)", "1,000,000", "Reinsurance notice check mandatory"],
                       ["Claims VP + Board notification", "Above 1,000,000", "Notify CEO, CFO and Board Risk Committee"]]),
            "Splitting a loss into several smaller payments to stay under an authority limit is prohibited and is itself a fraud red flag."]),
        ("4. Reserving", [
            ("bullets", ["Set an initial reserve within 3 business days of FNOL at the probable ultimate cost, not the best case.",
                         "Review reserves every 30 days and after any material development (new estimate, suit filed, injury update).",
                         "Reserve changes above 25,000 USD require Manager approval; above 250,000 USD require Director approval.",
                         "Catastrophe (CAT) claims are reserved using the CAT average-reserve table until an inspection is complete."])]),
        ("5. Reinsurance notice", [
            "Claims whose assessed amount reaches the treaty notice threshold must be reported to Reinsurance Accounting within 5 business days. "
            "Thresholds for the 2026 treaty year: Property Catastrophe XOL 500,000 USD; Casualty XOL 500,000 USD; Auto Quota Share 1,000,000 USD. "
            "Failure to give timely notice can jeopardise recovery."]),
        ("6. Denials and reservation of rights", [
            ("bullets", ["Every denial must be in writing, cite the specific policy provision and facts, and explain the appeal / complaint rights.",
                         "Never deny on suspicion of fraud alone: refer to SIU, send a reservation-of-rights letter and keep state clocks running.",
                         "A policy cancelled for non-payment before the date of loss provides no coverage for that loss.",
                         "Flood and surface-water losses are excluded under the homeowners form unless a flood endorsement is on the policy."])]),
        ("7. Vendor management", [
            "Preferred vendors must be licensed, insured and in good standing. Vendors with three or more SIU cases in 24 months are moved to "
            "'watch' status; payments to watch-status vendors need Manager approval regardless of amount."]),
    ])


def siu_guidelines():
    build("cardinal_ridge_siu_fraud_detection_guidelines.pdf", "Special Investigations Unit (SIU) Fraud Detection Guidelines",
          "CRIG-SIU-002", [
        ("1. Purpose", [
            "Insurance fraud raises premiums for every policyholder. These guidelines describe the red flags that trigger referral to the "
            "Special Investigations Unit and how to handle a referral lawfully. A red flag is a reason to investigate, never proof of fraud."]),
        ("2. Red-flag scoring model", [
            "The claims system scores every claim from 0 to 100. Points are added for each flag that applies:",
            ("table", [["Red flag", "Points"],
                       ["Loss within 30 days of policy inception (31-60 days)", "20 (10)"],
                       ["Reported more than 30 days after the loss (more than 14 days)", "15 (8)"],
                       ["Amount within 5% below a settlement-authority threshold", "15"],
                       ["Claim at or above 90% of the coverage limit", "10"],
                       ["Round-dollar amount of 5,000 USD or more", "5"],
                       ["3 or more other claims by the customer in 24 months (2 claims)", "20 (10)"],
                       ["Vendor linked to 3 or more SIU cases (1-2 cases)", "20 (10)"],
                       ["Two or more address changes in 12 months", "8"],
                       ["Policy cancelled within 30 days after the loss", "10"],
                       ["No witnesses and no police report", "8"]]),
            "Bands: 50 or more = HIGH (refer to SIU before any payment); 25-49 = MEDIUM (supervisor review and extra documentation); "
            "below 25 = LOW (normal handling)."]),
        ("3. Organised vendor rings", [
            "Typical pattern: a body shop, restoration contractor or clinic submits many claims of similar size just below a settlement-authority "
            "limit (for example 9,200-9,980 USD against the 10,000 USD junior limit), is new to the network, and is linked to several SIU cases. "
            "Handlers must check the vendor history before approving any claim that involves such a vendor."]),
        ("4. Referral procedure", [
            ("bullets", ["Refer within 2 business days of the HIGH score; document the red flags in the file.",
                         "Do not tell the policyholder that fraud is suspected. Send an acknowledgement and, if needed, a reservation-of-rights letter.",
                         "State prompt-payment clocks continue to run during an investigation: send written extension / status letters as the state requires.",
                         "SIU may request recorded statements, examinations under oath, medical or repair records, and ISO ClaimSearch reports.",
                         "Where fraud is substantiated, SIU files the state fraud-bureau report within the statutory deadline (typically 30-60 days)."])]),
        ("5. Outcomes", [
            ("bullets", ["Cleared: claim returns to the adjuster; paid within the remaining state clock.",
                         "Denied for misrepresentation: denial letter approved by Coverage Counsel.",
                         "Referred to law enforcement / state fraud bureau: handled only by SIU leadership."])]),
        ("6. Privacy and fairness", [
            "Investigations must follow privacy law (see the Privacy & Data Protection Policy) and must not use protected-class characteristics. "
            "Scores and flags are decision support: a human must make every referral and denial decision."]),
    ])


def underwriting_guidelines():
    build("cardinal_ridge_underwriting_guidelines.pdf", "Underwriting Guidelines - Personal & Commercial Lines", "CRIG-UW-003", [
        ("1. Authority and referral", [
            ("table", [["Item", "Underwriter", "Senior UW", "Chief UW"],
                       ["Annual premium", "up to 25,000", "up to 100,000", "above 100,000"],
                       ["Total insured value (property)", "up to 2,000,000", "up to 10,000,000", "above 10,000,000"],
                       ["Loss history (3 yrs)", "up to 2 claims", "up to 4 claims", "5 or more"]])]),
        ("2. Homeowners (HO-3)", [
            ("bullets", ["Roof age above 20 years: decline wind/hail coverage on replacement-cost basis; offer actual cash value.",
                         "Coastal wind exposure (FL, TX within 25 miles of the coast): hurricane deductible of 2% of the dwelling limit applies.",
                         "Flood is NOT covered; offer a flood endorsement or refer the insured to the NFIP.",
                         "Prior losses: 3 or more paid claims in 3 years requires Senior UW approval."])]),
        ("3. Personal Auto", [
            ("bullets", ["Drivers with a major violation (DUI, reckless) in 3 years: refer to Senior UW.",
                         "Credit-based insurance scores are used only where permitted (not in CA).",
                         "Non-payment cancellation requires the notice period of the state.",
                         "Vehicles with salvage titles: liability only."])]),
        ("4. Commercial lines", [
            ("bullets", ["Commercial property: sprinkler status, construction class, protection class and occupancy are required; "
                         "vacant buildings over 60 days are ineligible.",
                         "General liability: contractor risks require certificates of insurance for subcontractors and a written safety program.",
                         "Workers' comp: experience modification factor above 1.25 requires Senior UW approval; roofing and logging are prohibited classes."])]),
        ("5. Referral triggers", [
            ("bullets", ["Material misrepresentation on the application.", "Loss runs missing or older than 60 days.",
                         "Exposure in a declared catastrophe zone during the event window.", "Risks above treaty capacity: notify Reinsurance."])]),
    ])


def ho3_policy():
    build("cardinal_ridge_homeowners_ho3_policy_form.pdf", "Homeowners Policy Form HO-3 (Summary of Coverage)", "CRIG-FORM-HO3", [
        ("1. Coverages", [
            ("table", [["Coverage", "Description", "Limit basis"],
                       ["A - Dwelling", "The home and attached structures (open perils)", "Policy dwelling limit"],
                       ["B - Other Structures", "Detached garage, fence, shed", "10% of Coverage A"],
                       ["C - Personal Property", "Contents (named perils)", "50% of Coverage A"],
                       ["D - Loss of Use", "Additional living expense", "20% of Coverage A"],
                       ["E - Personal Liability", "Legal liability to others", "Per policy"],
                       ["F - Medical Payments", "Guest medical expenses", "Per policy"]])]),
        ("2. Exclusions", [
            ("bullets", ["Flood, surface water, storm surge and groundwater seepage (a FLOOD endorsement is available for purchase).",
                         "Earth movement including earthquake (endorsement available).",
                         "Wear and tear, mold from long-term leaks, neglect, intentional loss.",
                         "Sewer / drain backup unless the water-backup endorsement is attached."])]),
        ("3. Deductibles", [
            "All-peril deductible applies per occurrence. In Florida and Texas, a named-hurricane loss carries a percentage deductible equal "
            "to 2% of the Coverage A (dwelling) limit. Wind/hail in Texas may carry a separate 1% deductible."]),
        ("4. Conditions", [
            ("bullets", ["Report a loss promptly and protect the property from further damage.",
                         "Provide proof of loss within 60 days of the insurer's request.",
                         "Misrepresentation or fraud voids coverage for the claim.",
                         "Coverage ends on the cancellation date; a loss after that date is not covered."])]),
    ])


def auto_policy():
    build("cardinal_ridge_personal_auto_policy_form.pdf", "Personal Auto Policy Form (Summary of Coverage)", "CRIG-FORM-PAP", [
        ("1. Coverages", [
            ("table", [["Coverage code", "Coverage", "Typical use"],
                       ["BI / PD", "Bodily injury and property damage liability", "Third-party claims"],
                       ["COLL", "Collision", "Your car damaged in a crash"],
                       ["COMP", "Comprehensive", "Theft, hail, glass, animal, fire"],
                       ["UM/UIM", "Uninsured / underinsured motorist", "Hit by uninsured driver"],
                       ["MEDPAY / PIP", "Medical payments / personal injury protection", "Medical bills"],
                       ["RENTAL", "Rental reimbursement", "Loss-of-use during repairs"]])]),
        ("2. Exclusions", [
            ("bullets", ["Racing, intentional damage, commercial use (rideshare requires an endorsement).",
                         "Wear and tear, mechanical breakdown, and tires unless damaged by a covered loss.",
                         "Losses occurring after cancellation, lapse or non-renewal date."])]),
        ("3. Claims duties", [
            ("bullets", ["Report accidents promptly; file a police report for injuries, theft or damage over the state reporting threshold.",
                         "Allow inspection of the vehicle; use of a Direct Repair Program shop is optional - you may choose your own shop.",
                         "Total loss: settlement at actual cash value less the deductible."])]),
    ])


def cat_plan():
    build("cardinal_ridge_catastrophe_response_plan.pdf", "Catastrophe (CAT) Response Plan", "CRIG-CAT-005", [
        ("1. Activation", [
            "A catastrophe event is declared by the Chief Claims Officer when an event is expected to generate more than 500 claims or 25 million "
            "USD of insured loss. Each event receives a CAT code, for example CAT-2025-HURR-FL (Hurricane, Florida), CAT-2025-HURR-TX and "
            "CAT-2026-HAIL-TX (hail, Texas)."]),
        ("2. Operating model", [
            ("bullets", ["Surge adjusters: independent adjusters are engaged under CAT authority (JUNIOR 10,000 USD) with desk review above that.",
                         "Triage: life-safety and uninhabitable homes first; drone and satellite imagery for roofs.",
                         "Advance payments: up to 5,000 USD for additional living expenses without full inspection.",
                         "Claims are tagged with the CAT code so reserves, reinsurance and regulatory reports can be produced by event."])]),
        ("3. Regulatory notes", [
            ("bullets", ["Regulators may extend or suspend claims deadlines after a declared disaster - always check the state bulletin.",
                         "Florida: acknowledge within 7 calendar days; decide within 60 calendar days of notice.",
                         "Hurricane percentage deductible (2% of dwelling limit) applies only to named-storm losses in FL and TX."])]),
        ("4. Reinsurance", [
            "Property Catastrophe XOL treaty RI-2026-PROP-XOL: retention 5,000,000 USD, limit 100,000,000 USD. Aggregate event losses and "
            "notify the reinsurers when the event reaches 50% of the retention."]),
    ])


def reinsurance():
    build("cardinal_ridge_reinsurance_treaty_summary.pdf", "Reinsurance Treaty Summary - 2026 Treaty Year", "CRIG-RI-006", [
        ("1. Treaties", [
            ("table", [["Treaty", "Type", "Lines", "Retention", "Limit", "Cession", "Claim notice at"],
                       ["RI-2026-PROP-XOL", "Excess of Loss", "HOME, COMM_PROPERTY", "5,000,000", "100,000,000", "100% above retention", "500,000"],
                       ["RI-2026-AUTO-QS", "Quota Share", "AUTO", "-", "-", "20% of every loss", "1,000,000"],
                       ["RI-2026-CASUALTY-XOL", "Excess of Loss", "GL, WC", "1,000,000", "24,000,000", "100% above retention", "500,000"]])]),
        ("2. Notice requirements", [
            "Claims at or above the notice threshold must be reported to the reinsurer within 5 business days. Late notice may reduce recovery. "
            "Reinsurance Accounting maintains the large-loss register."]),
    ])


def privacy():
    build("cardinal_ridge_privacy_and_data_protection_policy.pdf", "Privacy & Data Protection Policy", "CRIG-PRV-007", [
        ("1. Principles", [
            ("bullets", ["Collect and use personal information only for underwriting, claims, fraud prevention and legal obligations (GLBA).",
                         "Mask SSNs, driver-licence numbers, bank and card numbers in tickets, e-mails and AI prompts.",
                         "Provide the annual privacy notice and honour opt-out rights; state laws (for example CCPA/CPRA in California) may add rights.",
                         "Notify affected individuals and regulators of a data breach within the state-law deadline (often 30-60 days)."])]),
        ("2. Use of AI", [
            ("bullets", ["AI tools provide decision support only; a licensed human decides coverage, denial and fraud referral.",
                         "AI outputs must be explainable: cite the rule, tool result or document used.",
                         "No protected-class attributes may be used in fraud scoring or pricing.",
                         "Customer personal data must be redacted before being sent to external model providers."])]),
    ])


def commercial_guidelines():
    build("cardinal_ridge_commercial_property_and_wc_claims_guidelines.pdf",
          "Commercial Property & Workers' Compensation Claims Guidelines", "CRIG-COM-008", [
        ("1. Commercial property", [
            ("bullets", ["Large losses (assessed amount of 250,000 USD or more) require a field adjuster, a forensic accountant for business interruption "
                         "and notice to Reinsurance when the treaty threshold is reached.",
                         "Fire losses: obtain the fire-department report and cause-and-origin findings; consider SIU where arson indicators appear.",
                         "Advance payments for emergency mitigation are allowed up to the adjuster's authority."])]),
        ("2. Workers' compensation", [
            ("bullets", ["Employer report of injury is due to the carrier within 7 days; late reporting by the employee (over 30 days) is a red flag.",
                         "Unwitnessed injuries, Monday-morning injuries and clinics with high-volume billing patterns warrant medical bill review and SIU triage.",
                         "Use the state fee schedule; IME (independent medical examination) may be requested when treatment exceeds guidelines.",
                         "Return-to-work program: contact employer within 5 business days to explore modified duty."])]),
        ("3. General liability", [
            ("bullets", ["Obtain the incident report, witness statements and contract / certificate-of-insurance details; tender to additional insureds where applicable.",
                         "Reserve for defence costs separately from indemnity."])]),
    ])


# ----------------------------------------------------------------------------------------------
# State regulation summaries (SIMPLIFIED demo values, aligned with the state_regulations table)
# ----------------------------------------------------------------------------------------------
STATES = {
    "tx": ("Texas", "Texas Prompt Payment of Claims Act (Tex. Ins. Code ch. 542)", 15, 15, 5, "business",
           "Request additional information within 15 business days; if more time is needed the insurer must tell the claimant why. "
           "Late payment carries statutory interest. Hail and wind claims may carry a separate percentage deductible; named-hurricane deductible 2%."),
    "fl": ("Florida", "Florida Claims Administration Statute (Fla. Stat. 627.70131)", 7, 60, 60, "calendar",
           "Acknowledge within 7 calendar days; begin investigation within 7 days of proof of loss; pay or deny within 60 days of notice. "
           "Hurricane deductible 2% of dwelling limit for named storms. Flood is excluded unless a flood endorsement or NFIP policy is in place."),
    "ca": ("California", "California Fair Claims Settlement Practices Regulations (10 CCR 2695)", 15, 40, 30, "calendar",
           "Acknowledge within 15 calendar days; accept or deny within 40 calendar days of proof of claim; pay within 30 calendar days of acceptance. "
           "A written denial must state the reasons and refer the claimant to the Department of Insurance."),
    "ny": ("New York", "New York Insurance Regulation 64 (11 NYCRR 216)", 15, 15, 5, "business",
           "Acknowledge within 15 business days; accept or reject within 15 business days of receiving proof of claim; pay within 5 business days. "
           "Workers' compensation is administered through the Workers' Compensation Board."),
    "oh": ("Ohio", "Ohio Administrative Code 3901-1-54 (Unfair Property/Casualty Claims Settlement Practices)", 15, 21, 10, "calendar",
           "Acknowledge within 15 calendar days; decide within 21 calendar days of proof of loss; pay within 10 calendar days of settlement agreement. "
           "Insurers must keep complaint records for the state department of insurance."),
    "il": ("Illinois", "Illinois Insurance Code section 154.6 and 50 Ill. Adm. Code 919", 10, 30, 30, "business",
           "Acknowledge within 10 business days; decide within 30 business days of proof of loss; pay within 30 business days of acceptance. "
           "Written denial must identify the policy provision relied upon."),
}


def state_docs():
    for code, (name, statute, ack, dec, pay, unit, notes) in STATES.items():
        build(f"state_{code}_claims_regulations_summary.pdf", f"{name} - Claims Handling Regulations Summary", f"CRIG-REG-{code.upper()}", [
            ("1. Legal source (simplified)", [statute + ". This summary uses simplified, fictionalised figures for demonstration. Always confirm with Compliance."]),
            ("2. Claim-handling clocks", [
                ("table", [["Milestone", f"{name} standard", "Clock type"],
                           ["Acknowledge the claim", f"{ack} days", unit],
                           ["Accept or deny the claim", f"{dec} days after proof of loss / notice", unit],
                           ["Pay an accepted claim", f"{pay} days", unit]]),
                "A missed clock is a BREACH: the claim becomes NON-COMPLIANT, late-payment interest may accrue and the file must be escalated to Compliance."]),
            ("3. State-specific notes", [notes]),
            ("4. Required actions when a clock is at risk", [
                ("bullets", ["Send a written status / extension letter explaining what is still needed.",
                             "Escalate to the Claims Manager when fewer than 3 days remain.",
                             "Record the reason for any delay in the claim notes; accrue interest in the reserve where applicable.",
                             "A pending SIU investigation does NOT pause the state clock."])]),
        ])


if __name__ == "__main__":
    for old in OUT.glob("*.pdf"):
        old.unlink()
    for fn in (claims_guidelines, siu_guidelines, underwriting_guidelines, ho3_policy, auto_policy, cat_plan,
               reinsurance, privacy, commercial_guidelines, state_docs):
        fn()
