"use client";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Card, CardHeader, PageHeader } from "@/components/ui";
import { QueryBoundary } from "@/components/ui/query-state";
import { useCases, useDashboard, useLots, usePickups } from "@/hooks/queries";
import { fmtDateTime, fmtKg, fmtNum } from "@/lib/utils";
import { useAuth } from "@/providers";
import type { AuditEntry, Page, Role } from "@/types/api";
import { get } from "@/lib/api";

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "danger" | "safe" }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className={`mt-1 font-display text-3xl font-semibold tabular ${tone === "danger" ? "text-danger" : tone === "safe" ? "text-safe" : ""}`}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
    </Card>
  );
}

function OrganizationOverview({ role }: { role: Role }) {
  const q = useDashboard();
  return (
    <>
      <PageHeader title={role === "ADMIN" ? "Organization overview" : "Operational overview"} sub={role === "ADMIN" ? "System health, organization-wide performance and administrative attention." : "What needs attention now, and what has been recovered."} />
      <QueryBoundary q={q}>
        {(d) => (
          <div className="space-y-5">
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Kpi label="Kg at risk" value={fmtNum(d.kpis.kg_at_risk)} sub={`${d.kpis.lots_at_risk} lots · ${d.kpis.loss_imminent} loss imminent`} tone={d.kpis.loss_imminent ? "danger" : undefined} />
              <Kpi label="Kg recovered today" value={fmtNum(d.kpis.kg_recovered_today)} tone="safe" />
              <Kpi label="Meals recovered" value={fmtNum(d.kpis.meals_recovered_30d)} sub="Last 30 days, estimated" />
              <Kpi label="CO₂e avoided" value={`${fmtNum(d.kpis.co2e_avoided_kg_30d)} kg`} sub="Last 30 days, estimated" />
            </div>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Kpi label="Active cases" value={String(d.kpis.active_cases)} />
              <Link href="/recovery?status=pending_approval" className="block"><Kpi label="Pending approvals" value={String(d.kpis.pending_approvals)} tone={d.kpis.pending_approvals ? "danger" : undefined} /></Link>
              <Kpi label="Pickups today" value={String(d.kpis.pickups_today)} />
              <Kpi label="Recovery success rate" value={d.kpis.recovery_success_rate == null ? "–" : `${d.kpis.recovery_success_rate}%`} sub="Completed vs. closed without recovery" />
            </div>
            {role === "ADMIN" && <Card className="border-brand/30 bg-subtle/40 p-4"><p className="font-semibold">Administration</p><p className="mt-1 text-sm text-muted">Manage organization users, review compliance records and monitor the operational audit trail.</p><div className="mt-3 flex flex-wrap gap-2"><Link href="/settings" className="text-sm font-medium text-info hover:underline">Manage users</Link><Link href="/compliance" className="text-sm font-medium text-info hover:underline">Review compliance</Link></div></Card>}
            <div className="grid gap-5 lg:grid-cols-5">
              <Card className="lg:col-span-3">
                <CardHeader title="Food recovered, last 14 days" sub="Kilograms per day. Includes simulated demo history." />
                <div className="h-64 p-3" role="img" aria-label="Area chart of kilograms recovered per day over the last 14 days">
                  <ResponsiveContainer width="100%" height="100%"><AreaChart data={d.trend} margin={{ left: -12, right: 8, top: 8 }}>
                    <CartesianGrid stroke="hsl(var(--border))" vertical={false} /><XAxis dataKey="day" tickFormatter={(v: string) => v.slice(5)} tick={{ fill: "hsl(var(--muted))", fontSize: 11 }} stroke="hsl(var(--border))" /><YAxis tick={{ fill: "hsl(var(--muted))", fontSize: 11 }} stroke="hsl(var(--border))" />
                    <Tooltip contentStyle={{ background: "hsl(var(--surface))", border: "1px solid hsl(var(--border))", borderRadius: 8, color: "hsl(var(--fg))" }} formatter={(v: number) => [fmtKg(v), "Recovered"]} />
                    <Area type="monotone" dataKey="kg" stroke="hsl(var(--brand))" fill="hsl(var(--brand))" fillOpacity={0.15} strokeWidth={2} />
                  </AreaChart></ResponsiveContainer>
                </div>
              </Card>
              <Card className="lg:col-span-2">
                <CardHeader title="Recent activity" action={role !== "OPERATIONS_MANAGER" && <Link href="/compliance" className="text-xs text-info hover:underline">Audit trail</Link>} />
                <ul className="divide-y divide-border">
                  {d.recent_activity.map((e) => <li key={e.id} className="px-4 py-2.5"><p className="text-sm">{e.summary}</p><p className="text-xs text-muted">{e.actor} · {fmtDateTime(e.created_at)}</p></li>)}
                </ul>
              </Card>
            </div>
          </div>
        )}
      </QueryBoundary>
    </>
  );
}

