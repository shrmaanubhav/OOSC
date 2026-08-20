"use client";

import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { CriSeries, num } from "../lib/api";
import Panel from "./Panel";
import { Term } from "./Term";

const CLOSURE_DATE = "2026-02-28"; // real Hormuz closure onset

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
      caveat="Gaps are missing data, not zero — CRI renormalizes its weights over whatever components exist that day. AIS (O) publishes 2–9 days late by nature."
      className="min-h-[420px] h-full"
    >
      <p className="text-[11.5px] text-[#c2cfe0] leading-snug mb-2">
        <span style={{ color: "#4c9aff" }}>Blue (S)</span> and{" "}
        <span style={{ color: "#f2762e" }}>orange (E)</span> are news-derived and update same-day.{" "}
        <span style={{ color: "#2dd4a7" }}>Green (O)</span> is satellite ship-tracking, confirmed
        up to 9 days later. Watch blue/orange rise before green falls — that lead time is the
        early warning.
      </p>
      <ResponsiveContainer width="100%" height="100%" minHeight={200}>
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
    </Panel>
  );
}
