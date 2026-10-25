"use client";
import * as Slider from "@radix-ui/react-slider";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, FileText, Upload } from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { AllocationPanel } from "@/components/recovery/allocation-panel";
import { ConfidenceMeter, FreshnessRing, MethodBadge, RecoveryLadder, StatusBadge } from "@/components/recovery/signature";
import { Badge, Button, Card, CardHeader, ConfirmDialog, Field, Input, PageHeader, Select, Textarea } from "@/components/ui";
import { QueryBoundary } from "@/components/ui/query-state";
import { useCase, useRecipients } from "@/hooks/queries";
import { download, errorMessage, get, post, patch, upload } from "@/lib/api";
import { fmtDateTime, fmtKg, titleCase } from "@/lib/utils";
import { useAuth } from "@/providers";
import type { CaseDetail, Option } from "@/types/api";

interface Sim { p_success: number; recommended: { rung: string; label: string; est_recovery_kg: number } | null; hedge: { rung: string; label: string } | null; deadline: string; expected_recovery_kg: number; note: string }

function Simulator({ c }: { c: CaseDetail }) {
  const [v, setV] = useState({ pickup_delay_min: c.pickup_delay_min, acceptance_prob: 0.82, handover_buffer_min: c.handover_buffer_min, remaining_minutes: c.lot.freshness.remaining_minutes });
  const [debounced, setDebounced] = useState(v);
  useEffect(() => { const t = setTimeout(() => setDebounced(v), 250); return () => clearTimeout(t); }, [v]);
  const sim = useQuery({ queryKey: ["sim", c.id, debounced], queryFn: () => post<Sim>(`/recovery-cases/${c.id}/simulate`, debounced), placeholderData: (p) => p });
  const row = (label: string, key: keyof typeof v, min: number, max: number, step: number, fmt: (n: number) => string) => (
    <div>
      <div className="flex items-center justify-between text-sm"><label id={`l-${key}`} className="font-medium">{label}</label><span className="tabular text-muted">{fmt(v[key])}</span></div>
      <Slider.Root className="relative mt-2 flex h-9 touch-none select-none items-center" min={min} max={max} step={step} value={[v[key]]} onValueChange={([n]) => setV((s) => ({ ...s, [key]: n }))} aria-labelledby={`l-${key}`}>
        <Slider.Track className="relative h-1.5 grow rounded-full bg-subtle"><Slider.Range className="absolute h-full rounded-full bg-brand" /></Slider.Track>
        <Slider.Thumb className="block h-6 w-6 rounded-full border-2 border-brand bg-surface shadow-card" aria-label={label} />
      </Slider.Root>
    </div>
  );
  return (
    <Card>
      <CardHeader title="What-if simulator" sub="Change the inputs to see how the plan shifts." action={<MethodBadge method="SIMULATED" />} />
      <div className="grid gap-6 p-4 md:grid-cols-2">
        <div className="space-y-3">
          {row("Pickup delay", "pickup_delay_min", 0, 240, 5, (n) => `${n} min`)}
          {row("Acceptance probability", "acceptance_prob", 0, 1, 0.01, (n) => `${Math.round(n * 100)}%`)}
          {row("Handover buffer", "handover_buffer_min", 0, 120, 5, (n) => `${n} min`)}
          {row("Remaining safe time", "remaining_minutes", 0, Math.max(c.lot.window_minutes, 600), 10, (n) => `${Math.floor(n / 60)}h ${n % 60}m`)}
        </div>
        <div className="space-y-3" aria-live="polite">
          {sim.data ? (<>
            <ConfidenceMeter value={sim.data.p_success} simulated label="Estimated recovery success" />
            <dl className="grid grid-cols-2 gap-3 text-sm">
              <div><dt className="text-xs text-muted">Recommended</dt><dd className="font-semibold">{sim.data.recommended ? `${sim.data.recommended.rung} ${sim.data.recommended.label}` : "No pathway fits"}</dd></div>
              <div><dt className="text-xs text-muted">Backup</dt><dd className="font-semibold">{sim.data.hedge ? `${sim.data.hedge.rung} ${sim.data.hedge.label}` : "None"}</dd></div>
              <div><dt className="text-xs text-muted">Act by</dt><dd className="font-semibold tabular">{fmtDateTime(sim.data.deadline)}</dd></div>
              <div><dt className="text-xs text-muted">Expected recovery</dt><dd className="font-semibold tabular">{fmtKg(sim.data.expected_recovery_kg)}</dd></div>
            </dl>
            <p className="text-xs text-muted">{sim.data.note}</p>
          </>) : <p className="text-sm text-muted">Calculating…</p>}
        </div>
      </div>
    </Card>
  );
}

