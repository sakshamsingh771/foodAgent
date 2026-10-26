"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Badge, Button, Card, ConfirmDialog, Field, Input, PageHeader, Select, Textarea } from "@/components/ui";
import { QueryBoundary } from "@/components/ui/query-state";
import { errorMessage, get, patch, post } from "@/lib/api";
import { fmtDateTime, titleCase } from "@/lib/utils";
import { useAuth } from "@/providers";
import type { InvitationRow, User } from "@/types/api";

const ROLES = ["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER", "LOGISTICS", "AUDITOR"];
const STATUS_TONE = { ACTIVE: "safe", PENDING: "warn", REJECTED: "danger", DISABLED: "danger" } as const;
const INV_TONE = { pending: "info", used: "safe", expired: "neutral", revoked: "danger" } as const;
interface Overview { users_by_role: Record<string, { active: number; inactive: number }>; pending_approvals: number; pending_users?: number; exception_counts: Record<string, number>; recent_security_events: { seq: number; summary: string; created_at: string }[] }
type Action = { u: User; kind: "role" | "deactivate" | "reactivate" | "approve" | "reject"; role?: string };

export default function UsersPage() {
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const [q, setQ] = useState(""); const [role, setRole] = useState(""); const [status, setStatus] = useState("");
  const qs = new URLSearchParams(Object.entries({ q: q.trim(), role, status }).filter(([, v]) => v)).toString();
  const users = useQuery({ queryKey: ["users", qs], queryFn: () => get<User[]>(`/users${qs ? `?${qs}` : ""}`) });
  const invites = useQuery({ queryKey: ["invitations"], queryFn: () => get<InvitationRow[]>("/invitations") });
  const overview = useQuery({ queryKey: ["admin-overview"], queryFn: () => get<Overview>("/admin/overview") });
  const refresh = () => { for (const k of ["users", "invitations", "admin-overview"]) qc.invalidateQueries({ queryKey: [k] }); };

  const [act, setAct] = useState<Action | null>(null);
  const [reason, setReason] = useState("");
  const decide = useMutation({
    mutationFn: () => {
      const a = act!; const r = reason.trim();
      if (a.kind === "approve") return post(`/users/${a.u.id}/approve`, { reason: r || undefined });
      if (a.kind === "reject") return post(`/users/${a.u.id}/reject`, { reason: r || undefined });
      return patch(`/users/${a.u.id}`, { role: a.kind === "role" ? a.role : undefined, is_active: a.kind === "deactivate" ? false : a.kind === "reactivate" ? true : undefined, reason: r });
    },
    onSuccess: () => { toast.success("Done. The change is recorded in the audit log."); setAct(null); setReason(""); refresh(); },
    onError: (e) => toast.error(errorMessage(e)),
  });

  const [email, setEmail] = useState(""); const [invRole, setInvRole] = useState("LOGISTICS"); const [needsApproval, setNeedsApproval] = useState(false);
  const [created, setCreated] = useState<InvitationRow | null>(null);
  const invite = useMutation({
    mutationFn: () => post<InvitationRow>("/invitations", { email: email.trim(), role: invRole, requires_approval: needsApproval }),
    onSuccess: (r) => { setCreated(r); setEmail(""); toast.success("Invitation created."); refresh(); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const revoke = useMutation({ mutationFn: (id: string) => post(`/invitations/${id}/revoke`), onSuccess: () => { toast.success("Invitation revoked."); refresh(); }, onError: (e) => toast.error(errorMessage(e)) });

  const needsReason = act && !["approve", "reject"].includes(act.kind);
  const title = !act ? "" : act.kind === "approve" ? `Approve ${act.u.full_name}?` : act.kind === "reject" ? `Reject ${act.u.full_name}?` : act.kind === "deactivate" ? `Deactivate ${act.u.full_name}?` : act.kind === "reactivate" ? `Reactivate ${act.u.full_name}?` : `Change role of ${act.u.full_name}?`;
  const body = !act ? "" : act.kind === "approve" ? `They receive the ${titleCase((act.u.requested_role || "").toLowerCase())} role and can sign in.` : act.kind === "reject" ? "They will not be able to sign in." : act.kind === "role" ? `Their role becomes ${titleCase((act.role || "").toLowerCase())} and access changes immediately.` : act.kind === "deactivate" ? "They are signed out and can no longer log in." : "They can log in again.";

  return (
    <>
      <PageHeader title="Users & roles" sub="Invite staff, approve requests, assign roles and activate or deactivate accounts for your organization." />
      {overview.data && (
        <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Card className="p-4"><p className="text-xs uppercase text-muted">Pending accounts</p><p className="font-display text-3xl font-semibold">{overview.data.pending_users ?? 0}</p></Card>
          <Card className="p-4"><p className="text-xs uppercase text-muted">Cases awaiting approval</p><p className="font-display text-3xl font-semibold">{overview.data.pending_approvals}</p></Card>
          <Card className="p-4"><p className="text-xs uppercase text-muted">Overdue pickups</p><p className="font-display text-3xl font-semibold">{overview.data.exception_counts.overdue_pickups}</p></Card>
          <Card className="p-4"><p className="text-xs uppercase text-muted">Active users</p><p className="font-display text-3xl font-semibold">{Object.values(overview.data.users_by_role).reduce((a, r) => a + r.active, 0)}</p></Card>
        </div>
      )}

      <Card className="mb-5 p-4">
        <h2 className="font-display text-base font-semibold">Invite a team member</h2>
        <p className="text-sm text-muted">The invitation is bound to this email address and role, expires in 7 days and works once. Email delivery isn&apos;t configured, so copy the link and send it yourself.</p>
        <form className="mt-3 grid gap-3 sm:grid-cols-[1fr_12rem_auto] sm:items-end" onSubmit={(ev) => { ev.preventDefault(); invite.mutate(); }}>
          <Field label="Email"><Input type="email" required value={email} onChange={(ev) => setEmail(ev.target.value)} autoComplete="off" /></Field>
          <Field label="Role"><Select value={invRole} onChange={(ev) => setInvRole(ev.target.value)}>{ROLES.map((r) => <option key={r} value={r}>{titleCase(r.toLowerCase())}</option>)}</Select></Field>
          <Button type="submit" loading={invite.isPending} disabled={!email.trim()}>Create invitation</Button>
        </form>
        <label className="mt-2 flex min-h-9 items-center gap-2 text-sm"><input type="checkbox" checked={needsApproval} onChange={(ev) => setNeedsApproval(ev.target.checked)} />Require admin approval after they register</label>
        {created?.invite_url && (
          <div role="status" className="mt-3 rounded-md bg-subtle p-3 text-sm">
            <p className="font-medium">Invitation link (shown once)</p>
            <code className="mt-1 block break-all text-xs">{created.invite_url}</code>
            <Button size="sm" variant="secondary" className="mt-2" onClick={() => navigator.clipboard.writeText(created.invite_url!).then(() => toast.success("Link copied."), () => toast.error("Couldn't copy. Select the link and copy it manually."))}>Copy link</Button>
          </div>
        )}
      </Card>

      <div className="mb-3 grid gap-3 sm:grid-cols-[1fr_12rem_10rem]">
        <Input aria-label="Search users" placeholder="Search name or email" value={q} onChange={(ev) => setQ(ev.target.value)} />
        <Select aria-label="Filter by role" value={role} onChange={(ev) => setRole(ev.target.value)}><option value="">All roles</option>{[...ROLES, "RECIPIENT"].map((r) => <option key={r} value={r}>{titleCase(r.toLowerCase())}</option>)}</Select>
        <Select aria-label="Filter by status" value={status} onChange={(ev) => setStatus(ev.target.value)}><option value="">All statuses</option>{Object.keys(STATUS_TONE).map((s) => <option key={s} value={s}>{titleCase(s.toLowerCase())}</option>)}</Select>
      </div>
      <Card className="overflow-x-auto">
        <QueryBoundary q={users} isEmpty={(d) => d.length === 0} empty={{ title: "No users match", body: "Try clearing the search or filters." }}>
          {(rows) => (
            <table className="w-full min-w-[46rem] text-sm">
              <caption className="sr-only">Users in your organization</caption>
              <thead className="border-b border-border text-left text-xs text-muted"><tr>{["Name", "Email", "Role", "Status", "Last sign-in", "Actions"].map((h) => <th key={h} scope="col" className="px-4 py-2.5 font-medium">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-border">
                {rows.map((u) => {
                  const self = u.id === me?.id; const st = u.status ?? "ACTIVE"; const pending = st === "PENDING"; const locked = self || u.role === "RECIPIENT" || pending || st === "REJECTED";
                  return (
                    <tr key={u.id}>
                      <td className="px-4 py-3 font-medium">{u.full_name}{self && <span className="ml-2 text-xs text-muted">(you)</span>}</td>
                      <td className="px-4 py-3 text-muted">{u.email}</td>
                      <td className="px-4 py-3">
                        {locked ? <Badge>{pending ? `Requested: ${titleCase((u.requested_role || "").toLowerCase())}` : titleCase(u.role.toLowerCase())}</Badge> : (
                          <Select aria-label={`Role for ${u.full_name}`} value={u.role} onChange={(ev) => ev.target.value !== u.role && setAct({ u, kind: "role", role: ev.target.value })}>{ROLES.map((r) => <option key={r} value={r}>{titleCase(r.toLowerCase())}</option>)}</Select>
                        )}
                      </td>
                      <td className="px-4 py-3"><Badge tone={STATUS_TONE[st]}>{titleCase(st.toLowerCase())}</Badge></td>
                      <td className="px-4 py-3 text-muted">{fmtDateTime(u.last_login_at)}</td>
                      <td className="px-4 py-3">
                        {pending && !self ? (
                          <span className="flex gap-2"><Button size="sm" onClick={() => setAct({ u, kind: "approve" })}>Approve</Button><Button size="sm" variant="secondary" onClick={() => setAct({ u, kind: "reject" })}>Reject</Button></span>
                        ) : !self && st !== "REJECTED" && u.role !== "RECIPIENT" ? (
                          <Button size="sm" variant="secondary" onClick={() => setAct({ u, kind: st === "DISABLED" ? "reactivate" : "deactivate" })}>{st === "DISABLED" ? "Reactivate" : "Deactivate"}</Button>
                        ) : null}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </QueryBoundary>
      </Card>

      <h2 className="mb-2 mt-6 font-display text-base font-semibold">Invitations</h2>
      <Card className="overflow-x-auto">
        <QueryBoundary q={invites} isEmpty={(d) => d.length === 0} empty={{ title: "No invitations yet", body: "Invite a colleague above." }}>
          {(rows) => (
            <table className="w-full min-w-[40rem] text-sm">
              <caption className="sr-only">Invitations</caption>
              <thead className="border-b border-border text-left text-xs text-muted"><tr>{["Email", "Role", "Status", "Expires", "Actions"].map((h) => <th key={h} scope="col" className="px-4 py-2.5 font-medium">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-border">
                {rows.map((i) => (
                  <tr key={i.id}>
                    <td className="px-4 py-3">{i.email}</td><td className="px-4 py-3">{titleCase(i.role.toLowerCase())}{i.requires_approval && <span className="ml-1 text-xs text-muted">(approval)</span>}</td>
                    <td className="px-4 py-3"><Badge tone={INV_TONE[i.status]}>{titleCase(i.status)}</Badge></td><td className="px-4 py-3 text-muted">{fmtDateTime(i.expires_at)}</td>
                    <td className="px-4 py-3">{i.status === "pending" && <Button size="sm" variant="secondary" loading={revoke.isPending && revoke.variables === i.id} onClick={() => revoke.mutate(i.id)}>Revoke</Button>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </QueryBoundary>
      </Card>

      {overview.data && overview.data.recent_security_events.length > 0 && (
        <Card className="mt-5 p-4"><h2 className="font-display text-base font-semibold">Recent security events</h2>
          <ul className="mt-2 space-y-1 text-sm">{overview.data.recent_security_events.map((e) => <li key={e.seq}>{e.summary}</li>)}</ul></Card>
      )}
      <ConfirmDialog open={!!act} onOpenChange={(o) => !o && setAct(null)} title={title} body={body} confirmLabel="Confirm" danger={act?.kind === "deactivate" || act?.kind === "reject"} loading={decide.isPending}
        onConfirm={() => { if (needsReason && reason.trim().length < 3) { toast.error("Please give a reason."); return; } decide.mutate(); }}>
        <Textarea aria-label="Reason" placeholder={needsReason ? "Reason (required)" : "Note (optional)"} value={reason} onChange={(ev) => setReason(ev.target.value)} rows={2} />
      </ConfirmDialog>
    </>
  );
}
