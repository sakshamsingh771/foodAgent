"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FlaskConical, RotateCcw } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Badge, Button, Card, CardHeader, ConfirmDialog, PageHeader, Select } from "@/components/ui";
import { QueryBoundary } from "@/components/ui/query-state";
import { errorMessage, get, post } from "@/lib/api";
import { fmtDateTime, titleCase } from "@/lib/utils";
import { useAuth } from "@/providers";

interface Cat { scenarios: { kind: string; title: string; target: "case" | "lot" | "plant"; description: string }[]; runs: { id: string; kind: string; status: string; at: string; effects: string[] }[]; disclaimer: string }
interface Targets { case: { id: string; label: string }[]; lot: { id: string; label: string }[]; plant: { id: string; label: string }[] }

export default function Scenarios() {
  const { user } = useAuth(); const qc = useQueryClient();
  const cat = useQuery({ queryKey: ["scenarios"], queryFn: () => get<Cat>("/scenarios/catalog") });
  const targets = useQuery({ queryKey: ["scenario-targets"], queryFn: () => get<Targets>("/scenarios/targets") });
  const [sel, setSel] = useState<{ kind: string; target: "case" | "lot" | "plant"; title: string } | null>(null); const [tid, setTid] = useState("");
  const [effects, setEffects] = useState<string[] | null>(null); const [resetOpen, setResetOpen] = useState(false);
  const canRun = !!user && ["ADMIN", "OPERATIONS_MANAGER"].includes(user.role);
  const refresh = () => { ["scenarios", "scenario-targets", "lots", "cases", "case", "pickups", "dashboard", "plant", "audit", "notifications"].forEach((k) => qc.invalidateQueries({ queryKey: [k] })); };
  const preview = useMutation({ mutationFn: (v: { kind: string; target_id: string }) => post<{ effects: string[] }>("/scenarios/preview", v), onSuccess: (d) => setEffects(d.effects), onError: (e) => { toast.error(errorMessage(e)); setSel(null); } });
  const apply = useMutation({ mutationFn: (v: { kind: string; target_id: string }) => post("/scenarios/apply", { ...v, confirm: true }), onSuccess: () => { toast.success("Scenario applied. The dashboard and audit trail are updated."); setSel(null); setEffects(null); refresh(); }, onError: (e) => toast.error(errorMessage(e)) });
  const reset = useMutation({ mutationFn: () => post<{ reverted: number }>("/scenarios/reset"), onSuccess: (d) => { toast.success(`Reset complete: ${d.reverted} scenario(s) reverted.`); setResetOpen(false); refresh(); }, onError: (e) => toast.error(errorMessage(e)) });
  const options = sel && targets.data ? targets.data[sel.target] : [];
  return (
    <>
      <PageHeader title="Scenario control" sub="Rehearse disruptions on simulated state. Every run is confirmed, audited and reversible." actions={canRun && <Button variant="secondary" onClick={() => setResetOpen(true)}><RotateCcw className="h-4 w-4" aria-hidden />Reset scenarios</Button>} />
      <p className="mb-4 rounded-md border border-border bg-subtle px-3 py-2 text-xs text-muted">{cat.data?.disclaimer ?? "Scenarios change simulated state only."}{!canRun && " Your role can view scenarios but not run them."}</p>
      <QueryBoundary q={cat}>
        {(c) => (
          <div className="grid gap-5 lg:grid-cols-3">
            <div className="grid gap-3 sm:grid-cols-2 lg:col-span-2">
              {c.scenarios.map((s) => (
                <Card key={s.kind} className="flex flex-col p-4"><div className="flex items-center gap-2"><FlaskConical className="h-4 w-4 text-brand" aria-hidden /><h2 className="font-semibold">{s.title}</h2></div><p className="mt-1 flex-1 text-sm text-muted">{s.description}</p><Button className="mt-3" variant="secondary" disabled={!canRun} onClick={() => { setSel(s); setTid(""); setEffects(null); }}>Set up</Button></Card>
              ))}
            </div>
            <Card><CardHeader title="Recent runs" /><ul className="divide-y divide-border">{c.runs.length === 0 && <li className="p-4 text-sm text-muted">No scenarios run yet.</li>}{c.runs.map((r) => <li key={r.id} className="px-4 py-3"><div className="flex items-center justify-between"><span className="text-sm font-medium">{titleCase(r.kind)}</span><Badge tone={r.status === "active" ? "warn" : "neutral"}>{r.status}</Badge></div><p className="text-xs text-muted">{fmtDateTime(r.at)}</p>{r.effects[0] && <p className="mt-1 text-xs text-muted">{r.effects[0]}</p>}</li>)}</ul></Card>
          </div>
        )}
      </QueryBoundary>
      <ConfirmDialog open={!!sel} onOpenChange={(o) => { if (!o) { setSel(null); setEffects(null); } }} title={sel ? `${sel.title}: confirm` : ""} body="Choose a target and review the impact. Nothing changes until you confirm." confirmLabel="Apply scenario" danger loading={apply.isPending}
        onConfirm={() => (effects && sel && tid ? apply.mutate({ kind: sel.kind, target_id: tid }) : toast.error("Pick a target and review the impact first."))}>
        <div className="space-y-3">
          <Select aria-label="Target" className="w-full" value={tid} onChange={(e) => { setTid(e.target.value); setEffects(null); if (e.target.value && sel) preview.mutate({ kind: sel.kind, target_id: e.target.value }); }}><option value="">Choose a {sel?.target}…</option>{options.map((o) => <option key={o.id} value={o.id}>{o.label}</option>)}</Select>
          {options.length === 0 && <p className="text-sm text-muted">There&apos;s nothing to target right now.</p>}
          {preview.isPending && <p className="text-sm text-muted">Working out the impact…</p>}
          {effects && <div className="rounded-md border border-border p-3" aria-live="polite"><p className="text-xs font-medium uppercase tracking-wide text-muted">Impact (simulated)</p><ul className="mt-1 list-disc space-y-1 pl-5 text-sm">{effects.map((e) => <li key={e}>{e}</li>)}</ul></div>}
        </div>
      </ConfirmDialog>
      <ConfirmDialog open={resetOpen} onOpenChange={setResetOpen} title="Reset all scenarios?" body="Every active scenario is reverted to its previous state. The audit trail keeps a record of both." confirmLabel="Reset" loading={reset.isPending} onConfirm={() => reset.mutate()} />
    </>
  );
}
