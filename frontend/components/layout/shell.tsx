"use client";
import * as Dialog from "@radix-ui/react-dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell, Leaf, Menu, Moon, Search, Sun, SunMoon, LogOut } from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Badge, Button, Popover } from "@/components/ui";
import { get, logout, post } from "@/lib/api";
import { cn, titleCase } from "@/lib/utils";
import { useAuth, useLive } from "@/providers";
import type { Notification, Page } from "@/types/api";
import { homeFor } from "@/lib/home";
import { navFor } from "@/lib/rbac";
const MOBILE_KEYS = ["/dashboard", "/operations", "/recovery", "/logistics", "/recipients"];

export function useNav() {
  const { user } = useAuth();
  return navFor(user?.role, user?.permissions);
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const next = theme === "light" ? "dark" : theme === "dark" ? "system" : "light";
  const Icon = !mounted || theme === "system" ? SunMoon : theme === "dark" ? Moon : Sun;
  return (
    <Button variant="ghost" size="sm" aria-label={`Theme: ${mounted ? theme : "system"}. Switch to ${next}.`} onClick={() => setTheme(next)} className="w-10 px-0"><Icon className="h-5 w-5" aria-hidden /></Button>
  );
}

function LiveDot() {
  const s = useLive();
  return <span className="hidden items-center gap-1.5 text-xs text-muted sm:flex" role="status"><span className={cn("h-2 w-2 rounded-full", s === "live" ? "bg-safe" : "bg-warn")} aria-hidden />{s === "live" ? "Live" : "Reconnecting…"}</span>;
}

function Notifications() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["notifications"], queryFn: () => get<Page<Notification> & { unread: number }>("/notifications?page_size=15"), refetchInterval: 60_000 });
  const readAll = async () => { await post("/notifications/read-all"); qc.invalidateQueries({ queryKey: ["notifications"] }); };
  const read = async (id: string) => { await post(`/notifications/${id}/read`); qc.invalidateQueries({ queryKey: ["notifications"] }); };
  const unread = q.data?.unread ?? 0;
  return (
    <Popover.Root>
      <Popover.Trigger asChild>
        <Button variant="ghost" size="sm" className="relative w-10 px-0" aria-label={`Notifications, ${unread} unread`}>
          <Bell className="h-5 w-5" aria-hidden />{unread > 0 && <span className="absolute right-1 top-1 grid h-4 min-w-4 place-items-center rounded-full bg-danger px-1 text-[10px] font-semibold text-white">{unread > 9 ? "9+" : unread}</span>}
        </Button>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Content align="end" sideOffset={8} className="z-50 w-[min(24rem,calc(100vw-1.5rem))] rounded-lg border border-border bg-surface shadow-pop">
          <div className="flex items-center justify-between border-b border-border px-3 py-2"><span className="font-semibold">Notifications</span><button onClick={readAll} disabled={!unread} className="min-h-9 text-xs text-info disabled:opacity-40">Mark all read</button></div>
          <ul className="max-h-96 overflow-y-auto">
            {q.isPending && <li className="p-4 text-sm text-muted">Loading…</li>}
            {q.data?.items.length === 0 && <li className="p-6 text-center text-sm text-muted">You&apos;re all caught up.</li>}
            {q.data?.items.map((n) => (
              <li key={n.id} className={cn("border-b border-border/60 px-3 py-2.5 last:border-0", !n.read && "bg-subtle/70")}>
                <button className="w-full text-left" onClick={() => read(n.id)}>
                  <div className="flex items-center gap-2"><Badge tone={n.severity === "critical" ? "danger" : n.severity === "warning" ? "warn" : "info"}>{titleCase(n.type)}</Badge>{!n.read && <span className="h-2 w-2 rounded-full bg-info" aria-label="Unread" />}</div>
                  <p className="mt-1 text-sm font-medium">{n.title}</p>{n.body && <p className="text-xs text-muted">{n.body}</p>}
                </button>
              </li>
            ))}
          </ul>
        </Popover.Content>
      </Popover.Portal>
    </Popover.Root>
  );
}

