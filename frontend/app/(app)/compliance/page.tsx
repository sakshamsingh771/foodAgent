"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, Plus, ShieldCheck, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { Badge, Button, Card, CardHeader, Dialog, Field, Input, PageHeader, Select } from "@/components/ui";
import { QueryBoundary } from "@/components/ui/query-state";
import { ApiError, download, errorMessage, get, upload } from "@/lib/api";
import { fmtDateTime, titleCase } from "@/lib/utils";
import { useAuth } from "@/providers";
import type { AuditEntry, Page } from "@/types/api";
import { Pager } from "@/components/ui/pager";

interface Doc { id: string; title: string; doc_type: string; issuer: string; reference: string; valid_until: string | null; status: string; has_file: boolean; original_name: string | null }
const TONE: Record<string, "safe" | "warn" | "danger" | "neutral"> = { valid: "safe", expiring_soon: "warn", expired: "danger", no_expiry: "neutral" };

function AddDoc() {
  const qc = useQueryClient(); const [open, setOpen] = useState(false);
  const m = useMutation({ mutationFn: (fd: FormData) => upload("/compliance/documents", fd), onSuccess: () => { toast.success("Document added."); qc.invalidateQueries({ queryKey: ["docs"] }); qc.invalidateQueries({ queryKey: ["audit"] }); setOpen(false); }, onError: (e) => toast.error(e instanceof ApiError && e.details?.length ? `${e.details[0].field}: ${e.details[0].message}` : errorMessage(e)) });
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild><Button variant="secondary"><Plus className="h-4 w-4" aria-hidden />Add document</Button></Dialog.Trigger>
      <Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-50 bg-black/45" /><Dialog.Content className="fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-border bg-surface p-5 shadow-pop">
        <Dialog.Title className="font-display text-lg font-semibold">Add a compliance document</Dialog.Title><Dialog.Description className="text-sm text-muted">Licences, labels, certificates and SOPs.</Dialog.Description>
        <form className="mt-4 space-y-3" onSubmit={(e) => { e.preventDefault(); const fd = new FormData(e.currentTarget); if (!(fd.get("file") as File)?.size) fd.delete("file"); if (!fd.get("valid_until")) fd.delete("valid_until"); m.mutate(fd); }}>
          <Field label="Title"><Input name="title" required minLength={2} /></Field>
          <Field label="Type"><Select name="doc_type" className="w-full" defaultValue="license">{["license", "label", "certificate", "sop", "other"].map((t) => <option key={t} value={t}>{titleCase(t)}</option>)}</Select></Field>
          <div className="grid grid-cols-2 gap-3"><Field label="Issuer"><Input name="issuer" /></Field><Field label="Reference"><Input name="reference" /></Field></div>
          <Field label="Valid until" hint="Leave empty if it doesn't expire"><Input name="valid_until" type="date" /></Field>
          <Field label="File (optional)" hint="JPG, PNG, PDF, CSV or TXT up to 10 MB"><Input name="file" type="file" accept=".jpg,.jpeg,.png,.pdf,.csv,.txt" className="py-2" /></Field>
          <div className="flex justify-end gap-2 pt-2"><Dialog.Close asChild><Button type="button" variant="secondary">Cancel</Button></Dialog.Close><Button type="submit" loading={m.isPending}>Save</Button></div>
        </form></Dialog.Content></Dialog.Portal>
    </Dialog.Root>
  );
}

