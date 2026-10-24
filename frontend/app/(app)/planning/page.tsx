"use client";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Area, CartesianGrid, ComposedChart, Line, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardHeader, PageHeader, Select } from "@/components/ui";
import { MethodBadge } from "@/components/recovery/signature";
import { QueryBoundary } from "@/components/ui/query-state";
import { get } from "@/lib/api";
import { fmtKg } from "@/lib/utils";

interface F { product: { id: string; name: string } | null; products: { id: string; name: string }[]; series: { day: string; p50: number; p80: number; actual: number | null; surplus_kg: number; forecast: boolean }[]; backtest: { days: number; mape_pct: number | null; actual_within_p80_pct: number | null }; why_changed: string[]; note: string; recovery_adjusted_production_kg: number }
const axis = { tick: { fill: "hsl(var(--muted))", fontSize: 11 }, stroke: "hsl(var(--border))" };

export default function Planning() {
  const [pid, setPid] = useState("");
  const q = useQuery({ queryKey: ["planning", pid], queryFn: () => get<F>(`/planning/forecast${pid ? `?product_id=${pid}` : ""}`) });
  return (
    <>
      <PageHeader title="Planning" sub="Demand forecast and expected surplus, so production can account for recovery." actions={q.data && <Select aria-label="Product" value={pid || q.data.product?.id || ""} onChange={(e) => setPid(e.target.value)}>{q.data.products.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select>} />
      <QueryBoundary q={q} isEmpty={(d) => !d.product} empty={{ title: "No forecast data yet" }}>
        {(d) => (
          <div className="space-y-5">
            <Card>
              <CardHeader title={`${d.product!.name}: daily demand (kg)`} sub="P50 is the median forecast; P80 leaves room for a high-demand day." action={<MethodBadge method="STATISTICAL" />} />
              <div className="h-72 p-3" role="img" aria-label="Chart of P50 and P80 demand forecast against historical actuals">
                <ResponsiveContainer width="100%" height="100%"><ComposedChart data={d.series} margin={{ left: -8 }}><CartesianGrid stroke="hsl(var(--border))" vertical={false} /><XAxis dataKey="day" tickFormatter={(v: string) => v.slice(5)} {...axis} /><YAxis {...axis} domain={["auto", "auto"]} />
                  <Tooltip contentStyle={{ background: "hsl(var(--surface))", border: "1px solid hsl(var(--border))", borderRadius: 8, color: "hsl(var(--fg))" }} />
                  <Area dataKey="p80" name="P80" stroke="none" fill="hsl(var(--info))" fillOpacity={0.12} /><Line dataKey="p50" name="P50" stroke="hsl(var(--brand))" strokeWidth={2} dot={false} /><Line dataKey="actual" name="Actual" stroke="hsl(var(--fg))" strokeWidth={1.5} dot={{ r: 2 }} connectNulls={false} /></ComposedChart></ResponsiveContainer>
              </div>
            </Card>
            <div className="grid gap-5 md:grid-cols-3">
              <Card className="p-4"><p className="text-xs font-medium uppercase tracking-wide text-muted">Backtest error (MAPE)</p><p className="mt-1 font-display text-3xl font-semibold tabular">{d.backtest.mape_pct == null ? "–" : `${d.backtest.mape_pct}%`}</p><p className="text-xs text-muted">Over {d.backtest.days} past days of stored data</p></Card>
              <Card className="p-4"><p className="text-xs font-medium uppercase tracking-wide text-muted">Actuals within P80</p><p className="mt-1 font-display text-3xl font-semibold tabular">{d.backtest.actual_within_p80_pct == null ? "–" : `${d.backtest.actual_within_p80_pct}%`}</p></Card>
              <Card className="p-4"><p className="text-xs font-medium uppercase tracking-wide text-muted">Expected surplus, next 7 days</p><p className="mt-1 font-display text-3xl font-semibold tabular">{fmtKg(d.recovery_adjusted_production_kg)}</p><p className="text-xs text-muted">Suggested production reduction</p></Card>
            </div>
            <Card><CardHeader title="Why did the forecast change?" /><ul className="list-disc space-y-1 p-4 pl-8 text-sm">{d.why_changed.length ? d.why_changed.map((w) => <li key={w}>{w}</li>) : <li className="text-muted">No changes recorded.</li>}</ul></Card>
            <p className="text-xs text-muted">{d.note}</p>
          </div>
        )}
      </QueryBoundary>
    </>
  );
}
