"use client";
import * as Tooltip from "@radix-ui/react-tooltip";
import { motion, useReducedMotion } from "framer-motion";
import { Check, HelpCircle, ShieldAlert, X } from "lucide-react";
import { Badge, Popover } from "@/components/ui";
import { cn, fmtDuration, fmtKg, titleCase } from "@/lib/utils";
import type { FreshState, Method, Option } from "@/types/api";

const STATE = {
  SAFE: { label: "Safe", color: "hsl(var(--safe))", tone: "safe" as const },
  ACT_SOON: { label: "Act soon", color: "hsl(var(--warn))", tone: "warn" as const },
  LOSS_IMMINENT: { label: "Loss imminent", color: "hsl(var(--danger))", tone: "danger" as const },
};

export function FreshnessRing({ percent, remainingMinutes, state, size = 112, compact = false }: { percent: number; remainingMinutes: number; state: FreshState; size?: number; compact?: boolean }) {
  const reduce = useReducedMotion();
  const s = STATE[state], r = 44, c = 2 * Math.PI * r, pct = Math.max(0, Math.min(100, percent));
  const label = `Freshness ${Math.round(pct)} percent. ${s.label}. ${fmtDuration(remainingMinutes)} remaining.`;
  return (
    <Tooltip.Provider delayDuration={150}>
      <Tooltip.Root>
        <Tooltip.Trigger asChild>
          <div role="img" aria-label={label} tabIndex={0} className="inline-flex flex-col items-center gap-1" style={{ width: size }}>
            <svg viewBox="0 0 100 100" width={size} height={size} aria-hidden>
              <circle cx="50" cy="50" r={r} fill="none" stroke="hsl(var(--border))" strokeWidth="9" />
              <motion.circle cx="50" cy="50" r={r} fill="none" stroke={s.color} strokeWidth="9" strokeLinecap="round" transform="rotate(-90 50 50)"
                strokeDasharray={c} initial={reduce ? false : { strokeDashoffset: c }} animate={{ strokeDashoffset: c * (1 - pct / 100) }} transition={{ duration: reduce ? 0 : 0.7, ease: "easeOut" }} />
              <text x="50" y={compact ? 55 : 49} textAnchor="middle" fontSize="20" fontWeight="600" fill="hsl(var(--fg))" className="tabular">{Math.round(pct)}%</text>
              {!compact && <text x="50" y="64" textAnchor="middle" fontSize="8.5" fill="hsl(var(--muted))">Freshness</text>}
            </svg>
            {!compact && <><span className="text-sm font-medium" style={{ color: s.color }}>{s.label}</span><span className="text-xs text-muted tabular">{fmtDuration(remainingMinutes)} remaining</span></>}
          </div>
        </Tooltip.Trigger>
        <Tooltip.Portal>
          <Tooltip.Content sideOffset={6} className="z-50 max-w-60 rounded-md border border-border bg-surface px-3 py-2 text-xs shadow-pop">
            Rule-based window: time left until the recorded safe-until time, as a share of the lot&apos;s full window. It is not a food-safety certification.
          </Tooltip.Content>
        </Tooltip.Portal>
      </Tooltip.Root>
    </Tooltip.Provider>
  );
}

export const FreshBadge = ({ state }: { state: FreshState }) => <Badge tone={STATE[state].tone}>{STATE[state].label}</Badge>;

const METHOD_HELP: Record<Method, string> = {
  RULE: "A fixed, deterministic rule. No learning involved.", STATISTICAL: "Calculated from historical rates stored in the system.",
  ML: "Output of a trained machine-learning model.", LLM: "Text produced by a language model.", SIMULATED: "Modelled from the inputs you set. Not a real outcome.",
};
export const MethodBadge = ({ method }: { method: Method }) => <Badge tone="neutral" title={METHOD_HELP[method]} className="uppercase tracking-wide">{method}</Badge>;

