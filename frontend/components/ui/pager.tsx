"use client";
import { Button } from "@/components/ui";

export function Pager({ page, pages, total, onPage }: { page: number; pages: number; total: number; onPage: (p: number) => void }) {
  return (
    <div className="mt-4 flex items-center justify-between text-sm text-muted">
      <span>{total} total</span>
      <div className="flex items-center gap-2"><Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button><span className="tabular">Page {page} of {pages}</span><Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button></div>
    </div>
  );
}
