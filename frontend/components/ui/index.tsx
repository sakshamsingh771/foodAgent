"use client";
import * as Dialog from "@radix-ui/react-dialog";
import * as Popover from "@radix-ui/react-popover";
import { AlertTriangle, Inbox, Loader2 } from "lucide-react";
import { forwardRef } from "react";
import { cn } from "@/lib/utils";

type BtnProps = React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger"; size?: "sm" | "md"; loading?: boolean };
export const Button = forwardRef<HTMLButtonElement, BtnProps>(function Button({ className, variant = "primary", size = "md", loading, disabled, children, ...p }, ref) {
  const v = {
    primary: "bg-brand text-brand-fg hover:opacity-90", secondary: "bg-surface border border-border hover:bg-subtle",
    ghost: "hover:bg-subtle", danger: "bg-danger text-white hover:opacity-90",
  }[variant];
  return (
    <button ref={ref} disabled={disabled || loading} className={cn("inline-flex items-center justify-center gap-2 rounded-md font-medium transition disabled:cursor-not-allowed disabled:opacity-50", size === "sm" ? "min-h-9 px-3 text-sm" : "min-h-11 px-4 text-sm", v, className)} {...p}>
      {loading && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}{children}
    </button>
  );
});

export const Card = ({ className, ...p }: React.HTMLAttributes<HTMLDivElement>) => <div className={cn("rounded-lg border border-border bg-surface shadow-card", className)} {...p} />;
export const CardHeader = ({ title, action, sub }: { title: string; action?: React.ReactNode; sub?: string }) => (
  <div className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
    <div><h2 className="text-base font-semibold">{title}</h2>{sub && <p className="text-xs text-muted">{sub}</p>}</div>{action}
  </div>
);

export const Input = forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(function Input({ className, ...p }, ref) {
  return <input ref={ref} className={cn("min-h-11 w-full rounded-md border border-border bg-surface px-3 text-sm placeholder:text-muted/70 disabled:opacity-60", className)} {...p} />;
});
export const Select = forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(function Select({ className, ...p }, ref) {
  return <select ref={ref} className={cn("min-h-11 rounded-md border border-border bg-surface px-3 text-sm", className)} {...p} />;
});
export const Textarea = forwardRef<HTMLTextAreaElement, React.TextareaHTMLAttributes<HTMLTextAreaElement>>(function Textarea({ className, ...p }, ref) {
  return <textarea ref={ref} className={cn("min-h-20 w-full rounded-md border border-border bg-surface px-3 py-2 text-sm", className)} {...p} />;
});
export function Field({ label, error, children, hint }: { label: string; error?: string; children: React.ReactNode; hint?: string }) {
  return (
    <label className="block space-y-1.5 text-sm">
      <span className="font-medium">{label}</span>{children}
      {hint && !error && <span className="block text-xs text-muted">{hint}</span>}
      {error && <span role="alert" className="block text-xs text-danger">{error}</span>}
    </label>
  );
}

const TONES = { safe: "bg-safe/12 text-safe", warn: "bg-warn/14 text-warn", danger: "bg-danger/12 text-danger", info: "bg-info/12 text-info", neutral: "bg-subtle text-muted" };
export const Badge = ({ tone = "neutral", className, ...p }: React.HTMLAttributes<HTMLSpanElement> & { tone?: keyof typeof TONES }) => (
  <span className={cn("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium", TONES[tone], className)} {...p} />
);

export const Skeleton = ({ className }: { className?: string }) => <div aria-hidden className={cn("animate-pulse rounded-md bg-subtle", className)} />;
export function LoadingState({ rows = 4 }: { rows?: number }) {
  return <div role="status" aria-label="Loading" className="space-y-3 p-4">{Array.from({ length: rows }).map((_, i) => <Skeleton key={i} className="h-12" />)}</div>;
}
export function EmptyState({ title, body, action }: { title: string; body?: string; action?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 px-6 py-12 text-center">
      <Inbox className="h-8 w-8 text-muted" aria-hidden /><p className="font-medium">{title}</p>
      {body && <p className="max-w-sm text-sm text-muted">{body}</p>}{action}
    </div>
  );
}
export function ErrorState({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="flex flex-col items-center gap-3 px-6 py-12 text-center">
      <AlertTriangle className="h-8 w-8 text-danger" aria-hidden /><p className="max-w-sm text-sm">{message}</p>
      {onRetry && <Button variant="secondary" size="sm" onClick={onRetry}>Try again</Button>}
    </div>
  );
}
export function PageHeader({ title, sub, actions }: { title: string; sub?: string; actions?: React.ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div><h1 className="text-2xl font-semibold sm:text-3xl">{title}</h1>{sub && <p className="mt-1 text-sm text-muted">{sub}</p>}</div>
      {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
    </div>
  );
}

export function ConfirmDialog({ open, onOpenChange, title, body, confirmLabel, danger, loading, onConfirm, children }: {
  open: boolean; onOpenChange: (o: boolean) => void; title: string; body?: string; confirmLabel: string; danger?: boolean; loading?: boolean; onConfirm: () => void; children?: React.ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 z-50 bg-black/45" />
        <Dialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100vw-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg border border-border bg-surface p-5 shadow-pop">
          <Dialog.Title className="font-display text-lg font-semibold">{title}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-muted">{body}</Dialog.Description>
          {children && <div className="mt-4">{children}</div>}
          <div className="mt-5 flex justify-end gap-2">
            <Dialog.Close asChild><Button variant="secondary">Cancel</Button></Dialog.Close>
            <Button variant={danger ? "danger" : "primary"} loading={loading} onClick={onConfirm}>{confirmLabel}</Button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export { Dialog, Popover };
