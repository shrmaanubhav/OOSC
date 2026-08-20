"use client";

import DeckGL from "@deck.gl/react";
import type { Layer } from "@deck.gl/core";
import { ArcLayer, GeoJsonLayer, ScatterplotLayer, TextLayer } from "@deck.gl/layers";
import { useEffect, useMemo, useRef, useState } from "react";
import { Allocation, CriSeries, TwinGraph, riskRgb } from "../lib/api";
import Panel from "./Panel";

const INITIAL_VIEW = { longitude: 62, latitude: 19, zoom: 3.05, pitch: 28, bearing: 0 };

/** deck.gl only, no basemap tiles: a tile server is a network call, and the
 *  demo has to survive with networking off. Coastlines come from a 126KB
 *  Natural Earth GeoJSON served out of /public. */
export default function FlowMap({
  twin,
  allocation,
  cri,
  cursorDate,
  onCursorChange,
}: {
  twin: TwinGraph | null;
  allocation: Allocation[];
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

  useEffect(() => {
    if (!playing || dates.length === 0) return;
    const t = setInterval(() => {
      const i = dates.indexOf(cursorDate);
      if (i >= dates.length - 1) {
        setPlaying(false);
        return;
      }
      onCursorChange(dates[i + 1]);
    }, 55);
    return () => clearInterval(t);
  }, [playing, cursorDate, dates, onCursorChange]);

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

  const arcs = useMemo(
    () =>
      allocation
        .map((a) => ({
          ...a,
          from: sourcePos.get(a.source),
          to: refineryPos.get(a.refinery),
        }))
        .filter((a) => a.from && a.to)
        .sort((a, b) => b.kbd - a.kbd)
        .slice(0, 120),
    [allocation, sourcePos, refineryPos]
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
      title="Crude flow map"
      subtitle="Allocation arcs from the procurement LP · corridor dots coloured by CRI on the scrubbed date"
      asOf={cursorDate}
      caveat="Sources and refineries are drawn at their shipping corridor / discharge port — the twin geocodes corridors and ports, not fields and plants."
      className="min-h-[420px]"
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
        <div
          ref={boxRef}
          className="relative flex-1 min-h-[300px] rounded-md overflow-hidden border border-[var(--border)]"
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
            value={cursorIdx}
            onChange={(e) => onCursorChange(dates[Number(e.target.value)])}
            className="flex-1"
          />
          <span className="mono text-[11px] text-[var(--muted)] w-[86px] text-right">
            {cursorDate}
          </span>
        </div>
      </div>
    </Panel>
  );
}
