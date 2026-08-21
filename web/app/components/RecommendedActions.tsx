"use client";

import { Allocation, fmt } from "../lib/api";

// Standard VLCC cargo size, ~2 million bbl (270,000-320,000 DWT crude
// tanker) -- the industry-standard round figure used to convert an LP's
// kbd allocation RATE into a cargo count a procurement desk actually
// schedules against.
const VLCC_BBL = 2_000_000;
const WINDOW_DAYS = 30;

function cargoesPerWindow(kbd: number): number {
  const total_bbl = kbd * 1000 * WINDOW_DAYS;
  return total_bbl / VLCC_BBL;
}

/** The brief asks for a plan a procurement team can act on within hours.
 *  The Sankey shows the LP's solution as an aggregate; this turns the same
 *  solution into line items sized the way a desk actually schedules
 *  cargoes -- VLCC count over a 30-day window, real transit time (from the
 *  LP's own searoute distance), and the delta against the status-quo
 *  baseline solve (severity=0, λ=0), not just the raw kbd rate. Derived
 *  entirely from data the LP/backend already returned, not a new model. */
export default function RecommendedActions({
  allocation,
  baseline,
}: {
  allocation: Allocation[];
  baseline: Allocation[];
}) {
  if (allocation.length === 0) return null;

  const baselineByPair = new Map(
    baseline.map((b) => [`${b.source}::${b.refinery}`, b.kbd])
  );

  const rows = [...allocation]
    .filter((a) => a.kbd > 50) // hide LP noise below a real cargo size
    .sort((a, b) => b.kbd - a.kbd)
    .slice(0, 5)
    .map((r) => {
      const baseKbd = baselineByPair.get(`${r.source}::${r.refinery}`) ?? 0;
      return { ...r, deltaKbd: r.kbd - baseKbd, isNewPair: baseKbd === 0 };
    });

  return (
    <div className="mt-3 pt-3 border-t border-[var(--border)]">
      <p className="text-[11px] text-[var(--muted)] uppercase tracking-wide mb-2">
        Recommended actions — top allocations from this solve, vs. status-quo sourcing
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
            <span className="truncate flex-1">
              <b className="text-[var(--foreground)]">{r.source}</b>{" "}
              <span className="text-[var(--muted)]">({r.country})</span> → {r.refinery}
            </span>
            <span
              className="mono text-[10.5px] shrink-0"
              style={{ color: r.deltaKbd > 0 ? "var(--ok)" : r.deltaKbd < 0 ? "var(--bad)" : "var(--muted)" }}
              title="vs. status-quo sourcing (severity=0, λ=0 solve)"
            >
              {r.isNewPair ? "new" : `${r.deltaKbd >= 0 ? "+" : ""}${fmt(r.deltaKbd, 0)} kbd`}
            </span>
            <span className="mono text-[10px] text-[var(--muted)] shrink-0" title="≈ VLCCs/month at this rate, 2M bbl/cargo">
              ≈{fmt(cargoesPerWindow(r.kbd), 1)} VLCC/mo
            </span>
            <span className="mono text-[10px] text-[var(--muted)] shrink-0" title="transit time, real sea-route distance">
              {fmt(r.transit_days, 1)}d transit
            </span>
            <span className="mono text-[10px] text-[var(--muted)] shrink-0">
              via {r.corridor_id === "none" ? "no corridor" : r.corridor_id}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
