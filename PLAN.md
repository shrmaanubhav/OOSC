# Project Sentinel — Phase List

Full design doc lives in the conversation history that produced this repo (schemas, formulas, weights). This file is the short-form phase index. See `CLAUDE.md` for standing rules that apply to every phase.

- [x] **Phase 0** — Repo scaffold (Python via uv, Next.js 15 in `web/`, dir structure, gitignore, PLAN.md, CLAUDE.md)
- [x] **Phase 1** — PortWatch ingestion (`ingest/portwatch.py`) — no key required. Exit: chokepoint6 collapse table for last 200 days.
- [x] **Phase 2** — GDELT ingestion + hand-built reference CSVs (`data/reference/`). Reference CSVs done and validated. GDELT's DOC API rate-limited us past usability (see `data/snapshots/gdelt/NOTE.md`); switched to `ingest/gdelt_bigquery.py` against the public BigQuery GKG dataset instead — 8,149 articles + 688 daily timeline points, ~78GB cloud-side query cost (well under the 1TB free tier), ~440KB actually on disk.
- [x] **Phase 3** — Event extractor (`agent/extractor.py`) + Corridor Risk Index v1 (`core/risk.py`). All four CRI components (O/S/E/X) verified live: S spikes to 0.67-0.97 on 28 Feb-1 Mar 2026 while O is still 0 -- exit criterion ("S leads O") confirmed. 54 real events extracted from GDELT via Groq (MVP-capped at 500 articles/corridor, hit Groq's 200k-token daily cap partway through but degraded gracefully). Two real bugs found and fixed along the way: a pandas groupby/apply quirk that silently dropped corridor_id, and unhandled daily (as opposed to per-minute) rate limiting.
- [x] **Phase 4** — Digital twin (`core/twin.py`) + PPAC PDF parsing (`ingest/ppac.py`). PPAC Ready Reckoner Table 4.1 parsed (23 refineries, authoritative capacities) and cross-checked into refineries.csv, correcting several earlier estimates (Visakh was off ~2x, HMEL-Bathinda was missing, Urals was wrongly tagged as Hormuz-transiting). Twin: 57 nodes, 54 edges, serializes to JSON, sample path Murban->Hormuz->New Mangalore->MRPL verified sane.
- [ ] **Phase 5** — Scenario cascade (`core/scenario.py`), procurement LP (`core/procurement.py`), reserve LP (`core/reserve.py`, thin).
- [ ] **Phase 6** — Backtest (`core/backtest.py`) + provenance validator (`agent/provenance.py`).
- [ ] **Phase 7** — Agent loop + tools (`agent/`) + FastAPI/SSE (`api/main.py`).
- [ ] **Phase 8** — Frontend (`web/`): flow map, CRI timeline, sankey, waterfall, gauge, backtest panel.
- [ ] **Phase 9** — Demo rehearsal + polish. No new features.

Scope: Risk Intelligence + Scenario Modeller + Procurement Orchestrator built deep. Reserve Optimiser and Digital Twin kept thin (correct shape, no UI polish). EIA/data.gov.in (key-gated) sources are stretch — deferred behind config until keys are supplied.

Work stops after each phase for review — do not chain into the next phase without explicit go-ahead.
