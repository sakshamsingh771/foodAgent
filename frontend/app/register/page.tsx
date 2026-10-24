"use client";
import { zodResolver } from "@hookform/resolvers/zod";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { toast } from "sonner";
import { z } from "zod";
import { Button, Field, Input } from "@/components/ui";
import { ApiError, errorMessage, registerOrg } from "@/lib/api";

const schema = z.object({
  organization_name: z.string().trim().min(2, "Enter your organization's name."), full_name: z.string().trim().min(2, "Enter your full name."),
  email: z.string().trim().email("Enter a valid email address."),
  password: z.string().min(10, "Use at least 10 characters.").regex(/[A-Za-z]/, "Include a letter.").regex(/\d/, "Include a number."),
});
type V = z.infer<typeof schema>;

export default function RegisterPage() {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);
  const f = useForm<V>({ resolver: zodResolver(schema) });
  const e = f.formState.errors;
  const submit = f.handleSubmit(async (v) => {
    setErr(null);
    try { await registerOrg(v); toast.success("Your organization is ready."); router.replace("/dashboard"); }
    catch (x) {
      if (x instanceof ApiError && x.details) x.details.forEach((d) => f.setError(d.field as keyof V, { message: d.message }));
      setErr(errorMessage(x));
    }
  });
  return (
    <main className="grid min-h-screen place-items-center px-4 py-10">
      <div className="w-full max-w-sm">
        <h1 className="text-xl font-semibold">Create your organization</h1><p className="mt-1 text-sm text-muted">You&apos;ll be the administrator and can invite your team afterwards.</p>
        <form onSubmit={submit} noValidate className="mt-4 space-y-4">
          <Field label="Organization name" error={e.organization_name?.message}><Input autoComplete="organization" {...f.register("organization_name")} /></Field>
          <Field label="Your name" error={e.full_name?.message}><Input autoComplete="name" {...f.register("full_name")} /></Field>
          <Field label="Work email" error={e.email?.message}><Input type="email" autoComplete="email" {...f.register("email")} /></Field>
          <Field label="Password" error={e.password?.message} hint="At least 10 characters, with letters and numbers."><Input type="password" autoComplete="new-password" {...f.register("password")} /></Field>
          {err && <p role="alert" className="rounded-md bg-danger/10 px-3 py-2 text-sm text-danger">{err}</p>}
          <Button type="submit" className="w-full" loading={f.formState.isSubmitting}>Create account</Button>
        </form>
        <p className="mt-4 text-sm text-muted">Already registered? <Link href="/login" className="font-medium text-info hover:underline">Sign in</Link></p>
      </div>
    </main>
  );
}
