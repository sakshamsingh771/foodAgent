"use client";
import { Button } from "@/components/ui";
export default function Error({ reset }: { error: Error; reset: () => void }) {
  return <main className="grid min-h-screen place-items-center px-4 text-center"><div><h1 className="text-2xl font-semibold">Something went wrong</h1><p className="mt-2 text-sm text-muted">We couldn&apos;t load this screen. Your data is safe.</p><Button className="mt-4" onClick={reset}>Try again</Button></div></main>;
}