export function CommandPalette({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const router = useRouter();
  const nav = useNav();
  const [q, setQ] = useState("");
  const res = useQuery({ queryKey: ["search", q], enabled: open && q.trim().length >= 2, queryFn: () => get<{ results: { type: string; id: string; title: string; subtitle: string; href: string }[] }>(`/search?q=${encodeURIComponent(q.trim())}`) });
  const go = (href: string) => { onOpenChange(false); setQ(""); router.push(href); };
  const pages = nav.filter((n) => n.label.toLowerCase().includes(q.toLowerCase()));
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/45" />
        <Dialog.Content className="fixed left-1/2 top-[12vh] z-50 w-[calc(100vw-1.5rem)] max-w-xl -translate-x-1/2 overflow-hidden rounded-lg border border-border bg-surface shadow-pop">
          <Dialog.Title className="sr-only">Search foodAgent</Dialog.Title>
          <Dialog.Description className="sr-only">Search lots, recovery cases, recipients, products and documents, or jump to a page.</Dialog.Description>
          <div className="flex items-center gap-2 border-b border-border px-3"><Search className="h-4 w-4 text-muted" aria-hidden /><input autoFocus value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search lots, cases, recipients, documents…" aria-label="Search" className="min-h-12 flex-1 bg-transparent text-sm outline-none" /></div>
          <div className="max-h-[60vh] overflow-y-auto p-2">
            {pages.length > 0 && <p className="px-2 pb-1 pt-2 text-xs font-medium text-muted">Pages</p>}
            {pages.slice(0, q ? 4 : 12).map((n) => <button key={n.href} onClick={() => go(n.href)} className="flex min-h-11 w-full items-center gap-2 rounded-md px-2 text-left text-sm hover:bg-subtle"><n.icon className="h-4 w-4 text-muted" />{n.label}</button>)}
            {res.data && res.data.results.length > 0 && <p className="px-2 pb-1 pt-3 text-xs font-medium text-muted">Results</p>}
            {res.data?.results.map((r) => <button key={`${r.type}${r.id}`} onClick={() => go(r.href)} className="flex min-h-11 w-full items-center justify-between gap-2 rounded-md px-2 text-left text-sm hover:bg-subtle"><span><span className="font-medium">{r.title}</span><span className="block text-xs text-muted">{r.subtitle}</span></span><Badge>{r.type}</Badge></button>)}
            {res.isFetching && <p className="px-2 py-3 text-xs text-muted">Searching…</p>}
            {res.data && res.data.results.length === 0 && q.trim().length >= 2 && !res.isFetching && <p className="px-2 py-3 text-sm text-muted">No matches for “{q}”.</p>}
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, ready } = useAuth();
  const router = useRouter();
  const path = usePathname();
  const nav = useNav();
  const [cmd, setCmd] = useState(false);
  const [drawer, setDrawer] = useState(false);

  useEffect(() => { if (ready && !user) router.replace("/login"); }, [ready, user, router]);
  useEffect(() => {
    const h = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setCmd((v) => !v); } };
    window.addEventListener("keydown", h); return () => window.removeEventListener("keydown", h);
  }, []);
  useEffect(() => setDrawer(false), [path]);
  useEffect(() => {
    if (user && nav.length && path !== "/unauthorized" && !nav.some((n) => path === n.href || path.startsWith(n.href + "/"))) router.replace("/unauthorized");
  }, [user, nav, path, router]);

  if (!ready || !user) return <div className="grid min-h-screen place-items-center text-sm text-muted" role="status">Loading foodAgent…</div>;
  const crumb = nav.find((n) => path === n.href || path.startsWith(n.href + "/"));
  const Links = ({ mobile = false }: { mobile?: boolean }) => (
    <nav aria-label="Main" className="space-y-0.5">
      {nav.map((n) => {
        const on = path === n.href || path.startsWith(n.href + "/");
        return <Link key={n.href} href={n.href} aria-current={on ? "page" : undefined} className={cn("flex min-h-11 items-center gap-3 rounded-md px-3 text-sm font-medium transition", on ? "bg-brand text-brand-fg" : "text-muted hover:bg-subtle hover:text-fg")}><n.icon className="h-[18px] w-[18px]" aria-hidden />{n.label}</Link>;
      })}
    </nav>
  );
  const out = async () => { await logout(); toast.success("You've been signed out."); router.replace("/login"); };

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[15rem_1fr]">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded-md focus:bg-surface focus:px-3 focus:py-2">Skip to content</a>
      <aside className="sticky top-0 hidden h-screen flex-col border-r border-border bg-surface p-3 lg:flex">
        <Link href={homeFor(user.role)} className="mb-5 flex items-center gap-2 px-3 py-2"><span className="grid h-8 w-8 place-items-center rounded-md bg-brand text-brand-fg"><Leaf className="h-4 w-4" aria-hidden /></span><span className="font-display text-xl font-semibold">foodAgent</span></Link>
        <div className="flex-1 overflow-y-auto"><Links /></div>
        <p className="px-3 pt-3 text-[11px] leading-snug text-muted">Decision support only. foodAgent doesn&apos;t certify food as safe.</p>
      </aside>
      <div className="flex min-w-0 flex-col pb-16 lg:pb-0">
        <header className="sticky top-0 z-30 flex min-h-14 items-center gap-2 border-b border-border bg-surface/95 px-3 backdrop-blur sm:px-5">
          <Dialog.Root open={drawer} onOpenChange={setDrawer}>
            <Dialog.Trigger asChild><Button variant="ghost" size="sm" className="w-10 px-0 lg:hidden" aria-label="Open menu"><Menu className="h-5 w-5" /></Button></Dialog.Trigger>
            <Dialog.Portal><Dialog.Overlay className="fixed inset-0 z-50 bg-black/45" />
              <Dialog.Content className="fixed inset-y-0 left-0 z-50 w-72 max-w-[85vw] overflow-y-auto bg-surface p-3 shadow-pop">
                <Dialog.Title className="mb-3 px-3 font-display text-xl font-semibold">foodAgent</Dialog.Title><Dialog.Description className="sr-only">Site navigation</Dialog.Description><Links mobile />
              </Dialog.Content></Dialog.Portal>
          </Dialog.Root>
          <div className="min-w-0 flex-1 text-sm text-muted" aria-label="Breadcrumb"><span className="hidden sm:inline">foodAgent / </span><span className="font-medium text-fg">{crumb?.label ?? "Overview"}</span></div>
          <Button variant="secondary" size="sm" onClick={() => setCmd(true)} className="hidden gap-2 text-muted sm:inline-flex"><Search className="h-4 w-4" aria-hidden />Search<kbd className="rounded border border-border px-1 text-[10px]">Ctrl K</kbd></Button>
          <Button variant="ghost" size="sm" onClick={() => setCmd(true)} className="w-10 px-0 sm:hidden" aria-label="Search"><Search className="h-5 w-5" /></Button>
          <LiveDot /><ThemeToggle /><Notifications />
          <Popover.Root>
            <Popover.Trigger asChild><Button variant="ghost" size="sm" className="gap-2 px-2" aria-label="Account menu"><span className="grid h-8 w-8 place-items-center rounded-full bg-subtle text-xs font-semibold">{user.full_name.split(" ").map((p) => p[0]).slice(0, 2).join("")}</span></Button></Popover.Trigger>
            <Popover.Portal><Popover.Content align="end" sideOffset={8} className="z-50 w-64 rounded-lg border border-border bg-surface p-3 shadow-pop">
              <p className="font-medium">{user.full_name}</p><p className="text-xs text-muted">{user.email}</p><Badge className="mt-2">{titleCase(user.role.toLowerCase())}</Badge>
              <Button variant="secondary" size="sm" className="mt-3 w-full" onClick={out}><LogOut className="h-4 w-4" aria-hidden />Sign out</Button>
            </Popover.Content></Popover.Portal>
          </Popover.Root>
        </header>
        <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-3 py-5 sm:px-6 sm:py-7">{children}</main>
      </div>
      <nav aria-label="Quick navigation" className="fixed inset-x-0 bottom-0 z-30 grid border-t border-border bg-surface lg:hidden" style={{ gridTemplateColumns: `repeat(${Math.min(5, nav.filter((n) => MOBILE_KEYS.includes(n.href)).length || 1)}, 1fr)` }}>
        {nav.filter((n) => MOBILE_KEYS.includes(n.href)).slice(0, 5).map((n) => {
          const on = path === n.href || path.startsWith(n.href + "/");
          return <Link key={n.href} href={n.href} aria-current={on ? "page" : undefined} className={cn("flex min-h-14 flex-col items-center justify-center gap-0.5 text-[11px]", on ? "font-semibold text-brand" : "text-muted")}><n.icon className="h-5 w-5" aria-hidden />{n.label.replace("Live Operations", "Live")}</Link>;
        })}
      </nav>
      <CommandPalette open={cmd} onOpenChange={setCmd} />
    </div>
  );
}
