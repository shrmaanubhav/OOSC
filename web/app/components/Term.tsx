"use client";

import { useState } from "react";

/** Every acronym on this dashboard (CRI, λ, kbd, MMT, AUC, O/S/E/X,
 *  chokepoint6...) is jargon a judge hasn't seen before. One glossary,
 *  wrapped around first-use in each panel, instead of teaching the
 *  vocabulary nowhere and assuming it. */
export const GLOSSARY: Record<string, string> = {
  CRI: "Corridor Risk Index (0-100). Composite score for how disrupted a shipping chokepoint is right now.",
  lambda: "Risk-aversion dial. 0 = cheapest crude regardless of route risk. High = actively avoid risky corridors even if pricier.",
  kbd: "Thousand barrels per day - a flow rate.",
  "kbd-d": "Thousand-barrels-per-day-days - a flow rate multiplied by how many days it's sustained. Used for cumulative shortfall.",
  MMT: "Million Metric Tonnes - the standard unit for crude oil storage volumes.",
  AUC: "Area Under Curve (0-1). How well the risk score predicted real disruptions, tested on data it never trained on. 0.5 = coin flip, 1.0 = perfect.",
  O: "Observed disruption - from real satellite ship-tracking (AIS), 2-9 days delayed by nature.",
  S: "Signal pressure - from live news coverage volume and tone. Updates same-day.",
  E: "Event severity - specific incidents (attacks, closures, truces) extracted from news, weighted by recency.",
  X: "Exposure - how much of India's crude imports flow through this corridor.",
  chokepoint6: "IMF PortWatch's ID for the Strait of Hormuz.",
  chokepoint4: "IMF PortWatch's ID for the Bab el-Mandeb Strait.",
  SPR: "Strategic Petroleum Reserve - India's 5.33 MMT emergency stockpile (~9.5 days of cover). Smaller than India's ~74 days of total national storage.",
  GDELT: "Global news-monitoring dataset used for the S and E risk components.",
  LP: "Linear program - the solver that assigns each crude source to a refinery to minimise cost + risk.",
};

export function Term({ id, children }: { id: keyof typeof GLOSSARY; children: React.ReactNode }) {
  const [open, setOpen] = useState(false);
  const def = GLOSSARY[id];
  if (!def) return <>{children}</>;
  return (
    <span className="relative inline-block">
      <span
        className="border-b border-dotted border-[var(--muted)] cursor-help"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
      >
        {children}
      </span>
      {open && (
        <span className="absolute z-50 left-0 top-full mt-1 w-64 rounded-md bg-[var(--panel-2)] border border-[var(--border)] p-2 text-[11px] leading-snug text-[var(--foreground)] shadow-lg">
          {def}
        </span>
      )}
    </span>
  );
}
