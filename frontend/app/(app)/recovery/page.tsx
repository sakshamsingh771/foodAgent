"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { FreshBadge, StatusBadge } from "@/components/recovery/signature";
import { Card, Input, PageHeader, Select } from "@/components/ui";
import { QueryBoundary } from "@/components/ui/query-state";
import { useCases } from "@/hooks/queries";
import { fmtDuration, fmtKg } from "@/lib/utils";
import { Pager } from "@/components/ui/pager";

function List() {
  const sp = useSearchParams();
  const [q, setQ] = useState(""); const [status, setStatus] = useState(sp.get("status") ?? ""); const [rung, setRung] = useState(""); const [page, setPage] = useState(1);
  const qs = new URLSearchParams({ page: String(page), page_size: "15", sort: "urgency", ...(q && { q }), ...(status && { status }), ...(rung && { rung }) }).toString();
  const cases = useCases(qs);
  return (
    <>
      <PageHeader title="Recovery cases" sub="Every at-risk lot being worked toward its best recovery pathway." />
      <div className="mb-4 flex flex-wrap gap-2">
        <Input placeholder="Search case or lot" aria-label="Search cases" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="max-w-xs" />
        <Select aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}><option value="">All statuses</option>{["pending_approval", "awaiting_recipient", "accepted", "pickup_scheduled", "in_transit", "completed", "rejected", "cancelled"].map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}</Select>
        <Select aria-label="Rung" value={rung} onChange={(e) => { setRung(e.target.value); setPage(1); }}><option value="">Any rung</option>{["R1", "R2", "R3", "R4"].map((r) => <option key={r}>{r}</option>)}</Select>
      </div>
      <Card className="overflow-x-auto">
        <QueryBoundary q={cases} isEmpty={(d) => d.items.length === 0} empty={{ title: "No recovery cases", body: "Open a case from Live Operations when a lot is at risk." }}>
          {(d) => (
            <table className="w-full min-w-[44rem] text-sm"><caption className="sr-only">Recovery cases</caption>
              <thead className="border-b border-border text-left text-xs text-muted"><tr>{["Case", "Product", "Quantity", "Freshness", "Time left", "Rung", "Status"].map((h) => <th key={h} scope="col" className="px-4 py-2.5 font-medium">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-border">
                {d.items.map((c) => (
                  <tr key={c.id} className="hover:bg-subtle/50">
                    <td className="px-4 py-3"><Link href={`/recovery/${c.id}`} className="font-medium text-info hover:underline">{c.case_number}</Link></td>
                    <td className="px-4 py-3">{c.lot.product.name}<span className="block text-xs text-muted">{c.lot.lot_code}</span></td><td className="px-4 py-3 tabular">{fmtKg(c.quantity_kg)}</td>
                    <td className="px-4 py-3"><FreshBadge state={c.lot.freshness.state} /></td><td className="px-4 py-3 tabular">{fmtDuration(c.lot.freshness.remaining_minutes)}</td>
                    <td className="px-4 py-3">{c.selected_rung ?? "–"}</td><td className="px-4 py-3"><StatusBadge status={c.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </QueryBoundary>
      </Card>
      {cases.data && <Pager page={cases.data.page} pages={cases.data.pages} total={cases.data.total} onPage={setPage} />}
    </>
  );
}
export default function Page() { return <Suspense><List /></Suspense>; }