function Evidence({ c }: { c: CaseDetail }) {
  const { user } = useAuth();
  const qc = useQueryClient(); const ref = useRef<HTMLInputElement>(null); const [kind, setKind] = useState("photo");
  const m = useMutation({
    mutationFn: (file: File) => { const fd = new FormData(); fd.append("file", file); fd.append("kind", kind); return upload(`/recovery-cases/${c.id}/evidence`, fd); },
    onSuccess: () => { toast.success("Evidence added. The options were re-checked."); qc.invalidateQueries({ queryKey: ["case", c.id] }); if (ref.current) ref.current.value = ""; },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const have = new Set(c.evidence.map((e) => e.kind));
  const closed = ["completed", "cancelled", "rejected"].includes(c.status);
  const canUpload = !!user && ["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER"].includes(user.role);
  return (
    <Card>
      <CardHeader title="Evidence" sub={`${Math.round(c.evidence_score * 100)}% of required evidence on file`} />
      <div className="space-y-3 p-4">
        <div className="flex flex-wrap gap-1.5">{c.required_evidence.map((k) => <Badge key={k} tone={have.has(k) ? "safe" : "warn"}>{have.has(k) ? "✓ " : ""}{titleCase(k)}</Badge>)}</div>
        <ul className="divide-y divide-border">{c.evidence.length === 0 && <li className="py-2 text-sm text-muted">No evidence uploaded yet.</li>}
          {c.evidence.map((e) => <li key={e.id} className="flex items-center justify-between gap-2 py-2 text-sm"><span className="flex min-w-0 items-center gap-2"><FileText className="h-4 w-4 shrink-0 text-muted" aria-hidden /><span className="truncate">{e.original_name}</span><Badge>{titleCase(e.kind)}</Badge></span>
            <button className="min-h-9 text-info hover:underline" onClick={() => download(`/recovery-cases/${c.id}/evidence/${e.id}/file`, e.original_name).catch((x) => toast.error(errorMessage(x)))}>Download</button></li>)}
        </ul>
        {!closed && canUpload && <div className="flex flex-wrap items-center gap-2">
          <Select aria-label="Evidence type" value={kind} onChange={(e) => setKind(e.target.value)}>{["photo", "temperature_log", "label", "lab_report", "other"].map((k) => <option key={k} value={k}>{titleCase(k)}</option>)}</Select>
          <input ref={ref} type="file" accept=".jpg,.jpeg,.png,.pdf,.csv,.txt" className="sr-only" id="ev-file" onChange={(e) => e.target.files?.[0] && m.mutate(e.target.files[0])} />
          <Button variant="secondary" loading={m.isPending} onClick={() => ref.current?.click()}><Upload className="h-4 w-4" aria-hidden />Upload file</Button>
          <span className="text-xs text-muted">JPG, PNG, PDF, CSV or TXT up to 10 MB</span>
        </div>}
      </div>
    </Card>
  );
}

export default function CasePage() {
  const { id } = useParams<{ id: string }>();
  const { user } = useAuth(); const qc = useQueryClient();
  const q = useCase(id); const recipients = useRecipients();
  const [pick, setPick] = useState<Option | null>(null); const [recipient, setRecipient] = useState(""); const [note, setNote] = useState("");
  const [dlg, setDlg] = useState<null | "approve" | "reject" | "replan" | "cancel">(null); const [reason, setReason] = useState("");
  const [when, setWhen] = useState(""); const [logi, setLogi] = useState("");
  const logistics = useQuery({ queryKey: ["logi-users"], queryFn: () => get<{ id: string; name: string }[]>("/users/logistics"), enabled: !!user && ["ADMIN", "OPERATIONS_MANAGER"].includes(user.role) });
  const done = () => { qc.invalidateQueries({ queryKey: ["case", id] }); qc.invalidateQueries({ queryKey: ["cases"] }); qc.invalidateQueries({ queryKey: ["dashboard"] }); setDlg(null); setReason(""); };
  const act = useMutation({ mutationFn: ({ path, body }: { path: string; body?: unknown }) => post(path, body), onSuccess: (_d, v) => { toast.success(v.path.endsWith("approve") ? "Plan approved. The recipient has been notified." : "Done."); done(); }, onError: (e) => toast.error(errorMessage(e)) });
  const pickupMut = useMutation({ mutationFn: ({ path, body, method }: { path: string; body?: unknown; method?: "patch" }) => (method === "patch" ? patch(path, body) : post(path, body)), onSuccess: () => { toast.success("Pickup updated."); done(); }, onError: (e) => toast.error(errorMessage(e)) });

  const canApprove = !!user && ["ADMIN", "RECOVERY_MANAGER"].includes(user.role);
  const canClose = canApprove;   const canPickup = !!user && ["ADMIN", "OPERATIONS_MANAGER", "LOGISTICS"].includes(user.role);
  const canSchedule = !!user && ["ADMIN", "OPERATIONS_MANAGER"].includes(user.role);

  return (
    <QueryBoundary q={q}>
      {(c) => {
        const rec = c.options.find((o) => o.is_recommended);
        const eligibleRecipients = (recipients.data ?? []).filter((r) => pick && r.accepts_rungs.includes(pick.rung));
        const pickup = c.pickups.find((p) => !["cancelled"].includes(p.status));
        const NEXT: Record<string, string> = { scheduled: "in_transit", assigned: "in_transit", in_transit: "arrived" };
        return (
          <>
            <Link href="/recovery" className="mb-3 inline-flex min-h-9 items-center gap-1 text-sm text-muted hover:text-fg"><ArrowLeft className="h-4 w-4" aria-hidden />All cases</Link>
            <PageHeader title={c.case_number} sub={`${c.lot.product.name} · ${c.lot.lot_code} · ${fmtKg(c.quantity_kg)}`} actions={<StatusBadge status={c.status} />} />
            <p className="mb-4 rounded-md border border-border bg-subtle px-3 py-2 text-xs text-muted">{c.disclaimer}</p>
            <div className="grid gap-5 lg:grid-cols-3">
              <div className="space-y-5 lg:col-span-2">
                <Card>
                  <CardHeader title="Recovery ladder" sub={`Plan v${c.plan_version}${c.replan_count ? ` · replanned ${c.replan_count}×` : ""}`} />
                  <div className="p-4">
                    <RecoveryLadder options={c.options} selected={c.status === "pending_approval" ? pick?.rung : c.selected_rung} disabled={!canApprove || c.status !== "pending_approval"}
                      onSelect={canApprove && c.status === "pending_approval" ? (o) => { setPick(o); setRecipient(o.recipient_id ?? ""); } : undefined} />
                    {canApprove && c.status === "pending_approval" && (
                      <div className="mt-4 flex flex-wrap gap-2 border-t border-border pt-4">
                        <Button disabled={!pick && !rec} onClick={() => { if (!pick && rec) { setPick(rec); setRecipient(rec.recipient_id ?? ""); } setDlg("approve"); }}>Approve {pick?.rung ?? rec?.rung ?? ""} plan</Button>
                        <Button variant="secondary" onClick={() => setDlg("replan")}>Replan</Button><Button variant="secondary" onClick={() => setDlg("reject")}>Reject</Button>
                      </div>
                    )}
                    {c.recipient && c.selected_rung && <p className="mt-3 text-sm">Assigned to <strong>{c.recipient.name}</strong> via {c.selected_rung}.</p>}
                  </div>
                </Card>
                {!["rejected"].includes(c.status) && <AllocationPanel caseId={c.id} status={c.status} canManage={canApprove} canTransport={canPickup} canSimulate={!!user && ["ADMIN", "RECOVERY_MANAGER"].includes(user.role)} />}
                {["pending_approval", "awaiting_recipient", "accepted"].includes(c.status) && user && ["ADMIN", "RECOVERY_MANAGER"].includes(user.role) && <Simulator c={c} />}
                {c.recipient && (pickup || (c.status === "accepted" && canSchedule)) && (
                  <Card>
                    <CardHeader title="Pickup & handover" />
                    <div className="space-y-3 p-4">
                      {pickup ? (<>
                        <div className="flex flex-wrap items-center gap-2"><StatusBadge status={pickup.status} /><span className="text-sm tabular">Scheduled {fmtDateTime(pickup.scheduled_for)} · ETA {fmtDateTime(pickup.eta)}</span>{pickup.delay_minutes > 0 && <Badge tone="warn">Delayed {pickup.delay_minutes} min</Badge>}</div>
                        {pickup.logistics_user && <p className="text-sm text-muted">Driver: {pickup.logistics_user.name}</p>}
                        {canPickup && <div className="flex flex-wrap gap-2">
                          {NEXT[pickup.status] && <Button size="sm" loading={pickupMut.isPending} onClick={() => pickupMut.mutate({ path: `/pickups/${pickup.id}/status`, body: { status: NEXT[pickup.status] }, method: "patch" })}>Mark {titleCase(NEXT[pickup.status]).toLowerCase()}</Button>}
                          {pickup.status === "arrived" && <Button size="sm" loading={pickupMut.isPending} onClick={() => pickupMut.mutate({ path: `/pickups/${pickup.id}/handover`, body: {} })}>Confirm handover</Button>}
                          {["scheduled", "in_transit"].includes(pickup.status) && <Button size="sm" variant="secondary" onClick={() => pickupMut.mutate({ path: `/pickups/${pickup.id}/delay`, body: { minutes: 30, reason: "Vehicle running late" } })}>Report 30 min delay</Button>}
                        </div>}
                      </>) : (
                        <form className="grid gap-3 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); if (when) pickupMut.mutate({ path: `/recovery-cases/${c.id}/pickup`, body: { scheduled_for: new Date(when).toISOString(), logistics_user_id: logi || null } }); }}>
                          <Field label="Pickup time"><Input type="datetime-local" required value={when} onChange={(e) => setWhen(e.target.value)} /></Field>
                          <Field label="Driver"><Select className="w-full" value={logi} onChange={(e) => setLogi(e.target.value)}><option value="">Unassigned</option>{logistics.data?.map((u) => <option key={u.id} value={u.id}>{u.name}</option>)}</Select></Field>
                          <div className="flex items-end"><Button type="submit" className="w-full" loading={pickupMut.isPending}>Schedule pickup</Button></div>
                        </form>
                      )}
                    </div>
                  </Card>
                )}
                <Card>
                  <CardHeader title="Activity & audit history" sub="Each entry is chained to the one before it." />
                  <ol className="divide-y divide-border">{c.timeline.map((e) => <li key={e.id} className="flex gap-3 px-4 py-2.5"><time dateTime={e.created_at} className="w-24 shrink-0 text-xs tabular text-muted">{new Date(e.created_at).toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}</time><div><p className="text-sm">{e.summary}</p><p className="text-xs text-muted">{e.actor}</p></div></li>)}</ol>
                </Card>
              </div>
              <div className="space-y-5">
                <Card className="flex flex-col items-center gap-3 p-5"><FreshnessRing percent={c.lot.freshness.percent} remainingMinutes={c.lot.freshness.remaining_minutes} state={c.lot.freshness.state} size={140} /><p className="text-xs text-muted">Window ends {fmtDateTime(c.lot.safe_until)}</p></Card>
                {rec && c.status === "pending_approval" && <Card className="p-4"><ConfidenceMeter value={rec.confidence} factors={rec.factors} /><p className="mt-2 text-xs text-muted">Recommended: {rec.rung} {rec.label} · <MethodBadge method={rec.method} /></p></Card>}
                <Evidence c={c} />
                {canClose && !["completed", "cancelled", "rejected"].includes(c.status) && <Button variant="secondary" className="w-full" onClick={() => setDlg("cancel")}>Close without recovery</Button>}
              </div>
            </div>

            <ConfirmDialog open={dlg === "approve"} onOpenChange={(o) => !o && setDlg(null)} title="Confirm recovery plan" body={`You are approving ${pick?.rung ?? rec?.rung} for ${c.case_number}. foodAgent doesn't certify food safety; your approval confirms you've reviewed the condition evidence.`} confirmLabel="Approve plan" loading={act.isPending}
              onConfirm={() => act.mutate({ path: `/recovery-cases/${c.id}/approve`, body: { rung: pick?.rung ?? rec?.rung, recipient_id: recipient || (pick ?? rec)?.recipient_id, note } })}>
              <div className="space-y-3"><Field label="Recipient"><Select className="w-full" value={recipient || (pick ?? rec)?.recipient_id || ""} onChange={(e) => setRecipient(e.target.value)}>{(recipients.data ?? []).filter((r) => r.accepts_rungs.includes((pick ?? rec)?.rung ?? "")).map((r) => <option key={r.id} value={r.id}>{r.name} · {r.distance_km} km</option>)}</Select></Field><Field label="Note (optional)"><Textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} /></Field></div>
            </ConfirmDialog>
            <ConfirmDialog open={dlg === "reject"} onOpenChange={(o) => !o && setDlg(null)} title="Reject this plan?" body="The lot goes back to available stock." confirmLabel="Reject plan" danger loading={act.isPending} onConfirm={() => act.mutate({ path: `/recovery-cases/${c.id}/reject`, body: { note: reason } })}><Field label="Reason"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></Field></ConfirmDialog>
            <ConfirmDialog open={dlg === "replan"} onOpenChange={(o) => !o && setDlg(null)} title="Replan this case" body="The engine re-scores every rung with current conditions." confirmLabel="Replan" loading={act.isPending} onConfirm={() => reason.trim().length >= 3 ? act.mutate({ path: `/recovery-cases/${c.id}/replan`, body: { reason, exclude_rung: pick?.rung ?? undefined } }) : toast.error("Add a short reason (at least 3 characters).")}>
              <div className="space-y-2"><Field label="Reason"><Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} /></Field>{pick && <p className="text-xs text-muted">The selected rung ({pick.rung}) will be ruled out.</p>}</div>
            </ConfirmDialog>
            <ConfirmDialog open={dlg === "cancel"} onOpenChange={(o) => !o && setDlg(null)} title="Close without recovery?" body="Any open pickup is cancelled and the lot returns to available stock." confirmLabel="Close case" danger loading={act.isPending} onConfirm={() => act.mutate({ path: `/recovery-cases/${c.id}/cancel`, body: { note: reason } })}><Field label="Reason"><Textarea value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} /></Field></ConfirmDialog>
          </>
        );
      }}
    </QueryBoundary>
  );
}
