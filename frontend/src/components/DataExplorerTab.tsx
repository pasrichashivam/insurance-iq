import { useState } from "react";
import { Database, Play, Loader2, Copy, Check, AlertTriangle, SearchX, Terminal } from "lucide-react";
import { runDataExplorer, type DataExplorerResult } from "@/lib/api";

import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";

const EXAMPLES = [
  "Top 10 customers by total claimed amount",
  "SELECT state, COUNT(*) AS open_claims FROM claims_current WHERE status='OPEN' GROUP BY state ORDER BY open_claims DESC",
];

export default function DataExplorerTab() {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<DataExplorerResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const run = async () => {
    if (!query.trim() || loading) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await runDataExplorer(query));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Request failed");
    } finally {
      setLoading(false);
    }
  };

  const copySql = async () => {
    if (!result?.sql) return;
    await navigator.clipboard.writeText(result.sql);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-bold font-heading flex items-center gap-2">
          <Database className="w-6 h-6 text-primary" /> Data Explorer
        </h2>
        <p className="text-sm text-muted-foreground mt-1">
          Ask in plain English or paste a SQL SELECT. The agent runs it on the insurance database and shows the top 50
          rows plus the exact query it executed.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Question or SQL query</CardTitle>
          <CardDescription>Read-only: only SELECT statements are executed.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <Textarea
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) run();
            }}
            rows={4}
            placeholder="e.g. Which adjusters have the most open claims?   — or —   SELECT * FROM claims_current LIMIT 10"
            className="font-mono text-sm"
          />
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={run} disabled={loading || !query.trim()}>
              {loading ? <Loader2 className="w-4 h-4 mr-2 animate-spin" /> : <Play className="w-4 h-4 mr-2" />}
              Run
            </Button>
            <span className="text-xs text-muted-foreground">Ctrl+Enter to run · Try:</span>
            {EXAMPLES.map((ex) => (
              <Button key={ex} variant="outline" size="sm" className="max-w-[260px] truncate" onClick={() => setQuery(ex)}>
                <span className="truncate">{ex}</span>
              </Button>
            ))}
          </div>
        </CardContent>
      </Card>

      {error && (
        <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          <AlertTriangle className="w-4 h-4" /> {error}
        </div>
      )}

      {result && (
        <>
          <Card>
            <CardHeader className="flex-row items-center justify-between space-y-0">
              <CardTitle className="text-base flex items-center gap-2">
                <Terminal className="w-4 h-4" /> Executed query
                <Badge variant="outline">{result.mode === "sql" ? "your SQL" : "agent-generated"}</Badge>
              </CardTitle>
              {result.sql && (
                <Button variant="ghost" size="sm" onClick={copySql}>
                  {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                </Button>
              )}
            </CardHeader>
            <CardContent>
              <pre className="whitespace-pre-wrap break-words rounded-md bg-muted/50 p-3 text-xs font-mono">
                {result.sql || "— no query was executed —"}
              </pre>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                Results
                {result.status === "ok" && (
                  <Badge variant="secondary">
                    {result.row_count} row{result.row_count === 1 ? "" : "s"}
                    {result.truncated ? " (top 50 shown)" : ""}
                  </Badge>
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              {result.status === "ok" ? (
                <div className="max-h-[420px] overflow-auto rounded-md border border-border">
                  <table className="w-max min-w-full text-xs">
                    <thead className="sticky top-0 bg-muted">
                      <tr>
                        {result.columns.map((c, i) => (
                          <th key={i} className="px-3 py-2 text-left font-semibold whitespace-nowrap border-b border-border">
                            {c}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {result.rows.map((row, r) => (
                        <tr key={r} className="odd:bg-muted/20 hover:bg-muted/40">
                          {row.map((cell, c) => (
                            <td key={c} className="px-3 py-1.5 whitespace-nowrap border-b border-border/50">
                              {cell === null ? <span className="text-muted-foreground">NULL</span> : String(cell)}
                            </td>
                          ))}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                  <SearchX className="w-5 h-5" />
                  <div>
                    <p className="font-medium text-foreground">{result.message}</p>
                    {result.detail && <p className="text-xs mt-1">{result.detail}</p>}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}
