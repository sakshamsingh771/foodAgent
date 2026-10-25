"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { toast } from "sonner";
import { StatusBadge } from "@/components/recovery/signature";
import { Badge, Button, Card, PageHeader } from "@/components/ui";
import { QueryBoundary } from "@/components/ui/query-state";
import { usePickups } from "@/hooks/queries";
import { errorMessage, get, patch, post } from "@/lib/api";
import { fmtDateTime, fmtKg } from "@/lib/utils";

const FLOW = ["pending", "assigned", "scheduled", "in_transit", "arrived", "handed_over", "completed"];
const NEXT: Record<string, string> = { scheduled: "in_transit", assigned: "in_transit", in_transit: "arrived" };

export default function Logistics() {
  const q = usePickups("active=true&page_size=50"); const done = usePickups("status=completed&page_size=10"); const qc = useQueryClient();
  const refresh = () => { qc.invalidateQueries({ queryKey: ["pickups"] }); qc.invalidateQueries({ queryKey: ["case"] }); };
  const adv = useMutation({ mutationFn: (v: { id: string; status: string }) => patch(`/pickups/${v.id}/status`, { status: v.status }), onSuccess: () => { toast.success("Status updated."); refresh(); }, onError: (e) => toast.error(errorMessage(e)) });
  const hand = useMutation({ mutationFn: (id: string) => post(`/pickups/${id}/handover`, {}), onSuccess: () => { toast.success("Handover confirmed."); refresh(); }, onError: (e) => toast.error(errorMessage(e)) });
  const delay = useMutation({ mutationFn: (id: string) => post(`/pickups/${id}/delay`, { minutes: 30, reason: "Vehicle running late" }), onSuccess: () => { toast.warning("Delay recorded and the team was notified."); refresh(); }, onError: (e) => toast.error(errorMessage(e)) });
  const allocs = useQuery({ queryKey: ["active-allocations"], queryFn: () => get<{ id: string; case_id: string; case_number: string; recipient_name: string; rung: string; quantity_kg: number; status: string; eta: string | null }[]>("/allocations/active") });
  const handAlloc = useMutation({ mutationFn: (id: string) => post(`/allocations/${id}/handover`, {}), onSuccess: () => { toast.success("Handover confirmed."); qc.invalidateQueries({ queryKey: ["active-allocations"] }); refresh(); }, onError: (e) => toast.error(errorMessage(e)) });
  return (
    <>
      <PageHeader title="Logistics" sub="Pickups and handovers, soonest first." />
      <QueryBoundary q={q} isEmpty={(d) => d.items.length === 0} empty={{ title: "No active pickups", body: "Pickups appear after a recipient accepts a lot and a time is scheduled." }}>
        {(d) => <div className="space-y-3">{d.items.map((p) => {
          const idx = FLOW.indexOf(p.status);
          return (
            <Card key={p.id} className="p-4">
              <div className="flex flex-wrap items-start justify-between gap-2"><div><Link href={`/recovery/${p.case_id}`} className="font-semibold text-info hover:underline">{p.case_number}</Link><p className="text-sm text-muted">{p.product} · {fmtKg(p.quantity_kg)} → {p.recipient}</p></div><div className="flex items-center gap-2">{p.delay_minutes > 0 && <Badge tone="warn">+{p.delay_minutes} min</Badge>}<StatusBadge status={p.status} /></div></div>
              <ol className="mt-3 flex gap-1" aria-label="Pickup progress">{["scheduled", "in_transit", "arrived", "handed_over"].map((s) => <li key={s} className={`h-1.5 flex-1 rounded-full ${FLOW.indexOf(s) <= idx ? "bg-brand" : "bg-subtle"}`} aria-label={`${s.replace("_", " ")}${FLOW.indexOf(s) <= idx ? " reached" : ""}`} />)}</ol>
              <p className="mt-2 text-sm text-muted">ETA {fmtDateTime(p.eta)}{p.logistics_user ? ` · ${p.logistics_user.name}` : " · Unassigned"}</p>
              <div className="mt-3 flex flex-wrap gap-2">
                {NEXT[p.status] && <Button size="sm" loading={adv.isPending} onClick={() => adv.mutate({ id: p.id, status: NEXT[p.status] })}>Mark {NEXT[p.status].replace("_", " ")}</Button>}
                {p.status === "arrived" && <Button size="sm" loading={hand.isPending} onClick={() => hand.mutate(p.id)}>Confirm handover</Button>}
                {["scheduled", "in_transit", "assigned"].includes(p.status) && <><Button size="sm" variant="secondary" loading={delay.isPending} onClick={() => delay.mutate(p.id)}>Report 30 min delay</Button><Button size="sm" variant="ghost" onClick={() => adv.mutate({ id: p.id, status: "cancelled" })}>Cancel pickup</Button></>}
              </div>
            </Card>
          );
        })}</div>}
      </QueryBoundary>
      <h2 className="mb-2 mt-8 text-lg font-semibold">Multi-recipient allocations</h2>
      <Card><QueryBoundary q={allocs} isEmpty={(d) => d.length === 0} empty={{ title: "No open allocations", body: "Offered and accepted allocation slices appear here." }}>{(d) => <ul className="divide-y divide-border">{d.map((a) => <li key={a.id} className="flex flex-wrap items-center justify-between gap-2 p-3 text-sm"><div><Link href={`/recovery/${a.case_id}`} className="font-semibold text-info hover:underline">{a.case_number}</Link> · {a.recipient_name} · {fmtKg(a.quantity_kg)} <StatusBadge status={a.status} />{a.eta && <span className="text-muted"> · est. {fmtDateTime(a.eta)}</span>}</div>{a.status === "accepted" ? <Button size="sm" loading={handAlloc.isPending} onClick={() => handAlloc.mutate(a.id)}>Confirm handover</Button> : <span className="text-xs text-muted">Awaiting recipient</span>}</li>)}</ul>}</QueryBoundary></Card>
      <h2 className="mb-2 mt-8 text-lg font-semibold">Recently completed</h2>
      <Card><QueryBoundary q={done} isEmpty={(d) => d.items.length === 0} empty={{ title: "Nothing completed yet" }}>{(d) => <ul className="divide-y divide-border">{d.items.map((p) => <li key={p.id} className="flex justify-between gap-2 px-4 py-3 text-sm"><span>{p.case_number} · {p.product}</span><span className="text-muted tabular">{fmtKg(p.received_kg ?? 0)} · {fmtDateTime(p.handed_over_at)}</span></li>)}</ul>}</QueryBoundary></Card>
    </>
  );
}
