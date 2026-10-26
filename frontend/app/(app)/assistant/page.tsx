"use client";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Sparkles } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Card, EmptyState, Field, PageHeader, Select, Textarea } from "@/components/ui";
import { ApiError, errorMessage, get, post } from "@/lib/api";
import type { AiResult, AiStatus, Page } from "@/types/api";

type Req = { path: string; body: unknown; label: string };
const CHIPS = [
  { label: "Which surplus listings need urgent attention?", kind: "chat" },
  { label: "Summarize our recent food recovery performance.", kind: "chat" },
  { label: "What actions could help reduce food waste?", kind: "chat" },
  { label: "Which constraints are preventing allocation?", kind: "chat" },
] as const;
const RETRYABLE = new Set(["AI_TIMEOUT", "AI_UPSTREAM_ERROR", "AI_RATE_LIMITED", "AI_BAD_OUTPUT", "NETWORK"]);

function List({ title, items, tone }: { title: string; items: string[]; tone?: "safe" | "warn" | "danger" | "info" }) {
  if (!items.length) return null;
  return (
    <section className="mt-4"><h3 className="flex items-center gap-2 text-sm font-semibold"><Badge tone={tone}>{title}</Badge></h3>
      {/* model text is rendered as plain text only; never as HTML */}
      <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">{items.map((t, i) => <li key={i}>{t}</li>)}</ul></section>
  );
}

export default function AssistantPage() {
  const status = useQuery({ queryKey: ["ai-status"], queryFn: () => get<AiStatus>("/ai/status") });
  const cases = useQuery({ queryKey: ["cases", "assistant"], queryFn: () => get<Page<{ id: string; case_number: string }>>("/recovery-cases?page_size=50&active=true") });
  const [question, setQuestion] = useState("");
  const [caseId, setCaseId] = useState("");
  const [last, setLast] = useState<Req | null>(null);
  const run = useMutation({ mutationFn: (r: Req) => { setLast(r); return post<AiResult>(r.path, r.body); } });
  const send = (r: Req) => run.mutate(r);
  const ready = status.data?.configured === true;
  const err = run.error;
  const retry = err instanceof ApiError ? RETRYABLE.has(err.code) : !!err;

  return (
    <>
      <PageHeader title="AI assistant" sub="Gemini explains your organization's recorded data and the optimizer's results. It cannot change any records." />
      {status.data && !ready && <p role="status" className="mb-4 rounded-md bg-warn/14 px-3 py-2 text-sm text-warn">{status.data.message}</p>}
      {status.isError && <p role="alert" className="mb-4 rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{errorMessage(status.error)}</p>}
      <div className="grid gap-5 lg:grid-cols-[22rem_1fr]">
        <Card className="space-y-4 p-4 self-start">
          <form onSubmit={(e) => { e.preventDefault(); if (question.trim().length >= 3) send({ path: "/ai/chat", body: { message: question.trim(), case_id: caseId || undefined }, label: question.trim() }); }} className="space-y-3">
            <Field label="Ask a question"><Textarea rows={3} maxLength={800} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="e.g. Why did this recovery attempt fail?" disabled={!ready || run.isPending} /></Field>
            <Button type="submit" className="w-full" loading={run.isPending} disabled={!ready || question.trim().length < 3}>Ask</Button>
          </form>
          <div className="flex flex-wrap gap-2" aria-label="Suggested questions">
            {CHIPS.map((c) => <button key={c.label} type="button" disabled={!ready || run.isPending} onClick={() => { setQuestion(c.label); send({ path: "/ai/chat", body: { message: c.label }, label: c.label }); }}
              className="min-h-9 rounded-full border border-border px-3 text-left text-xs hover:bg-subtle disabled:opacity-50">{c.label}</button>)}
          </div>
          <div className="space-y-2 border-t border-border pt-4">
            <Field label="Recovery case (optional)"><Select value={caseId} onChange={(e) => setCaseId(e.target.value)}><option value="">— none —</option>{cases.data?.items.map((c) => <option key={c.id} value={c.id}>{c.case_number}</option>)}</Select></Field>
            <Button variant="secondary" className="w-full" disabled={!ready || !caseId || run.isPending} onClick={() => send({ path: "/ai/allocation/explain", body: { case_id: caseId }, label: "Explain allocation plan" })}>Explain allocation plan</Button>
            <Button variant="secondary" className="w-full" disabled={!ready || run.isPending} onClick={() => send({ path: "/ai/failures", body: { case_id: caseId || undefined }, label: "Analyse failures and delays" })}>Analyse failures &amp; delays</Button>
            <Button variant="secondary" className="w-full" disabled={!ready || run.isPending} onClick={() => send({ path: "/ai/recommendations", body: {}, label: "Recovery recommendations" })}>Recovery recommendations</Button>
            <Button variant="secondary" className="w-full" disabled={!ready || run.isPending} onClick={() => send({ path: "/ai/summary", body: { days: 7 }, label: "7-day operations summary" })}>7-day operations summary</Button>
          </div>
        </Card>

        <div aria-live="polite">
          {run.isPending && <Card className="p-5 text-sm text-muted" role="status">Gemini is analysing your data…</Card>}
          {err && !run.isPending && (
            <Card className="p-5"><p role="alert" className="text-sm text-danger">{errorMessage(err)}</p>
              {retry && last && <Button className="mt-3" variant="secondary" onClick={() => send(last)}>Retry</Button>}</Card>
          )}
          {!run.isPending && !err && !run.data && (
            <EmptyState title="Ask about your food recovery operations" body={ready ? "Pick a suggested question or choose an action on the left. Answers are based only on your organization's recorded data." : "The assistant becomes available once the server is configured with a Gemini key."} />
          )}
          {run.data && !run.isPending && !err && (
            <Card className="p-5">
              <div className="flex items-center gap-2"><Sparkles className="h-4 w-4 text-info" aria-hidden /><h2 className="font-display text-lg font-semibold">{last?.label}</h2><Badge tone="info">AI-generated</Badge></div>
              <p className="mt-3 text-sm">{run.data.answer.summary}</p>
              <List title="Recorded facts" items={run.data.answer.facts} tone="safe" />
              <List title="Hypotheses (unconfirmed)" items={run.data.answer.hypotheses} tone="warn" />
              <List title="Recommendations" items={run.data.answer.recommendations} tone="info" />
              <List title="Risks" items={run.data.answer.risks} tone="danger" />
              <List title="Next steps" items={run.data.answer.next_steps} />
              <List title="Missing information" items={run.data.answer.missing_information} tone="warn" />
              {run.data.answer.warnings.map((w) => <p key={w} className="mt-3 text-xs text-warn">{w}</p>)}
              <details className="mt-5 rounded-md border border-border p-3 text-xs">
                <summary className="min-h-9 cursor-pointer font-medium">Inspect the data{run.data.kind === "explain" ? " and optimizer result" : ""} used</summary>
                <pre className="mt-2 max-h-96 overflow-auto whitespace-pre-wrap break-words">{JSON.stringify(run.data.data, null, 2)}</pre>
              </details>
              <p className="mt-3 text-xs text-muted">{run.data.disclaimer}</p>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
