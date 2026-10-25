"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Badge, Button, Card, CardHeader, ConfirmDialog, Field, Input, Select, Textarea } from "@/components/ui";
import { errorMessage, get, post } from "@/lib/api";
import { fmtDateTime, fmtKg, titleCase } from "@/lib/utils";
import type { AllocationCompare, AllocationPlan, AllocationRow, AllocationSim, AllocationSummary, Recipient } from "@/types/api";

const STRATEGIES: Record<string, string> = {
  max_recovery: "Maximum feasible recovery", fastest: "Fastest feasible", lowest_distance: "Shortest distance (cost proxy)",
  lowest_risk: "Lowest operational risk", non_human_pathway: "Feed / biogas only",
};
const SCENARIOS: Record<string, string> = {
  none: "No change (baseline)", recipient_rejection: "Recipient rejection", capacity_reduction: "Recipient capacity reduction", vehicle_delay: "Vehicle delay",
  missing_evidence: "Missing safety evidence", no_feasible_option: "No feasible recovery option",
};
const tone = (s: string) => (["accepted", "completed"].includes(s) ? "safe" : ["rejected", "failed", "cancelled"].includes(s) ? "danger" : ["proposed", "offered"].includes(s) ? "warn" : "neutral") as "safe" | "danger" | "warn" | "neutral";

function PlanView({ plan, title }: { plan: AllocationPlan; title?: string }) {
  return (
    <div className="space-y-2 text-sm">
      {title && <p className="font-medium">{title}</p>}
      <p className="text-muted">{plan.explanation}</p>
      <p className="tabular">Allocated <strong>{fmtKg(plan.allocated_kg)}</strong> · unallocated <strong>{fmtKg(plan.unallocated_kg)}</strong> · <Badge tone={plan.status === "feasible" ? "safe" : plan.status === "partial" ? "warn" : "danger"}>{titleCase(plan.status)}</Badge></p>
      {plan.lines.length > 0 && <ul className="divide-y divide-border rounded-md border border-border">{plan.lines.map((l) => (
        <li key={l.recipient_id} className="px-3 py-2"><div className="flex flex-wrap justify-between gap-2"><span className="font-medium">{l.recipient_name} <Badge tone="info">{l.rung}</Badge></span><span className="tabular">{fmtKg(l.quantity_kg)}</span></div>
          <p className="text-xs text-muted">{l.why} Est. {l.needed_minutes} min needed, {l.margin_minutes} min margin (heuristic).</p></li>))}</ul>}
      {plan.rejected.length > 0 && <details className="text-xs text-muted"><summary className="cursor-pointer">Why other candidates were not used ({plan.rejected.length})</summary>
        <ul className="mt-1 list-disc pl-5">{plan.rejected.map((r, i) => <li key={i}>{r.recipient_name}{r.rung ? ` (${r.rung})` : ""}: {r.reason}</li>)}</ul></details>}
      {plan.warnings.map((w, i) => <p key={i} role="status" className="rounded-md bg-warn/10 px-2 py-1 text-xs text-warn">{w}</p>)}
    </div>
  );
}

