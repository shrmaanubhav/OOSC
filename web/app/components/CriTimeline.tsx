"use client";

import { useMemo } from "react";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CLOSURE_DATE, CriSeries, num } from "../lib/api";
import Panel from "./Panel";
import { Term } from "./Term";

/** CRI over time with its components. The point of this chart is the lead
 *  relationship: S (news) spikes days before O (AIS) confirms, because
 *  PortWatch publishes with a 2-9 day lag. Both are drawn on the same axis
 *  so that gap is visible rather than asserted. */
export default function CriTimeline({
  data,
  cursorDate,
  onCursorChange,
}: {
  data: CriSeries;
  cursorDate?: string;
  onCursorChange?: (d: string) => void;
}) {
  const series = data.series.map((p) => ({
    ...p,
    O100: p.O == null ? null : p.O * 100,
    S100: p.S == null ? null : p.S * 100,
    E100: p.E == null ? null : p.E * 100,
  }));

  // Pre-war days carry fewer components, so CRI there renormalises over less
  // weight (core/risk.py:165-174). Derive where composition first improves
  // rather than pinning a date: GDELT's first *usable* day is not its
  // backfill_start -- compute_S's 90d rolling z-score (min_periods=7) eats the
  // first ~4 weeks, so any constant here would be wrong by about a month.
  const baseComponents = data.series[0]?.components_used;
  const enrichedFrom = data.series.find((p) => p.components_used !== baseComponents)?.date;

  // Recharts calls labelFormatter on every mouse move; a Map, not a linear find.
  const compsByDate = useMemo(
    () => new Map(data.series.map((p) => [p.date, p.components_used])),
    [data.series]
  );

  return (
    <Panel
      title={<>Corridor Risk Index (<Term id="CRI">CRI</Term>)</>}
      subtitle={
        <>
          <Term id="chokepoint6">{data.corridor_id}</Term> · weights{" "}
          <Term id="O">O</Term> {data.weights.O} · <Term id="S">S</Term> {data.weights.S} ·{" "}
          <Term id="E">E</Term> {data.weights.E} · <Term id="X">X</Term> {data.weights.X}
        </>
      }
      asOf={data.as_of}
      caveat="Gaps are missing data, not zero — CRI renormalizes its weights over whatever components exist that day. AIS (O) publishes 2–9 days late by nature. In the shaded pre-war era only O and X exist, giving CRI a floor of 8.2 from exposure alone — the two eras are not strictly comparable."
      className="h-full"
    >
      {/* Flex column so the chart takes whatever the copy leaves. Without it
          ResponsiveContainer's height="100%" resolves against the full box and
          the panel overflows by the paragraph's height. Same shape as FlowMap. */}
      <div className="flex flex-col h-full">
        <p className="text-[11.5px] text-[#c2cfe0] leading-snug mb-2 shrink-0">
          Shaded = pre-war Hormuz: only <Term id="O">O</Term> (AIS) and <Term id="X">X</Term>{" "}
          (exposure) existed, so CRI there renormalises over half the index weight — partial, not
          confirmed-calm.{" "}
          {enrichedFrom && (
            <>
              News (<Term id="S">S</Term>) joins {enrichedFrom}.{" "}
            </>
          )}
          <span style={{ color: "#4c9aff" }}>Blue (S)</span> /{" "}
          <span style={{ color: "#f2762e" }}>orange (E)</span> are news-derived, same-day;{" "}
          <span style={{ color: "#2dd4a7" }}>green (O)</span> is ship-tracking, up to 9 days late
          — watch blue rise before green falls.
        </p>
        <ResponsiveContainer
          width="100%"
          height="100%"
          minHeight={160}
          className="flex-1 min-h-0"
        >
          <ComposedChart
            data={series}
            margin={{ top: 4, right: 8, bottom: 0, left: -18 }}
            onClick={(e) => {
              const label = e?.activeLabel;
              if (typeof label === "string") onCursorChange?.(label);
            }}
          >
            <defs>
              <linearGradient id="criFill" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#e5484d" stopOpacity={0.42} />
                <stop offset="100%" stopColor="#e5484d" stopOpacity={0.02} />
              </linearGradient>
            </defs>
            <CartesianGrid stroke="#223044" strokeDasharray="2 4" vertical={false} />
            {/* Declared before the series: recharts paints cartesian children in
                declaration order, so lower down this would wash over the CRI fill. */}
            {enrichedFrom && (
              <ReferenceArea
                x1={data.series[0].date}
                x2={enrichedFrom}
                fill="#7d8ea6"
                fillOpacity={0.15}
                stroke="#7d8ea6"
                strokeOpacity={0.55}
                strokeDasharray="3 3"
                label={{
                  value: "O + X only",
                  position: "insideBottomLeft",
                  fill: "#7d8ea6",
                  fontSize: 10,
                }}
              />
            )}
            <XAxis
              dataKey="date"
              tick={{ fill: "#7d8ea6", fontSize: 10 }}
              stroke="#223044"
              minTickGap={44}
            />
            <YAxis
              domain={[0, 100]}
              tick={{ fill: "#7d8ea6", fontSize: 10 }}
              stroke="#223044"
              width={46}
            />
            <Tooltip
              contentStyle={{
                background: "#111823",
                border: "1px solid #223044",
                borderRadius: 8,
                fontSize: 12,
              }}
              labelStyle={{ color: "#dbe4f0" }}
              labelFormatter={(d) => `${d} · components: ${compsByDate.get(String(d)) || "none"}`}
              formatter={(v, name) => {
                const n = num(v);
                return [n == null ? "no data" : n.toFixed(1), String(name)];
              }}
            />
            <ReferenceLine
              x={CLOSURE_DATE}
              stroke="#f0b429"
              strokeDasharray="4 3"
              label={{ value: "closure", fill: "#f0b429", fontSize: 10, position: "insideTopRight" }}
            />
            {cursorDate && <ReferenceLine x={cursorDate} stroke="#4c9aff" strokeWidth={1.5} />}
            <Legend
              wrapperStyle={{ fontSize: 11, color: "#7d8ea6" }}
              iconType="plainline"
              verticalAlign="top"
              height={22}
            />
            <Area
              type="monotone"
              dataKey="CRI"
              name="CRI"
              stroke="#e5484d"
              strokeWidth={2}
              fill="url(#criFill)"
              connectNulls={false}
              dot={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="S100"
              name="S · news signal (leading)"
              stroke="#4c9aff"
              strokeWidth={1.4}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="O100"
              name="O · AIS observed (lagging)"
              stroke="#2dd4a7"
              strokeWidth={1.4}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="E100"
              name="E · event severity"
              stroke="#f2762e"
              strokeWidth={1}
              strokeDasharray="3 3"
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          </ComposedChart>
        </ResponsiveContainer>
      </div>
    </Panel>
  );
}
