"use client";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { toast } from "sonner";
import { FreshBadge, FreshnessRing, StatusBadge } from "@/components/recovery/signature";
import { Button, Card, Input, PageHeader, Select } from "@/components/ui";
import { Pager } from "@/components/ui/pager";
import { QueryBoundary } from "@/components/ui/query-state";
import { useLots } from "@/hooks/queries";
import { errorMessage, post } from "@/lib/api";
import { fmtKg, fmtTime } from "@/lib/utils";
import { useAuth, useLive } from "@/providers";

export default function Operations() {
  const { user } = useAuth();
  const live = useLive();
  const qc = useQueryClient();
  const [q, setQ] = useState(""); const [urgency, setUrgency] = useState("AT_RISK"); const [page, setPage] = useState(1);
  const qs = new URLSearchParams({ page: String(page), page_size: "12", sort: "time_to_loss", ...(q ? { q } : {}), ...(urgency ? { urgency } : {}) }).toString();
  const lots = useLots(qs);
  const open = useMutation({
    mutationFn: (lot_id: string) => post<{ id: string }>("/recovery-cases", { lot_id }),
    onSuccess: () => { toast.success("Recovery case opened. A manager can now review the plan."); qc.invalidateQueries({ queryKey: ["lots"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const canOpen = user && ["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER"].includes(user.role);
  return (
    <>
      <PageHeader title="Live Operations" sub="Lots closest to losing their recovery window come first." actions={<span className="inline-flex min-h-11 items-center gap-2 rounded-md border border-border bg-surface px-3 text-sm" role="status"><span className={`h-2 w-2 rounded-full ${live === "live" ? "bg-safe" : "bg-warn"}`} />{live === "live" ? "Live" : "Reconnecting…"}</span>} />
      <div className="mb-4 flex flex-wrap gap-2">
        <Input placeholder="Search lot or product" aria-label="Search lots" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="max-w-xs" />
        <Select aria-label="Urgency" value={urgency} onChange={(e) => { setUrgency(e.target.value); setPage(1); }}>
          <option value="AT_RISK">At risk</option><option value="LOSS_IMMINENT">Loss imminent</option><option value="ACT_SOON">Act soon</option><option value="SAFE">Safe</option><option value="">All active</option>
        </Select>
      </div>
      <QueryBoundary q={lots} isEmpty={(d) => d.items.length === 0} empty={{ title: "No lots match", body: "Try a different filter. Nothing at risk right now is good news." }}>
        {(d) => (
          <>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {d.items.map((l) => (
                <Card key={l.id} className="flex gap-4 p-4">
                  <FreshnessRing percent={l.freshness.percent} remainingMinutes={l.freshness.remaining_minutes} state={l.freshness.state} size={92} compact />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-1.5"><FreshBadge state={l.freshness.state} />{l.is_simulated && <span className="text-[11px] text-muted">Simulated</span>}</div>
                    <p className="mt-1 truncate font-semibold">{l.product.name}</p>
                    <p className="text-xs text-muted tabular">{l.lot_code} · {fmtKg(l.quantity_kg)} · {l.plant.city}</p>
                    <p className="mt-1 text-xs text-muted">Window ends {fmtTime(l.safe_until)}</p>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      {l.open_case ? <><StatusBadge status={l.open_case.status} /><Link href={`/recovery/${l.open_case.id}`} className="text-sm font-medium text-info hover:underline">{l.open_case.case_number}</Link></>
                        : canOpen && l.status === "available" ? <Button size="sm" loading={open.isPending && open.variables === l.id} onClick={() => open.mutate(l.id)}>Open recovery case</Button> : <span className="text-xs text-muted">No case</span>}
                    </div>
                  </div>
                </Card>
              ))}
            </div>
            <Pager page={d.page} pages={d.pages} total={d.total} onPage={setPage} />
          </>
        )}
      </QueryBoundary>
    </>
  );
}
