# Project Sentinel — Phase Plan

Full design doc lives in the conversation history that produced this repo (schemas, formulas, weights). This file is the phase-by-phase build log — what's done, what's partial, and why. See `CLAUDE.md` for standing rules that apply to every phase, and `README.md` for how to run what exists today.

Scope: Risk Intelligence + Scenario Modeller + Procurement Orchestrator built deep. Reserve Optimiser and Digital Twin kept thin (correct shape, no UI polish). EIA/data.gov.in (key-gated) sources are stretch — deferred behind config until keys are supplied.

Work stops after each phase for review — do not chain into the next phase without explicit go-ahead.

## Status

| Phase | Name | Status |
|---|---|---|
| 0 | Repo scaffold | ✅ Done |
| 1 | PortWatch ingestion | ✅ Done |
| 2 | GDELT ingestion + reference CSVs | ✅ Done |
| 3 | Event extractor + Corridor Risk Index | ✅ Done |
| 4 | Digital twin + PPAC parsing | ✅ Done |
| 5 | Scenario cascade, procurement LP, reserve LP | ✅ Done |
| 6 | Backtest + provenance validator | ✅ Done |
| 7 | Agent loop + tools | ✅ Done |
| 8 | Frontend | ✅ Done |
| 9 | Demo rehearsal + polish | ⬜ Not started |

---

## Phase 0 — Repo scaffold

Python via `uv`, Next.js 15 in `web/`, directory structure, `.gitignore`, `PLAN.md`, `CLAUDE.md`.

**Exit criterion:** `git log` shows a commit; directory tree matches the design; Python imports succeed.

**Status:** Done.

---

## Phase 1 — PortWatch ingestion

`ingest/portwatch.py` — no key required.

**Exit criterion:** chokepoint6 collapse table for the last 200 days.

**Status:** Done. Live IMF PortWatch data confirms the real Hormuz collapse (transits down to ~1% of baseline by mid-March 2026).

---

## Phase 2 — GDELT ingestion + hand-built reference CSVs

`ingest/gdelt_bigquery.py` (primary) / `ingest/gdelt.py` (fallback), `data/reference/*.csv`.

**Exit criterion:** deduped GDELT article/timeline data on disk; reference CSVs present and internally consistent.

**Status:** Done. Reference CSVs validated (`ingest/validate_reference.py`). GDELT's DOC 2.0 API rate-limited past usability (see `data/snapshots/gdelt/NOTE.md` for the full failure history — three separate bugs found and fixed along the way); switched to `ingest/gdelt_bigquery.py` against the public BigQuery GKG dataset instead — 8,149 articles + 688 daily timeline points, ~78GB cloud-side query cost (well under the 1TB/month free tier), ~440KB actually on disk.

---

## Phase 3 — Event extractor + Corridor Risk Index v1

`agent/extractor.py`, `core/risk.py`.

**Exit criterion:** `CRI(chokepoint6)` plotted across Feb–Aug 2026 shows the collapse; the `S` (signal) component visibly leads the `O` (observed) component around late Feb.

