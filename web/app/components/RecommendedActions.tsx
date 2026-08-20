"use client";

import { Allocation, fmt } from "../lib/api";

/** The brief asks for a plan a procurement team can act on within hours.
 *  The Sankey shows the LP's solution as an aggregate; this turns the same
 *  solution into line items — the artifact that actually reads as an
 *  action rather than a chart. Derived entirely from the allocation the
 *  LP already returned, not a new computation. */
export default function RecommendedActions({ allocation }: { allocation: Allocation[] }) {
  if (allocation.length === 0) return null;

  const rows = [...allocation]
    .filter((a) => a.kbd > 50) // hide LP noise below a real cargo size
    .sort((a, b) => b.kbd - a.kbd)
    .slice(0, 5);

  return (
    <div className="mt-3 pt-3 border-t border-[var(--border)]">
      <p className="text-[11px] text-[var(--muted)] uppercase tracking-wide mb-2">
        Recommended actions — top allocations from this solve
      </p>
      <div className="space-y-1.5">
        {rows.map((r, i) => (
          <div
            key={i}
            className="flex items-center gap-2 text-[11.5px] bg-[var(--panel-2)] border border-[var(--border)] rounded px-2.5 py-1.5"
          >
            <span className="mono text-[var(--accent)] shrink-0 w-16 text-right">
              {fmt(r.kbd, 0)} kbd
            </span>
            <span className="text-[var(--muted)]">·</span>
            <span className="truncate">
              <b className="text-[var(--foreground)]">{r.source}</b>{" "}
              <span className="text-[var(--muted)]">({r.country})</span> → {r.refinery}
            </span>
            <span className="mono text-[10px] text-[var(--muted)] ml-auto shrink-0">
              via {r.corridor_id === "none" ? "no corridor" : r.corridor_id}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
