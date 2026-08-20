"use client";

import {
  Bar,
  BarChart,
  Cell,
  CartesianGrid,
  LabelList,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { ScenarioResult, fmt, num } from "../lib/api";
import Panel from "./Panel";

/** Cascade impact as a waterfall: baseline crude price, the modeled shock,
 *  the resulting level, then the macro consequences that follow from it.
 *  Recharts has no waterfall primitive, so the standard trick applies --
 *  a transparent "base" bar carries each floating bar up to its start. */
export default function ImpactWaterfall({
  data,
  severity,
  onSeverityChange,
  compliance,
  onComplianceChange,
  secondCorridor,
  onSecondCorridorChange,
  loading,
}: {
  data: ScenarioResult | null;
  severity: number;
  onSeverityChange: (v: number) => void;
  compliance: boolean;
  onComplianceChange: (v: boolean) => void;
  secondCorridor: boolean;
  onSecondCorridorChange: (v: boolean) => void;
  loading: boolean;
}) {
  const p0 = data?.price_baseline_usd_bbl ?? 0;
  const p1 = data?.price_usd_bbl ?? 0;
  const delta = p1 - p0;

  const bars = data
    ? [
        { name: "Baseline", base: 0, value: p0, kind: "total" as const },
        { name: "Shock Δ", base: p0, value: delta, kind: "delta" as const },
        { name: "Scenario", base: 0, value: p1, kind: "total" as const },
      ]
    : [];

  const runCutCount = Object.keys(data?.run_cuts ?? {}).length;

  return (
    <Panel
      title="Impact cascade"
      subtitle="Corridor shock → reroute attempt → refinery cuts → price → India macro"
      asOf={data ? `severity ${severity.toFixed(2)}` : undefined}
      caveat={data?.confidence?.macro}
      className="min-h-[400px]"
      right={loading ? <span className="asof">running…</span> : undefined}
    >
      <div className="flex flex-col h-full gap-3">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <div className="flex-1 min-w-[190px]">
            <div className="flex items-baseline justify-between mb-1">
              <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">
                Hormuz severity
              </label>
              <span className="mono text-[12px] text-[var(--accent)]">
                {severity.toFixed(2)}
              </span>
            </div>
            <input
              type="range"
              min={0}
              max={1}
              step={0.05}
              value={severity}
              onChange={(e) => onSeverityChange(Number(e.target.value))}
              className="w-full"
            />
          </div>
          <label className="flex items-center gap-2 text-[11px] text-[var(--muted)] cursor-pointer select-none">
            <input
              type="checkbox"
              checked={compliance}
              onChange={(e) => onComplianceChange(e.target.checked)}
              className="accent-[var(--accent)]"
            />
            sanctions compliance
          </label>
          <label className="flex items-center gap-2 text-[11px] text-[var(--muted)] cursor-pointer select-none">
            <input
              type="checkbox"
              checked={secondCorridor}
              onChange={(e) => onSecondCorridorChange(e.target.checked)}
              className="accent-[var(--accent)]"
            />
            + Bab el-Mandeb closed
          </label>
        </div>

        <div className="h-[170px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={bars} margin={{ top: 16, right: 8, bottom: 0, left: -20 }}>
              <CartesianGrid stroke="#223044" strokeDasharray="2 4" vertical={false} />
              <XAxis dataKey="name" tick={{ fill: "#7d8ea6", fontSize: 10 }} stroke="#223044" />
              <YAxis
                tick={{ fill: "#7d8ea6", fontSize: 10 }}
                stroke="#223044"
                width={46}
                unit="$"
              />
              <Tooltip
                cursor={{ fill: "#ffffff08" }}
                contentStyle={{
                  background: "#111823",
                  border: "1px solid #223044",
                  borderRadius: 8,
                  fontSize: 12,
                }}
                formatter={(v, n) =>
                  n === "base" ? [null, null] : [`$${fmt(num(v), 2)}/bbl`, "value"]
                }
              />
              <Bar dataKey="base" stackId="w" fill="transparent" isAnimationActive={false} />
              <Bar dataKey="value" stackId="w" isAnimationActive={false} radius={[3, 3, 0, 0]}>
                {bars.map((b, i) => (
                  <Cell key={i} fill={b.kind === "total" ? "#4c9aff" : "#e5484d"} />
                ))}
                <LabelList
                  dataKey="value"
                  position="top"
                  formatter={(v) => {
                    const n = num(v);
                    return n == null ? "" : `$${n.toFixed(1)}`;
                  }}
                  style={{ fill: "#dbe4f0", fontSize: 10 }}
                />
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <Metric
            label="shortfall"
            value={`${fmt(data?.total_shortfall_kbd, 0)} kbd`}
            tone={data && data.total_shortfall_kbd > 0 ? "bad" : "ok"}
          />
          <Metric
            label="refineries cut"
            value={`${runCutCount}`}
            tone={runCutCount > 0 ? "bad" : "ok"}
          />
          <Metric
            label="import bill Δ (yr)"
            value={`$${fmt((data?.macro.import_bill_delta_annualized_usd ?? 0) / 1e9, 1)}B`}
            tone={delta > 0 ? "warn" : undefined}
          />
          <Metric
            label="CPI impact"
            value={`${fmt((data?.macro.cpi_impact_pct ?? 0) * 100, 2)} pp`}
            tone={delta > 0 ? "warn" : undefined}
          />
        </div>
      </div>
    </Panel>
  );
}

function Metric({
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
      <div className="mono text-[14px] mt-0.5" style={{ color }}>
        {value}
      </div>
    </div>
  );
}