export function AllocationPanel({ caseId, status, canManage, canTransport, canSimulate }: { caseId: string; status: string; canManage: boolean; canTransport: boolean; canSimulate: boolean }) {
  const qc = useQueryClient();
  const [strategy, setStrategy] = useState("max_recovery");
  const [preview, setPreview] = useState<AllocationPlan | null>(null);
  const [compare, setCompare] = useState<AllocationCompare | null>(null);
  const [sim, setSim] = useState<AllocationSim | null>(null);
  const [scenario, setScenario] = useState("recipient_rejection"); const [simRecipient, setSimRecipient] = useState(""); const [simCap, setSimCap] = useState("0"); const [simDelay, setSimDelay] = useState("60");
  const [dlg, setDlg] = useState<null | { kind: "commit" } | { kind: "cancel" | "failure" | "delay"; a: AllocationRow }>(null); const [reason, setReason] = useState("");
  const sum = useQuery({ queryKey: ["allocations", caseId], queryFn: () => get<AllocationSummary>(`/recovery-cases/${caseId}/allocations`), refetchInterval: 15000 });
  const recips = useQuery({ queryKey: ["recipients"], queryFn: () => get<Recipient[]>("/recipients") });
  const refresh = () => { qc.invalidateQueries({ queryKey: ["allocations", caseId] }); qc.invalidateQueries({ queryKey: ["case", caseId] }); qc.invalidateQueries({ queryKey: ["cases"] }); setDlg(null); setReason(""); };
  const run = useMutation({
    mutationFn: ({ path, body }: { path: string; body?: unknown }) => post<Record<string, unknown>>(path, body),
    onSuccess: (d) => { const rp = d.replan as { requires_human_intervention?: boolean } | undefined; toast[(d.requires_human_intervention || rp?.requires_human_intervention) ? "warning" : "success"]((d.requires_human_intervention || rp?.requires_human_intervention) ? "Done. Human intervention is needed for part of the quantity." : "Done."); refresh(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const doPreview = useMutation({ mutationFn: () => post<{ plan: AllocationPlan }>(`/recovery-cases/${caseId}/allocation/plan`, { strategy }), onSuccess: (d) => setPreview(d.plan), onError: (e) => toast.error(errorMessage(e)) });
  const doCompare = useMutation({ mutationFn: () => post<AllocationCompare>(`/recovery-cases/${caseId}/allocation/compare`, {}), onSuccess: setCompare, onError: (e) => toast.error(errorMessage(e)) });
  const doSim = useMutation({
    mutationFn: () => post<AllocationSim>(`/recovery-cases/${caseId}/allocation/simulate`, { scenario, strategy, recipient_id: simRecipient || undefined, capacity_kg: Number(simCap), delay_minutes: Number(simDelay) }),
    onSuccess: setSim, onError: (e) => toast.error(errorMessage(e)),
  });
  const closed = ["completed", "cancelled", "rejected"].includes(status);
  const d = sum.data;
  const proposed = d?.allocations.filter((a) => a.status === "proposed") ?? [];

  return (
    <Card>
      <CardHeader title="Multi-recipient allocation" sub="Splits a lot across recipients within capacity, deadline and safety limits." />
      <div className="space-y-5 p-4">
        {d && (
          <>
            <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <div><dt className="text-xs text-muted">Lot quantity</dt><dd className="font-semibold tabular">{fmtKg(d.lot_quantity_kg)}</dd></div>
              <div><dt className="text-xs text-muted">Reserved</dt><dd className="font-semibold tabular">{fmtKg(d.reserved_kg)}</dd></div>
              <div><dt className="text-xs text-muted">Unallocated</dt><dd className="font-semibold tabular">{fmtKg(d.unallocated_kg)}</dd></div>
              <div><dt className="text-xs text-muted">Time left</dt><dd className="font-semibold tabular">{Math.floor(d.remaining_minutes / 60)}h {d.remaining_minutes % 60}m</dd></div>
            </dl>
            {!closed && d.unallocated_kg > 0 && d.remaining_minutes <= 120 && (
              <p role="alert" className="rounded-md bg-danger/10 p-3 text-sm">Deadline warning: only {Math.floor(d.remaining_minutes / 60)}h {d.remaining_minutes % 60}m of safe time remain with {fmtKg(d.unallocated_kg)} still unallocated. A person must approve any plan.</p>
            )}
            {d.allocations.length === 0 ? <p className="text-sm text-muted">No allocations yet. Preview a plan below.</p> : (
              <ul className="divide-y divide-border rounded-md border border-border">{d.allocations.map((a) => (
                <li key={a.id} className="space-y-1 px-3 py-2.5 text-sm">
                  <div className="flex flex-wrap items-center justify-between gap-2"><span className="font-medium">{a.recipient_name} <Badge tone="info">{a.rung}</Badge> <Badge tone={tone(a.status)}>{titleCase(a.status)}</Badge></span><span className="tabular font-semibold">{fmtKg(a.quantity_kg)}</span></div>
                  <p className="text-xs text-muted">{a.why}</p>
                  <p className="text-xs text-muted tabular">Capacity left {fmtKg(a.recipient_remaining_kg)} of {fmtKg(a.recipient_capacity_kg)}{a.eta ? ` · est. ${fmtDateTime(a.eta)}` : ""}{a.delay_minutes ? ` · delayed ${a.delay_minutes} min` : ""}{a.response_reason ? ` · "${a.response_reason}"` : ""}</p>
                  {["proposed", "offered", "accepted"].includes(a.status) && !closed && (
                    <div className="flex flex-wrap gap-2 pt-1">
                      {canTransport && ["offered", "accepted"].includes(a.status) && <>
                        <Button size="sm" variant="secondary" onClick={() => { setReason(""); setDlg({ kind: "delay", a }); }}>Report delay</Button>
                        <Button size="sm" variant="secondary" onClick={() => { setReason(""); setDlg({ kind: "failure", a }); }}>Transport failed</Button></>}
                      {canTransport && a.status === "accepted" && <Button size="sm" loading={run.isPending} onClick={() => run.mutate({ path: `/allocations/${a.id}/handover` })}>Confirm handover</Button>}
                      {canManage && <Button size="sm" variant="secondary" onClick={() => { setReason(""); setDlg({ kind: "cancel", a }); }}>Cancel (override)</Button>}
                    </div>)}
                </li>))}</ul>)}
            {proposed.length > 0 && canManage && (
              <div className="flex flex-wrap items-center gap-2 rounded-md bg-warn/10 p-3 text-sm"><span>{proposed.length} proposed allocation(s) need approval. Recipients are notified only after you approve.</span>
                <Button size="sm" loading={run.isPending} onClick={() => run.mutate({ path: `/recovery-cases/${caseId}/allocation/approve`, body: {} })}>Approve and offer</Button></div>)}
            {d.replan_count > 0 && <p className="text-xs text-muted">Replanned {d.replan_count}× · {d.excluded_recipients.length} recipient(s) excluded after rejecting this lot.</p>}
          </>
        )}

        {!closed && (
          <div className="space-y-3 border-t border-border pt-4">
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Strategy"><Select value={strategy} onChange={(e) => setStrategy(e.target.value)}>{Object.entries(STRATEGIES).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
              <Button variant="secondary" loading={doPreview.isPending} onClick={() => doPreview.mutate()}>Preview plan</Button>
              {canSimulate && <Button variant="secondary" loading={doCompare.isPending} onClick={() => doCompare.mutate()}>Compare strategies</Button>}
              {canManage && <Button disabled={!preview || preview.lines.length === 0} onClick={() => setDlg({ kind: "commit" })}>Commit this plan…</Button>}
            </div>
            {preview && <div className="rounded-md border border-border p-3"><PlanView plan={preview} title="Preview (nothing reserved yet)" /></div>}
            {compare && (
              <div className="overflow-x-auto rounded-md border border-border">
                <table className="w-full text-left text-sm"><caption className="sr-only">Strategy comparison</caption>
                  <thead className="bg-subtle text-xs text-muted"><tr><th className="p-2">Strategy</th><th className="p-2">Recovered</th><th className="p-2">Unallocated</th><th className="p-2">Status</th><th className="p-2">Recipients</th></tr></thead>
                  <tbody>{compare.strategies.map((s) => <tr key={s.strategy} className="border-t border-border"><td className="p-2">{STRATEGIES[s.strategy]}</td><td className="p-2 tabular">{fmtKg(s.allocated_kg)}</td><td className="p-2 tabular">{fmtKg(s.unallocated_kg)}</td><td className="p-2">{titleCase(s.status)}</td><td className="p-2 text-xs">{s.lines.map((l) => `${l.recipient_name} ${l.quantity_kg}`).join(", ") || "none"}</td></tr>)}</tbody></table>
                <p className="border-t border-border p-2 text-xs text-muted">{compare.label} Existing single-recipient engine would recover {fmtKg(compare.baseline_single_recipient.allocated_kg)}. Strategies are trade-offs under the same safety limits, not interchangeable.</p>
              </div>)}
          </div>
        )}

        {canSimulate && !closed && (
          <div className="space-y-3 border-t border-border pt-4">
            <p className="text-sm font-medium">What-if scenario <Badge tone="neutral">Simulated, no side effects</Badge></p>
            <div className="flex flex-wrap items-end gap-2">
              <Field label="Scenario"><Select value={scenario} onChange={(e) => setScenario(e.target.value)}>{Object.entries(SCENARIOS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</Select></Field>
              {["recipient_rejection", "capacity_reduction"].includes(scenario) && <Field label="Recipient"><Select value={simRecipient} onChange={(e) => setSimRecipient(e.target.value)}><option value="">Choose…</option>{recips.data?.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}</Select></Field>}
              {scenario === "capacity_reduction" && <Field label="New capacity (kg)"><Input type="number" min={0} value={simCap} onChange={(e) => setSimCap(e.target.value)} /></Field>}
              {scenario === "vehicle_delay" && <Field label="Delay (min)"><Input type="number" min={0} max={720} value={simDelay} onChange={(e) => setSimDelay(e.target.value)} /></Field>}
              <Button variant="secondary" loading={doSim.isPending} onClick={() => doSim.mutate()}>Run scenario</Button>
            </div>
            {sim && (
              <div className="grid gap-3 md:grid-cols-2" aria-live="polite">
                <div className="rounded-md border border-border p-3"><PlanView plan={sim.before} title="Before" /></div>
                <div className="rounded-md border border-border p-3"><PlanView plan={sim.after} title={`After: ${sim.changes.join(" ") || "no change"}`} /></div>
                <p className="text-xs text-muted md:col-span-2">Change in allocated quantity: <strong className="tabular">{sim.delta.allocated_kg > 0 ? "+" : ""}{sim.delta.allocated_kg} kg</strong>. {sim.note}</p>
              </div>)}
          </div>
        )}
        <p className="text-[11px] text-muted">Decisions come from a deterministic rule-based optimizer. Time estimates are fixed heuristics, not routing data. Evidence thresholds are operational heuristics, not validated food-safety rules. A person must approve.</p>
      </div>

      <ConfirmDialog open={dlg?.kind === "commit"} onOpenChange={(o) => !o && setDlg(null)} title="Reserve quantity for this plan?" body="This reserves the food for the listed recipients. They are not notified until you approve the proposed allocations." confirmLabel="Commit plan" loading={run.isPending}
        onConfirm={() => run.mutate({ path: `/recovery-cases/${caseId}/allocation/commit`, body: { strategy, confirm: true } })}>{preview && <PlanView plan={preview} />}</ConfirmDialog>
      <ConfirmDialog open={!!dlg && dlg.kind !== "commit"} onOpenChange={(o) => !o && setDlg(null)} danger loading={run.isPending}
        title={dlg?.kind === "cancel" ? "Cancel this allocation?" : dlg?.kind === "failure" ? "Report transport failure" : "Report transport delay"}
        body={dlg?.kind === "failure" ? "Only this slice is released and re-planned. No alternative vehicle is modelled." : dlg?.kind === "delay" ? "If the delay breaks the deadline, only this slice is released and re-planned." : "A manual override needs a reason and is written to the audit trail."}
        confirmLabel="Confirm"
        onConfirm={() => {
          if (!dlg || dlg.kind === "commit") return;
          if (reason.trim().length < 3) return void toast.error("Add a short reason.");
          if (dlg.kind === "cancel") run.mutate({ path: `/allocations/${dlg.a.id}/cancel`, body: { reason } });
          else run.mutate({ path: `/allocations/${dlg.a.id}/transport`, body: { kind: dlg.kind, minutes: dlg.kind === "delay" ? 30 : 0, reason } });
        }}>
        <Field label="Reason"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} /></Field>
      </ConfirmDialog>
    </Card>
  );
}
