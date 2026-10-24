"use client";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import Link from "next/link";
import { Card, CardHeader, PageHeader } from "@/components/ui";
import { QueryBoundary } from "@/components/ui/query-state";
import { useDashboard } from "@/hooks/queries";
import { fmtDateTime, fmtKg, fmtNum } from "@/lib/utils";

function Kpi({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: "danger" | "safe" }) {
  return (
    <Card className="p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted">{label}</p>
      <p className={`mt-1 font-display text-3xl font-semibold tabular ${tone === "danger" ? "text-danger" : tone === "safe" ? "text-safe" : ""}`}>{value}</p>
      {sub && <p className="mt-0.5 text-xs text-muted">{sub}</p>}
    </Card>
  );
}

export default function Dashboard() {
  const q = useDashboard();
  return (
    <>
      <PageHeader title="Overview" sub="What needs attention now, and what has been recovered." />
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
                <CardHeader title="Recent activity" action={<Link href="/compliance" className="text-xs text-info hover:underline">Audit trail</Link>} />
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
