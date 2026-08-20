"use client";

import { useState } from "react";

/** A judge gets ~90 seconds. This strip is the one-sentence-per-panel map
 *  so they know what question each panel answers before they start
 *  reading numbers. Dismissible so it doesn't compete with the dashboard
 *  once someone's oriented. */
export default function OnboardingStrip() {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;
  return (
    <div className="panel px-4 py-3 mb-4 flex justify-between items-start gap-4">
      <p className="text-[12.5px] text-[#c2cfe0] leading-relaxed">
        <b className="text-[var(--foreground)]">How to read this — each panel answers one question.</b>{" "}
        <span className="text-[var(--muted)]">Map</span> = who supplies India and through which
        corridor. <span className="text-[var(--muted)]">Risk Index</span> = is a corridor
        disrupted, and did we see it coming before satellites confirmed it.{" "}
        <span className="text-[var(--muted)]">Reallocation</span> = what to buy instead, and from
        where. <span className="text-[var(--muted)]">Impact cascade</span> = what a closure costs,
        end to end. <span className="text-[var(--muted)]">Reserve</span> = how long until the
        strategic stockpile runs out. <span className="text-[var(--muted)]">Backtest</span> = proof
        this isn&apos;t guessing — scored against the real 2026 Hormuz closure it never trained on.
      </p>
      <button
        onClick={() => setDismissed(true)}
        className="text-[var(--muted)] hover:text-[var(--foreground)] shrink-0 text-[13px] leading-none px-1"
        aria-label="Dismiss"
      >
        ✕
      </button>
    </div>
  );
}
