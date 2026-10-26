"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { FreshBadge } from "@/components/recovery/signature";
import { Button, Card, Dialog, Field, Input, PageHeader, Select, Textarea } from "@/components/ui";
import { QueryBoundary } from "@/components/ui/query-state";
import { useLots } from "@/hooks/queries";
import { ApiError, errorMessage, get, post } from "@/lib/api";
import { cn, fmtDateTime, fmtDuration, fmtKg, titleCase } from "@/lib/utils";
import { useAuth } from "@/providers";
import { can } from "@/lib/rbac";
import type { Lot } from "@/types/api";
import { Pager } from "@/components/ui/pager";

const schema = z.object({
  plant_id: z.string().min(1, "Choose a plant."), product_id: z.string().min(1, "Choose a product."),
  lot_code: z.string().trim().min(3, "Use at least 3 characters.").regex(/^[A-Za-z0-9\-_.]+$/, "Letters, numbers, - _ . only."),
  quantity_kg: z.coerce.number({ invalid_type_error: "Enter a quantity." }).positive("Must be more than 0.").max(100000),
  hours_safe: z.coerce.number({ invalid_type_error: "Enter hours." }).positive("Must be more than 0.").max(24 * 365),
  storage: z.enum(["ambient", "chilled", "frozen"]),
});
type V = z.infer<typeof schema>;

function NewLot() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const plants = useQuery({ queryKey: ["plants"], queryFn: () => get<{ id: string; name: string }[]>("/plants") });
  const products = useQuery({ queryKey: ["products"], queryFn: () => get<{ id: string; name: string }[]>("/products") });
  const f = useForm<V>({ resolver: zodResolver(schema), defaultValues: { storage: "chilled" } });
  const e = f.formState.errors;
  const m = useMutation({
    mutationFn: (v: V) => { const now = new Date(); return post("/lots", { plant_id: v.plant_id, product_id: v.product_id, lot_code: v.lot_code, quantity_kg: v.quantity_kg, storage: v.storage, produced_at: now.toISOString(), safe_until: new Date(now.getTime() + v.hours_safe * 3600e3).toISOString() }); },
    onSuccess: () => { toast.success("Lot registered."); qc.invalidateQueries({ queryKey: ["lots"] }); f.reset({ storage: "chilled" }); setOpen(false); },
    onError: (x) => { if (x instanceof ApiError && x.details) x.details.forEach((d) => f.setError(d.field as keyof V, { message: d.message })); toast.error(errorMessage(x)); },
  });
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild><Button><Plus className="h-4 w-4" aria-hidden />Register lot</Button></Dialog.Trigger>
      <Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-50 bg-black/45" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-surface p-5 shadow-pop">
          <Dialog.Title className="font-display text-lg font-semibold">Register a lot</Dialog.Title><Dialog.Description className="text-sm text-muted">Record surplus stock and how long it stays recoverable.</Dialog.Description>
          <form onSubmit={f.handleSubmit((v) => m.mutate(v))} noValidate className="mt-4 space-y-3">
            <Field label="Plant" error={e.plant_id?.message}><Select className="w-full" {...f.register("plant_id")}><option value="">Choose…</option>{plants.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
            <Field label="Product" error={e.product_id?.message}><Select className="w-full" {...f.register("product_id")}><option value="">Choose…</option>{products.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</Select></Field>
            <Field label="Lot code" error={e.lot_code?.message}><Input {...f.register("lot_code")} /></Field>
            <div className="grid grid-cols-2 gap-3">
              <Field label="Quantity (kg)" error={e.quantity_kg?.message}><Input type="number" inputMode="decimal" step="any" {...f.register("quantity_kg")} /></Field>
              <Field label="Safe window (hours)" error={e.hours_safe?.message} hint="From now"><Input type="number" inputMode="decimal" step="any" {...f.register("hours_safe")} /></Field>
            </div>
            <Field label="Storage" error={e.storage?.message}><Select className="w-full" {...f.register("storage")}><option value="chilled">Chilled</option><option value="ambient">Ambient</option><option value="frozen">Frozen</option></Select></Field>
            <div className="flex justify-end gap-2 pt-2"><Dialog.Close asChild><Button type="button" variant="secondary">Cancel</Button></Dialog.Close><Button type="submit" loading={m.isPending}>Save lot</Button></div>
          </form>
        </Dialog.Content></Dialog.Portal>
    </Dialog.Root>
  );
}