export function ConfidenceMeter({ value, factors, simulated, label = "Recovery confidence" }: { value: number; factors?: Record<string, number | boolean>; simulated?: boolean; label?: string }) {
  const pct = Math.round(value * 100);
  const color = pct >= 70 ? "bg-safe" : pct >= 50 ? "bg-warn" : "bg-danger";
  const rows: [string, string][] = factors ? [
    ["Historical acceptance", `${Math.round(Number(factors.acceptance ?? 0) * 100)}%`],
    ["Time margin", `${factors.margin_minutes ?? 0} min to spare`],
    ["Freshness", `factor ${Number(factors.freshness_factor ?? 0).toFixed(2)}`],
    ["Evidence completeness", `factor ${Number(factors.evidence_factor ?? 0).toFixed(2)}`],
    ["Pickup feasibility", `${factors.needed_minutes ?? 0} min needed`],
  ] : [];
  return (
    <div>
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{label}</span>
        <Popover.Root>
          <Popover.Trigger className="inline-flex min-h-9 items-center gap-1 rounded text-xs text-info underline-offset-2 hover:underline"><HelpCircle className="h-3.5 w-3.5" aria-hidden />Why?</Popover.Trigger>
          <Popover.Portal>
            <Popover.Content sideOffset={6} className="z-50 w-72 rounded-lg border border-border bg-surface p-3 text-sm shadow-pop">
              <p className="font-medium">How this estimate is built</p>
              {rows.length > 0 && <dl className="mt-2 space-y-1">{rows.map(([k, v]) => <div key={k} className="flex justify-between gap-2"><dt className="text-muted">{k}</dt><dd className="tabular">{v}</dd></div>)}</dl>}
              <p className="mt-2 text-xs text-muted">{simulated ? "This number is simulated from the inputs you set." : "Estimated from stored history and current conditions."} It supports a decision; it is not a safety guarantee.</p>
            </Popover.Content>
          </Popover.Portal>
        </Popover.Root>
      </div>
      <div className="mt-1.5 flex items-center gap-3">
        <div className="h-2.5 flex-1 overflow-hidden rounded-full bg-subtle" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label={label}>
          <div className={cn("h-full rounded-full transition-all", color)} style={{ width: `${pct}%` }} />
        </div>
        <span className="w-10 text-right text-sm font-semibold tabular">{pct}%</span>
      </div>
      {simulated && <p className="mt-1 text-xs text-muted">Simulated</p>}
    </div>
  );
}

export function RecoveryLadder({ options, selected, onSelect, disabled }: { options: Option[]; selected?: string | null; onSelect?: (o: Option) => void; disabled?: boolean }) {
  return (
    <ol className="space-y-2" aria-label="Recovery ladder">
      {options.map((o, i) => {
        const active = selected === o.rung;
        return (
          <li key={o.rung}>
            <div className={cn("rounded-lg border p-3", active ? "border-brand ring-1 ring-brand" : "border-border", !o.eligible && "bg-subtle/60")}>
              <div className="flex flex-wrap items-center gap-2">
                <span className={cn("grid h-8 w-8 place-items-center rounded-md text-sm font-semibold", o.eligible ? "bg-brand text-brand-fg" : "bg-border text-muted")}>{o.rung}</span>
                <span className="font-medium">{o.label}</span>
                {o.is_recommended && <Badge tone="safe"><Check className="h-3 w-3" aria-hidden />Recommended</Badge>}
                {o.is_hedge && <Badge tone="info">Backup</Badge>}
                {!o.eligible && <Badge tone="neutral"><X className="h-3 w-3" aria-hidden />Not available</Badge>}
                <span className="ml-auto"><MethodBadge method={o.method} /></span>
              </div>
              <p className="mt-2 text-sm text-muted">{o.reason}</p>
              {o.eligible && (
                <div className="mt-2 grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
                  <ConfidenceMeter value={o.confidence} factors={o.factors} />
                  <div className="text-sm sm:text-right"><div className="text-xs text-muted">Estimated recovery</div><div className="font-semibold tabular">{fmtKg(o.est_recovery_kg)}</div></div>
                </div>
              )}
              {o.eligible && o.recipient_name && <p className="mt-2 text-xs text-muted">Next action: offer to <strong className="text-fg">{o.recipient_name}</strong></p>}
              {o.eligible && o.requires_food_safety_review && <p className="mt-1 flex items-center gap-1 text-xs text-warn"><ShieldAlert className="h-3.5 w-3.5" aria-hidden />Human-consumption pathway: a person must review condition evidence before approval.</p>}
              {onSelect && o.eligible && <button disabled={disabled} onClick={() => onSelect(o)} className="mt-2 min-h-9 rounded-md border border-border px-3 text-sm hover:bg-subtle disabled:opacity-50" aria-pressed={active}>{active ? "Selected" : `Choose ${o.rung}`}</button>}
            </div>
            {i < options.length - 1 && <div aria-hidden className="ml-4 h-3 border-l-2 border-dashed border-border" />}
          </li>
        );
      })}
    </ol>
  );
}

export const CASE_TONE: Record<string, "safe" | "warn" | "danger" | "info" | "neutral"> = {
  pending_approval: "warn", awaiting_recipient: "info", accepted: "info", pickup_scheduled: "info", in_transit: "info", completed: "safe", rejected: "danger", cancelled: "neutral",
  scheduled: "info", assigned: "info", arrived: "info", handed_over: "safe", pending: "neutral",
};
export const StatusBadge = ({ status }: { status: string }) => <Badge tone={CASE_TONE[status] ?? "neutral"}>{titleCase(status)}</Badge>;
