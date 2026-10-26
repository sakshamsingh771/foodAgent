"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { toast } from "sonner";
import { Badge, Button, Card, ConfirmDialog, PageHeader, Select, Textarea } from "@/components/ui";
import { QueryBoundary } from "@/components/ui/query-state";
import { errorMessage, get, patch } from "@/lib/api";
import { titleCase } from "@/lib/utils";
import { useAuth } from "@/providers";
import type { User } from "@/types/api";

const ROLES = ["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER", "LOGISTICS", "AUDITOR"];
interface Overview { users_by_role: Record<string, { active: number; inactive: number }>; pending_approvals: number; exception_counts: Record<string, number>; recent_security_events: { seq: number; summary: string; created_at: string }[] }

export default function UsersPage() {
  const { user: me } = useAuth();
  const qc = useQueryClient();
  const users = useQuery({ queryKey: ["users"], queryFn: () => get<User[]>("/users") });
  const overview = useQuery({ queryKey: ["admin-overview"], queryFn: () => get<Overview>("/admin/overview") });
  const [pending, setPending] = useState<{ u: User; role?: string; active?: boolean } | null>(null);
  const [reason, setReason] = useState("");
  const m = useMutation({
    mutationFn: () => patch(`/users/${pending!.u.id}`, { role: pending!.role, is_active: pending!.active, reason: reason.trim() }),
    onSuccess: () => { toast.success("User updated and recorded in the audit log."); setPending(null); setReason(""); qc.invalidateQueries({ queryKey: ["users"] }); qc.invalidateQueries({ queryKey: ["admin-overview"] }); },
    onError: (e) => toast.error(errorMessage(e)),
  });
  const verb = pending?.active === false ? "Deactivate" : pending?.active === true ? "Reactivate" : "Change role of";
  return (
    <>
      <PageHeader title="Users & roles" sub="Assign roles, deactivate accounts and review recent security events for your organization." />
      {overview.data && (
        <div className="mb-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
          <Card className="p-4"><p className="text-xs uppercase text-muted">Pending approvals</p><p className="font-display text-3xl font-semibold">{overview.data.pending_approvals}</p></Card>
          <Card className="p-4"><p className="text-xs uppercase text-muted">Missing evidence</p><p className="font-display text-3xl font-semibold">{overview.data.exception_counts.missing_evidence}</p></Card>
          <Card className="p-4"><p className="text-xs uppercase text-muted">Overdue pickups</p><p className="font-display text-3xl font-semibold">{overview.data.exception_counts.overdue_pickups}</p></Card>
          <Card className="p-4"><p className="text-xs uppercase text-muted">Active users</p><p className="font-display text-3xl font-semibold">{Object.values(overview.data.users_by_role).reduce((a, r) => a + r.active, 0)}</p></Card>
        </div>
      )}
      <Card className="overflow-x-auto">
        <QueryBoundary q={users} isEmpty={(d) => d.length === 0} empty={{ title: "No users" }}>
          {(rows) => (
            <table className="w-full min-w-[40rem] text-sm">
              <caption className="sr-only">Users in your organization</caption>
              <thead className="border-b border-border text-left text-xs text-muted"><tr>{["Name", "Email", "Role", "Status", "Actions"].map((h) => <th key={h} scope="col" className="px-4 py-2.5 font-medium">{h}</th>)}</tr></thead>
              <tbody className="divide-y divide-border">
                {rows.map((u) => {
                  const self = u.id === me?.id; const locked = self || u.role === "RECIPIENT";
                  return (
                    <tr key={u.id}>
                      <td className="px-4 py-3 font-medium">{u.full_name}{self && <span className="ml-2 text-xs text-muted">(you)</span>}</td>
                      <td className="px-4 py-3 text-muted">{u.email}</td>
                      <td className="px-4 py-3">
                        {locked ? <Badge>{titleCase(u.role.toLowerCase())}</Badge> : (
                          <Select aria-label={`Role for ${u.full_name}`} value={u.role} onChange={(e) => e.target.value !== u.role && setPending({ u, role: e.target.value })}>{ROLES.map((r) => <option key={r} value={r}>{titleCase(r.toLowerCase())}</option>)}</Select>
                        )}
                      </td>
                      <td className="px-4 py-3"><Badge tone={u.is_active === false ? "danger" : "safe"}>{u.is_active === false ? "Inactive" : "Active"}</Badge></td>
                      <td className="px-4 py-3">{!locked && <Button size="sm" variant="secondary" onClick={() => setPending({ u, active: u.is_active === false })}>{u.is_active === false ? "Reactivate" : "Deactivate"}</Button>}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </QueryBoundary>
      </Card>
      {overview.data && overview.data.recent_security_events.length > 0 && (
        <Card className="mt-5 p-4"><h2 className="font-display text-base font-semibold">Recent security events</h2>
          <ul className="mt-2 space-y-1 text-sm">{overview.data.recent_security_events.map((e) => <li key={e.seq}>{e.summary}</li>)}</ul></Card>
      )}
      <ConfirmDialog open={!!pending} onOpenChange={(o) => !o && setPending(null)} title={`${verb} ${pending?.u.full_name ?? ""}?`}
        body={pending?.role ? `Their role becomes ${titleCase(pending.role.toLowerCase())} and their access changes immediately.` : pending?.active === false ? "They are signed out and can no longer log in." : "They can log in again."}
        confirmLabel="Confirm" danger={pending?.active === false} loading={m.isPending} onConfirm={() => { if (reason.trim().length < 3) { toast.error("Please give a reason."); return; } m.mutate(); }}>
        <Textarea aria-label="Reason" placeholder="Reason (required)" value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
      </ConfirmDialog>
    </>
  );
}
