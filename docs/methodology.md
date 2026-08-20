# Methodology & known limitations

Every caveat below also appears inline in the dashboard (each panel's ⚠
line, or the "ⓘ methodology" expandable card in the header) — this page
exists so a reviewer can audit every assumption in one read instead of
hunting across five collapsed captions. If something here isn't also
findable in the running app, that's a bug in the app, not this page.

## AIS data (O — observed disruption)

Source: IMF PortWatch. Publishes **2–9 days late** by nature, and
PortWatch itself documents GPS jamming/AIS spoofing in the conflict zone.
Never described as real-time anywhere in this build.

## News signal (S) and event severity (E)

Source: GDELT (BigQuery GKG dataset), extracted into discrete events via
an LLM with a hallucination guard (`evidence_span` must appear verbatim
in the source text). Only 54 events were extracted in this build's run
(token-quota-capped), 14 of them for Hormuz. `core/risk.py` reports `E`
as genuinely missing (`NaN`, weights renormalized) rather than
substituting zero when data is short — the correct behavior, but it does
mean `E` is thin. GDELT coverage in this build starts January 2026, so
`S`/`E` are unavailable for anything earlier (this matters for the
backtest — see below).

## Refinery capacity

Source: PPAC Ready Reckoner, Table 4.1 — **monthly-aggregate granularity
only**, not real-time throughput.

## Procurement cost

`core/procurement.py`'s LP cost term is a real `searoute` sea-distance
proxy, **not** real FOB/freight/war-risk/demurrage pricing — no primary
source for those is ingested in this build (deferred, Tier 2). The
anti-concentration safeguard is verified correct via synthetic
self-check, but doesn't visibly bind on this build's real numbers: a
pure-distance model can't reproduce Russia's actual cost-competitiveness,
which comes from price discount, not proximity.

## Sanctions flag

`sanctions_flag` in `data/reference/sources.csv` is a **hand-tagged
column** (Urals/ESPO/Sokol/Merey marked `True`), not backed by a live
sanctioned-vessel or sanctioned-entity list (e.g. OpenSanctions). The
"sanctions compliance" toggle in the dashboard is a real LP constraint —
it does prevent those grades from substituting — but the underlying flag
is a static, manually-curated column, not fed from a real screening
service.

## Scenario cascade

- **Demand** uses refinery nameplate capacity as a proxy for actual
  throughput (India's refineries run at high utilization, but this isn't
  the same as PPAC reporting an exact figure).
- **Product shortfall** uses one national-average yield mix (PPAC Table
  4.5) applied to every refinery, not refinery-specific yields.
- **Price** is calibrated on the real Feb–Mar 2026 $65→$113.57/bbl move
  (not an invented elasticity) — see `calibrate_elasticity()` in
  `core/scenario.py` for the derivation and its own caveats.
- **CPI impact** assumes 1:1 crude-to-retail pass-through, which ignores
  India's actively-adjusted fuel excise duty cushioning.

## Strategic reserve (SPR)

The gauge shows India's **5.33 MMT strategic reserve (~9.5 days of
cover)** — this is **not** the same as India's ~74 days of total national
storage (refinery + private + strategic combined). The two numbers are
kept distinct everywhere in this build (`CLAUDE.md` rule 10); conflating
them is the single most likely misread of that panel.

## Digital twin

The crude flow map **is** the digital twin view — a `networkx` graph of
source → corridor → port → refinery, geospatially rendered and driven by
the same severity/λ controls as the other panels. There is no separate
twin artifact; the map is deliberately kept thin per project scope
(`core/twin.py`'s own docstring) rather than gold-plated at the expense
of the three deep pillars (Risk Intelligence, Scenario Modeller,
Procurement Orchestrator).

## Backtest

Fit window (Bab el-Mandeb, Oct 2023–Feb 2024) and validation window
(Hormuz, Feb–Aug 2026) are asymmetric on purpose, and that asymmetry is
reported rather than hidden:

- The **fit window's CRI is O-only** — GDELT coverage in this build
  starts January 2026, so `S`/`E`/`X` are all unavailable that far back.
  The **validation window has the full four-component index**.
- Real AUC: **0.979 at h=7, 0.919 at h=14, undefined at h=30** — not
  zero. At h=30 the sustained closure leaves almost every validation-day
  label positive, which makes AUC mathematically undefined, not bad.
- Disruption labels use a **corridor-specific threshold** (each
  corridor's own pre-crisis 95th-percentile of `O`, floored at 0.02)
  rather than one global cutoff, because the two corridors' baseline AIS
  noise floors are wildly different — Bab el-Mandeb's pre-2023 `O` is
  ~0 every day, Hormuz's ordinary-day noise reaches ~0.22.

## Demo reliability

This dashboard runs on frozen snapshots (`data/snapshots/`) rather than
live feeds. That's a deliberate choice for demo/judging reliability, not
a limitation being hidden — the ingestion pipeline behind every snapshot
is real, runnable, and documented per-source in `ingest/`, and `PLAN.md`
records exactly what ran against live data and what's cached.
