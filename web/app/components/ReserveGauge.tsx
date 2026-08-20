"use client";

import { Area, AreaChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { ReserveResult, fmt, num } from "../lib/api";
import Panel from "./Panel";
import { Term } from "./Term";

/** Days-of-cover gauge + the drawdown curve behind it. The gauge reads the
 *  SPR only — conflating it with India's ~74 days of total national storage
 *  is the single most likely misread of this panel, so the caveat is not
 *  optional. */
export default function ReserveGauge({
  data,
  dailyGap,
  onDailyGapChange,
  loading,
}: {
  data: ReserveResult | null;
  dailyGap: number;
  onDailyGapChange: (v: number) => void;
  loading: boolean;
}) {
  const cover = data?.days_of_cover_at_start ?? 0;
  const exhausted = data?.days_to_exhaustion ?? null;
  // fraction of the horizon survived -- what the arc fills to
  const frac =
    exhausted == null ? 1 : Math.max(0, Math.min(1, exhausted / (data?.duration_days || 90)));

  const R = 52;
  const CIRC = Math.PI * R; // semicircle
  const tone = exhausted == null ? "#2dd4a7" : exhausted < 15 ? "#e5484d" : exhausted < 45 ? "#f0b429" : "#a3d13a";

  return (
    <Panel
      title={<Term id="SPR">Strategic reserve</Term>}
      subtitle="Multi-period SPR drawdown LP against a sustained supply gap"
      asOf={data ? `${dailyGap} kbd gap` : undefined}
      caveat={data?.caveat}
      className="min-h-[330px]"
      right={loading ? <span className="asof">solving…</span> : undefined}
    >
      <div className="flex flex-col h-full gap-3">
        <div className="flex items-center gap-4">
          <svg viewBox="0 0 130 74" className="w-[142px] shrink-0">
            <path
              d={`M ${65 - R} 64 A ${R} ${R} 0 0 1 ${65 + R} 64`}
              fill="none"
              stroke="#223044"
              strokeWidth={11}
              strokeLinecap="round"
            />
            <path
              d={`M ${65 - R} 64 A ${R} ${R} 0 0 1 ${65 + R} 64`}
              fill="none"
              stroke={tone}
              strokeWidth={11}
              strokeLinecap="round"
              strokeDasharray={`${frac * CIRC} ${CIRC}`}
            />
            <text
              x={65}
              y={54}
              textAnchor="middle"
              fill={tone}
              fontSize={21}
              className="mono"
              fontWeight={600}
            >
              {exhausted == null ? "—" : exhausted}
            </text>
            <text x={65} y={68} textAnchor="middle" fill="#7d8ea6" fontSize={8.5}>
              {exhausted == null ? "not exhausted" : "days to exhaustion"}
            </text>
          </svg>

          <div className="flex-1 min-w-0 space-y-1.5">
            <Row label="SPR capacity" value={`${fmt((data?.capacity_bbl ?? 0) / 1e6, 1)}M bbl`} />
            <Row label="days of cover" value={`${fmt(cover, 1)} d`} />
            <Row label="max pumpout" value={`${fmt(data?.max_pumpout_rate_kbd, 0)} kbd`} />
            <Row
              label="unserved (cumulative)"
              value={`${fmt(data?.total_unserved_kbd_days, 0)} kbd·d`}
              tone={data && data.total_unserved_kbd_days > 0 ? "bad" : "ok"}
            />
          </div>
        </div>

        <div>
          <div className="flex items-baseline justify-between mb-1">
            <label className="text-[11px] text-[var(--muted)] uppercase tracking-wide">
              daily supply gap
            </label>
            <span className="mono text-[12px] text-[var(--accent)]">{dailyGap} kbd</span>
          </div>
          <input
            type="range"
            min={0}
            max={4000}
            step={100}
            value={dailyGap}
            onChange={(e) => onDailyGapChange(Number(e.target.value))}
            className="w-full"
          />
        </div>

        <div className="h-[92px]">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart
              data={data?.schedule ?? []}
              margin={{ top: 4, right: 4, bottom: 0, left: -30 }}
            >
              <XAxis dataKey="day" tick={{ fill: "#7d8ea6", fontSize: 9 }} stroke="#223044" />
              <YAxis tick={{ fill: "#7d8ea6", fontSize: 9 }} stroke="#223044" width={44} />
              <Tooltip
                contentStyle={{
                  background: "#111823",
                  border: "1px solid #223044",
                  borderRadius: 8,
                  fontSize: 11,
                }}
                formatter={(v) => [`${fmt(num(v), 0)} kb`, "stock"]}
                labelFormatter={(d) => `day ${d}`}
              />
              <Area
                type="monotone"
                dataKey="stock_kbd_equiv"
                stroke={tone}
                fill={tone}
                fillOpacity={0.16}
                strokeWidth={1.6}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>
    </Panel>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone?: "ok" | "bad" }) {
  return (
    <div className="flex items-baseline justify-between gap-2">
      <span className="text-[11px] text-[var(--muted)]">{label}</span>
      <span
        className="mono text-[12px]"
        style={{ color: tone === "bad" ? "var(--bad)" : tone === "ok" ? "var(--ok)" : "var(--foreground)" }}
      >
        {value}
      </span>
    </div>
  );
}