**Status:** Done. All four CRI components (O/S/E/X) verified live: `S` spikes to 0.67–0.97 on 28 Feb–1 Mar 2026 while `O` is still 0 — exit criterion confirmed with real data. 54 real events extracted from GDELT via Groq (MVP-capped at 500 articles/corridor; hit Groq's 200k-token daily cap partway through but degraded gracefully rather than losing completed work). Two real bugs found and fixed: a pandas `groupby`/`apply` quirk that silently dropped `corridor_id`, and unhandled *daily* (as opposed to per-minute) rate limiting.

---

## Phase 4 — Digital twin + PPAC parsing

`core/twin.py`, `ingest/ppac.py`.

**Exit criterion:** twin serializes to JSON; a sample query (source → route → corridor → port → refinery) returns a sane, complete path.

**Status:** Done. PPAC Ready Reckoner Table 4.1 parsed (23 refineries, authoritative capacities) and cross-checked into `refineries.csv`, correcting several earlier estimates (Visakh was off ~2x, HMEL-Bathinda was missing entirely, Urals was wrongly tagged as Hormuz-transiting). Twin: 57 nodes, 54 edges. Sample path Murban → Hormuz → New Mangalore → MRPL verified sane, with real `searoute` distances.

---

## Phase 5 — Scenario cascade, procurement LP, reserve LP (the three deep pillars + thin reserve)

`core/scenario.py`: cascade engine per §2.4 (blocked volume → reroute feasibility incl. recursive bypass-corridor-CRI check → refinery impact via assay compatibility → product shortfall → price via elasticity calibrated on the real Feb–Mar 2026 ΔP/ΔQ, report the calibration and residual → macro India impact).
`core/procurement.py`: the LP from §2.5 (PuLP/CBC), λ exposed as a parameter so the frontend slider can drive it later; anti-concentration term included (this is what stops the optimizer from converging on ~70% Russia).
`core/reserve.py`: thin multi-period LP per §2.6 — correct shape and constraints, doesn't need UI polish yet.

**Exit criterion:** `run_scenario('chokepoint6', 1.0, 90)` produces a full cascade with sourced numbers at every step; the LP solves fast and visibly reallocates when λ changes; reserve LP produces a day-by-day drawdown schedule that hits zero under a 90-day dual-corridor closure.

**Status:** Done. All three modules built, self-checked (11/11 self-checks pass repo-wide), and verified against real data. Anti-concentration mechanism verified correct via synthetic self-check; on this build's real numbers (distance-only cost proxy, no price/freight data) nothing naturally exceeds the cap, reported honestly in `core/procurement.py`'s own output rather than faked. Found and fixed three real bugs along the way: `core/procurement.py` recomputed ~500 searoute distances per solve (2.4s → ~150ms after caching); `core/scenario.py`'s import-bill-delta was off by exactly 1000x (mbd→kbd conversion never rescaled to bbl); `core/reserve.py`'s LP was genuinely degenerate (erratic draw schedule tying the same objective as smooth depletion) until a time-weighted tie-break was added. Also caught and fixed a real Phase 2 data error: "Arab Light (via Yanbu)" was tagged as not transiting any corridor despite its own notes describing the Bab el-Mandeb crossing — now correctly coupled.

---

## Phase 6 — Backtest + provenance validator

`core/backtest.py`: fit the logistic calibration on Red Sea (Oct 2023–Feb 2024) labels, validate out-of-sample on Hormuz (Feb–Aug 2026); report AUC and a reliability curve for h=7,14,30.
`agent/provenance.py`: extract every numeral from an agent response, check it traces to a tool result within rounding tolerance, flag orphans.

**Exit criterion:** a real AUC number exists and is defensible; deliberately feeding the agent a question with no backing data produces a visible provenance violation.

**Status:** Done. `core/backtest.py` fits a single-feature (CRI/100 → risk) logistic calibration on the real Bab el-Mandeb/Houthi crisis (Oct 2023–Feb 2024, chokepoint4) and validates out-of-sample on the real Hormuz closure (Feb–Aug 2026, chokepoint6): AUC 0.979 at h=7, 0.919 at h=14, undefined at h=30 (the closure is sustained enough that almost every validation-window day is a positive at that horizon — reported honestly rather than faked). Disruption labels use a corridor-specific threshold (each corridor's own pre-crisis 95th-percentile O, floored at 0.02) rather than one global cutoff, because chokepoint4's baseline AIS noise is ~0 while chokepoint6's is ~0.22 — a real, reported asymmetry, as is the fact that the fit window's CRI is O-only (GDELT/X don't reach back to 2023–24) while the validation window has the full O/S/E/X index. Found and fixed a real bug along the way: `core/risk.py`'s `compute_E` returned a fabricated neutral 0.5 (not NaN) for any date before an extraction run's earliest known event, silently treating "no event data yet" as "confirmed calm" — this was collapsing the fit window's CRI into a narrow band and blowing up the logistic fit's coefficients (classic quasi-separation); fixed by returning NaN pre-coverage, plus added L2 regularization to `fit_logistic` since a small, near-separable sample will always be prone to this. `agent/provenance.py` extracts every numeral from a response and checks it traces (within tolerance) to a number that actually appeared in the tool results passed to it; self-check and `main()` both demonstrate a grounded response producing zero violations and a fabricated figure ($42 billion) producing a visible, named violation.

---

## Phase 7 — Agent loop + tools

`agent/tools.py` (wrapping everything in `core/` — the only numeric path the LLM is allowed to use), `agent/loop.py` (≤6-step tool-calling loop, same shape as the user's prior `GraphAgentToolCallingService` pattern, ported to Python), `agent/prompts/analyst.md` (versioned, per the §3.2 output contract). FastAPI + SSE in `api/main.py`.

**Exit criterion:** the agent answers "what happens if Bab el-Mandeb closes too?" using ≥3 tool calls, zero provenance violations, and surfaces the Saudi East-West → Bab el-Mandeb coupling from `bypass_routes.csv` without being told to.

**Status:** Done, verified live on `gemini-3.6-flash`: 5 tool calls, **21/21 numbers traced, zero provenance violations**, and it reached for `get_bypass_routes` unprompted and led with the Saudi East-West → Yanbu → Bab el-Mandeb coupling. Tool JSON Schema is defined once and shared between the prompt text and every provider's function-calling API, with a self-check asserting schema/signature parity so the model's view and the executable signature can't drift. The loop withholds tool schemas on its final step, which is what makes the ≤6 budget binding rather than advisory; `run_iter()` is the generator the SSE endpoint streams and `run()` just drains it, so streaming and synchronous paths can't diverge.

Three real provider bugs found and fixed, all now isolated in `agent/llm.py`: groq's `openai/gpt-oss-20b` routes any tool-shaped intent through its native tool channel and HTTP 400s when no schema is passed (this killed the original prose-JSON contract outright and forced the move to native function calling); an inlined `genai.Client()` gets closed out from under its own request; and Gemini 3.x rejects a replayed `functionCall` that lost its `thought_signature`, so the model's original part is now preserved verbatim rather than reconstructed.

Also hit Groq's 200k-token *daily* cap mid-verification — the loop degraded gracefully and kept completed work, exactly as rule 7 requires, and verification continued on Gemini.

---

## Phase 8 — Frontend

Next.js: animated flow map (§4.1, deck.gl/MapLibre, time scrubber), CRI timeline (§4.2), Sankey (§4.3), impact waterfall (§4.4), days-of-cover gauge (§4.5), backtest panel (§4.6), λ slider wired to the procurement LP, provenance badge wired to Phase 6's validator. Dark theme, consistent semantic color ramps, as-of timestamps on every chart element, per the design constraints.

**Exit criterion:** full demo runs end-to-end from `data/snapshots/` with networking disabled ("airplane mode" test).

**Status:** Done. All panels built and verified against real data in a browser: flow map (deck.gl, time scrubber with play), CRI timeline (S-leads-O visible, closure marked), Sankey (country → operator), impact waterfall, days-of-cover gauge, backtest panel, λ slider, and the provenance badge. Verified live: the λ slider genuinely re-solves server-side and shifts the allocation (Russia 40% → 41% as risk aversion pushes off high-CRI Hormuz — a real re-solve, not a decorative control), and the agent panel streams tool-call chips over SSE and lands the badge on **✓ 23/23 traced**.

**Airplane-mode confirmed by network trace:** every request the page makes goes to `localhost:3000` or `127.0.0.1:8000` — no CDN, no map tiles, no font fetch, no external host of any kind. Two things had to change to earn that: `next/font/google` was dropped for a system font stack (it fetches at build time), and the basemap is a 126KB Natural Earth GeoJSON in `web/public/` drawn by deck.gl rather than a tile server. `npm run build` passes clean with no warnings.

Found and fixed a real backend concurrency bug in the process: `core/risk.py` read the PortWatch snapshot through duckdb's module-level default connection, which is not thread-safe — FastAPI runs sync endpoints in a threadpool, so the dashboard's parallel first load raced it into "Attempting to execute an unsuccessful or closed pending query result". It was a plain `SELECT *`, so it's `pd.read_parquet` now, cached. `api/main.py`'s self-check gained a parallel-request regression test, since serial checks pass straight through this class of bug.

One caveat on verification: the browser pane in this environment doesn't composite frames, so the WebGL map could not be confirmed *visually* — deck.gl reports `onLoad` with no errors, WebGL2 is available, and its container measures correctly, but a human should eyeball the map once before demoing.

---

## Phase 9 — Demo rehearsal + polish

Walk the demo script beginning to end at least twice without touching a terminal. Fix whatever breaks. Add the one-line limitations disclosure (lag, spoofing, PPAC monthly granularity) somewhere visible. No new features in this phase — buffer only.

**Exit criterion:** two clean 4-minute run-throughs.

**Status:** Not started.

---

## Verification approach (applies across phases)

Each phase's own exit criterion (above) is the primary check, run and shown before moving on. Where a phase produces numeric/statistical output (CRI, backtest AUC, LP solve, price calibration), Claude prints the actual numbers/plots for the user to eyeball — not just "it ran without error." Phase 8 and 9 additionally require an actual browser check (start the Next.js dev server, click through the views) rather than just a build-success check.
