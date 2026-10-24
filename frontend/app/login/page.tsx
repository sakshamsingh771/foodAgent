"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import { Leaf } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button, Field, Input } from "@/components/ui";
import { errorMessage, login } from "@/lib/api";
import { homeFor } from "@/lib/home";

const schema = z.object({ email: z.string().trim().email("Enter a valid email address."), password: z.string().min(1, "Enter your password.") });
type V = z.infer<typeof schema>;

export default function LoginPage() {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const f = useForm<V>({ resolver: zodResolver(schema) });
  const submit = f.handleSubmit(async (v) => {
    setErr(null);
    try { const s = await login(v.email, v.password); toast.success(`Welcome back, ${s.user.full_name.split(" ")[0]}.`); router.replace(homeFor(s.user.role)); }
    catch (e) { setErr(errorMessage(e)); }
  });
  return (
    <main className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center gap-2"><span className="grid h-10 w-10 place-items-center rounded-md bg-brand text-brand-fg"><Leaf className="h-5 w-5" aria-hidden /></span><div><p className="font-display text-2xl font-semibold leading-none">foodAgent</p><p className="text-xs text-muted">Turn surplus into recovery.</p></div></div>
        <h1 className="text-xl font-semibold">Sign in</h1>
        <form onSubmit={submit} noValidate className="mt-4 space-y-4">
          <Field label="Email" error={f.formState.errors.email?.message}><Input type="email" autoComplete="email" inputMode="email" aria-invalid={!!f.formState.errors.email} {...f.register("email")} /></Field>
          <Field label="Password" error={f.formState.errors.password?.message}><Input type="password" autoComplete="current-password" aria-invalid={!!f.formState.errors.password} {...f.register("password")} /></Field>
          {err && <p role="alert" className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{err}</p>}
          <Button type="submit" className="w-full" loading={f.formState.isSubmitting}>Sign in</Button>
        </form>
        <p className="mt-4 text-sm text-muted">New organization? <Link href="/register" className="font-medium text-info underline-offset-2 hover:underline">Create an account</Link></p>
        <details className="mt-6 rounded-md border border-border p-3 text-xs text-muted">
          <summary className="min-h-9 cursor-pointer font-medium text-fg">Demo accounts (simulated data)</summary>
          <p className="mt-2">Password for all: <code>FoodAgent#2026demo</code></p>
          <ul className="mt-1 space-y-0.5"><li>admin@verdanafoods.demo</li><li>ops@verdanafoods.demo</li><li>recovery@verdanafoods.demo</li><li>logistics@verdanafoods.demo</li><li>auditor@verdanafoods.demo</li><li>recipient@annapurna.demo</li></ul>
        </details>
        <p className="mt-6 text-xs text-muted">foodAgent provides decision support and workflow assistance. It does not certify food as safe for human consumption.</p>
      </div>
    </main>
  );
}
