"use client";

import DeckGL from "@deck.gl/react";
import type { Layer } from "@deck.gl/core";
import { ArcLayer, GeoJsonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { useEffect, useMemo, useRef, useState } from "react";
import { Allocation, CLOSURE_DATE, CriSeries, TwinGraph, fmt, riskRgb } from "../lib/api";
import Panel from "./Panel";
import { Term } from "./Term";

const INITIAL_VIEW = { longitude: 62, latitude: 19, zoom: 3.05, pitch: 28, bearing: 0 };

/** deck.gl only, no basemap tiles: a tile server is a network call, and the
 *  demo has to survive with networking off. Coastlines come from a 126KB
 *  Natural Earth GeoJSON served out of /public. */
export default function FlowMap({
  twin,
  allocation,
  baselineAllocation,
  cri,
  cursorDate,
  onCursorChange,
}: {
  twin: TwinGraph | null;
  allocation: Allocation[];
  baselineAllocation: Allocation[];
  cri: Record<string, CriSeries>;
  cursorDate: string;
  onCursorChange: (d: string) => void;
}) {
  const [land, setLand] = useState<GeoJSON.FeatureCollection | null>(null);
  const [playing, setPlaying] = useState(false);

  // deck.gl leaves its drawing buffer at the 300x150 canvas default when it
  // is given percentage sizing inside a flex column -- the CSS box is right
  // but nothing paints. Measuring the container and handing DeckGL concrete
  // pixel width/height is the reliable fix.
  const boxRef = useRef<HTMLDivElement | null>(null);
  const [size, setSize] = useState({ width: 0, height: 0 });
  useEffect(() => {
    const el = boxRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect;
      setSize({ width: Math.round(width), height: Math.round(height) });
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  useEffect(() => {
    fetch("/land-110m.geojson")
      .then((r) => r.json())
      .then(setLand)
      .catch(() => setLand(null));
  }, []);

  // The scrubber walks the CRI date axis; the map recolours corridors to
  // their risk on that date, so scrubbing replays the actual closure.
  const dates = useMemo(
    () => cri.chokepoint6?.series.map((p) => p.date) ?? [],
    [cri]
  );
  const cursorIdx = Math.max(0, dates.indexOf(cursorDate));

  // Dragging the range input fires an onChange per pixel; committing each one
  // straight to cursorDate would rebuild the deck.gl layers and the whole
  // dashboard that many times, which is what made the slider feel stuck.
  // Track the thumb position locally and debounce the expensive commit.
  const [scrubIdx, setScrubIdx] = useState(cursorIdx);
  useEffect(() => setScrubIdx(cursorIdx), [cursorIdx]);
  const scrubTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const handleScrub = (idx: number) => {
    setScrubIdx(idx);
    if (scrubTimer.current) clearTimeout(scrubTimer.current);
    scrubTimer.current = setTimeout(() => onCursorChange(dates[idx]), 60);
  };
  useEffect(() => () => clearTimeout(scrubTimer.current), []);

  // A ref, not `cursorDate` in the deps below: with cursorDate as a dependency
  // the interval was torn down and recreated on every single tick (each
  // onCursorChange changes cursorDate, which re-runs this effect), so the
  // real per-tick cost was interval-teardown + effect-rerun + render, not the
  // requested delay -- that's why tuning the ms argument alone didn't move
  // the total time. The interval now lives for the whole playback.
  const playIdxRef = useRef(cursorIdx);
  useEffect(() => {
    if (!playing) playIdxRef.current = dates.indexOf(cursorDate);
  }, [cursorDate, dates, playing]);

  useEffect(() => {
    if (!playing || dates.length === 0) return;
    const t = setInterval(() => {
      const i = playIdxRef.current;
      if (i >= dates.length - 1) {
        setPlaying(false);
        return;
      }
      playIdxRef.current = i + 1;
      onCursorChange(dates[i + 1]);
    }, 22); // 593 frames * 22ms ~= 13s
    return () => clearInterval(t);
  }, [playing, dates, onCursorChange]);

  const criAt = (corridorId: string): number | null => {
    const pt = cri[corridorId]?.series.find((p) => p.date === cursorDate);
    return pt?.CRI ?? null;
  };

  const nodesById = useMemo(() => {
    const m = new Map<string, TwinGraph["nodes"][number]>();
    twin?.nodes.forEach((n) => m.set(n.id, n));
    return m;
  }, [twin]);

  const positioned = useMemo(
    () => (twin?.nodes ?? []).filter((n) => n.lat != null && n.lon != null),
    [twin]
  );

  // Refineries have no coordinates of their own in the twin; place them at
  // the port that feeds them so allocation arcs have somewhere to land.
  const refineryPos = useMemo(() => {
    const m = new Map<string, [number, number]>();
    twin?.edges
      .filter((e) => e.key === "FEEDS")
      .forEach((e) => {
        const port = nodesById.get(e.source);
        if (port?.lat != null && port?.lon != null && !m.has(e.target)) {
          m.set(e.target, [port.lon, port.lat]);
        }
      });
    return m;
  }, [twin, nodesById]);

  const sourcePos = useMemo(() => {
    // Sources aren't geocoded as nodes either; use the first corridor/port
    // they ship via as their origin.
    const m = new Map<string, [number, number]>();
    twin?.edges
      .filter((e) => e.key === "SHIPS_VIA")
      .forEach((e) => {
        const dest = nodesById.get(e.target);
        if (dest?.lat != null && dest?.lon != null && !m.has(e.source)) {
          m.set(e.source, [dest.lon, dest.lat]);
        }
      });
    return m;
  }, [twin, nodesById]);

  // The procurement LP answers "given this severity, what should we buy?" -- it
  // is not a per-day historical record. Before the closure the honest answer is
  // the unshocked solve (severity 0), which routes ~2,950 kbd through Hormuz;
  // after it, the shocked solve the severity slider is set to, which routes
  // Hormuz to zero. Scrubbing across the onset therefore shows the real
  // reallocation instead of pinning the post-closure picture to every date.
  // Two states, not a ramp, because the LP itself is a cliff: severities 0
  // through 0.75 all return the identical allocation.
  const preClosure = cursorDate < CLOSURE_DATE;
  const shownAllocation = preClosure && baselineAllocation.length ? baselineAllocation : allocation;

  // Per-corridor totals for the readout under the map -- plain sums over the
  // LP's own rows, so every number still traces to a tool result.
  const byCorridor = useMemo(() => {
    const m = new Map<string, number>();
    shownAllocation.forEach((a) => m.set(a.corridor_id, (m.get(a.corridor_id) ?? 0) + a.kbd));
    return [...m.entries()].sort((a, b) => b[1] - a[1]);
  }, [shownAllocation]);

  const arcs = useMemo(
    () =>
      shownAllocation
        .map((a) => ({
          ...a,
          from: sourcePos.get(a.source),
          to: refineryPos.get(a.refinery),
        }))
        .filter((a) => a.from && a.to)
        .sort((a, b) => b.kbd - a.kbd)
        .slice(0, 120),
    [shownAllocation, sourcePos, refineryPos]
  );

  const maxKbd = Math.max(1, ...arcs.map((a) => a.kbd));

  const layers: Layer[] = [
    land &&
      new GeoJsonLayer({
        id: "land",
        data: land,
        stroked: true,
        filled: true,
        getFillColor: [22, 31, 44],
        getLineColor: [42, 58, 82],
        lineWidthMinPixels: 0.7,
      }),
    new ArcLayer({
      id: "flows",
      data: arcs,
      getSourcePosition: (d) => d.from as [number, number],
      getTargetPosition: (d) => d.to as [number, number],
      getSourceColor: (d) => [...riskRgb(criAt(d.corridor_id)), 190] as [number, number, number, number],
      getTargetColor: [76, 154, 255, 150] as [number, number, number, number],
      getWidth: (d) => 0.7 + (d.kbd / maxKbd) * 5.5,
      getHeight: 0.32,
      pickable: true,
      updateTriggers: { getSourceColor: [cursorDate] },
    }),
    new ScatterplotLayer({
      id: "nodes",
      data: positioned,
      getPosition: (d) => [d.lon as number, d.lat as number],
      getRadius: (d) => (d.kind === "Corridor" ? 13 : 6),
      radiusUnits: "pixels",
      getFillColor: (d) =>
        d.kind === "Corridor"
          ? ([...riskRgb(criAt(d.id)), 235] as [number, number, number, number])
          : ([76, 154, 255, 170] as [number, number, number, number]),
      stroked: true,
      getLineColor: [10, 14, 20, 220],
      lineWidthMinPixels: 1.5,
      pickable: true,
      updateTriggers: { getFillColor: [cursorDate] },
    }),
    new TextLayer({
      id: "corridor-labels",
      data: positioned.filter((n) => n.kind === "Corridor"),
      getPosition: (d) => [d.lon as number, d.lat as number],
      getText: (d) => `${d.name ?? d.id}  ${criAt(d.id)?.toFixed(0) ?? "—"}`,
      getSize: 11,
      getColor: [219, 228, 240, 235],
      getPixelOffset: [0, -19],
      fontFamily: "ui-monospace, Menlo, Consolas, monospace",
      characterSet: "auto",
      updateTriggers: { getText: [cursorDate] },
    }),
  ].filter(Boolean) as Layer[];

  return (
    <Panel
      title="Crude flow map — the digital twin, live"
      subtitle={
        <>
          Arc width = allocated kbd · arc/dot colour = <Term id="CRI">CRI</Term> on the scrubbed
          date · scrub across {CLOSURE_DATE} to see the reallocation
        </>
      }
      asOf={cursorDate}
      caveat="Sources and refineries are drawn at their shipping corridor / discharge port — the twin geocodes corridors and ports, not fields and plants."
      className="h-full"
      right={
        <button
          onClick={() => setPlaying((p) => !p)}
          className="text-[11px] px-2 py-1 rounded border border-[var(--border)] bg-[var(--panel-2)] hover:border-[var(--accent)] transition-colors"
        >
          {playing ? "⏸ pause" : "▶ play"}
        </button>
      }
    >
      <div className="flex flex-col h-full gap-2">
        {/* Where the crude actually goes, per corridor, for the regime on screen.
            This is the "how it shifted" readout: Hormuz carries the largest share
            before the closure and drops out of the solution entirely after it. */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 shrink-0">
          <span
            className="text-[10px] px-1.5 py-0.5 rounded border"
            style={{
              borderColor: preClosure ? "#2dd4a755" : "#e5484d55",
              color: preClosure ? "var(--ok)" : "var(--bad)",
            }}
          >
            {preClosure ? "pre-closure sourcing" : "post-closure sourcing"}
          </span>
          {byCorridor.map(([cid, kbd]) => {
            const name =
              nodesById.get(cid)?.name ?? (cid === "none" ? "outside all corridors" : cid);
            return (
              <span key={cid} className="flex items-center gap-1.5 text-[11px]">
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{
                    background:
                      cid === "none" ? "#7d8ea6" : `rgb(${riskRgb(criAt(cid)).join(",")})`,
                  }}
                />
                <span className="text-[var(--muted)]">{name}</span>
                <span className="mono">{fmt(kbd, 0)} kbd</span>
              </span>
            );
          })}
        </div>
        <div
          ref={boxRef}
          className="relative flex-1 min-h-0 rounded-md overflow-hidden border border-[var(--border)]"
        >
          <DeckGL
            initialViewState={INITIAL_VIEW}
            controller={true}
            layers={layers}
            width={size.width || 600}
            height={size.height || 320}
            style={{ background: "#0a0e14", position: "absolute", inset: "0" }}
            onError={(e: Error) => console.error("[deck]", e)}
            getTooltip={({ object }) => {
              if (!object) return null;
              const o = object as Record<string, unknown>;
              if (o.kbd != null)
                return {
                  text: `${o.source} → ${o.refinery}\n${(o.kbd as number).toFixed(0)} kbd · via ${o.corridor_id}`,
                };
              if (o.kind)
                return { text: `${o.name ?? o.id}\n${o.kind}` };
              return null;
            }}
          />
        </div>
        <div className="flex items-center gap-3 px-1">
          <input
            type="range"
            min={0}
            max={Math.max(0, dates.length - 1)}
            value={scrubIdx}
            onChange={(e) => handleScrub(Number(e.target.value))}
            className="flex-1"
          />
          <span className="mono text-[11px] text-[var(--muted)] w-[86px] text-right">
            {dates[scrubIdx] ?? cursorDate}
          </span>
        </div>
      </div>
    </Panel>
  );
}
