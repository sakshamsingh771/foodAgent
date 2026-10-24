"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Languages } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { FreshnessRing, StatusBadge } from "@/components/recovery/signature";
import { Badge, Button, Card, ConfirmDialog, PageHeader, Textarea } from "@/components/ui";
import { QueryBoundary } from "@/components/ui/query-state";
import { useRecipients } from "@/hooks/queries";
import { errorMessage, get, post } from "@/lib/api";
import { fmtDateTime, fmtKg, fmtTime } from "@/lib/utils";
import { useAuth } from "@/providers";
import type { Freshness } from "@/types/api";

interface Offer { id: string; case_number: string; status: string; rung: string; product: string; quantity_kg: number; storage: string; plant_city: string; safe_until: string; freshness: Freshness; note: string; pickup: { id: string; status: string; scheduled_for: string; eta: string; logistics_user: { name: string } | null } | null }

const T = {
  en: { title: "Offers for you", sub: "Lots offered to your organization.", accept: "Accept", decline: "Decline", why: "Why can't you take it?", confirm: "Confirm handover", none: "No offers right now", noneBody: "New offers will appear here as soon as they're approved.", qty: "Quantity", pickup: "Pickup", window: "Use-by window", declineTitle: "Decline this lot?", declineBody: "Tell us why so we can find another option quickly.", back: "Cancel", send: "Decline lot", received: "Received in full?", mark: "Yes, confirm received", acceptDone: "Thank you. We've let the plant know.", cold: "Storage" },
  hi: { title: "आपके लिए प्रस्ताव", sub: "आपके संगठन को दिए गए खाद्य लॉट।", accept: "स्वीकार करें", decline: "अस्वीकार करें", why: "आप क्यों नहीं ले सकते?", confirm: "हैंडओवर की पुष्टि करें", none: "अभी कोई प्रस्ताव नहीं", noneBody: "स्वीकृत होते ही नए प्रस्ताव यहाँ दिखेंगे।", qty: "मात्रा", pickup: "पिकअप", window: "उपयोग की समय-सीमा", declineTitle: "यह लॉट अस्वीकार करें?", declineBody: "कारण बताएँ ताकि हम जल्दी दूसरा विकल्प ढूँढ सकें।", back: "रद्द करें", send: "लॉट अस्वीकार करें", received: "क्या पूरा माल मिला?", mark: "हाँ, प्राप्ति की पुष्टि करें", acceptDone: "धन्यवाद। हमने प्लांट को सूचित कर दिया है।", cold: "भंडारण" },
};

interface AllocOffer { id: string; case_id: string; quantity_kg: number; rung: string; status: string; eta: string | null }

function AllocationOffers() {
  const qc = useQueryClient(); const [kg, setKg] = useState<Record<string, string>>({});
  const q = useQuery({ queryKey: ["recipient-allocs"], queryFn: () => get<AllocOffer[]>("/recipient/allocations") });
  const respond = useMutation({
    mutationFn: (v: { id: string; accept: boolean; accepted_kg?: number; reason?: string }) => post(`/recipient/allocations/${v.id}/respond`, { accept: v.accept, accepted_kg: v.accepted_kg, reason: v.reason }),
    onSuccess: () => { toast.success("Response recorded."); qc.invalidateQueries({ queryKey: ["recipient-allocs"] }); }, onError: (e) => toast.error(errorMessage(e)),
  });
  if (!q.data?.length) return null;
  return (
    <section aria-label="Split-lot offers" className="mb-6 space-y-3">
      <h2 className="text-sm font-semibold">Split-lot offers</h2>
      {q.data.map((o) => (
        <Card key={o.id} className="p-4">
          <div className="flex flex-wrap items-center justify-between gap-2"><p className="font-medium tabular">{fmtKg(o.quantity_kg)} via {o.rung} <StatusBadge status={o.status} /></p>{o.eta && <span className="text-xs text-muted">Est. {fmtDateTime(o.eta)}</span>}</div>
          {o.status === "offered" && <div className="mt-3 flex flex-wrap items-end gap-2">
            <Button loading={respond.isPending} onClick={() => respond.mutate({ id: o.id, accept: true })}>Accept all</Button>
            <input aria-label="Accept only this many kg" className="h-10 w-28 rounded-md border border-border bg-surface px-2 text-sm" type="number" min={1} max={o.quantity_kg} placeholder="Partial kg" value={kg[o.id] ?? ""} onChange={(e) => setKg((s) => ({ ...s, [o.id]: e.target.value }))} />
            <Button variant="secondary" disabled={!kg[o.id]} onClick={() => respond.mutate({ id: o.id, accept: true, accepted_kg: Number(kg[o.id]) })}>Accept part</Button>
            <Button variant="secondary" onClick={() => respond.mutate({ id: o.id, accept: false, reason: "Cannot take this lot" })}>Decline</Button></div>}
        </Card>))}
    </section>
  );
}

