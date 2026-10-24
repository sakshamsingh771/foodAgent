"use client";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Badge, Button, Card, CardHeader, Field, Input, PageHeader, Select } from "@/components/ui";
import { QueryBoundary } from "@/components/ui/query-state";
import { errorMessage, get, post } from "@/lib/api";
import { titleCase } from "@/lib/utils";
import { useAuth } from "@/providers";
import type { User } from "@/types/api";

export default function Settings() {
  const { user } = useAuth(); const { theme, setTheme } = useTheme(); const qc = useQueryClient();
  const [mounted, setMounted] = useState(false); useEffect(() => setMounted(true), []);
  const isAdmin = user?.role === "ADMIN";
  const org = useQuery({ queryKey: ["org"], queryFn: () => get<{ name: string; type: string; is_demo: boolean } | null>("/organizations/current") });
  const users = useQuery({ queryKey: ["users"], enabled: isAdmin, queryFn: () => get<User[]>("/users") });
  const add = useMutation({ mutationFn: (b: Record<string, string>) => post("/users", b), onSuccess: () => { toast.success("Teammate added."); qc.invalidateQueries({ queryKey: ["users"] }); }, onError: (e) => toast.error(errorMessage(e)) });
  return (
    <>
      <PageHeader title="Settings" />
      <div className="grid gap-5 lg:grid-cols-2">
        <Card><CardHeader title="Appearance" /><div className="space-y-2 p-4"><Field label="Theme"><Select className="w-full" value={mounted ? theme : "system"} onChange={(e) => setTheme(e.target.value)}><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></Select></Field></div></Card>
        <Card><CardHeader title="Organization" /><dl className="space-y-2 p-4 text-sm"><div className="flex justify-between"><dt className="text-muted">Name</dt><dd>{org.data?.name ?? "–"}</dd></div><div className="flex justify-between"><dt className="text-muted">Your role</dt><dd><Badge>{user ? titleCase(user.role.toLowerCase()) : ""}</Badge></dd></div>{org.data?.is_demo && <p className="text-xs text-muted">This is a demo organization with simulated data.</p>}</dl></Card>
        {isAdmin && <Card className="lg:col-span-2"><CardHeader title="Team" />
          <QueryBoundary q={users} isEmpty={(d) => d.length === 0}>{(rows) => <ul className="divide-y divide-border">{rows.map((u) => <li key={u.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2.5 text-sm"><span>{u.full_name}<span className="block text-xs text-muted">{u.email}</span></span><Badge>{titleCase(u.role.toLowerCase())}</Badge></li>)}</ul>}</QueryBoundary>
          <form className="grid gap-3 border-t border-border p-4 sm:grid-cols-5" onSubmit={(e) => { e.preventDefault(); const f = e.currentTarget; const d = Object.fromEntries(new FormData(f)) as Record<string, string>; add.mutate(d, { onSuccess: () => f.reset() }); }}>
            <Field label="Name"><Input name="full_name" required minLength={2} /></Field><Field label="Email"><Input name="email" type="email" required /></Field>
            <Field label="Temporary password" hint="10+ chars, letters and numbers"><Input name="password" type="password" required minLength={10} autoComplete="new-password" /></Field>
            <Field label="Role"><Select name="role" className="w-full" defaultValue="OPERATIONS_MANAGER">{["ADMIN", "OPERATIONS_MANAGER", "RECOVERY_MANAGER", "LOGISTICS", "AUDITOR"].map((r) => <option key={r} value={r}>{titleCase(r.toLowerCase())}</option>)}</Select></Field>
            <div className="flex items-end"><Button type="submit" className="w-full" loading={add.isPending}>Add teammate</Button></div>
          </form></Card>}
        <Card className="lg:col-span-2 p-4 text-sm text-muted"><p className="font-medium text-fg">About foodAgent</p><p className="mt-1">foodAgent provides decision support and workflow assistance. It does not independently certify food as safe for human consumption; human approval is required wherever it applies. Recommendations are labelled RULE, STATISTICAL or SIMULATED so you can see how each was produced.</p></Card>
      </div>
    </>
  );
}
