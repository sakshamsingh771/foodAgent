"use client";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button, Card, CardHeader, PageHeader } from "@/components/ui";
import { QueryBoundary } from "@/components/ui/query-state";
import { download, errorMessage, get } from "@/lib/api";
import { fmtNum } from "@/lib/utils";
import { toast } from "sonner";

interface S { totals: { kg: number; meals: number; co2e_kg: number }; by_rung: { rung: string; label: string; kg: number; meals: number; co2e_kg: number }[]; weekly: { week: string; kg: number; co2e_kg: number }[]; includes_demo_history: boolean; method_note: string }
const COLORS = ["hsl(var(--brand))", "hsl(var(--info))", "hsl(var(--warn))", "hsl(var(--muted))"];
const tip = { contentStyle: { background: "hsl(var(--surface))", border: "1px solid hsl(var(--border))", borderRadius: 8, color: "hsl(var(--fg))" } };
const axis = { tick: { fill: "hsl(var(--muted))", fontSize: 11 }, stroke: "hsl(var(--border))" };

export default function Sustainability() {
  const q = useQuery({ queryKey: ["sustainability"], queryFn: () => get<S>("/sustainability/summary?days=90") });
  return (
    <>
      <PageHeader title="Sustainability" sub="Last 90 days." actions={<Button variant="secondary" onClick={() => download("/sustainability/export.csv", "foodagent-sustainability.csv").catch((e) => toast.error(errorMessage(e)))}><Download className="h-4 w-4" aria-hidden />Export CSV</Button>} />
      <QueryBoundary q={q} isEmpty={(d) => d.totals.kg === 0} empty={{ title: "No recovery recorded yet", body: "Metrics appear once a handover is confirmed." }}>
        {(d) => (
          <div className="space-y-5">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              {[["Food recovered", `${fmtNum(d.totals.kg)} kg`], ["Meals recovered (est.)", fmtNum(d.totals.meals)], ["CO₂e avoided (est.)", `${fmtNum(d.totals.co2e_kg)} kg`]].map(([l, v]) => <Card key={l} className="p-4"><p className="text-xs font-medium uppercase tracking-wide text-muted">{l}</p><p className="mt-1 font-display text-3xl font-semibold tabular">{v}</p></Card>)}
            </div>
            <div className="grid gap-5 lg:grid-cols-2">
              <Card><CardHeader title="Weekly recovery" /><div className="h-64 p-3" role="img" aria-label="Line chart of weekly kilograms recovered"><ResponsiveContainer width="100%" height="100%"><LineChart data={d.weekly} margin={{ left: -12 }}><CartesianGrid stroke="hsl(var(--border))" vertical={false} /><XAxis dataKey="week" tickFormatter={(v: string) => v.slice(5)} {...axis} /><YAxis {...axis} /><Tooltip {...tip} /><Line type="monotone" dataKey="kg" name="Kg recovered" stroke="hsl(var(--brand))" strokeWidth={2} dot={false} /></LineChart></ResponsiveContainer></div></Card>
              <Card><CardHeader title="Recovery by rung" sub="Share of kilograms" /><div className="h-64 p-3" role="img" aria-label="Donut chart of kilograms recovered by rung"><ResponsiveContainer width="100%" height="100%"><PieChart><Pie data={d.by_rung.filter((r) => r.kg > 0)} dataKey="kg" nameKey="label" innerRadius="55%" outerRadius="85%" paddingAngle={2}>{d.by_rung.map((_, i) => <Cell key={i} fill={COLORS[i]} stroke="hsl(var(--surface))" />)}</Pie><Tooltip {...tip} /><Legend wrapperStyle={{ fontSize: 12 }} /></PieChart></ResponsiveContainer></div></Card>
              <Card className="lg:col-span-2"><CardHeader title="CO₂e avoided by rung (est.)" /><div className="h-56 p-3" role="img" aria-label="Bar chart of estimated CO2e avoided by rung"><ResponsiveContainer width="100%" height="100%"><BarChart data={d.by_rung} margin={{ left: -12 }}><CartesianGrid stroke="hsl(var(--border))" vertical={false} /><XAxis dataKey="rung" {...axis} /><YAxis {...axis} /><Tooltip {...tip} /><Bar dataKey="co2e_kg" name="CO₂e (kg)" fill="hsl(var(--brand))" radius={[4, 4, 0, 0]} /></BarChart></ResponsiveContainer></div></Card>
            </div>
            <p className="text-xs text-muted">{d.method_note}{d.includes_demo_history ? " Includes simulated demo history." : ""}</p>
          </div>
        )}
      </QueryBoundary>
    </>
  );
}
