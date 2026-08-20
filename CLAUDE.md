# Project Sentinel — standing instructions

AI-driven energy supply-chain resilience system for India, backtested against the real Feb–Aug 2026 Strait of Hormuz closure. See `PLAN.md` for the phase index.

## Rules

1. **Commit discipline.** Conventional commit messages: `feat:`, `fix:`, `docs:`, `data:`, `chore:`. Never add Claude as co-author. Never `git push` unless asked.
2. **Stop after each phase.** Implement, run the phase's exit criterion, show the result, wait for go-ahead. Don't chain phases silently.
3. **Snapshot discipline.** Anything the demo depends on gets frozen to `data/snapshots/` before moving on. Demo must run with zero network calls — never re-fetch at demo time.
4. **No LLM arithmetic.** Every number in agent-facing output must trace to a tool result in `core/`. The LLM extracts, routes, narrates — never computes. Provenance validator (`agent/provenance.py`, Phase 6) enforces this in code.
5. **Cite reference data.** Every number in `data/reference/*.csv` (refineries, sources, SPR, bypass routes) gets an inline source comment — PPAC Ready Reckoner, MoPNG parliament reply, etc. Never trust an LLM's memory for these figures; verify against PPAC.
6. **Fixed CRI baseline, not trailing.** Seasonal baseline window is fixed at 2024-01-01 → 2026-02-27. A trailing window collapses to match a sustained closure and silently reads "normal" — this is the easiest correctness bug to introduce by accident.
7. **Key-gated ingestion (EIA, data.gov.in, LLM calls) waits, doesn't block.** Build against the documented schema/client, wire behind config, use cached/mocked responses until keys arrive. Flag clearly what hasn't run against live data. When a provider's rate/token limit is hit, fail gracefully and keep whatever succeeded — never let one exhausted quota discard already-completed work.
8. **Data-quality flags are a feature.** AIS spoofing/blackout days, PortWatch lag (2–9 days), PPAC's monthly-aggregate-only granularity — surface these, don't hide them. Never claim "real-time."
9. **No scope creep.** Reserve Optimiser and Digital Twin are deliberately thin — correct shape and constraints, no UI polish. Don't gold-plate them at the expense of Risk Intelligence, Scenario Modeller, Procurement Orchestrator, or the backtest.
10. **9.5 days vs ~74 days.** SPR strategic reserve (5.33 MMT ≈ 9.5 days) is not the same as total national storage (~74 days of net imports). Keep these distinct everywhere.

## Stack

- Backend: Python 3.12 via `uv`, FastAPI + SSE, DuckDB, pandas, networkx, pulp, httpx, pydantic.
- LLM backend: provider-switchable via `agent/llm.py` and `.env`'s `LLM_PROVIDER` (groq default, openai, gemini) — never import a provider SDK directly outside that module.
- GDELT: primary path is BigQuery (`ingest/gdelt_bigquery.py`, needs `GOOGLE_APPLICATION_CREDENTIALS`); the DOC 2.0 API (`ingest/gdelt.py`) is a fallback that rate-limits too aggressively for a full historical backfill.
- Frontend: Next.js 15 (`web/`, App Router, TypeScript, Tailwind) + deck.gl/react-map-gl/maplibre-gl + recharts.
- No Neo4j — the twin is ~60 nodes, networkx in memory is sufficient.