function OperationsDashboard() {
  const lots = useLots("page=1&page_size=5&sort=time_to_loss&urgency=AT_RISK");
  const cases = useCases("page=1&page_size=5&sort=urgency&active=true");
  return (
    <>
      <PageHeader title="Operations command center" sub="Act on urgent inventory and move recovery cases forward." />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card><CardHeader title="Urgent lots" action={<Link href="/operations" className="text-xs text-info hover:underline">Open live operations</Link>} />
          <QueryBoundary q={lots} isEmpty={(d) => d.items.length === 0} empty={{ title: "No urgent lots", body: "Nothing needs immediate action." }}>
            {(d) => <ul className="divide-y divide-border">{d.items.map((l) => <li key={l.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm"><span><b>{l.product.name}</b><span className="block text-xs text-muted">{l.lot_code} · {fmtKg(l.quantity_kg)}</span></span><span className="text-danger tabular">{l.freshness.remaining_minutes} min</span></li>)}</ul>}
          </QueryBoundary>
        </Card>
        <Card><CardHeader title="Active recovery work" action={<Link href="/recovery" className="text-xs text-info hover:underline">View cases</Link>} />
          <QueryBoundary q={cases} isEmpty={(d) => d.items.length === 0} empty={{ title: "No active cases" }}>
            {(d) => <ul className="divide-y divide-border">{d.items.map((c) => <li key={c.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm"><span><b>{c.case_number}</b><span className="block text-xs text-muted">{c.lot.product.name}</span></span><span className="text-xs text-muted">{c.status.replaceAll("_", " ")}</span></li>)}</ul>}
          </QueryBoundary>
        </Card>
      </div>
    </>
  );
}

function RecoveryDashboard() {
  const cases = useCases("page=1&page_size=8&sort=urgency&status=pending_approval");
  return (
    <>
      <PageHeader title="Recovery review" sub="Evaluate evidence, compare pathways and make accountable recovery decisions." />
      <Card><CardHeader title="Cases requiring your review" action={<Link href="/recovery?status=pending_approval" className="text-xs text-info hover:underline">All pending cases</Link>} />
        <QueryBoundary q={cases} isEmpty={(d) => d.items.length === 0} empty={{ title: "No pending approvals", body: "New cases will appear here after operations opens them." }}>
          {(d) => <ul className="divide-y divide-border">{d.items.map((c) => <li key={c.id} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3 text-sm"><span><Link href={`/recovery/${c.id}`} className="font-medium text-info hover:underline">{c.case_number}</Link><span className="block text-xs text-muted">{c.lot.product.name} · {fmtKg(c.quantity_kg)}</span></span><span className="text-warn">Pending review</span></li>)}</ul>}
        </QueryBoundary>
      </Card>
    </>
  );
}

function AuditorDashboard() {
  const q = useQuery<AuditEntry[]>({ queryKey: ["dashboard-audit"], queryFn: async () => (await get<Page<AuditEntry>>("/audit?page=1&page_size=8")).items });
  return (
    <>
      <PageHeader title="Audit review" sub="Read-only oversight of decisions, evidence and the tamper-evident record." />
      <Card><CardHeader title="Latest recorded events" action={<Link href="/compliance" className="text-xs text-info hover:underline">Open compliance</Link>} />
        <QueryBoundary q={q} isEmpty={(d) => d.length === 0} empty={{ title: "No audit events" }}>
          {(rows) => <ol className="divide-y divide-border">{rows.map((e) => <li key={e.id} className="px-4 py-3 text-sm"><p>{e.summary}</p><p className="text-xs text-muted">{e.actor} · {fmtDateTime(e.created_at)}</p></li>)}</ol>}
        </QueryBoundary>
      </Card>
    </>
  );
}

function LogisticsDashboard() {
  const q = usePickups("active=true&page_size=8");
  return (
    <>
      <PageHeader title="Logistics board" sub="Manage only the physical movements assigned or available to you." />
      <Card><CardHeader title="Active pickup jobs" action={<Link href="/logistics" className="text-xs text-info hover:underline">Open logistics</Link>} />
        <QueryBoundary q={q} isEmpty={(d) => d.items.length === 0} empty={{ title: "No active pickup jobs", body: "Jobs appear after a recovery offer is accepted and scheduled." }}>
          {(d) => <ul className="divide-y divide-border">{d.items.map((p) => <li key={p.id} className="flex items-center justify-between gap-3 px-4 py-3 text-sm"><span><b>{p.case_number}</b><span className="block text-xs text-muted">{p.product} · {p.recipient ?? "Unassigned"}</span></span><span className="text-xs text-muted">{p.status.replaceAll("_", " ")}</span></li>)}</ul>}
        </QueryBoundary>
      </Card>
    </>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  if (user?.role === "OPERATIONS_MANAGER") return <OperationsDashboard />;
  if (user?.role === "RECOVERY_MANAGER") return <RecoveryDashboard />;
  if (user?.role === "AUDITOR") return <AuditorDashboard />;
  if (user?.role === "LOGISTICS") return <LogisticsDashboard />;
  return <OrganizationOverview role={user?.role ?? "ADMIN"} />;
}
