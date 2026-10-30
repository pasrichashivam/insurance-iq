import { useEffect, useState } from "react";
import {
  ClipboardCheck,
  Play,
  FileText,
  CheckCircle,
  XCircle,
  Copy,
  Check,
  ChevronDown,
  Loader2,
  AlertTriangle,
  Activity,
  UserCheck,
  ThumbsUp,
  ThumbsDown,
  Pencil,
} from "lucide-react";
import {
  runUnderwriting,
  reviewUnderwriting,
  type UnderwritingResult,
  type UnderwritingSubmission,
} from "@/lib/api";

import { Card, CardHeader, CardTitle, CardDescription, CardContent, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import MarkdownContent from "@/components/MarkdownContent";

const DEFAULT_REQUEST = `Underwrite submission SUB-DEMO-03.`;

const PHASE_NAMES = ["Application & Risk", "Loss History", "Referral Desk (HITL)", "Underwriters Memo"] as const;

type PhaseStatus = "pending" | "running" | "done" | "review" | "error";
interface Phase {
  name: string;
  status: PhaseStatus;
  content: string | null;
}

const idlePhases = (): Phase[] => PHASE_NAMES.map((name) => ({ name, status: "pending", content: null }));

const money = (n: number) => `$${Math.round(n).toLocaleString()}`;

const recommendationStyle = (rec: string) =>
  rec.startsWith("DECLINE")
    ? "bg-destructive/10 text-destructive border-destructive/30"
    : rec.startsWith("REFER")
      ? "bg-amber-500/10 text-amber-600 border-amber-500/30"
      : "bg-success/10 text-success border-success/30";

export default function UnderwriterTab() {
  const [request, setRequest] = useState(DEFAULT_REQUEST);
  const [loading, setLoading] = useState(false);
  const [phases, setPhases] = useState<Phase[]>([]);
  const [result, setResult] = useState<UnderwritingResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expandedPhase, setExpandedPhase] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [samples, setSamples] = useState<UnderwritingSubmission[]>([]);

  // Human-in-the-loop reviewer inputs
  const [authority, setAuthority] = useState("SENIOR UNDERWRITER");
  const [reason, setReason] = useState("");
  const [comment, setComment] = useState("");

  const memo = result?.underwriter_memo ?? null;
  const pending = result?.status === "PENDING_REVIEW" ? result.pending_review : null;
  const assessment = result?.assessment ?? null;

  const applyResult = (data: UnderwritingResult) => {
    setResult(data);
    if (data.status === "PENDING_REVIEW" && data.pending_review) {
      setAuthority(data.pending_review.args.referral_authority);
      setReason(data.pending_review.args.reason);
      setComment("");
      setPhases([
        { name: PHASE_NAMES[0], status: "done", content: data.application_result },
        { name: PHASE_NAMES[1], status: "done", content: data.loss_history_result },
        { name: PHASE_NAMES[2], status: "review", content: "Awaiting human review of the proposed referral." },
        { name: PHASE_NAMES[3], status: "pending", content: null },
      ]);
      setExpandedPhase(PHASE_NAMES[2]);
    } else {
      setPhases([
        { name: PHASE_NAMES[0], status: "done", content: data.application_result },
        { name: PHASE_NAMES[1], status: "done", content: data.loss_history_result },
        {
          name: PHASE_NAMES[2],
          status: "done",
          content: `${data.referral_result ?? ""}${data.human_review ? `\n\nHUMAN REVIEW: ${data.human_review}` : ""}`,
        },
        { name: PHASE_NAMES[3], status: "done", content: data.underwriter_memo },
      ]);
      setExpandedPhase(PHASE_NAMES[3]);
    }
  };

  const handleRun = async () => {
    if (!request.trim() || loading) return;
    setLoading(true);
    setResult(null);
    setError(null);
    setExpandedPhase(null);
    setPhases([{ ...idlePhases()[0], status: "running" }, ...idlePhases().slice(1)]);

    const t1 = setTimeout(() => {
      setPhases((p) => p.map((ph, i) => (i === 0 ? { ...ph, status: "done" } : i === 1 ? { ...ph, status: "running" } : ph)));
    }, 4000);
    const t2 = setTimeout(() => {
      setPhases((p) => p.map((ph, i) => (i <= 1 ? { ...ph, status: "done" } : i === 2 ? { ...ph, status: "running" } : ph)));
    }, 8000);

    try {
      applyResult(await runUnderwriting(request));
    } catch (err: any) {
      setError(err.message);
      setPhases((p) => p.map((ph) => (ph.status === "running" ? { ...ph, status: "error" } : ph)));
    } finally {
      clearTimeout(t1);
      clearTimeout(t2);
      setLoading(false);
    }
  };

  const handleDecision = async (decision: "approve" | "edit" | "reject") => {
    if (!result || loading) return;
    setLoading(true);
    setError(null);
    setPhases((p) => p.map((ph, i) => (i === 2 ? { ...ph, status: "done" } : i === 3 ? { ...ph, status: "running" } : ph)));
    try {
      applyResult(
        await reviewUnderwriting({
          thread_id: result.thread_id,
          decision,
          reviewer_comment: comment,
          edited_authority: decision === "edit" ? authority : undefined,
          edited_reason: decision === "edit" ? reason : undefined,
        }),
      );
    } catch (err: any) {
      setError(err.message);
      setPhases((p) => p.map((ph) => (ph.status === "running" ? { ...ph, status: "error" } : ph)));
    } finally {
      setLoading(false);
    }
  };

  const handleCopy = () => {
    if (memo) {
      navigator.clipboard.writeText(memo);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const reset = () => {
    setRequest(DEFAULT_REQUEST);
    setPhases([]);
    setResult(null);
    setError(null);
    setExpandedPhase(null);
  };

  const completedCount = phases.filter((p) => p.status === "done").length;
  const progressPct = phases.length > 0 ? Math.round((completedCount / phases.length) * 100) : 0;
  const allDone = phases.length > 0 && completedCount === phases.length;

  return (
    <div className="space-y-6 animate-fade-in">
      {/* ── Row 1: Input ────────────────────────────────────── */}
      <Card className="shadow-md">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-primary/20 to-accent/10 shadow-sm">
                <ClipboardCheck className="h-5 w-5 text-primary" />
              </div>
              <div>
                <CardTitle className="text-lg">Underwriter Navigator</CardTitle>
                <CardDescription>
                  Cardinal Ridge — Application & Risk · Loss History · Referral Desk (Human-in-the-Loop) · Underwriters Memo
                </CardDescription>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="sm" onClick={reset}>
                Reset
              </Button>
              <Button size="sm" disabled={!request.trim() || loading || !!pending} onClick={handleRun} className="shadow-sm">
                {loading ? (
                  <>
                    <Loader2 className="h-4 w-4 animate-spin" /> Running…
                  </>
                ) : (
                  <>
                    <Play className="h-4 w-4" /> Run Underwriting
                  </>
                )}
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            className="font-mono text-sm min-h-[110px] resize-none"
            value={request}
            onChange={(e) => setRequest(e.target.value)}
            placeholder="Enter a submission id, e.g. Underwrite submission SUB-DEMO-01…"
          />
          {samples.length > 0 && (
            <div className="flex flex-wrap gap-2">
              {samples.map((s) => (
                <button
                  key={s.submission_id}
                  type="button"
                  onClick={() => setRequest(`Underwrite submission ${s.submission_id}\n\nContext: ${s.business_type} — ${s.applicant}, ${s.industry}, ${s.state}.`)}
                  className="rounded-full border bg-muted/40 px-3 py-1 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  title={`${s.business_type} · ${s.line} · TIV ${money(s.total_insured_value)}`}
                >
                  <span className="font-mono">{s.submission_id}</span> · {s.applicant}
                </button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Risk snapshot (deterministic engine) ─────────────── */}
      {assessment && (
        <Card className="shadow-md animate-fade-in">
          <CardContent className="pt-6">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Applicant</p>
                <p className="text-sm font-semibold truncate">{assessment.applicant}</p>
                <p className="text-xs text-muted-foreground">{assessment.business_type}</p>
              </div>
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Risk score</p>
                <p className="text-sm font-semibold">
                  {assessment.risk_score}/100 · {assessment.risk_tier}
                </p>
              </div>
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Indicated premium</p>
                <p className="text-sm font-semibold">{money(assessment.pricing.indicated_annual_premium)}</p>
                <p className="text-xs text-muted-foreground">
                  {money(assessment.pricing.suggested_range[0])} – {money(assessment.pricing.suggested_range[1])}
                </p>
              </div>
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Authority needed</p>
                <p className="text-sm font-semibold">{assessment.required_authority}</p>
              </div>
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Recommendation</p>
                <Badge variant="outline" className={`mt-0.5 ${recommendationStyle(assessment.recommendation)}`}>
                  {assessment.recommendation}
                </Badge>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Row 2: Pipeline + Memo ──────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 items-stretch">
        {/* ━━━━ Left: Agent pipeline + HITL panel (2 cols) ━━━━ */}
        <div className="lg:col-span-2 flex flex-col">
          <Card className={`flex flex-col flex-1 min-h-[520px] shadow-md overflow-hidden ${phases.length === 0 ? "border-dashed" : ""}`}>
            <div className="h-[2px] w-full bg-gradient-to-r from-primary via-accent to-primary opacity-60" />
            <CardHeader className="pb-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-primary/15 to-accent/10 shadow-sm">
                    <Activity className="h-5 w-5 text-primary" />
                  </div>
                  <div>
                    <CardTitle className="text-sm font-semibold">Underwriting Pipeline</CardTitle>
                    <CardDescription className="text-xs">Specialist agents with a human referral gate</CardDescription>
                  </div>
                </div>
                {phases.length > 0 && (
                  <Badge variant="secondary" className="text-[10px] font-mono tabular-nums px-2.5 py-0.5">
                    {completedCount}/{phases.length}
                  </Badge>
                )}
              </div>
              {phases.length > 0 && (
                <div className="mt-3 h-2 w-full rounded-full bg-secondary/60 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ease-out ${allDone ? "bg-gradient-to-r from-primary to-accent" : "animate-shimmer"}`}
                    style={{ width: `${progressPct}%` }}
                  />
                </div>
              )}
            </CardHeader>

            <Separator />

            <CardContent className="flex-1 pt-4">
              {phases.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full py-12 text-center text-muted-foreground">
                  <div className="flex h-14 w-14 items-center justify-center rounded-full border-2 border-dashed border-border mb-4">
                    <ClipboardCheck className="h-7 w-7 opacity-25" />
                  </div>
                  <p className="text-sm font-medium">Run underwriting to see the agent pipeline.</p>
                  <p className="text-xs text-muted-foreground/60 mt-1">
                    High-risk applications pause at the Referral Desk until a human reviewer approves, edits or rejects the referral.
                  </p>
                </div>
              ) : (
                <div className="relative">
                  <div className="absolute left-[18px] top-3 bottom-3 w-[2px] bg-gradient-to-b from-border via-border/60 to-border rounded-full" />
                  <div className="space-y-0">
                    {phases.map((ph, i) => {
                      const isDone = ph.status === "done";
                      const isRunning = ph.status === "running";
                      const isReview = ph.status === "review";
                      const isError = ph.status === "error";
                      const canExpand = (isDone || isReview) && !!ph.content;
                      const isExpanded = expandedPhase === ph.name;
                      return (
                        <div key={ph.name}>
                          <button
                            type="button"
                            onClick={() => canExpand && setExpandedPhase(isExpanded ? null : ph.name)}
                            className={`w-full flex items-center gap-3 rounded-lg px-2 py-3 text-left transition-all duration-200 relative z-10
                              ${canExpand ? "hover:bg-muted/50 cursor-pointer" : "cursor-default"} ${isExpanded ? "bg-muted/50" : ""}`}
                          >
                            <div
                              className={`flex h-[30px] w-[30px] shrink-0 items-center justify-center rounded-full border-2 bg-card transition-all duration-300
                              ${isDone ? "border-transparent bg-gradient-to-br from-primary via-fuchsia-500 to-accent shadow-[0_0_8px_hsl(var(--primary)/0.35)]" : isRunning ? "border-primary bg-primary/10" : isReview ? "border-amber-500 bg-amber-500/10" : isError ? "border-destructive bg-destructive/10" : "border-border bg-muted"}`}
                            >
                              {isDone && <CheckCircle className="h-3.5 w-3.5 text-primary-foreground" />}
                              {isRunning && <Loader2 className="h-3.5 w-3.5 text-primary animate-spin" />}
                              {isReview && <UserCheck className="h-3.5 w-3.5 text-amber-600" />}
                              {isError && <XCircle className="h-3.5 w-3.5 text-destructive" />}
                              {ph.status === "pending" && <span className="text-[10px] font-bold text-muted-foreground">{i + 1}</span>}
                            </div>
                            <div className="flex-1 min-w-0">
                              <span className={`block text-sm font-medium truncate ${ph.status === "pending" ? "text-muted-foreground" : "text-card-foreground"}`}>
                                {ph.name}
                              </span>
                              {isRunning && <span className="text-[10px] font-semibold text-primary animate-pulse">Processing…</span>}
                              {isReview && <span className="text-[10px] font-semibold text-amber-600">Waiting for human review</span>}
                              {isDone && <span className="text-[10px] font-medium bg-gradient-to-r from-primary via-fuchsia-500 to-accent bg-clip-text text-transparent">Complete</span>}
                              {isError && <span className="text-[10px] text-destructive/80">Failed</span>}
                            </div>
                            {canExpand && (
                              <ChevronDown className={`h-4 w-4 text-muted-foreground transition-transform duration-200 shrink-0 ${isExpanded ? "rotate-180" : ""}`} />
                            )}
                          </button>
                          {isExpanded && ph.content && (
                            <div className="ml-[42px] mr-2 mb-2 animate-fade-in">
                              <div className="max-h-[220px] overflow-y-auto rounded-lg border bg-background/80 p-4 shadow-inner">
                                <MarkdownContent className="text-xs leading-relaxed text-muted-foreground">{ph.content}</MarkdownContent>
                              </div>
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                </div>
              )}

              {/* Human-in-the-loop review panel */}
              {pending && (
                <div className="mt-4 rounded-lg border border-amber-500/40 bg-amber-500/5 p-4 space-y-3 animate-fade-in">
                  <div className="flex items-center gap-2 text-sm font-semibold text-amber-700">
                    <UserCheck className="h-4 w-4" /> Human review required
                  </div>
                  <p className="text-xs text-muted-foreground">
                    The Referral Desk wants to file a referral for <span className="font-mono">{pending.args.submission_id}</span>. Approve it, edit it, or reject it.
                  </p>
                  {assessment && assessment.referral_reasons.length > 0 && (
                    <ul className="list-disc pl-5 text-xs text-muted-foreground">
                      {assessment.referral_reasons.map((r) => (
                        <li key={r}>{r}</li>
                      ))}
                    </ul>
                  )}
                  <div className="space-y-2">
                    <label className="block text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Refer to</label>
                    <select
                      className="w-full rounded-md border bg-background px-2 py-1.5 text-sm"
                      value={authority}
                      onChange={(e) => setAuthority(e.target.value)}
                    >
                      {pending.authority_options.map((o) => (
                        <option key={o} value={o}>
                          {o}
                        </option>
                      ))}
                    </select>
                    <label className="block text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Referral reason</label>
                    <Textarea className="min-h-[60px] resize-none text-xs" value={reason} onChange={(e) => setReason(e.target.value)} />
                    <label className="block text-[10px] font-semibold uppercase tracking-widest text-muted-foreground">Reviewer comment</label>
                    <Textarea
                      className="min-h-[48px] resize-none text-xs"
                      value={comment}
                      onChange={(e) => setComment(e.target.value)}
                      placeholder="Optional (recorded in the memo)"
                    />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button size="sm" disabled={loading} onClick={() => handleDecision("approve")}>
                      <ThumbsUp className="h-3.5 w-3.5" /> Approve
                    </Button>
                    <Button size="sm" variant="outline" disabled={loading} onClick={() => handleDecision("edit")}>
                      <Pencil className="h-3.5 w-3.5" /> Edit & approve
                    </Button>
                    <Button size="sm" variant="outline" disabled={loading} onClick={() => handleDecision("reject")}>
                      <ThumbsDown className="h-3.5 w-3.5" /> Reject
                    </Button>
                  </div>
                </div>
              )}
            </CardContent>

            {allDone && (
              <CardFooter className="border-t pt-4 pb-4 mt-auto">
                <div className="flex w-full items-center justify-between text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/50">
                  <span>3 Agents · 1 Human gate</span>
                  <div className="flex items-center gap-1.5">
                    <span className="h-1.5 w-1.5 rounded-full bg-gradient-to-r from-primary to-accent animate-pulse" />
                    Complete
                  </div>
                </div>
              </CardFooter>
            )}
          </Card>
        </div>

        {/* ━━━━ Right: Underwriters Memo (3 cols) ━━━━ */}
        <div className="lg:col-span-3 flex flex-col">
          <Card className="flex flex-col flex-1 h-[520px] shadow-md overflow-hidden">
            <div className="h-[2px] w-full bg-gradient-to-r from-accent via-primary to-accent opacity-60" />
            <CardHeader className="pb-4">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-gradient-to-br from-primary/15 to-accent/10 shadow-sm">
                    <FileText className="h-5 w-5 text-primary" />
                  </div>
                  <div>
                    <CardTitle className="text-sm font-semibold">Underwriters Memo</CardTitle>
                    <CardDescription className="text-xs">Risk, pricing, authority and conditions for the underwriting file</CardDescription>
                  </div>
                </div>
                {memo && (
                  <Button variant="outline" size="sm" onClick={handleCopy} className="shadow-sm">
                    {copied ? (
                      <>
                        <Check className="h-3.5 w-3.5" /> Copied
                      </>
                    ) : (
                      <>
                        <Copy className="h-3.5 w-3.5" /> Copy
                      </>
                    )}
                  </Button>
                )}
              </div>
            </CardHeader>

            <Separator />

            <CardContent className="flex-1 pt-0 pb-6 flex flex-col relative w-full">
              {memo ? (
                <div className="relative flex-1 w-full mt-4">
                  <div className="absolute inset-0 rounded-lg border bg-muted/20 p-5 shadow-inner overflow-y-auto animate-slide-in-right">
                    <MarkdownContent className="text-[13px] leading-[1.75] text-card-foreground">{memo}</MarkdownContent>
                  </div>
                </div>
              ) : error ? (
                <div className="flex flex-col items-center justify-center h-full py-12 text-center animate-fade-in">
                  <div className="flex h-14 w-14 items-center justify-center rounded-full bg-destructive/10 mb-4">
                    <AlertTriangle className="h-7 w-7 text-destructive" />
                  </div>
                  <p className="text-sm font-semibold text-destructive mb-1">Underwriting Failed</p>
                  <p className="text-sm text-muted-foreground max-w-xs">{error}</p>
                </div>
              ) : pending ? (
                <div className="flex flex-col items-center justify-center h-full py-16 text-center animate-fade-in">
                  <UserCheck className="h-10 w-10 text-amber-600 mb-4" />
                  <p className="text-sm font-semibold text-card-foreground">Paused for human review</p>
                  <p className="text-xs text-muted-foreground mt-1 max-w-xs">
                    The memo is written after the reviewer approves, edits or rejects the referral.
                  </p>
                </div>
              ) : loading ? (
                <div className="flex flex-col items-center justify-center h-full py-16 text-center animate-fade-in">
                  <Loader2 className="h-10 w-10 text-primary animate-spin mb-4" />
                  <p className="text-sm font-semibold text-card-foreground">Preparing Underwriters Memo</p>
                  <p className="text-xs text-muted-foreground mt-1">Agents are analysing the application, pricing and loss history.</p>
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center h-full py-16 text-center">
                  <div className="flex h-14 w-14 items-center justify-center rounded-full border-2 border-dashed border-border mb-4">
                    <FileText className="h-7 w-7 text-muted-foreground/25" />
                  </div>
                  <p className="text-sm font-medium text-muted-foreground">Submit a submission id to generate the Underwriters Memo.</p>
                  <p className="text-xs text-muted-foreground/60 mt-1">The memo will appear here after the agents (and any human review) complete.</p>
                </div>
              )}
            </CardContent>

            {memo && (
              <CardFooter className="border-t pt-4 pb-4 mt-auto">
                <div className="flex w-full items-center justify-between text-[10px] font-semibold uppercase tracking-widest text-muted-foreground/50">
                  <span>Risk engine numbers · LLM narrative</span>
                  <div className="flex items-center gap-1.5">
                    <span className="h-1.5 w-1.5 rounded-full bg-gradient-to-r from-primary to-accent" />
                    Complete
                  </div>
                </div>
              </CardFooter>
            )}
          </Card>
        </div>
      </div>
    </div>
  );
}
