"use client";

import { useMemo } from "react";
import { Allocation, fmt } from "../lib/api";

type Band = { key: string; value: number; y0: number; y1: number; color: string };

const COUNTRY_COLORS = [
  "#4c9aff", "#2dd4a7", "#f0b429", "#f2762e", "#e5484d",
  "#a78bfa", "#22b8cf", "#a3d13a", "#ff8fab", "#8d9db6",
];

/** Country → operator flow. Hand-rolled SVG rather than pulling in
 *  d3-sankey: with exactly two columns and no crossing-minimisation to do,
 *  the layout is a cumulative sum on each side and a cubic between them. */
export default function Sankey({
  allocation,
  operatorByRefinery,
  height = 300,
}: {
  allocation: Allocation[];
  operatorByRefinery: Record<string, string>;
  height?: number;
}) {
  const { left, right, links, total } = useMemo(() => {
    const byCountry = new Map<string, number>();
    const byOperator = new Map<string, number>();
    const byPair = new Map<string, number>();

    for (const a of allocation) {
      const op = operatorByRefinery[a.refinery] ?? "Other";
      byCountry.set(a.country, (byCountry.get(a.country) ?? 0) + a.kbd);
      byOperator.set(op, (byOperator.get(op) ?? 0) + a.kbd);
      const k = `${a.country}||${op}`;
      byPair.set(k, (byPair.get(k) ?? 0) + a.kbd);
    }

    const total = [...byCountry.values()].reduce((s, v) => s + v, 0) || 1;
    const pad = 4;
    const usable = height - pad * 2;

    const build = (m: Map<string, number>): Band[] => {
      const sorted = [...m.entries()].sort((a, b) => b[1] - a[1]);
      let y = pad;
      return sorted.map(([key, value], i) => {
        const h = Math.max(1.5, (value / total) * (usable - (sorted.length - 1) * 3));
        const band = { key, value, y0: y, y1: y + h, color: COUNTRY_COLORS[i % COUNTRY_COLORS.length] };
        y += h + 3;
        return band;
      });
    };

    const left = build(byCountry);
    const right = build(byOperator);

    // walk each side's bands in order, consuming vertical space per link so
    // ribbons stack inside their band instead of all starting at its top
    const leftCursor = new Map(left.map((b) => [b.key, b.y0]));
    const rightCursor = new Map(right.map((b) => [b.key, b.y0]));
    const links = [...byPair.entries()]
      .map(([k, v]) => ({ country: k.split("||")[0], op: k.split("||")[1], value: v }))
      .sort((a, b) => b.value - a.value)
      .map((l) => {
        const lb = left.find((b) => b.key === l.country)!;
        const rb = right.find((b) => b.key === l.op)!;
        const lh = (l.value / lb.value) * (lb.y1 - lb.y0);
        const rh = (l.value / rb.value) * (rb.y1 - rb.y0);
        const ly = leftCursor.get(l.country)!;
        const ry = rightCursor.get(l.op)!;
        leftCursor.set(l.country, ly + lh);
        rightCursor.set(l.op, ry + rh);
        return { ...l, ly, lh, ry, rh, color: lb.color };
      });

    return { left, right, links, total };
  }, [allocation, operatorByRefinery, height]);

  if (allocation.length === 0)
    return <p className="text-[12px] text-[var(--muted)]">No allocation to display.</p>;

  const W = 620;
  const colW = 11;
  const xL = 128;
  const xR = W - 128 - colW;

  return (
    <svg viewBox={`0 0 ${W} ${height}`} className="w-full" style={{ height }}>
      {links.map((l, i) => {
        const x0 = xL + colW;
        const x1 = xR;
        const mid = (x0 + x1) / 2;
        return (
          <path
            key={i}
            d={`M${x0},${l.ly} C${mid},${l.ly} ${mid},${l.ry} ${x1},${l.ry} L${x1},${l.ry + l.rh} C${mid},${l.ry + l.rh} ${mid},${l.ly + l.lh} ${x0},${l.ly + l.lh} Z`}
            fill={l.color}
            opacity={0.26}
          >
            <title>{`${l.country} → ${l.op}: ${fmt(l.value, 0)} kbd`}</title>
          </path>
        );
      })}

      {left.map((b) => (
        <g key={b.key}>
          <rect x={xL} y={b.y0} width={colW} height={b.y1 - b.y0} fill={b.color} rx={2} />
          <text
            x={xL - 7}
            y={(b.y0 + b.y1) / 2}
            textAnchor="end"
            dominantBaseline="middle"
            fill="#dbe4f0"
            fontSize={10.5}
          >
            {b.key}
          </text>
          <text
            x={xL - 7}
            y={(b.y0 + b.y1) / 2 + 11}
            textAnchor="end"
            dominantBaseline="middle"
            fill="#7d8ea6"
            fontSize={9}
            className="mono"
          >
            {((b.value / total) * 100).toFixed(1)}%
          </text>
        </g>
      ))}

      {right.map((b) => (
        <g key={b.key}>
          <rect x={xR} y={b.y0} width={colW} height={b.y1 - b.y0} fill="#2f3f57" rx={2} />
          <text
            x={xR + colW + 7}
            y={(b.y0 + b.y1) / 2}
            dominantBaseline="middle"
            fill="#dbe4f0"
            fontSize={10.5}
          >
            {b.key}
          </text>
        </g>
      ))}

      <text x={xL} y={height - 1} fill="#7d8ea6" fontSize={9.5} textAnchor="middle">
        source country
      </text>
      <text x={xR + colW} y={height - 1} fill="#7d8ea6" fontSize={9.5} textAnchor="middle">
        refinery operator
      </text>
    </svg>
  );
}
