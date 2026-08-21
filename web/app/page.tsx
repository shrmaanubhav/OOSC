"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import AgentPanel from "./components/AgentPanel";
import BacktestPanel from "./components/BacktestPanel";
import CriTimeline from "./components/CriTimeline";
import FlowMap from "./components/FlowMap";
import ImpactWaterfall from "./components/ImpactWaterfall";
import OnboardingStrip from "./components/OnboardingStrip";
import Panel from "./components/Panel";
import ProcurementPanel from "./components/ProcurementPanel";
import ReserveGauge from "./components/ReserveGauge";
import SidebarNav, { PanelKey } from "./components/SidebarNav";
import {
  BacktestResult,
  BypassRoutes,
  Corridors,
  CriSeries,
  DisruptionProbability,
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
  const [probability, setProbability] = useState<Record<string, DisruptionProbability>>({});
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
  // status-quo baseline (no shock, no risk aversion) -- fetched once, used
  // by RecommendedActions to show "+X kbd vs current sourcing" deltas
  const [procBaseline, setProcBaseline] = useState<ProcurementResult | null>(null);

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
      get<DisruptionProbability>("/api/probability/chokepoint6?horizon_days=7"),
      get<DisruptionProbability>("/api/probability/chokepoint4?horizon_days=7"),
      get<ProcurementResult>("/api/procurement?severity=0&lambda_risk=0"),
    ])
      .then(([c6, c4, tw, co, by, bt, refs, p6, p4, procBase]) => {
        setCri({ chokepoint6: c6, chokepoint4: c4 });
        setProbability({ chokepoint6: p6, chokepoint4: p4 });
        setTwin(tw);
        setCorridors(co);
        setBypass(by);
        setBacktest(bt);
        setRefineries(refs.rows);
        setProcBaseline(procBase);
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
  // "map" default per the demo brief: the flow map is the most orienting
  // entry point, and it's what the header's corridor chips already point at.
  const [activePanel, setActivePanel] = useState<PanelKey>("map");

  return (
    <main className="h-screen flex flex-col p-4 lg:p-5 max-w-[1900px] mx-auto w-full">
      <header className="flex flex-wrap items-end justify-between gap-3 mb-4 shrink-0">
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
            const p = probability[c.corridor_id];
            return (
              <div
                key={c.corridor_id}
                className="panel px-3 py-1.5 flex items-center gap-2.5"
                title={
                  p
                    ? `${c.note}\n\nP(disruption within ${p.horizon_days}d) = ${(p.probability * 100).toFixed(0)}% as of now (CRI=${p.cri_now}). ${p.caveat}`
                    : c.note
                }
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
                <div className="text-right leading-tight">
                  <span className="mono text-[16px]" style={{ color: riskColor(v) }}>
                    {v == null ? "—" : v.toFixed(0)}
                  </span>
                  {p && (
                    <div className="asof mono">
                      P({p.horizon_days}d) {(p.probability * 100).toFixed(0)}%
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </header>

      {err && (
        <div className="panel px-4 py-3 mb-4 border-[#e5484d55] bg-[#e5484d12] shrink-0">
          <p className="text-[12.5px] text-[var(--bad)]">
            Can’t reach the API ({err}). Start it with{" "}
            <code className="mono">uv run python api/main.py</code>.
          </p>
        </div>
      )}

      <div className="shrink-0">
        <OnboardingStrip />
      </div>

      {showMethodology && (
        <section className="panel mt-0 mb-4 px-4 py-3 border-[var(--accent)]/40 shrink-0">
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
              <b className="text-[var(--foreground)]">Sanctions flag</b> — still a per-grade column
              in <code className="mono">data/reference/sources.csv</code> (Urals/ESPO/Sokol/Merey),
              not entity-resolved to a specific vessel. Now backed by a real pull: OFAC’s SDN list
              via OpenSanctions counts 439 vessels under the US-RUSHAR (Russia) program and 60 under
              US-VEN (Venezuela), 2026-08-20 (<code className="mono">ingest/sanctions.py</code>) —
              real evidence the sanctions regime is active, not proof a specific cargo used a
              specific listed tanker.
            </li>
            <li>
              <b className="text-[var(--foreground)]">Scenario cascade</b> — demand uses each
              refinery’s actual FY2025-26 processing throughput (PPAC Table 4.1), not nameplate
              capacity; still one national yield mix applied to every refinery, and 1:1
              crude-to-CPI pass-through that ignores India’s fuel excise cushioning. The 90-day
              import-bill figure now uses a real observed price-decay half-life (~42 days, fit on
              PPAC’s own Apr→Jun 2026 monthly averages) instead of holding the peak price flat.
            </li>
            <li>
              <b className="text-[var(--foreground)]">Digital twin</b> — the flow map above{" "}
              <i>is</i> the twin view: a networkx graph of source → corridor → port → refinery,
              geospatially rendered and driven by the same severity/λ controls as the other
              panels, not a separate artifact.
            </li>
            <li>
              <b className="text-[var(--foreground)]">Backtest</b> — fit window CRI (Bab
              el-Mandeb, Oct 2023–Feb 2024) now has O and S (GDELT was specifically backfilled for
              this window); E is still unavailable (LLM event extraction never ran against these
              older articles) and X has no chokepoint4 figure by design. Validation window (Hormuz)
              has all four components. AUC is undefined, not zero, at horizons where the sustained
              closure leaves only one label class.
            </li>
            <li>
              <b className="text-[var(--foreground)]">Live disruption probability</b> — the P(7d)
              figure on each corridor chip above reuses this same calibration, applied to today’s
              CRI. Because it was fit on Bab el-Mandeb’s much narrower CRI range, it is measurably
              under-confident on Hormuz: even during the real, ongoing, near-total closure this
              build backtests against, it reports well under 50% — a genuine cross-corridor
              transfer limitation, shown rather than hidden.
            </li>
          </ul>
        </section>
      )}

      {/* Single-panel-focus body: a left rail picks which one panel shows in
          the main area; the Analyst stays docked on the right at all times,
          regardless of which panel is focused -- it's the constant surface,
          not one card among seven. */}
      <div className="flex-1 min-h-0 flex flex-col xl:flex-row gap-4">
        <SidebarNav active={activePanel} onChange={setActivePanel} />

        <div className="flex-1 min-w-0 min-h-0 overflow-y-auto">
          {activePanel === "map" && (
            <FlowMap
              twin={twin}
              allocation={proc?.allocation ?? []}
              cri={cri}
              cursorDate={cursorDate}
              onCursorChange={onCursorChange}
            />
          )}
          {activePanel === "risk" && cri.chokepoint6 && (
            <CriTimeline
              data={cri.chokepoint6}
              cursorDate={cursorDate}
              onCursorChange={onCursorChange}
            />
          )}
          {activePanel === "procurement" && (
            <ProcurementPanel
              data={proc}
              baseline={procBaseline}
              lambdaRisk={lambdaRisk}
              onLambdaChange={setLambdaRisk}
              antiConcentration={antiConc}
              onAntiConcentrationChange={setAntiConc}
              operatorByRefinery={operatorByRefinery}
              loading={procLoading}
            />
          )}
          {activePanel === "impact" && (
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
          )}
          {activePanel === "reserve" && (
            <ReserveGauge
              data={reserve}
              dailyGap={dailyGap}
              onDailyGapChange={setDailyGap}
              loading={resLoading}
            />
          )}
          {activePanel === "backtest" && <BacktestPanel data={backtest} />}
          {activePanel === "bypass" && (
            <Panel
              title="Bypass routes"
              subtitle="And where their cargo actually ends up"
              className="min-h-[440px] h-full"
            >
              <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                {(bypass?.routes ?? []).map((r) => {
                  const coupled = r.discharge_corridor !== "none";
                  return (
                    <div
                      key={r.route_name}
                      className="bg-[var(--panel-2)] border rounded-md px-3 py-2.5"
                      style={{ borderColor: coupled ? "#f0b42955" : "var(--border)" }}
                    >
                      <div className="text-[12.5px] leading-tight">{r.route_name}</div>
                      <div className="mono text-[15px] mt-1.5">
                        {r.capacity_kbd == null ? "—" : `${fmt(r.capacity_kbd, 0)} kbd`}
                      </div>
                      <div className="asof mt-1.5 leading-snug">
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
            </Panel>
          )}
        </div>

        <div className="xl:w-[400px] w-full xl:h-full shrink-0">
          <AgentPanel />
        </div>
      </div>

      <footer className="asof mt-3 leading-relaxed border-t border-[var(--border)] pt-2 shrink-0">
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
