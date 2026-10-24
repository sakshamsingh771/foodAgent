"use client";
import { ShieldOff } from "lucide-react";
import Link from "next/link";
import { homeFor } from "@/lib/home";
import { useAuth } from "@/providers";

export default function Unauthorized() {
  const { user } = useAuth();
  return (
    <div className="mx-auto flex max-w-md flex-col items-center gap-3 py-20 text-center">
      <ShieldOff className="h-10 w-10 text-muted" aria-hidden /><h1 className="text-2xl font-semibold">You don&apos;t have access to this page</h1>
      <p className="text-sm text-muted">Your role doesn&apos;t include this area. If you think that&apos;s a mistake, ask an administrator in your organization.</p>
      <Link href={user ? homeFor(user.role) : "/login"} className="mt-2 inline-flex min-h-11 items-center rounded-md bg-brand px-4 text-sm font-medium text-brand-fg">Go to my home page</Link>
    </div>
  );
}
