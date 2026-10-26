"use client";
import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { toast } from "sonner";
import { Button, Card, PageHeader } from "@/components/ui";
import { QueryBoundary } from "@/components/ui/query-state";
import { download, errorMessage, get } from "@/lib/api";
import { fmtDateTime } from "@/lib/utils";

interface Ex { missing_evidence: { id: string; case_number: string; status: string }[]; stale_pending_approval: { id: string; case_number: string; status: string }[]; overdue_pickups: { id: string; case_number: string; status: string; scheduled_for: string }[]; failed_pickups: { id: string; case_number: string; status: string }[] }
const EXPORTS = [["cases", "Recovery cases"], ["inventory", "Inventory"], ["pickups", "Logistics"], ["exceptions", "Exceptions"]] as const;

function Section({ title, empty, children }: { title: string; empty: string; children: React.ReactNode[] }) {
  return <Card className="p-4"><h2 className="font-display text-base font-semibold">{title} <span className="text-muted">({children.length})</span></h2>{children.length === 0 ? <p className="mt-2 text-sm text-muted">{empty}</p> : <ul className="mt-2 space-y-1 text-sm">{children}</ul>}</Card>;
}

export default function Reports() {
  const q = useQuery({ queryKey: ["exceptions"], queryFn: () => get<Ex>("/reports/exceptions") });
  const dl = async (k: string) => { try { await download(`/reports/${k}.csv`, `foodagent-${k}.csv`); } catch (e) { toast.error(errorMessage(e)); } };
  return (
    <>
      <PageHeader title="Reports & exceptions" sub="Read-only exception findings and CSV exports for your organization. Every export is recorded in the audit log." />
      <div className="mb-5 flex flex-wrap gap-2">{EXPORTS.map(([k, label]) => <Button key={k} variant="secondary" onClick={() => dl(k)}><Download className="h-4 w-4" aria-hidden />{label} CSV</Button>)}</div>
      <QueryBoundary q={q}>
        {(d) => (
          <div className="grid gap-4 lg:grid-cols-2">
            <Section title="Cases missing evidence" empty="Every case has at least one evidence file.">{d.missing_evidence.map((c) => <li key={c.id}>{c.case_number} · {c.status}</li>)}</Section>
            <Section title="Approvals waiting over 4 hours" empty="No stale approvals.">{d.stale_pending_approval.map((c) => <li key={c.id}>{c.case_number}</li>)}</Section>
            <Section title="Overdue pickups" empty="No overdue pickups.">{d.overdue_pickups.map((p) => <li key={p.id}>{p.case_number} · due {fmtDateTime(p.scheduled_for)}</li>)}</Section>
            <Section title="Cancelled or failed pickups" empty="None recorded.">{d.failed_pickups.map((p) => <li key={p.id}>{p.case_number} · {p.status}</li>)}</Section>
          </div>
        )}
      </QueryBoundary>
    </>
  );
}
