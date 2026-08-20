"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AgentPanel from "./components/AgentPanel";
import BacktestPanel from "./components/BacktestPanel";
import CriTimeline from "./components/CriTimeline";
import FlowMap from "./components/FlowMap";
import ImpactWaterfall from "./components/ImpactWaterfall";
import OnboardingStrip from "./components/OnboardingStrip";
import ProcurementPanel from "./components/ProcurementPanel";
import ReserveGauge from "./components/ReserveGauge";
import {
  BacktestResult,
  BypassRoutes,
  Corridors,
  CriSeries,
  ProcurementResult,
  ReserveResult,
  ScenarioResult,
  TwinGraph,
  fmt,
  get,
  riskColor,
} from "./lib/api";

export default function Dashboard() {
  const [cri, setCri] = useState<Record<string, CriSeries>>({});
  const [twin, setTwin] = useState<TwinGraph | null>(null);
  const [corridors, setCorridors] = useState<Corridors | null>(null);
  const [bypass, setBypass] = useState<BypassRoutes | null>(null);
  const [backtest, setBacktest] = useState<BacktestResult | null>(null);
  const [refineries, setRefineries] = useState<{ name: string; operator: string }[]>([]);
  const [err, setErr] = useState<string | null>(null);

  const [cursorDate, setCursorDate] = useState("2026-03-08");

  // procurement controls
  const [lambdaRisk, setLambdaRisk] = useState(0);
  const [antiConc, setAntiConc] = useState(true);
  const [proc, setProc] = useState<ProcurementResult | null>(null);
  const [procLoading, setProcLoading] = useState(false);

  // scenario controls
  const [severity, setSeverity] = useState(1);
  const [compliance, setCompliance] = useState(false);
  const [secondCorridor, setSecondCorridor] = useState(false);
  const [scenario, setScenario] = useState<ScenarioResult | null>(null);
  const [scenLoading, setScenLoading] = useState(false);

  // reserve controls
  const [dailyGap, setDailyGap] = useState(500);
  const [reserve, setReserve] = useState<ReserveResult | null>(null);
  const [resLoading, setResLoading] = useState(false);

  useEffect(() => {
    Promise.all([
      get<CriSeries>("/api/cri/chokepoint6?start=2026-01-01"),
      get<CriSeries>("/api/cri/chokepoint4?start=2026-01-01"),
      get<TwinGraph>("/api/twin"),
      get<Corridors>("/api/corridors"),
      get<BypassRoutes>("/api/bypass_routes"),
      get<BacktestResult>("/api/backtest"),
      get<{ rows: { name: string; operator: string }[] }>("/api/reference/refineries"),
    ])
      .then(([c6, c4, tw, co, by, bt, refs]) => {
        setCri({ chokepoint6: c6, chokepoint4: c4 });
        setTwin(tw);
        setCorridors(co);
        setBypass(by);
        setBacktest(bt);
        setRefineries(refs.rows);
        if (c6.as_of) setCursorDate(c6.series[c6.series.length - 1].date);
      })
      .catch((e) => setErr(String(e)));
  }, []);

  // Debounced so dragging a slider doesn't queue one solve per pixel.
  const useDebounced = <T,>(value: T, ms: number) => {
    const [v, setV] = useState(value);
    useEffect(() => {
      const t = setTimeout(() => setV(value), ms);
      return () => clearTimeout(t);
    }, [value, ms]);
    return v;
  };

  const dLambda = useDebounced(lambdaRisk, 130);
  const dSeverity = useDebounced(severity, 130);
  const dGap = useDebounced(dailyGap, 130);

  useEffect(() => {
    setProcLoading(true);
    get<ProcurementResult>(
      `/api/procurement?corridor_id=chokepoint6&severity=${dSeverity}&lambda_risk=${dLambda}&anti_concentration=${antiConc}&compliance_mode=${compliance}`
    )
      .then(setProc)
      .catch((e) => setErr(String(e)))
      .finally(() => setProcLoading(false));
  }, [dLambda, dSeverity, antiConc, compliance]);

  useEffect(() => {
    setScenLoading(true);
    const second = secondCorridor ? "&second_corridor_id=chokepoint4&second_severity=1.0" : "";
    get<ScenarioResult>(
      `/api/scenario?corridor_id=chokepoint6&severity=${dSeverity}&duration_days=90&compliance_mode=${compliance}${second}`
    )
      .then(setScenario)
      .catch((e) => setErr(String(e)))
      .finally(() => setScenLoading(false));
  }, [dSeverity, compliance, secondCorridor]);

  useEffect(() => {
    setResLoading(true);
    get<ReserveResult>(`/api/reserve?daily_gap_kbd=${dGap}&duration_days=90`)
      .then(setReserve)
      .catch((e) => setErr(String(e)))
      .finally(() => setResLoading(false));
  }, [dGap]);

  const operatorByRefinery = useMemo(
    () => Object.fromEntries(refineries.map((r) => [r.name, r.operator])),
    [refineries]
  );

  const onCursorChange = useCallback((d: string) => setCursorDate(d), []);

  const criNow = cri.chokepoint6?.series.find((p) => p.date === cursorDate)?.CRI ?? null;
  const [showMethodology, setShowMethodology] = useState(false);

  return (
    <main className="min-h-screen p-4 lg:p-5 max-w-[1800px] mx-auto">
      <header className="flex flex-wrap items-end justify-between gap-3 mb-4">
        <div>
          <div className="flex items-center gap-2.5 flex-wrap">
            <h1 className="text-[19px] font-semibold tracking-tight">
              Project Sentinel
              <span className="text-[var(--muted)] font-normal text-[13px] ml-2.5">
                India energy supply-chain resilience
              </span>
            </h1>
            <span className="text-[10px] font-semibold tracking-wide px-2 py-0.5 rounded-full bg-[#2dd4a71f] text-[var(--ok)] border border-[#2dd4a755]">
              DEMO — {cri.chokepoint6?.as_of ?? "…"} SNAPSHOT
            </span>
          </div>
          <p className="asof mt-0.5">
            Backtested against the real Strait of Hormuz closure, 28 Feb 2026 → present. Runs
            entirely on frozen local snapshots for demo reliability — no live feeds, no network
            calls except the Analyst panel below. The ingestion pipeline itself is real and
            scheduled; see <code className="mono">ingest/</code> in the repo.{" "}
            <button
              onClick={() => setShowMethodology((v) => !v)}
              className="underline decoration-dotted text-[var(--accent)] hover:text-[var(--foreground)]"
            >
              ⓘ methodology &amp; limitations
            </button>
          </p>
        </div>
        <div className="flex items-center gap-2.5">
          {(corridors?.corridors ?? []).map((c) => {
            const v = cri[c.corridor_id]?.series.find((p) => p.date === cursorDate)?.CRI ?? null;
            return (
              <div
                key={c.corridor_id}
                className="panel px-3 py-1.5 flex items-center gap-2.5"
                title={c.note}
              >
                <span
                  className="w-2 h-2 rounded-full shrink-0"
                  style={{ background: riskColor(v) }}
                />
                <div className="leading-tight">
                  <div className="text-[11px]">{c.name}</div>
                  <div className="asof">
                    {c.india_crude_import_share_pct != null
                      ? `${c.india_crude_import_share_pct}% of India's crude`
                      : "coupling corridor"}
                  </div>
                </div>
                <span className="mono text-[16px]" style={{ color: riskColor(v) }}>
                  {v == null ? "—" : v.toFixed(0)}
                </span>
              </div>
            );
          })}
        </div>
      </header>

      {err && (
        <div className="panel px-4 py-3 mb-4 border-[#e5484d55] bg-[#e5484d12]">
          <p className="text-[12.5px] text-[var(--bad)]">
            Can’t reach the API ({err}). Start it with{" "}
            <code className="mono">uv run python api/main.py</code>.
          </p>
        </div>
      )}

      <OnboardingStrip />

      {showMethodology && (
        <section className="panel mt-0 mb-4 px-4 py-3 border-[var(--accent)]/40">
          <h3 className="text-[11px] uppercase tracking-wide text-[var(--foreground)] mb-2 font-semibold">
            Methodology &amp; known limitations
          </h3>
          <ul className="text-[12px] text-[#c2cfe0] leading-relaxed space-y-1.5 list-disc pl-4">
            <li>
              <b className="text-[var(--foreground)]">AIS data (O)</b> — IMF PortWatch, publishes
              2–9 days late and documents GPS jamming/spoofing in the conflict zone. Never
              real-time.
            </li>
            <li>
              <b className="text-[var(--foreground)]">Event severity (E)</b> — from a token-capped
              LLM extraction run (54 events total); thin by construction, reported as missing
              rather than zero when absent.
            </li>
            <li>
              <b className="text-[var(--foreground)]">Refinery capacity</b> — PPAC Ready Reckoner,
              monthly-aggregate granularity only.
            </li>
            <li>
              <b className="text-[var(--foreground)]">Procurement cost</b> — a real sea-route
              distance proxy, not FOB/freight/war-risk pricing (no primary source ingested for
              those yet).
            </li>
            <li>
              <b className="text-[var(--foreground)]">Sanctions flag</b> — a hand-tagged column in{" "}
              <code className="mono">data/reference/sources.csv</code> (Urals/ESPO/Sokol/Merey),
              not backed by a live sanctioned-vessel/entity list (e.g. OpenSanctions) yet.
            </li>
            <li>
              <b className="text-[var(--foreground)]">Scenario cascade</b> — demand uses nameplate
              refinery capacity, one national yield mix applied to every refinery, and 1:1
              crude-to-CPI pass-through that ignores India’s fuel excise cushioning.
            </li>
            <li>
              <b className="text-[var(--foreground)]">Digital twin</b> — the flow map above{" "}
              <i>is</i> the twin view: a networkx graph of source → corridor → port → refinery,
              geospatially rendered and driven by the same severity/λ controls as the other
              panels, not a separate artifact.
            </li>
            <li>
              <b className="text-[var(--foreground)]">Backtest</b> — fit window CRI (Bab
              el-Mandeb, Oct 2023–Feb 2024) is O-only since GDELT coverage doesn’t reach that far
              back; validation window (Hormuz) has all four components. AUC is undefined, not
              zero, at horizons where the sustained closure leaves only one label class.
            </li>
          </ul>
        </section>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4">
        <div className="xl:col-span-2 flex flex-col gap-4">
          <FlowMap
            twin={twin}
            allocation={proc?.allocation ?? []}
            cri={cri}
            cursorDate={cursorDate}
            onCursorChange={onCursorChange}
          />
          {cri.chokepoint6 && (
            <CriTimeline
              data={cri.chokepoint6}
              cursorDate={cursorDate}
              onCursorChange={onCursorChange}
            />
          )}
          <ProcurementPanel
            data={proc}
            lambdaRisk={lambdaRisk}
            onLambdaChange={setLambdaRisk}
            antiConcentration={antiConc}
            onAntiConcentrationChange={setAntiConc}
            operatorByRefinery={operatorByRefinery}
            loading={procLoading}
          />
        </div>

        <div className="flex flex-col gap-4">
          <ImpactWaterfall
            data={scenario}
            severity={severity}
            onSeverityChange={setSeverity}
            compliance={compliance}
            onComplianceChange={setCompliance}
            secondCorridor={secondCorridor}
            onSecondCorridorChange={setSecondCorridor}
            loading={scenLoading}
          />
          <AgentPanel />
          <ReserveGauge
            data={reserve}
            dailyGap={dailyGap}
            onDailyGapChange={setDailyGap}
            loading={resLoading}
          />
          <BacktestPanel data={backtest} />
        </div>
      </div>

      <section className="panel mt-4 px-4 py-3">
        <h3 className="text-[11px] uppercase tracking-wide text-[var(--muted)] mb-2">
          Bypass routes — and where their cargo actually ends up
        </h3>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-2.5">
          {(bypass?.routes ?? []).map((r) => {
            const coupled = r.discharge_corridor !== "none";
            return (
              <div
                key={r.route_name}
                className="bg-[var(--panel-2)] border rounded-md px-3 py-2"
                style={{ borderColor: coupled ? "#f0b42955" : "var(--border)" }}
              >
                <div className="text-[11.5px] leading-tight">{r.route_name}</div>
                <div className="mono text-[13px] mt-1">
                  {r.capacity_kbd == null ? "—" : `${fmt(r.capacity_kbd, 0)} kbd`}
                </div>
                <div className="asof mt-1 leading-snug">
                  {coupled ? (
                    <span className="text-[var(--warn)]">
                      ⚠ discharges via {r.discharge_corridor} — not a clean bypass
                    </span>
                  ) : (
                    <span className="text-[var(--ok)]">✓ outside all modeled corridors</span>
                  )}
                  <div className="mt-0.5">{r.status}</div>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <footer className="asof mt-4 leading-relaxed border-t border-[var(--border)] pt-3">
        Full methodology and limitations: click{" "}
        <button
          onClick={() => setShowMethodology(true)}
          className="underline decoration-dotted text-[var(--accent)] hover:text-[var(--foreground)]"
        >
          ⓘ methodology &amp; limitations
        </button>{" "}
        above. Current CRI(Hormuz) ={" "}
        <span className="mono">{criNow == null ? "—" : criNow.toFixed(1)}</span> as of {cursorDate}.
      </footer>
    </main>
  );
}