export default function Compliance() {
  const { user } = useAuth(); const [page, setPage] = useState(1);
  const canAudit = !!user && ["ADMIN", "RECOVERY_MANAGER", "AUDITOR"].includes(user.role); const canWrite = !!user && ["ADMIN", "OPERATIONS_MANAGER"].includes(user.role);
  const docs = useQuery({ queryKey: ["docs"], queryFn: () => get<Doc[]>("/compliance/documents") });
  const audit = useQuery({ queryKey: ["audit", page], enabled: canAudit, queryFn: () => get<Page<AuditEntry>>(`/audit?page=${page}&page_size=15`), placeholderData: (p) => p });
  const verify = useQuery({ queryKey: ["audit-verify"], enabled: canAudit, queryFn: () => get<{ valid: boolean; checked: number; first_invalid_seq: number | null; method: string }>("/audit/verify") });
  return (
    <>
      <PageHeader title="Compliance & audit" sub="Documents, approvals and a tamper-evident record of every critical action." actions={<>{canWrite && <AddDoc />}{canAudit && <Button variant="secondary" onClick={() => download("/audit/export.csv", "foodagent-audit.csv").catch((e) => toast.error(errorMessage(e)))}><Download className="h-4 w-4" aria-hidden />Audit CSV</Button>}</>} />
      {canAudit && verify.data && (
        <Card className={`mb-5 flex items-start gap-3 p-4 ${verify.data.valid ? "" : "border-danger"}`} role="status">
          {verify.data.valid ? <ShieldCheck className="mt-0.5 h-5 w-5 text-safe" aria-hidden /> : <ShieldAlert className="mt-0.5 h-5 w-5 text-danger" aria-hidden />}
          <div><p className="font-medium">{verify.data.valid ? `Audit chain verified: ${verify.data.checked} records intact` : `Audit chain broken at record ${verify.data.first_invalid_seq}`}</p><p className="text-xs text-muted">{verify.data.method}. Each record includes the hash of the one before, so edits are detectable. This is not a blockchain.</p></div>
        </Card>
      )}
      <Card className="mb-5 overflow-x-auto"><CardHeader title="Documents" />
        <QueryBoundary q={docs} isEmpty={(d) => d.length === 0} empty={{ title: "No documents yet", body: "Add licences, label templates and SOPs." }}>
          {(rows) => <table className="w-full min-w-[36rem] text-sm"><caption className="sr-only">Compliance documents</caption><thead className="border-b border-border text-left text-xs text-muted"><tr>{["Document", "Type", "Reference", "Valid until", "Status", ""].map((h) => <th key={h} scope="col" className="px-4 py-2.5 font-medium">{h}</th>)}</tr></thead>
            <tbody className="divide-y divide-border">{rows.map((d) => <tr key={d.id}><td className="px-4 py-3 font-medium">{d.title}<span className="block text-xs font-normal text-muted">{d.issuer}</span></td><td className="px-4 py-3">{titleCase(d.doc_type)}</td><td className="px-4 py-3 tabular text-muted">{d.reference || "–"}</td><td className="px-4 py-3 tabular">{d.valid_until ?? "No expiry"}</td><td className="px-4 py-3"><Badge tone={TONE[d.status]}>{titleCase(d.status)}</Badge></td><td className="px-4 py-3">{d.has_file && <button className="min-h-9 text-info hover:underline" onClick={() => download(`/compliance/documents/${d.id}/file`, d.original_name || "document").catch((e) => toast.error(errorMessage(e)))}>Download</button>}</td></tr>)}</tbody></table>}
        </QueryBoundary></Card>
      {canAudit && <Card><CardHeader title="Audit trail" />
        <QueryBoundary q={audit} isEmpty={(d) => d.items.length === 0} empty={{ title: "No audit events yet" }}>
          {(d) => <ol className="divide-y divide-border">{d.items.map((e) => <li key={e.id} className="grid gap-1 px-4 py-3 sm:grid-cols-[9rem_1fr]"><span className="text-xs tabular text-muted">#{e.seq} · {fmtDateTime(e.created_at)}</span><div><p className="text-sm">{e.summary}</p><p className="text-xs text-muted">{e.actor} · <code>{e.action}</code> · <span title={e.hash}>{e.hash.slice(0, 10)}…</span></p></div></li>)}</ol>}
        </QueryBoundary></Card>}
      {audit.data && <Pager page={audit.data.page} pages={audit.data.pages} total={audit.data.total} onPage={setPage} />}
    </>
  );
}
