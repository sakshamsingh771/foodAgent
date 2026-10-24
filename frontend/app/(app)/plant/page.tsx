"use client";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown } from "lucide-react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Badge, Card, CardHeader, PageHeader } from "@/components/ui";
import { QueryBoundary } from "@/components/ui/query-state";
import { get } from "@/lib/api";
import { fmtDateTime, fmtKg, fmtNum } from "@/lib/utils";

interface P { plant: { id: string; name: string } | null; series: { day: string; production_kg: number; oee: number; energy_kwh: number; downtime_min: number }[]; lines: { line: string; oee: number; downtime_min: number; production_kg: number }[]; anomalies: { id: string; line: string; kind: string; severity: string; description: string; detected_at: string; simulated: boolean; affected_lots: number }[]; lots_at_risk: number; kg_at_risk: number; note: string }
const axis = { tick: { fill: "hsl(var(--muted))", fontSize: 11 }, stroke: "hsl(var(--border))" };
const tip = { contentStyle: { background: "hsl(var(--surface))", border: "1px solid hsl(var(--border))", borderRadius: 8, color: "hsl(var(--fg))" } };

export default function Plant() {
  const q = useQuery({ queryKey: ["plant"], queryFn: () => get<P>("/plant/overview") });
  return (
    <QueryBoundary q={q} isEmpty={(d) => !d.plant} empty={{ title: "No plant configured" }}>
      {(d) => {
        const last = d.series[d.series.length - 1];
        const hit = d.anomalies.find((a) => !a.simulated || a.severity === "high");
        return (
          <>
            <PageHeader title="Plant operations" sub={d.plant!.name} />
            <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
              {[["Production today", last ? fmtKg(last.production_kg) : "–"], ["OEE", last ? `${last.oee}%` : "–"], ["Downtime today", last ? `${last.downtime_min} min` : "–"], ["Recovery risk", `${fmtNum(d.kg_at_risk)} kg`]].map(([l, v]) => <Card key={l} className="p-4"><p className="text-xs font-medium uppercase tracking-wide text-muted">{l}</p><p className="mt-1 font-display text-2xl font-semibold tabular">{v}</p></Card>)}
            </div>
            {hit && <Card className="mb-5 p-4"><p className="mb-2 text-sm font-semibold">How a plant problem becomes recovery risk</p>
              <ol className="flex flex-col items-start gap-1 text-sm">{[`${hit.line || "Line"}: ${hit.kind.replace(/_/g, " ")}`, "Production delayed or product held", "Freshness window shortened", `Recovery risk up: ${d.lots_at_risk} lot(s) / ${fmtKg(d.kg_at_risk)} now at risk`].map((s, i, a) => <li key={s} className="flex flex-col"><span className="rounded-md bg-subtle px-3 py-1.5">{s}</span>{i < a.length - 1 && <ArrowDown className="ml-4 h-4 w-4 text-muted" aria-hidden />}</li>)}</ol></Card>}
            <div className="grid gap-5 lg:grid-cols-2">
              <Card><CardHeader title="OEE and downtime, 14 days" /><div className="h-60 p-3" role="img" aria-label="Line chart of OEE percent over 14 days"><ResponsiveContainer width="100%" height="100%"><LineChart data={d.series} margin={{ left: -12 }}><CartesianGrid stroke="hsl(var(--border))" vertical={false} /><XAxis dataKey="day" tickFormatter={(v: string) => v.slice(5)} {...axis} /><YAxis {...axis} domain={[50, 100]} /><Tooltip {...tip} /><Line dataKey="oee" name="OEE %" stroke="hsl(var(--brand))" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></div></Card>
              <Card><CardHeader title="Energy, 14 days" /><div className="h-60 p-3" role="img" aria-label="Line chart of energy use in kilowatt-hours"><ResponsiveContainer width="100%" height="100%"><LineChart data={d.series} margin={{ left: -4 }}><CartesianGrid stroke="hsl(var(--border))" vertical={false} /><XAxis dataKey="day" tickFormatter={(v: string) => v.slice(5)} {...axis} /><YAxis {...axis} /><Tooltip {...tip} /><Line dataKey="energy_kwh" name="kWh" stroke="hsl(var(--info))" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></div></Card>
              <Card><CardHeader title="Lines today" /><table className="w-full text-sm"><caption className="sr-only">Production lines today</caption><thead className="text-left text-xs text-muted"><tr>{["Line", "OEE", "Downtime", "Output"].map((h) => <th key={h} scope="col" className="px-4 py-2 font-medium">{h}</th>)}</tr></thead><tbody className="divide-y divide-border">{d.lines.map((l) => <tr key={l.line}><td className="px-4 py-2.5">{l.line}</td><td className="px-4 py-2.5 tabular">{l.oee}%</td><td className="px-4 py-2.5 tabular">{l.downtime_min} min</td><td className="px-4 py-2.5 tabular">{fmtKg(l.production_kg)}</td></tr>)}</tbody></table></Card>
              <Card><CardHeader title="Anomalies" /><ul className="divide-y divide-border">{d.anomalies.length === 0 && <li className="p-4 text-sm text-muted">No anomalies recorded.</li>}{d.anomalies.map((a) => <li key={a.id} className="px-4 py-3"><div className="flex flex-wrap items-center gap-2"><Badge tone={a.severity === "high" ? "danger" : "warn"}>{a.severity}</Badge><span className="text-sm font-medium">{a.kind.replace(/_/g, " ")}</span>{a.simulated && <Badge>Simulated</Badge>}</div><p className="mt-1 text-sm text-muted">{a.description}</p><p className="text-xs text-muted">{fmtDateTime(a.detected_at)} · {a.affected_lots} lot(s) affected</p></li>)}</ul></Card>
            </div>
            <p className="mt-4 text-xs text-muted">{d.note}</p>
          </>
        );
      }}
    </QueryBoundary>
  );
}
