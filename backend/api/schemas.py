from typing import Literal, Optional

from pydantic import BaseModel


# ============================================================
# AGENT  Schemas
# ============================================================



class AuditRequest(BaseModel):
    request_text: str

class AuditResponse(BaseModel):
    coverage_result: str
    fraud_result: str
    compliance_result: str
    director_memo: str


class AssistantRequest(BaseModel):
    question: str

class AssistantResponse(BaseModel):
    answer: str


class DataExplorerRequest(BaseModel):
    query: str


class DataExplorerResponse(BaseModel):
    status: str  # ok | no_data | rejected
    mode: str  # sql | nl
    message: str
    sql: str
    columns: list[str]
    rows: list[list]
    row_count: int
    truncated: bool
    detail: str = ""


class UnderwritingRequest(BaseModel):
    request_text: str


class UnderwritingReviewRequest(BaseModel):
    thread_id: str
    decision: Literal["approve", "edit", "reject"]
    reviewer_comment: str = ""
    edited_authority: Optional[str] = None
    edited_reason: Optional[str] = None


class UnderwritingResponse(BaseModel):
    status: Literal["COMPLETED", "PENDING_REVIEW"]
    submission_id: str
    thread_id: str
    assessment: dict
    application_result: str
    loss_history_result: str
    referral_result: Optional[str] = None
    underwriter_memo: Optional[str] = None
    human_review: Optional[str] = None
    pending_review: Optional[dict] = None


# ============================================================
# RAG  Schemas
# ============================================================


class QueryRequest(BaseModel):
    query: str
    retriever_type: str = "similarity"

class QueryResponse(BaseModel):
    answer: str