"""Which supporting documents Cardinal Ridge requires for a claim (single source of truth).

Used by the claims-processing agent, the customer advisor ("what is still outstanding?") and by
insurance_data/generate_data.py (so the synthetic claim_documents table follows the same rules).
Mirrors sample_docs/cardinal_ridge_claims_documentation_and_processing_manual.pdf.
"""

DOC_LABELS = {
    "CLAIM_FORM": "Signed claim form / first report of injury",
    "PHOTOS": "Photos of the damage",
    "REPAIR_ESTIMATE": "Repair estimate",
    "CONTRACTOR_ESTIMATE": "Contractor repair / restoration estimate",
    "INVOICE": "Vendor invoice",
    "POLICE_REPORT": "Police report",
    "FIRE_REPORT": "Fire department / fire marshal report",
    "PROOF_OF_OWNERSHIP": "Proof of ownership",
    "ITEM_INVENTORY": "Itemised inventory of lost / stolen items",
    "MEDICAL_REPORT": "Medical report",
    "MEDICAL_BILLS": "Medical bills",
    "INCIDENT_REPORT": "Incident / accident report",
    "WITNESS_STATEMENT": "Witness statement",
    "WAGE_STATEMENT": "Wage statement",
    "FINANCIAL_RECORDS": "Financial records (business-income proof)",
    "PROOF_OF_LOSS": "Sworn proof of loss",
}

_BASE = ["CLAIM_FORM"]

_AUTO = {
    "COLLISION": ["PHOTOS", "REPAIR_ESTIMATE", "POLICE_REPORT"],
    "HAIL": ["PHOTOS", "REPAIR_ESTIMATE"],
    "THEFT": ["POLICE_REPORT", "PROOF_OF_OWNERSHIP"],
    "GLASS": ["REPAIR_ESTIMATE"],
    "VANDALISM": ["PHOTOS", "POLICE_REPORT", "REPAIR_ESTIMATE"],
    "LIABILITY_PD": ["POLICE_REPORT", "REPAIR_ESTIMATE"],
    "LIABILITY_BI": ["POLICE_REPORT", "MEDICAL_REPORT", "MEDICAL_BILLS"],
}
_HOME = {
    "WATER_DAMAGE": ["PHOTOS", "CONTRACTOR_ESTIMATE"],
    "WIND_HAIL": ["PHOTOS", "CONTRACTOR_ESTIMATE"],
    "LIGHTNING": ["PHOTOS", "CONTRACTOR_ESTIMATE"],
    "FLOOD": ["PHOTOS", "CONTRACTOR_ESTIMATE"],
    "FIRE": ["PHOTOS", "FIRE_REPORT", "CONTRACTOR_ESTIMATE"],
    "THEFT": ["POLICE_REPORT", "ITEM_INVENTORY"],
    "LIABILITY": ["MEDICAL_REPORT", "INCIDENT_REPORT"],
}
_COMM = {
    "FIRE": ["PHOTOS", "FIRE_REPORT", "CONTRACTOR_ESTIMATE"],
    "WATER_DAMAGE": ["PHOTOS", "CONTRACTOR_ESTIMATE"],
    "WIND_HAIL": ["PHOTOS", "CONTRACTOR_ESTIMATE"],
    "THEFT": ["POLICE_REPORT", "ITEM_INVENTORY"],
    "BUSINESS_INTERRUPTION": ["FINANCIAL_RECORDS"],
}
_GL = {
    "SLIP_FALL": ["INCIDENT_REPORT", "MEDICAL_REPORT", "WITNESS_STATEMENT"],
    "PROPERTY_DAMAGE_3P": ["PHOTOS", "REPAIR_ESTIMATE"],
    "PRODUCT_LIABILITY": ["INCIDENT_REPORT", "MEDICAL_REPORT"],
}
_WC = {
    "STRAIN": ["MEDICAL_REPORT", "INCIDENT_REPORT", "WAGE_STATEMENT"],
    "SLIP_FALL": ["MEDICAL_REPORT", "INCIDENT_REPORT", "WAGE_STATEMENT", "WITNESS_STATEMENT"],
    "MACHINERY": ["MEDICAL_REPORT", "INCIDENT_REPORT", "WAGE_STATEMENT", "WITNESS_STATEMENT"],
    "REPETITIVE_MOTION": ["MEDICAL_REPORT", "INCIDENT_REPORT", "WAGE_STATEMENT"],
}
_BY_LINE = {"AUTO": _AUTO, "HOME": _HOME, "COMM_PROPERTY": _COMM, "GL": _GL, "WC": _WC}


def required_documents(line: str, cause: str, amount: float = 0.0, has_vendor: bool = False) -> list[str]:
    """Ordered list of document types required before a claim can be decided."""
    docs = list(_BASE) + list(_BY_LINE.get(line, {}).get(cause, ["PHOTOS"]))
    if has_vendor or amount >= 10_000:
        if "INVOICE" not in docs and line in ("AUTO", "HOME", "COMM_PROPERTY", "GL"):
            docs.append("INVOICE")
    if line == "COMM_PROPERTY" and amount >= 250_000:
        docs.append("PROOF_OF_LOSS")
    return docs
