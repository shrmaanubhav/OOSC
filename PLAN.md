# Project Sentinel — Phase List

Full design doc lives in the conversation history that produced this repo (schemas, formulas, weights). This file is the short-form phase index. See `CLAUDE.md` for standing rules that apply to every phase.

- [x] **Phase 0** — Repo scaffold (Python via uv, Next.js 15 in `web/`, dir structure, gitignore, PLAN.md, CLAUDE.md)
- [x] **Phase 1** — PortWatch ingestion (`ingest/portwatch.py`) — no key required. Exit: chokepoint6 collapse table for last 200 days.
- [x] **Phase 2** — GDELT ingestion + hand-built reference CSVs (`data/reference/`). Reference CSVs done and validated. GDELT's DOC API rate-limited us past usability (see `data/snapshots/gdelt/NOTE.md`); switched to `ingest/gdelt_bigquery.py` against the public BigQuery GKG dataset instead — 8,149 articles + 688 daily timeline points, ~78GB cloud-side query cost (well under the 1TB free tier), ~440KB actually on disk.
- [x] **Phase 3** — Event extractor (`agent/extractor.py`) + Corridor Risk Index v1 (`core/risk.py`). All four CRI components (O/S/E/X) verified live: S spikes to 0.67-0.97 on 28 Feb-1 Mar 2026 while O is still 0 -- exit criterion ("S leads O") confirmed. 54 real events extracted from GDELT via Groq (MVP-capped at 500 articles/corridor, hit Groq's 200k-token daily cap partway through but degraded gracefully). Two real bugs found and fixed along the way: a pandas groupby/apply quirk that silently dropped corridor_id, and unhandled daily (as opposed to per-minute) rate limiting.
- [x] **Phase 4** — Digital twin (`core/twin.py`) + PPAC PDF parsing (`ingest/ppac.py`). PPAC Ready Reckoner Table 4.1 parsed (23 refineries, authoritative capacities) and cross-checked into refineries.csv, correcting several earlier estimates (Visakh was off ~2x, HMEL-Bathinda was missing, Urals was wrongly tagged as Hormuz-transiting). Twin: 57 nodes, 54 edges, serializes to JSON, sample path Murban->Hormuz->New Mangalore->MRPL verified sane.

### Phase 5 — Scenario cascade, procurement LP, reserve LP (the three deep pillars + thin reserve) [x] DONE
`core/scenario.py`: cascade engine per §2.4 (blocked volume → reroute feasibility incl. recursive bypass-corridor-CRI check → refinery impact via assay compatibility → product shortfall → price via elasticity calibrated on the real Feb–Mar 2026 ΔP/ΔQ, report the calibration and residual → macro India impact).
`core/procurement.py`: the LP from §2.5 (PuLP/CBC or highspy), λ exposed as a parameter so the frontend slider can drive it later; anti-concentration term included (this is what stops the optimizer from converging on ~70% Russia).
`core/reserve.py`: thin multi-period LP per §2.6 — correct shape and constraints, doesn't need UI polish yet.
**Exit criterion:** `run_scenario('chokepoint6', 1.0, 90)` produces a full cascade with sourced numbers at every step; the LP solves in milliseconds and visibly reallocates when λ changes; reserve LP produces a day-by-day drawdown schedule that hits zero under a 90-day dual-corridor closure.
**Status:** all three modules built, self-checked (11/11 self-checks pass repo-wide), and verified against real data. Anti-concentration mechanism verified correct via synthetic self-check; on this build's real numbers (distance-only cost proxy, no price/freight data) nothing naturally exceeds the cap, reported honestly in `core/procurement.py`'s own output rather than faked. Found and fixed three real bugs along the way: `core/procurement.py` recomputed ~500 searoute distances per solve (2.4s → ~150ms after caching); `core/scenario.py`'s import-bill-delta was off by exactly 1000x (mbd→kbd conversion never rescaled to bbl); `core/reserve.py`'s LP was genuinely degenerate (erratic draw schedule tying the same objective as smooth depletion) until a time-weighted tie-break was added. Also caught and fixed a real Phase 2 data error: "Arab Light (via Yanbu)" was tagged as not transiting any corridor despite its own notes describing the Bab el-Mandeb crossing — now correctly coupled.

### Phase 6 — Backtest + provenance validator
`core/backtest.py`: fit the logistic calibration on Red Sea (Oct 2023–Feb 2024) labels, validate out-of-sample on Hormuz (Feb–Aug 2026); report AUC and a reliability curve for h=7,14,30.
`agent/provenance.py`: extract every numeral from an agent response, check it traces to a tool result within rounding tolerance, flag orphans.
**Exit criterion:** a real AUC number exists and is defensible; deliberately feeding the agent a question with no backing data produces a visible provenance violation.

### Phase 7 — Agent loop + tools
`agent/tools.py` (wrapping everything in `core/` — the only numeric path the LLM is allowed to use), `agent/loop.py` (≤6-step tool-calling loop, same shape as the user's prior `GraphAgentToolCallingService` pattern, ported to Python), `agent/prompts/analyst.md` (versioned, per the §3.2 output contract). FastAPI + SSE in `api/main.py`.
**Exit criterion:** the agent answers "what happens if Bab el-Mandeb closes too?" using ≥3 tool calls, zero provenance violations, and surfaces the Saudi East-West → Bab el-Mandeb coupling from `bypass_routes.csv` without being told to.

### Phase 8 — Frontend
Next.js: animated flow map (§4.1, deck.gl/MapLibre, time scrubber), CRI timeline (§4.2), Sankey (§4.3), impact waterfall (§4.4), days-of-cover gauge (§4.5), backtest panel (§4.6), λ slider wired to the procurement LP, provenance badge wired to Phase 6's validator. Dark theme, consistent semantic color ramps, as-of timestamps on every chart element, per § design constraints.
**Exit criterion:** full demo runs end-to-end from `data/snapshots/` with networking disabled ("airplane mode" test).

### Phase 9 — Demo rehearsal + polish
Walk the §7 demo script beginning to end at least twice without touching a terminal. Fix whatever breaks. Add the one-line limitations disclosure (lag, spoofing, PPAC monthly granularity) somewhere visible. No new features in this phase — buffer only.
**Exit criterion:** two clean 4-minute run-throughs.

## Verification approach (applies across phases)
Each phase's own exit criterion (above) is the primary check, run and shown before moving on. Where a phase produces numeric/statistical output (CRI, backtest AUC, LP solve, price calibration), Claude prints the actual numbers/plots for the user to eyeball — not just "it ran without error." Phase 8 and 9 additionally require an actual browser check (start the Next.js dev server, click through the views) rather than just a build-success check.

Scope: Risk Intelligence + Scenario Modeller + Procurement Orchestrator built deep. Reserve Optimiser and Digital Twin kept thin (correct shape, no UI polish). EIA/data.gov.in (key-gated) sources are stretch — deferred behind config until keys are supplied.

Work stops after each phase for review — do not chain into the next phase without explicit go-ahead.
