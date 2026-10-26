import type { Role, User } from "@/types/api";

const BASE = (process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000").replace(/\/$/, "") + "/api/v1";
const KEY = "foodagent.session";

export interface Session { access_token: string; refresh_token: string; user: User }

export class ApiError extends Error {
  constructor(public status: number, public code: string, message: string, public details?: { field: string; message: string }[], public requestId?: string) {
    super(message);
  }
}

const FRIENDLY: Record<string, string> = {
  NETWORK: "We couldn't reach foodAgent. Check your connection and try again.",
  INTERNAL_ERROR: "Something went wrong on our side. Please try again.",
  FORBIDDEN_ROLE: "Your role doesn't have access to this action.",
  VALIDATION_ERROR: "We couldn't save this change. Check the highlighted fields and try again.",
};

export const session = {
  get(): Session | null {
    if (typeof window === "undefined") return null;
    try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch { return null; }
  },
  set(s: Session | null) {
    if (typeof window === "undefined") return;
    if (s) localStorage.setItem(KEY, JSON.stringify(s)); else localStorage.removeItem(KEY);
    window.dispatchEvent(new Event("foodagent:session"));
  },
};

export const EXPIRED_KEY = "foodagent.expired";
function markExpired() { try { sessionStorage.setItem(EXPIRED_KEY, "1"); } catch { /* ignore */ } }

let refreshing: Promise<Session | null> | null = null;
async function refresh(): Promise<Session | null> {
  const cur = session.get();
  if (!cur) return null;
  refreshing ??= fetch(`${BASE}/auth/refresh`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: cur.refresh_token }) })
    .then(async (r) => { if (!r.ok) throw new Error("refresh"); const s = await r.json(); session.set(s); return s as Session; })
    .catch(() => { markExpired(); session.set(null); return null; })
    .finally(() => { refreshing = null; });
  return refreshing;
}

async function parse(res: Response) {
  if (res.status === 204) return null;
  const ct = res.headers.get("content-type") || "";
  const body = ct.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    const e = (body as { error?: { code: string; message: string; details?: { field: string; message: string }[]; request_id?: string } })?.error;
    throw new ApiError(res.status, e?.code || "HTTP_ERROR", e?.message || FRIENDLY.INTERNAL_ERROR, e?.details, e?.request_id);
  }
  return body;
}

export async function raw(path: string, init: RequestInit = {}, retry = true): Promise<Response> {
  const s = session.get();
  const headers = new Headers(init.headers);
  if (s) headers.set("Authorization", `Bearer ${s.access_token}`);
  if (init.body && !(init.body instanceof FormData)) headers.set("Content-Type", "application/json");
  let res: Response;
  try { res = await fetch(`${BASE}${path}`, { ...init, headers }); }
  catch { throw new ApiError(0, "NETWORK", FRIENDLY.NETWORK); }
  if (res.status === 401 && retry && s) {
    const next = await refresh();
    if (next) return raw(path, init, false);
  }
  return res;
}

export async function api<T = unknown>(path: string, init: RequestInit = {}): Promise<T> {
  return (await parse(await raw(path, init))) as T;
}
export const get = <T,>(path: string) => api<T>(path);
export const post = <T,>(path: string, body?: unknown) => api<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });
export const patch = <T,>(path: string, body?: unknown) => api<T>(path, { method: "PATCH", body: JSON.stringify(body) });
export const upload = <T,>(path: string, form: FormData) => api<T>(path, { method: "POST", body: form });

export async function login(email: string, password: string) {
  const s = (await parse(await fetch(`${BASE}/auth/login`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) }).catch(() => { throw new ApiError(0, "NETWORK", FRIENDLY.NETWORK); }))) as Session;
  session.set(s);
  return s;
}
export interface RegisterBody {
  mode: "create_org" | "join"; full_name: string; email: string; password: string; confirm_password: string;
  organization_name?: string; invite_token?: string; setup_token?: string;
}
export interface RegisterResult { status: "ACTIVE" | "PENDING"; message: string; session: Session | null; user: User | null }
/** Public sign-up. The server decides role/organization/status; the client only submits identity + invitation/setup proof. */
export async function register(body: RegisterBody): Promise<RegisterResult> {
  const r = (await parse(await fetch(`${BASE}/auth/register`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => { throw new ApiError(0, "NETWORK", FRIENDLY.NETWORK); }))) as RegisterResult;
  if (r.session) session.set(r.session);
  return r;
}
export interface InvitationInfo { organization_name: string; role: Role; email: string; requires_approval: boolean; expires_at: string }
export async function lookupInvitation(token: string): Promise<InvitationInfo> {
  return (await parse(await fetch(`${BASE}/auth/invitation?token=${encodeURIComponent(token)}`).catch(() => { throw new ApiError(0, "NETWORK", FRIENDLY.NETWORK); }))) as InvitationInfo;
}
export async function demoAccounts(): Promise<{ password: string; accounts: { email: string; label: string }[] } | null> {
  try { const r = await fetch(`${BASE}/auth/demo-accounts`); return r.ok ? await r.json() : null; } catch { return null; }
}
export async function logout() {
  const s = session.get();
  if (s) await fetch(`${BASE}/auth/logout`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ refresh_token: s.refresh_token }) }).catch(() => undefined);
  session.set(null);
}
export async function download(path: string, filename: string) {
  const res = await raw(path);
  if (!res.ok) throw new ApiError(res.status, "DOWNLOAD", "We couldn't download that file.");
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url; a.download = filename; a.click();
  URL.revokeObjectURL(url);
}
export function errorMessage(e: unknown): string {
  if (e instanceof ApiError) return e.status === 0 ? FRIENDLY.NETWORK : e.message;
  return FRIENDLY.INTERNAL_ERROR;
}
export const API_BASE = BASE;
