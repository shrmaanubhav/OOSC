"use client";

import {
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from "recharts";
import { BacktestResult, fmt, num } from "../lib/api";
import Panel from "./Panel";
import { Term } from "./Term";

/** AUC per horizon + the reliability curve. A null AUC is shown as "n/a
 *  (single class)" rather than blanked or coerced to 0.5 — at h=30 the
 *  sustained closure leaves only positive labels, which makes AUC
 *  undefined, and that is itself the interesting fact. */
export default function BacktestPanel({ data }: { data: BacktestResult | null }) {
  const h7 = data?.horizons.find((h) => h.horizon === 7);
  const rel = h7?.reliability ?? [];
  const points = rel.map((r) => ({ x: r.mean_predicted, y: r.observed_rate, n: r.n }));

  return (
    <Panel
      title="Backtest"
      subtitle={
        data ? `fit: ${data.fit_window} → validate: ${data.validation_window}` : "loading…"
      }
      caveat={data?.caveat}
      className="min-h-[330px]"
    >
      <div className="flex flex-col h-full gap-3">
        <p className="text-[12px] text-[#c2cfe0] leading-relaxed">
          We fit this on the real 2023 Red Sea crisis and test it — untouched — against the real
          2026 Hormuz closure. An <Term id="AUC">AUC</Term> of {h7?.auc?.toFixed(2) ?? "—"} at 7
          days means the score almost perfectly separated &quot;disruption coming&quot; from
          &quot;business as usual&quot;, without ever seeing Hormuz during training.
        </p>
        <div className="grid grid-cols-3 gap-2">
          {(data?.horizons ?? []).map((h) => (
            <div
              key={h.horizon}
              className="bg-[var(--panel-2)] border border-[var(--border)] rounded-md px-3 py-2"
            >
              <div className="asof uppercase tracking-wide">h = {h.horizon} d</div>
              <div
                className="mono text-[17px] mt-0.5"
                style={{
                  color:
                    h.auc == null
                      ? "var(--muted)"
                      : h.auc > 0.9
                      ? "var(--ok)"
                      : h.auc > 0.7
                      ? "var(--warn)"
                      : "var(--bad)",
                }}
              >
                {h.auc == null ? "n/a" : h.auc.toFixed(3)}
              </div>
              <div className="asof">
                {h.auc == null ? "single class" : `AUC · n=${h.n_valid}`}
              </div>
            </div>
          ))}
        </div>

        <div className="flex-1 min-h-[130px]">
          <p className="asof mb-1">
            Reliability, h=7 · diagonal = perfectly calibrated
          </p>
          <ResponsiveContainer width="100%" height="100%">
            <ScatterChart margin={{ top: 4, right: 10, bottom: 2, left: -22 }}>
              <CartesianGrid stroke="#223044" strokeDasharray="2 4" />
              <XAxis
                type="number"
                dataKey="x"
                domain={[0, 1]}
                tick={{ fill: "#7d8ea6", fontSize: 9 }}
                stroke="#223044"
                label={{
                  value: "predicted",
                  fill: "#7d8ea6",
                  fontSize: 9,
                  position: "insideBottomRight",
                  offset: -2,
                }}
              />
              <YAxis
                type="number"
                dataKey="y"
                domain={[0, 1]}
                tick={{ fill: "#7d8ea6", fontSize: 9 }}
                stroke="#223044"
                width={44}
              />
              <ZAxis type="number" dataKey="n" range={[40, 190]} />
              <Tooltip
                contentStyle={{
                  background: "#111823",
                  border: "1px solid #223044",
                  borderRadius: 8,
                  fontSize: 11,
                }}
                formatter={(v, n) => [fmt(num(v), 3), n === "x" ? "predicted" : "observed"]}
              />
              <ReferenceLine
                segment={[
                  { x: 0, y: 0 },
                  { x: 1, y: 1 },
                ]}
                stroke="#4a5568"
                strokeDasharray="3 3"
              />
              <Scatter data={points} fill="#4c9aff" isAnimationActive={false} />
            </ScatterChart>
          </ResponsiveContainer>
        </div>

        {h7 && (
          <p className="asof leading-snug">
            Fit window CRI used <span className="mono">{h7.fit_components}</span> only; validation
            had <span className="mono">{h7.valid_components}</span>. Calibrating on a thinner signal
            than you validate on is a real asymmetry, not a detail.
          </p>
        )}
      </div>
    </Panel>
  );
}
