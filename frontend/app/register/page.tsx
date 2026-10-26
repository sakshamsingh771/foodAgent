"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { MailCheck } from "lucide-react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button, Field, Input } from "@/components/ui";
import { ApiError, errorMessage, lookupInvitation, register, type InvitationInfo } from "@/lib/api";
import { homeFor } from "@/lib/home";
import { titleCase } from "@/lib/utils";

const pw = z.string().min(10, "Use at least 10 characters.").regex(/[A-Za-z]/, "Include a letter.").regex(/\d/, "Include a number.");
const schema = z.object({
  full_name: z.string().trim().min(2, "Enter your full name."), email: z.string().trim().email("Enter a valid email address."),
  password: pw, confirm_password: z.string(), organization_name: z.string().trim().optional(), invite_token: z.string().trim().optional(), setup_token: z.string().trim().optional(),
});
type V = z.infer<typeof schema>;
type Mode = "join" | "create_org";

function RegisterForm() {
  const router = useRouter();
  const qs = useSearchParams();
  const inviteParam = qs.get("invite") || "";
  const [mode, setMode] = useState<Mode>(inviteParam ? "join" : "create_org");
  const [err, setErr] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);
  const [inv, setInv] = useState<InvitationInfo | null>(null);
  const [invErr, setInvErr] = useState<string | null>(null);
  const f = useForm<V>({ resolver: zodResolver(schema), defaultValues: { invite_token: inviteParam } });
  const e = f.formState.errors;
  const token = f.watch("invite_token");

  useEffect(() => {
    setInv(null); setInvErr(null);
    if (mode !== "join" || !token || token.length < 16) return;
    let live = true;
    lookupInvitation(token).then((i) => { if (live) { setInv(i); f.setValue("email", i.email); } }).catch((x) => live && setInvErr(errorMessage(x)));
    return () => { live = false; };
  }, [mode, token, f]);

  const submit = f.handleSubmit(async (v) => {
    setErr(null);
    if (v.password !== v.confirm_password) { f.setError("confirm_password", { message: "Passwords don't match." }); return; }
    if (mode === "create_org" && !v.organization_name) { f.setError("organization_name", { message: "Enter your organization's name." }); return; }
    if (mode === "join" && !v.invite_token) { f.setError("invite_token", { message: "Paste your invitation code." }); return; }
    try {
      const r = await register({ mode, full_name: v.full_name, email: v.email, password: v.password, confirm_password: v.confirm_password,
        organization_name: mode === "create_org" ? v.organization_name : undefined, invite_token: mode === "join" ? v.invite_token : undefined,
        setup_token: mode === "create_org" && v.setup_token ? v.setup_token : undefined });
      if (r.status === "ACTIVE" && r.user) { toast.success(r.message); router.replace(homeFor(r.user.role)); } else setDone(r.message);
    } catch (x) {
      if (x instanceof ApiError && x.details) x.details.forEach((d) => d.field && f.setError(d.field as keyof V, { message: d.message }));
      setErr(errorMessage(x));
    }
  });

  if (done) return (
    <main className="grid min-h-screen place-items-center px-4 py-10"><div className="w-full max-w-sm text-center">
      <MailCheck className="mx-auto h-10 w-10 text-info" aria-hidden /><h1 className="mt-3 text-xl font-semibold">Account awaiting approval</h1>
      <p role="status" className="mt-2 text-sm text-muted">{done}</p>
      <Link href="/login" className="mt-5 inline-block text-sm font-medium text-info hover:underline">Back to sign in</Link>
    </div></main>
  );

  return (
    <main className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <h1 className="text-xl font-semibold">Create your account</h1>
        <div role="tablist" aria-label="Registration type" className="mt-4 grid grid-cols-2 gap-1 rounded-md bg-subtle p-1 text-sm">
          {([["join", "Join with invitation"], ["create_org", "New organization"]] as const).map(([m, label]) => (
            <button key={m} role="tab" type="button" aria-selected={mode === m} onClick={() => { setMode(m); setErr(null); }}
              className={`min-h-10 rounded px-2 font-medium ${mode === m ? "bg-surface shadow-card" : "text-muted"}`}>{label}</button>
          ))}
        </div>
        <p className="mt-3 text-sm text-muted">
          {mode === "join" ? "Your administrator controls your role and organization. Staff access can't be self-selected." : "Your request is reviewed before administrator access is granted, unless you hold a setup code."}
        </p>
        <form onSubmit={submit} noValidate className="mt-4 space-y-4">
          {mode === "join" ? (
            <Field label="Invitation code" error={e.invite_token?.message ?? invErr ?? undefined} hint={inv ? `Joining ${inv.organization_name} as ${titleCase(inv.role.toLowerCase())}${inv.requires_approval ? " (needs admin approval)" : ""}.` : undefined}>
              <Input autoComplete="off" spellCheck={false} {...f.register("invite_token")} />
            </Field>
          ) : (
            <>
              <Field label="Organization name" error={e.organization_name?.message}><Input autoComplete="organization" {...f.register("organization_name")} /></Field>
              <Field label="Setup code (optional)" hint="Only if the platform operator gave you one." error={e.setup_token?.message}><Input autoComplete="off" type="password" {...f.register("setup_token")} /></Field>
            </>
          )}
          <Field label="Full name" error={e.full_name?.message}><Input autoComplete="name" {...f.register("full_name")} /></Field>
          <Field label="Work email" error={e.email?.message}><Input type="email" autoComplete="email" readOnly={mode === "join" && !!inv} {...f.register("email")} /></Field>
          <Field label="Password" error={e.password?.message} hint="At least 10 characters, with letters and numbers."><Input type="password" autoComplete="new-password" {...f.register("password")} /></Field>
          <Field label="Confirm password" error={e.confirm_password?.message}><Input type="password" autoComplete="new-password" {...f.register("confirm_password")} /></Field>
          {err && <p role="alert" className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{err}</p>}
          <Button type="submit" className="w-full" loading={f.formState.isSubmitting}>{mode === "join" ? "Join organization" : "Request organization"}</Button>
        </form>
        <p className="mt-4 text-sm text-muted">Already registered? <Link href="/login" className="font-medium text-info hover:underline">Sign in</Link></p>
      </div>
    </main>
  );
}

export default function RegisterPage() { return <Suspense fallback={null}><RegisterForm /></Suspense>; }
