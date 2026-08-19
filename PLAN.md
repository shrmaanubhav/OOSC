# Project Sentinel — Phase List

Full design doc lives in the conversation history that produced this repo (schemas, formulas, weights). This file is the short-form phase index. See `CLAUDE.md` for standing rules that apply to every phase.

- [x] **Phase 0** — Repo scaffold (Python via uv, Next.js 15 in `web/`, dir structure, gitignore, PLAN.md, CLAUDE.md)
- [x] **Phase 1** — PortWatch ingestion (`ingest/portwatch.py`) — no key required. Exit: chokepoint6 collapse table for last 200 days.
- [~] **Phase 2** — GDELT ingestion (`ingest/gdelt.py`) + hand-built reference CSVs (`data/reference/`) — no key required. Reference CSVs done and validated. GDELT backfill BLOCKED on IP-level rate limiting — see `data/snapshots/gdelt/NOTE.md` for what's missing and how to resume.
- [ ] **Phase 3** — Event extractor (`agent/extractor.py`) + Corridor Risk Index v1 (`core/risk.py`).
- [ ] **Phase 4** — Digital twin (`core/twin.py`) + PPAC PDF parsing (`ingest/ppac.py`).
- [ ] **Phase 5** — Scenario cascade (`core/scenario.py`), procurement LP (`core/procurement.py`), reserve LP (`core/reserve.py`, thin).
- [ ] **Phase 6** — Backtest (`core/backtest.py`) + provenance validator (`agent/provenance.py`).
- [ ] **Phase 7** — Agent loop + tools (`agent/`) + FastAPI/SSE (`api/main.py`).
- [ ] **Phase 8** — Frontend (`web/`): flow map, CRI timeline, sankey, waterfall, gauge, backtest panel.
- [ ] **Phase 9** — Demo rehearsal + polish. No new features.

Scope: Risk Intelligence + Scenario Modeller + Procurement Orchestrator built deep. Reserve Optimiser and Digital Twin kept thin (correct shape, no UI polish). EIA/data.gov.in (key-gated) sources are stretch — deferred behind config until keys are supplied.

Work stops after each phase for review — do not chain into the next phase without explicit go-ahead.
