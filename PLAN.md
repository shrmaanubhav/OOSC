# Project Sentinel — Phase List

Full design doc lives in the conversation history that produced this repo (schemas, formulas, weights). This file is the short-form phase index. See `CLAUDE.md` for standing rules that apply to every phase.

- [x] **Phase 0** — Repo scaffold (Python via uv, Next.js 15 in `web/`, dir structure, gitignore, PLAN.md, CLAUDE.md)
- [x] **Phase 1** — PortWatch ingestion (`ingest/portwatch.py`) — no key required. Exit: chokepoint6 collapse table for last 200 days.
- [x] **Phase 2** — GDELT ingestion + hand-built reference CSVs (`data/reference/`). Reference CSVs done and validated. GDELT's DOC API rate-limited us past usability (see `data/snapshots/gdelt/NOTE.md`); switched to `ingest/gdelt_bigquery.py` against the public BigQuery GKG dataset instead — 8,149 articles + 688 daily timeline points, ~78GB cloud-side query cost (well under the 1TB free tier), ~440KB actually on disk.
- [~] **Phase 3** — Event extractor (`agent/extractor.py`) + Corridor Risk Index v1 (`core/risk.py`). Both built and self-checked; CRI verified against real PortWatch O/X data (rises 8→87 across the actual Feb-Mar 2026 collapse). S/E components NaN pending GDELT backfill (Phase 2) and an ANTHROPIC_API_KEY for the extractor. Exit criterion ("S leads O") not yet visually confirmable until GDELT lands.
- [ ] **Phase 4** — Digital twin (`core/twin.py`) + PPAC PDF parsing (`ingest/ppac.py`).
- [ ] **Phase 5** — Scenario cascade (`core/scenario.py`), procurement LP (`core/procurement.py`), reserve LP (`core/reserve.py`, thin).
- [ ] **Phase 6** — Backtest (`core/backtest.py`) + provenance validator (`agent/provenance.py`).
- [ ] **Phase 7** — Agent loop + tools (`agent/`) + FastAPI/SSE (`api/main.py`).
- [ ] **Phase 8** — Frontend (`web/`): flow map, CRI timeline, sankey, waterfall, gauge, backtest panel.
- [ ] **Phase 9** — Demo rehearsal + polish. No new features.

Scope: Risk Intelligence + Scenario Modeller + Procurement Orchestrator built deep. Reserve Optimiser and Digital Twin kept thin (correct shape, no UI polish). EIA/data.gov.in (key-gated) sources are stretch — deferred behind config until keys are supplied.

Work stops after each phase for review — do not chain into the next phase without explicit go-ahead.
