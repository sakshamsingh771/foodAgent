"use client";
import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import { Toaster } from "sonner";
import { API_BASE, ApiError, api, raw, session, type Session } from "@/lib/api";
import type { User } from "@/types/api";

/* ---------- auth ---------- */
interface AuthCtx { user: User | null; ready: boolean }
const Auth = createContext<AuthCtx>({ user: null, ready: false });
export const useAuth = () => useContext(Auth);

function AuthProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient();
  const [s, setS] = useState<Session | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    let active = true;
    const sync = async () => {
      const next = session.get();
      if (!next) { if (active) { setS(null); qc.clear(); setReady(true); } return; }
      try {
        const user = await api<User>("/auth/me");
        if (active) {
          setS({ ...next, user });
          qc.clear();
          setReady(true);
        }
      } catch {
        session.set(null);
        if (active) { setS(null); setReady(true); }
      }
    };
    void sync();
    const onSession = () => { void sync(); };
    window.addEventListener("foodagent:session", onSession);
    window.addEventListener("storage", onSession);
    return () => { active = false; window.removeEventListener("foodagent:session", onSession); window.removeEventListener("storage", onSession); };
  }, [qc]);
  return <Auth.Provider value={{ user: s?.user ?? null, ready }}>{children}</Auth.Provider>;
}

/* ---------- live events (SSE over fetch so the token stays in a header) ---------- */
type LiveState = "connecting" | "live" | "reconnecting";
const Live = createContext<LiveState>("connecting");
export const useLive = () => useContext(Live);

const INVALIDATE: Record<string, string[]> = {
  "lot.updated": ["lots", "dashboard", "plant"], "freshness.updated": ["lots", "dashboard"],
  "recovery.created": ["cases", "lots", "dashboard"], "recovery.updated": ["cases", "case", "lots", "dashboard", "pickups", "recipient-cases"],
  "recovery.assigned": ["recipient-cases"], "recipient.accepted": ["cases", "case"], "pickup.delayed": ["pickups", "case", "dashboard"],
  "pickup.scheduled": ["pickups", "recipient-cases"], "pickup.updated": ["pickups", "recipient-cases"],
  "notification.created": ["notifications"], "scenario.triggered": ["lots", "cases", "case", "pickups", "dashboard", "plant", "scenarios", "audit"],
};

function LiveProvider({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  const qc = useQueryClient();
  const [state, setState] = useState<LiveState>("connecting");
  const lastId = useRef<string | null>(null);

  useEffect(() => {
    if (!user) return;
    let stop = false;
    const ctl = new AbortController();
    (async () => {
      let delay = 1000;
      while (!stop) {
        try {
          const res = await raw(`/events/stream${lastId.current ? `?last_id=${lastId.current}` : ""}`, { signal: ctl.signal, headers: { Accept: "text/event-stream" } });
          if (!res.ok || !res.body) throw new ApiError(res.status, "SSE", "stream");
          setState("live"); delay = 1000;
          const reader = res.body.getReader(); const dec = new TextDecoder(); let buf = "";
          for (;;) {
            const { value, done } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });
            let i: number;
            while ((i = buf.indexOf("\n\n")) >= 0) {
              const block = buf.slice(0, i); buf = buf.slice(i + 2);
              const ev = /^event: (.+)$/m.exec(block)?.[1]; const id = /^id: (.+)$/m.exec(block)?.[1];
              if (id) lastId.current = id;
              if (ev) (INVALIDATE[ev] || []).forEach((k) => qc.invalidateQueries({ queryKey: [k] }));
            }
          }
        } catch { if (stop) return; }
        if (stop) return;
        setState("reconnecting");
        await new Promise((r) => setTimeout(r, delay));
        delay = Math.min(delay * 2, 15000);
      }
    })();
    return () => { stop = true; ctl.abort(); setState("connecting"); };
  }, [user?.id, qc]);

  return <Live.Provider value={state}>{children}</Live.Provider>;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({
    defaultOptions: { queries: { staleTime: 15_000, retry: (n, e) => !(e instanceof ApiError && e.status > 0 && e.status < 500) && n < 2, refetchOnWindowFocus: false } },
  }));
  return (
    <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
      <QueryClientProvider client={client}>
        <AuthProvider><LiveProvider>{children}</LiveProvider></AuthProvider>
        <Toaster richColors position="top-right" closeButton />
      </QueryClientProvider>
    </ThemeProvider>
  );
}
