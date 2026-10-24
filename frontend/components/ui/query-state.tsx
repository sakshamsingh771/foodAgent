"use client";
import type { UseQueryResult } from "@tanstack/react-query";
import { errorMessage } from "@/lib/api";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui";

/** Renders loading / error / empty states for a query so no screen is ever blank. */
export function QueryBoundary<T>({ q, isEmpty, empty, children, rows }: {
  q: UseQueryResult<T>; isEmpty?: (d: T) => boolean; empty?: { title: string; body?: string; action?: React.ReactNode }; rows?: number; children: (d: T) => React.ReactNode;
}) {
  if (q.isPending) return <LoadingState rows={rows} />;
  if (q.isError) return <ErrorState message={errorMessage(q.error)} onRetry={() => q.refetch()} />;
  if (isEmpty?.(q.data)) return <EmptyState title={empty?.title ?? "Nothing here yet"} body={empty?.body} action={empty?.action} />;
  return <>{children(q.data)}</>;
}
