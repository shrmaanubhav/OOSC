"use client";

import { ProcurementResult, fmt } from "../lib/api";
import Panel from "./Panel";
import Sankey from "./Sankey";

/** The λ slider is the interactive centrepiece: λ scales how much the LP
 *  pays to avoid a high-CRI corridor. Re-solves server-side on every drag
 *  (the distance matrix is cached, so a solve is ~150ms). */
export default function ProcurementPanel({
  data,
  lambdaRisk,
  onLambdaChange,
  antiConcentration,
  onAntiConcentrationChange,
  operatorByRefinery,
  loading,
}: {
  data: ProcurementResult | null;
  lambdaRisk: number;
  onLambdaChange: (v: number) => void;
  antiConcentration: boolean;
  onAntiConcentrationChange: (v: boolean) => void;
  operatorByRefinery: Record<string, string>;
  loading: boolean;
}) {
  const shares = Object.entries(data?.country_shares ?? {}).sort((a, b) => b[1] - a[1]);
  const top = shares[0];
  const cap = data?.concentration_cap_pct ?? null;

  return (
    <Panel
      title="Procurement reallocation"
      subtitle="Source → refinery allocation LP · minimise cost + λ · CRI, with a per-country concentration cap"
      asOf={data ? `λ=${lambdaRisk}` : undefined}
      caveat={data?.caveat}
      className="min-h-[420px]"
      right={
        loading ? <span className="asof">solving…</span> : (
          <span className="asof mono">{data?.status ?? ""}</span>
        )
      }
    >
      <div className="flex flex-col h-full gap-3">
        <div className="grid grid-cols-[1fr_auto] gap-4 items-center">
          <div>
            <div className="flex items-baseline justify-between mb-1">
              <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">
                λ · risk aversion
              </label>
              <span className="mono text-[12px] text-[var(--accent)]">{lambdaRisk}</span>
            </div>
            <input
              type="range"
              min={0}
              max={200}
              step={5}
              value={lambdaRisk}
              onChange={(e) => onLambdaChange(Number(e.target.value))}
              className="w-full"
            />
            <div className="flex justify-between asof mt-0.5">
              <span>cost only</span>
              <span>avoid risky corridors at any cost</span>
            </div>
          </div>
          <label className="flex items-center gap-2 text-[11px] text-[var(--muted)] cursor-pointer select-none">
            <input
              type="checkbox"
              checked={antiConcentration}
              onChange={(e) => onAntiConcentrationChange(e.target.checked)}
              className="accent-[var(--accent)]"
            />
            anti-concentration cap
            {cap != null && <span className="mono text-[var(--foreground)]">{cap}%</span>}
          </label>
        </div>

        <div className="grid grid-cols-3 gap-2">
          <Stat label="allocated" value={`${fmt(data?.total_allocated_kbd, 0)} kbd`} />
          <Stat
            label="shortfall"
            value={`${fmt(data?.total_shortfall_kbd, 0)} kbd`}
            tone={data && data.total_shortfall_kbd > 0 ? "bad" : "ok"}
          />
          <Stat
            label="largest supplier"
            value={top ? `${top[0]} ${(top[1] * 100).toFixed(0)}%` : "—"}
            tone={cap != null && top && top[1] * 100 >= cap - 0.5 ? "warn" : undefined}
          />
        </div>

        <div className="flex-1 min-h-0 overflow-hidden">
          <Sankey
            allocation={data?.allocation ?? []}
            operatorByRefinery={operatorByRefinery}
            height={260}
          />
        </div>
      </div>
    </Panel>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "ok" | "warn" | "bad";
}) {
  const color =
    tone === "bad" ? "var(--bad)" : tone === "warn" ? "var(--warn)" : tone === "ok" ? "var(--ok)" : "var(--foreground)";
  return (
    <div className="bg-[var(--panel-2)] border border-[var(--border)] rounded-md px-3 py-2">
      <div className="asof uppercase tracking-wide">{label}</div>
      <div className="mono text-[15px] mt-0.5" style={{ color }}>
        {value}
      </div>
    </div>
  );
}
