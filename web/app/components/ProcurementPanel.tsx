"use client";

import { ProcurementResult, fmt } from "../lib/api";
import Panel from "./Panel";
import RecommendedActions from "./RecommendedActions";
import Sankey from "./Sankey";
import { Term } from "./Term";

/** The λ slider is the interactive centrepiece: λ scales how much the LP
 *  pays to avoid a high-CRI corridor. Re-solves server-side on every drag
 *  (the distance matrix is cached, so a solve is ~150ms). */
export default function ProcurementPanel({
  data,
  baseline,
  lambdaRisk,
  onLambdaChange,
  antiConcentration,
  onAntiConcentrationChange,
  operatorByRefinery,
  loading,
}: {
  data: ProcurementResult | null;
  baseline: ProcurementResult | null;
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
      subtitle={
        <>
          Source → refinery <Term id="LP">allocation LP</Term> · minimise cost +{" "}
          <Term id="lambda">λ</Term> · <Term id="CRI">CRI</Term>, with a per-country
          concentration cap
        </>
      }
      asOf={data ? `λ=${lambdaRisk}` : undefined}
      caveat={data?.caveat}
      className="min-h-[560px] h-full"
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
                <Term id="lambda">λ · risk aversion</Term>
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

        <div className="grid grid-cols-2 gap-2">
          <Stat label="allocated" value={`${fmt(data?.total_allocated_kbd, 0)} kbd`} />
          <Stat
            label="largest supplier"
            value={top ? `${top[0]} ${(top[1] * 100).toFixed(0)}%` : "—"}
            tone={cap != null && top && top[1] * 100 >= cap - 0.5 ? "warn" : undefined}
          />
        </div>

        <p className="text-[11.5px] text-[#c2cfe0] leading-snug">
          Band height = allocated <Term id="kbd">volume</Term>. Left = source country, right =
          refinery operator; ribbon width between them = <Term id="kbd">kbd</Term> flowing on that
          source → operator pair.
        </p>

        <div className="flex-1 min-h-0 overflow-hidden">
          <Sankey
            allocation={data?.allocation ?? []}
            operatorByRefinery={operatorByRefinery}
            height={300}
          />
        </div>

        <RecommendedActions allocation={data?.allocation ?? []} baseline={baseline?.allocation ?? []} />
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