function Inbox() {
  const { user } = useAuth(); const qc = useQueryClient();
  const [lang, setLang] = useState<"en" | "hi">(user?.language === "hi" ? "hi" : "en"); const t = T[lang];
  const q = useQuery({ queryKey: ["recipient-cases"], queryFn: () => get<Offer[]>("/recipient/cases") });
  const [declining, setDeclining] = useState<Offer | null>(null); const [reason, setReason] = useState("");
  const refresh = () => qc.invalidateQueries({ queryKey: ["recipient-cases"] });
  const respond = useMutation({ mutationFn: (v: { id: string; accept: boolean; reason?: string }) => post(`/recipient/cases/${v.id}/respond`, { accept: v.accept, reason: v.reason }), onSuccess: (_d, v) => { toast.success(v.accept ? t.acceptDone : "OK"); setDeclining(null); setReason(""); refresh(); }, onError: (e) => toast.error(errorMessage(e)) });
  const handover = useMutation({ mutationFn: (id: string) => post(`/pickups/${id}/handover`, {}), onSuccess: () => { toast.success("✓"); refresh(); }, onError: (e) => toast.error(errorMessage(e)) });
  return (
    <>
      <PageHeader title={t.title} sub={t.sub} actions={<Button variant="secondary" onClick={() => setLang(lang === "en" ? "hi" : "en")} aria-label="Switch language"><Languages className="h-4 w-4" aria-hidden />{lang === "en" ? "हिन्दी" : "English"}</Button>} />
      <AllocationOffers />
      <QueryBoundary q={q} isEmpty={(d) => d.length === 0} empty={{ title: t.none, body: t.noneBody }}>
        {(offers) => (
          <div className="space-y-3">{offers.map((o) => (
            <Card key={o.id} className="p-4">
              <div className="flex gap-4">
                <FreshnessRing percent={o.freshness.percent} remainingMinutes={o.freshness.remaining_minutes} state={o.freshness.state} size={88} compact />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2"><p className="font-semibold">{o.product}</p><StatusBadge status={o.status} /></div>
                  <p className="mt-1 text-sm text-muted">{t.qty}: <span className="tabular text-fg">{fmtKg(o.quantity_kg)}</span> · {o.plant_city} · {t.cold}: {o.storage}</p>
                  <p className="text-sm text-muted">{t.window}: {fmtDateTime(o.safe_until)}</p>
                  {o.pickup && <p className="text-sm text-muted">{t.pickup}: {fmtDateTime(o.pickup.scheduled_for)}{o.pickup.logistics_user ? ` · ${o.pickup.logistics_user.name}` : ""} · <StatusBadge status={o.pickup.status} /></p>}
                </div>
              </div>
              {o.status === "awaiting_recipient" && <div className="mt-4 grid grid-cols-2 gap-2"><Button loading={respond.isPending} onClick={() => respond.mutate({ id: o.id, accept: true })}>{t.accept}</Button><Button variant="secondary" onClick={() => setDeclining(o)}>{t.decline}</Button></div>}
              {o.pickup?.status === "arrived" && <Button className="mt-4 w-full" loading={handover.isPending} onClick={() => handover.mutate(o.pickup!.id)}>{t.confirm}</Button>}
              <p className="mt-3 text-[11px] text-muted">{o.note}</p>
            </Card>
          ))}</div>
        )}
      </QueryBoundary>
      <ConfirmDialog open={!!declining} onOpenChange={(o) => !o && setDeclining(null)} title={t.declineTitle} body={t.declineBody} confirmLabel={t.send} danger loading={respond.isPending}
        onConfirm={() => reason.trim() ? declining && respond.mutate({ id: declining.id, accept: false, reason }) : toast.error(t.why)}>
        <label className="block text-sm font-medium">{t.why}<Textarea className="mt-1.5" value={reason} onChange={(e) => setReason(e.target.value)} maxLength={300} /></label>
      </ConfirmDialog>
    </>
  );
}

function Directory() {
  const q = useRecipients();
  return (
    <>
      <PageHeader title="Recipients" sub="Organizations that can take recovered food. Acceptance rates come from stored history." />
      <QueryBoundary q={q} isEmpty={(d) => d.length === 0} empty={{ title: "No recipients yet" }}>
        {(rows) => <div className="grid gap-3 md:grid-cols-2">{rows.map((r) => (
          <Card key={r.id} className="p-4"><div className="flex items-start justify-between gap-2"><div><p className="font-semibold">{r.name}</p><p className="text-xs text-muted">{r.city} · {r.distance_km} km away</p></div><div className="flex gap-1">{r.accepts_rungs.map((x) => <Badge key={x} tone="info">{x}</Badge>)}</div></div>
            <dl className="mt-3 grid grid-cols-3 gap-2 text-sm"><div><dt className="text-xs text-muted">Past acceptance</dt><dd className="font-semibold tabular">{Math.round(r.acceptance_rate * 100)}%</dd></div><div><dt className="text-xs text-muted">Capacity</dt><dd className="font-semibold tabular">{fmtKg(r.capacity_kg)}</dd></div><div><dt className="text-xs text-muted">Phone</dt><dd className="tabular">{r.phone}</dd></div></dl></Card>
        ))}</div>}
      </QueryBoundary>
    </>
  );
}
export default function Page() { const { user } = useAuth(); return user?.role === "RECIPIENT" ? <Inbox /> : <Directory />; }
