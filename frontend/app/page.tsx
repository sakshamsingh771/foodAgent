"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { homeFor } from "@/lib/home";
import { useAuth } from "@/providers";

/** Routes by the role the backend verified (/auth/me), never by URL, email or stored hints. */
export default function Home() {
  const { user, ready } = useAuth();
  const router = useRouter();
  useEffect(() => { if (ready) router.replace(user ? homeFor(user.role) : "/login"); }, [ready, user, router]);
  return <div className="grid min-h-screen place-items-center text-sm text-muted" role="status">Loading foodAgent…</div>;
}
