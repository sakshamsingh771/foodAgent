"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { Eye, EyeOff, Leaf } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button, Field, Input } from "@/components/ui";
import { ApiError, EXPIRED_KEY, demoAccounts, errorMessage, login } from "@/lib/api";
import { homeFor } from "@/lib/home";

const schema = z.object({ email: z.string().trim().email("Enter a valid email address."), password: z.string().min(1, "Enter your password.") });
type V = z.infer<typeof schema>;

export default function LoginPage() {
  const router = useRouter();
  const [err, setErr] = useState<{ code?: string; message: string } | null>(null);
  const [show, setShow] = useState(false);
  const [expired, setExpired] = useState(false);
  const [demo, setDemo] = useState<{ password: string; accounts: { email: string; label: string }[] } | null>(null);
  const [busyDemo, setBusyDemo] = useState<string | null>(null);
  const f = useForm<V>({ resolver: zodResolver(schema) });

  useEffect(() => {
    try { if (sessionStorage.getItem(EXPIRED_KEY)) { setExpired(true); sessionStorage.removeItem(EXPIRED_KEY); } } catch { /* ignore */ }
    // Backend returns 404 outside development/demo, so nothing is shown in production.
    void demoAccounts().then(setDemo);
  }, []);

  const go = async (email: string, password: string) => {
    setErr(null);
    try {
      const s = await login(email, password);  // normal auth API; the role used for routing is the one the server returned
      toast.success(`Welcome back, ${s.user.full_name.split(" ")[0]}.`);
      router.replace(homeFor(s.user.role));
    } catch (e) { setErr({ code: e instanceof ApiError ? e.code : undefined, message: errorMessage(e) }); }
  };
  const submit = f.handleSubmit((v) => go(v.email, v.password));
  const pending = err?.code === "ACCOUNT_PENDING";

  return (
    <main className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2"><span className="grid h-10 w-10 place-items-center rounded-md bg-brand text-brand-fg"><Leaf className="h-5 w-5" aria-hidden /></span><div><p className="font-display text-2xl font-semibold leading-none">foodAgent</p><p className="text-xs text-muted">Turn surplus into recovery.</p></div></div>
        <h1 className="text-xl font-semibold">Sign in</h1>
        {expired && <p role="status" className="mt-3 rounded-md bg-warn/14 px-3 py-2 text-sm text-warn">Your session has expired. Please sign in again.</p>}
        <form onSubmit={submit} noValidate className="mt-4 space-y-4">
          <Field label="Email" error={f.formState.errors.email?.message}><Input type="email" autoComplete="email" inputMode="email" disabled={f.formState.isSubmitting} aria-invalid={!!f.formState.errors.email} {...f.register("email")} /></Field>
          <Field label="Password" error={f.formState.errors.password?.message}>
            <div className="relative">
              <Input type={show ? "text" : "password"} autoComplete="current-password" className="pr-11" disabled={f.formState.isSubmitting} aria-invalid={!!f.formState.errors.password} {...f.register("password")} />
              <button type="button" onClick={() => setShow((v) => !v)} aria-label={show ? "Hide password" : "Show password"} aria-pressed={show} className="absolute inset-y-0 right-0 grid w-11 place-items-center text-muted hover:text-fg">
                {show ? <EyeOff className="h-4 w-4" aria-hidden /> : <Eye className="h-4 w-4" aria-hidden />}
              </button>
            </div>
          </Field>
          {err && <p role="alert" className={pending ? "rounded-md bg-info/12 px-3 py-2 text-sm text-info" : "rounded-md bg-danger/10 px-3 py-2 text-sm text-danger"}>{err.message}</p>}
          <Button type="submit" className="w-full" loading={f.formState.isSubmitting} disabled={!!busyDemo}>Sign in</Button>
        </form>
        <p className="mt-4 text-sm text-muted">New here? <Link href="/register" className="font-medium text-info underline-offset-2 hover:underline">Create an account or join with an invitation</Link></p>
        {demo && demo.accounts.length > 0 && (
          <details className="mt-6 rounded-md border border-border p-3 text-xs text-muted">
            <summary className="min-h-9 cursor-pointer font-medium text-fg">Demo accounts (development only, simulated data)</summary>
            <p className="mt-2">Quick sign-in uses the normal login API with the demo password.</p>
            <ul className="mt-2 grid gap-1.5">
              {demo.accounts.map((a) => (
                <li key={a.email}>
                  <Button type="button" size="sm" variant="secondary" className="w-full justify-between" loading={busyDemo === a.email} disabled={!!busyDemo || f.formState.isSubmitting}
                    onClick={async () => { setBusyDemo(a.email); await go(a.email, demo.password); setBusyDemo(null); }}>
                    <span>{a.label}</span><span className="truncate pl-2 font-normal text-muted">{a.email}</span>
                  </Button>
                </li>
              ))}
            </ul>
          </details>
        )}
        <p className="mt-6 text-xs text-muted">foodAgent provides decision support and workflow assistance. It does not certify food as safe for human consumption.</p>
      </div>
    </main>
  );
}
