/**
 * api.ts — Centralized API client for the FastAPI backend.
 */

const BASE_URL = import.meta.env.VITE_API_URL || (import.meta.env.DEV ? "http://localhost:8080" : "");

async function request<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`, options);
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ─── RAG ─────────────────────────────────────────────────────

export async function uploadDocument(file: File) {
  const form = new FormData();
  form.append("files", file);
  return request<{ results: Array<{ filename: string; status: string; reason?: string; pages?: number; chunks?: number }> }>("/api/rag/upload", { method: "POST", body: form });
}

export async function uploadDocuments(files: File[]) {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  return request<{ results: Array<{ filename: string; status: string; reason?: string; pages?: number; chunks?: number }> }>("/api/rag/upload", { method: "POST", body: form });
}

export async function listUploads() {
  return request("/api/rag/uploads");
}

export async function askQuestion(query: string, retrieverType: string = "similarity") {
  return request<{ answer: string }>("/api/rag/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, retriever_type: retrieverType }),
  });
}

/** Index every PDF in the document store: local folder (APP_MODE=local) or GCS bucket (APP_MODE=cloud). */
export async function triggerStoreIngestion() {
  return request<{ status: string; files: number; pages: number; chunks: number }>("/api/rag/ingest", { method: "POST" });
}

// ─── Agent ───────────────────────────────────────────────────

export async function runAudit(requestText: string) {
  return request<{
    coverage_result: string;
    fraud_result: string;
    compliance_result: string;
    director_memo: string;
  }>("/api/agent/audit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request_text: requestText }),
  });
}

export async function askAssistant(question: string) {
  return request<{ answer: string }>("/api/agent/assistant", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
  });
}

// ─── Data Explorer ───────────────────────────────────────────

export interface DataExplorerResult {
  status: "ok" | "no_data" | "rejected";
  mode: "sql" | "nl";
  message: string;
  sql: string;
  columns: string[];
  rows: (string | number | null)[][];
  row_count: number;
  truncated: boolean;
  detail: string;
}

export async function runDataExplorer(query: string) {
  return request<DataExplorerResult>("/api/agent/data-explorer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query }),
  });
}

// ─── Underwriter Navigator ───────────────────────────────────

export interface UnderwritingAssessment {
  submission_id: string;
  applicant: string;
  line: string;
  state: string;
  business_type: string;
  risk_score: number;
  risk_tier: string;
  risk_drivers: Array<{ points: number; driver: string }>;
  pricing: { indicated_annual_premium: number; suggested_range: [number, number]; total_insured_value: number };
  required_authority: string;
  referral_required: boolean;
  referral_reasons: string[];
  recommendation: string;
  conditions: string[];
  reinsurance_notice_required: boolean;
}

export interface UnderwritingResult {
  status: "COMPLETED" | "PENDING_REVIEW";
  submission_id: string;
  thread_id: string;
  assessment: UnderwritingAssessment;
  application_result: string;
  loss_history_result: string;
  referral_result: string | null;
  underwriter_memo: string | null;
  human_review: string | null;
  pending_review: {
    tool: string;
    args: { submission_id: string; referral_authority: string; reason: string };
    description: string;
    allowed_decisions: string[];
    authority_options: string[];
  } | null;
}

export interface UnderwritingSubmission {
  submission_id: string;
  applicant: string;
  line: string;
  state: string;
  industry: string;
  total_insured_value: number;
  business_type: string;
}

export async function runUnderwriting(requestText: string) {
  return request<UnderwritingResult>("/api/agent/underwriting", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ request_text: requestText }),
  });
}

export async function reviewUnderwriting(body: {
  thread_id: string;
  decision: "approve" | "edit" | "reject";
  reviewer_comment?: string;
  edited_authority?: string;
  edited_reason?: string;
}) {
  return request<UnderwritingResult>("/api/agent/underwriting/review", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

// ─── Health ──────────────────────────────────────────────────

export async function healthCheck() {
  return request("/api/health");
}

export type AppMode = "local" | "cloud";

export interface SystemStatus {
  mode?: AppMode;
  backend?: { status: string; uptime: string; python_version: string; platform: string };
  gcp?: { project_id: string; region: string };
  storage?: { location: string; gcs_bucket: string; gcs_prefix: string };
  vector_search?: { backend: string; index_id: string; endpoint_id: string; stream_update: boolean };
  models?: { embedding: string; llm: string; llm_framework: string };
  ingestion?: { uploads_this_session: number };
}

export async function getSystemStatus() {
  return request<SystemStatus>("/api/status");
}
