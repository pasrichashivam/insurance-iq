import { useState } from "react";
import { Bot, Send } from "lucide-react";
import { askAssistant } from "@/lib/api";

const EXAMPLES = [
  "How many open claims do we have by state and line?",
  "Which vendors have the most claims just under $10,000, and how many SIU cases do they have?",
  "Which claims are past their state decision deadline and still open?",
  "Total paid vs. reserved for the CAT-2025-HURR-FL catastrophe",
  "Is claim CLM-DEMO-02 covered, and why?",
  "What does our SIU guideline say about referral timing?",
];

interface Entry {
  q: string;
  a: string | null;
  error: string | null;
  ts: number;
}

export default function AssistantTab() {
  const [question, setQuestion] = useState("");
  const [history, setHistory] = useState<Entry[]>([]);
  const [loading, setLoading] = useState(false);

  const ask = async (q?: string) => {
    const text = (q ?? question).trim();
    if (!text || loading) return;
    setQuestion("");
    setLoading(true);
    const entry: Entry = { q: text, a: null, error: null, ts: Date.now() };
    setHistory((h) => [entry, ...h]);
    try {
      const res = await askAssistant(text);
      setHistory((h) => h.map((e) => (e.ts === entry.ts ? { ...e, a: res.answer } : e)));
    } catch (err: any) {
      setHistory((h) => h.map((e) => (e.ts === entry.ts ? { ...e, error: err.message } : e)));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-6 animate-fade-in">
      <div className="rounded-lg border border-border bg-card p-6 shadow-sm">
        <div className="flex items-center gap-2.5 mb-1">
          <Bot className="w-[18px] h-[18px] text-primary" />
          <h2 className="text-base font-semibold font-heading text-card-foreground">Insurance Assistant</h2>
        </div>
        <p className="text-sm text-muted-foreground mb-4">
          One agent with database analytics (read-only SQL), claim tools and the policy documents. Numbers always come from tools.
        </p>
        <div className="flex gap-2">
          <input
            className="flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm"
            placeholder="Ask about claims, fraud, compliance, or policy rules…"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && ask()}
          />
          <button
            onClick={() => ask()}
            disabled={loading || !question.trim()}
            className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            <Send className="w-4 h-4" /> {loading ? "Thinking…" : "Ask"}
          </button>
        </div>
        <div className="flex flex-wrap gap-2 mt-4">
          {EXAMPLES.map((ex) => (
            <button
              key={ex}
              onClick={() => ask(ex)}
              className="text-xs rounded-full border border-border px-3 py-1 text-muted-foreground hover:text-foreground hover:bg-muted/50"
            >
              {ex}
            </button>
          ))}
        </div>
      </div>

      {history.map((e) => (
        <div key={e.ts} className="rounded-lg border border-border bg-card p-5 shadow-sm">
          <p className="text-sm font-semibold mb-2">{e.q}</p>
          {e.error ? (
            <p className="text-sm text-destructive">{e.error}</p>
          ) : e.a === null ? (
            <p className="text-sm text-muted-foreground">Agent is working…</p>
          ) : (
            <pre className="whitespace-pre-wrap text-sm font-sans text-foreground/90">{e.a}</pre>
          )}
        </div>
      ))}
    </div>
  );
}
