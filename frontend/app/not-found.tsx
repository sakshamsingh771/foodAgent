import Link from "next/link";
export default function NotFound() {
  return <main className="grid min-h-screen place-items-center px-4 text-center"><div><h1 className="text-3xl font-semibold">Page not found</h1><p className="mt-2 text-sm text-muted">That page doesn&apos;t exist or has moved.</p><Link href="/dashboard" className="mt-4 inline-flex min-h-11 items-center rounded-md bg-brand px-4 text-sm font-medium text-brand-fg">Back to overview</Link></div></main>;
}