function AdjustLot({ lot }: { lot: Lot }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [delta, setDelta] = useState(""); const [reason, setReason] = useState("");
  const d = Number(delta);
  const problem = !delta || Number.isNaN(d) || d === 0 ? "Enter a non-zero change in kg." : lot.quantity_kg + d <= 0 ? "Stock can't reach zero or below." : reason.trim().length < 5 ? "Give a reason (at least 5 characters)." : "";
  const m = useMutation({
    mutationFn: () => post(`/lots/${lot.id}/adjust`, { delta_kg: d, reason: reason.trim() }),
    onSuccess: () => { toast.success("Stock adjusted and recorded in the audit log."); qc.invalidateQueries({ queryKey: ["lots"] }); setOpen(false); setDelta(""); setReason(""); },
    onError: (x) => toast.error(errorMessage(x)),
  });
  const hist = useQuery({ queryKey: ["lot-history", lot.id], enabled: open, queryFn: () => get<{ seq: number; summary: string; created_at: string }[]>(`/lots/${lot.id}/history`) });
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild><Button variant="secondary" size="sm" aria-label={`Adjust stock for ${lot.lot_code}`}>Adjust</Button></Dialog.Trigger>
      <Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-50 bg-black/45" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-surface p-5 shadow-pop">
          <Dialog.Title className="font-display text-lg font-semibold">Adjust {lot.lot_code}</Dialog.Title>
          <Dialog.Description className="text-sm text-muted">Current stock {fmtKg(lot.quantity_kg)}. Use a negative number to remove stock. Reserved quantities can&apos;t be removed.</Dialog.Description>
          <div className="mt-4 space-y-3">
            <Field label="Change (kg)"><Input type="number" inputMode="decimal" step="any" value={delta} onChange={(e) => setDelta(e.target.value)} /></Field>
            <Field label="Reason" error={delta && problem ? problem : undefined}><Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={3} /></Field>
            {hist.data && hist.data.length > 0 && <div><p className="text-xs font-medium text-muted">Lot history</p><ul className="mt-1 max-h-32 space-y-1 overflow-y-auto text-xs">{hist.data.map((h) => <li key={h.seq}>{h.summary}</li>)}</ul></div>}
            <div className="flex justify-end gap-2 pt-2"><Dialog.Close asChild><Button type="button" variant="secondary">Cancel</Button></Dialog.Close><Button disabled={!!problem} loading={m.isPending} onClick={() => m.mutate()}>Apply adjustment</Button></div>
          </div>
        </Dialog.Content></Dialog.Portal>
    </Dialog.Root>
  );
}

export default function Inventory() {
  const { user } = useAuth();
  const [q, setQ] = useState(""); const [status, setStatus] = useState(""); const [urgency, setUrgency] = useState(""); const [sort, setSort] = useState("time_to_loss"); const [page, setPage] = useState(1);
  const qs = new URLSearchParams({ page: String(page), page_size: "15", sort, ...(q && { q }), ...(status && { status }), ...(urgency && { urgency }) }).toString();
  const lots = useLots(qs);
  const canWrite = can(user?.permissions, "lots:write");
  const canAdjust = can(user?.permissions, "lots:adjust");
  return (
    <>
      <PageHeader title="Inventory" sub="Every lot with its freshness window." actions={canWrite ? <NewLot /> : undefined} />
      <div className="mb-4 flex flex-wrap gap-2">
        <Input placeholder="Search lot or product" aria-label="Search" value={q} onChange={(e) => { setQ(e.target.value); setPage(1); }} className="max-w-xs" />
        <Select aria-label="Status" value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}><option value="">Active lots</option><option value="recovered">Recovered</option><option value="wasted">Wasted</option></Select>
        <Select aria-label="Freshness" value={urgency} onChange={(e) => { setUrgency(e.target.value); setPage(1); }}><option value="">Any freshness</option><option value="LOSS_IMMINENT">Loss imminent</option><option value="ACT_SOON">Act soon</option><option value="SAFE">Safe</option></Select>
        <Select aria-label="Sort" value={sort} onChange={(e) => setSort(e.target.value)}><option value="time_to_loss">Time to loss</option><option value="quantity">Quantity</option><option value="created">Newest</option></Select>
      </div>
      <Card className="overflow-x-auto">
        <QueryBoundary q={lots} isEmpty={(d) => d.items.length === 0} empty={{ title: "No lots found", body: "Register a lot or change the filters." }}>
          {(d) => (
            <table className="w-full min-w-[40rem] text-sm">
              <caption className="sr-only">Inventory lots</caption>
              <thead className="border-b border-border text-left text-xs text-muted"><tr>{["Lot", "Product", "Plant", "Quantity", "Freshness", "Time left", "Status", ...(canAdjust ? ["Actions"] : [])].map((h) => <th key={h} scope="col" className="px-4 py-2.5 font-medium">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-border">
                {d.items.map((l) => (
                  <tr key={l.id}>
                    <td className="px-4 py-3 font-medium tabular">{l.lot_code}</td><td className="px-4 py-3">{l.product.name}<span className="block text-xs text-muted">{titleCase(l.storage)}</span></td>
                    <td className="px-4 py-3 text-muted">{l.plant.city}</td><td className="px-4 py-3 tabular">{fmtKg(l.quantity_kg)}</td>
                    <td className="px-4 py-3"><FreshBadge state={l.freshness.state} /></td><td className={cn("px-4 py-3 tabular", l.freshness.state === "LOSS_IMMINENT" && "font-medium text-danger")}>{fmtDuration(l.freshness.remaining_minutes)}</td>
                    <td className="px-4 py-3 text-muted">{titleCase(l.status)}</td>
                    {canAdjust && <td className="px-4 py-3">{["available", "in_recovery"].includes(l.status) && <AdjustLot lot={l} />}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </QueryBoundary>
      </Card>
      {lots.data && <Pager page={lots.data.page} pages={lots.data.pages} total={lots.data.total} onPage={setPage} />}
    </>
  );
}
