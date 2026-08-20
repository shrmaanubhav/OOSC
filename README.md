# Project Sentinel

AI-driven energy supply-chain resilience system for India — built and
backtested against a real event, not a hypothetical: the Strait of Hormuz
closure that began 28 Feb 2026 and was still ongoing as of this build
(19–20 Aug 2026). Full background, architecture rationale, and formulas
live in `PLAN.md` (phase index) and the design doc referenced there;
this file is about running and understanding what exists **right now**
(Phases 0–8 complete).

## What's built so far

1. **Real AIS data** (IMF PortWatch) showing the Hormuz collapse.
2. **A Corridor Risk Index (CRI)** combining that AIS signal with news
   volume/tone (GDELT) and LLM-extracted discrete events, with a
   verified "news leads AIS by about a week" result.
3. **A digital twin** (crude sources → corridor → Indian port →
   refinery) built from PPAC's authoritative refinery capacity data.
4. **A procurement LP** allocating crude sources to refineries (cost +
   risk-adjusted, with an anti-concentration safeguard), a **scenario
   cascade engine** turning a corridor shock into refinery run-cuts,
   product shortfalls, a calibrated price impact, and India-macro
   impact (import bill, %GDP, CPI) — every number sourced or flagged,
   and a **reserve drawdown LP** showing days-of-cover under a shock.

5. **A backtest** (`core/backtest.py`) calibrating the CRI against a real,
   different crisis (Red Sea/Bab el-Mandeb, Oct 2023–Feb 2024) and
   validating out-of-sample against the real Hormuz closure, plus a
   **provenance validator** (`agent/provenance.py`) that catches any
   number an agent response can't trace back to an actual tool result.

6. **An agent** (`agent/loop.py`) that answers questions using only these
   tools, with every number in its answer checked in code against the
   tool results that produced it — and a **dashboard** (`web/`) that
   runs the whole thing with the network unplugged.

Phase 9 (demo rehearsal + polish) is not done yet.

## Run the dashboard

Two processes. Backend first:

```bash
uv run python api/main.py
```

Then the frontend, in a second terminal:

```bash
npm --prefix web run dev
```

Open http://localhost:3000. Everything except the Analyst panel works
with no API key and no internet — the backend reads only from
`data/snapshots/`, and the map's coastlines are a local GeoJSON rather
than a tile server. The Analyst panel is the one part that needs a live
LLM key (see `.env`); every other panel is fully offline.

The two interactive controls worth driving in a demo:

- **λ (risk aversion)** in the procurement panel re-solves the LP
  server-side on every drag and visibly shifts allocation away from
  high-CRI corridors.
- **Hormuz severity** + **“+ Bab el-Mandeb closed”** in the impact panel
  re-runs the full cascade, which is where the bypass-coupling point
  lands: the Saudi East-West pipeline stops being an escape route once
  its discharge corridor is also shut.

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node 22+ and npm (only needed once Phase 8/frontend starts — not
  required to run anything below)
- A free [Groq](https://console.groq.com/keys) API key (or OpenAI/Gemini
  — see `.env.example`) if you want to re-run event extraction
- A free Google Cloud project with the BigQuery API enabled, if you want
  to re-run the GDELT backfill (see `.env.example` for the exact setup
  steps — not needed just to explore the already-committed data)

## Setup

```bash
uv sync
cp .env.example .env
```

Edit `.env` and fill in whichever keys you actually have — nothing
below requires a key to run against the data already committed in
`data/snapshots/`. Keys only matter if you want to re-run ingestion
from scratch (live network calls) instead of reading what's there.

## Quick start — see the CRI in under a minute

Everything below reads from `data/snapshots/`, already committed to
this repo. No network calls, no keys needed.

```bash
uv run python core/risk.py
```

Prints the last 30 days of `CRI(chokepoint6)` (Strait of Hormuz) with
its four components (`O` observed/AIS, `S` news signal, `E` extracted
event severity, `X` exposure) and which ones had data on each day. To
see the headline result — news leading AIS by about a week around the
actual closure — inspect the Feb–Mar 2026 window:

```bash
uv run python -c "
from core.risk import compute_cri
import pandas as pd
df = compute_cri('chokepoint6')
with pd.option_context('display.max_rows', 40, 'display.width', 140):
    print(df.loc['2026-02-20':'2026-03-15'])
"
```

Watch `S` spike to ~0.7–0.97 on 28 Feb–1 Mar while `O` is still 0 —
AIS data (2–9 day lag by nature) doesn't confirm the collapse until
`O` starts climbing on 2–4 Mar.

## Explore the digital twin

```bash
uv run python core/twin.py
```

Builds the twin fresh from `data/reference/*.csv` + `data/snapshots/
portwatch/` (fast, no network — `searoute`'s routing data ships with
the package) and prints a sample path: a crude grade → the corridor it
transits → an Indian discharge port → the refinery it feeds, with real
maritime distances.

## Run a scenario

```bash
uv run python core/scenario.py
```

Runs `run_scenario('chokepoint6', 1.0, 90)` — a full Hormuz closure for
90 days — through the cascade: the procurement LP's reroute attempt,
refinery run-cuts, product shortfall (PPAC's real yield mix), a price
impact calibrated on the actual Feb–Mar 2026 $65→$113.57/bbl move, and
India-macro impact (import bill, %GDP, CPI). Also runs a harder variant
(sanctions-compliance mode, which blocks Russia/Venezuela substitution)
that actually triggers a refinery shortfall — the base scenario finds
enough non-Hormuz capacity to fully reroute, which is itself a real
finding (matches what MoPNG reported actually happening).

```bash
uv run python core/procurement.py   # just the allocation LP, incl. the λ/μ mechanics
uv run python core/reserve.py       # SPR drawdown schedule under a supply gap
```

## Backtest and provenance

```bash
uv run python core/backtest.py
```

Fits a logistic CRI-to-disruption-probability calibration on the real
Red Sea/Bab el-Mandeb crisis (Oct 2023–Feb 2024) and validates it
out-of-sample on the real Hormuz closure (Feb–Aug 2026), reporting AUC
and a reliability curve for h=7/14/30 days. Prints the real numbers
(AUC 0.979 at h=7, 0.919 at h=14, undefined at h=30 once the closure
makes almost every validation day a positive) plus the honest caveats:
the fit window's CRI is O-only (GDELT didn't reach back to 2023–24) and
each corridor uses its own noise-floor-calibrated disruption threshold.

```bash
uv run python agent/provenance.py
```

Runs the provenance validator against a grounded response (zero
violations) and an adversarial one with a fabricated figure (a named,
visible violation) — the agent loop runs every response through this
before it reaches the user, and the dashboard's provenance badge shows
the verdict.

## Ask the agent

```bash
uv run python agent/loop.py "what happens if Bab el-Mandeb closes too?"
```

Needs a live LLM key (`.env`, default provider `groq`; `LLM_PROVIDER=gemini`
and `openai` also work). The loop calls tools from `agent/tools.py` — the
only numeric path it's allowed to use — and prints how many of the numbers
in its answer traced back to an actual tool result.

Note that Groq's free tier caps at 200,000 tokens/**day**, separate from
its per-minute limit. When that's exhausted the loop degrades gracefully
rather than crashing, but you'll want `LLM_PROVIDER=gemini` to keep going.

## Re-running ingestion (optional — only if you want fresh data)

Each script is independently runnable and idempotent. Run in this order
if starting from nothing (later ones depend on earlier ones' snapshot
output):

```bash
# 1. IMF PortWatch — AIS chokepoint + Indian port data. No key needed.
uv run python ingest/portwatch.py

# 2. GDELT news signal, via BigQuery (primary path — needs
#    GOOGLE_APPLICATION_CREDENTIALS + GCP_PROJECT_ID in .env).
#    Does a dry-run cost check before every real query and refuses to
#    run past 200GB without --force -- verified live cost is ~78GB
#    total for both corridors, well under the 1TB/month free tier.
uv run python ingest/gdelt_bigquery.py

# 2b. Fallback if BigQuery access isn't set up: the DOC 2.0 API.
#     Rate-limits aggressively (see data/snapshots/gdelt/NOTE.md for
#     the full failure history) -- expect this to be slow/flaky.
# uv run python ingest/gdelt.py

# 3. Event extraction from GDELT articles via an LLM (needs a key
#    matching .env's LLM_PROVIDER, default groq). MVP-capped at 500
#    articles/corridor by default (EXTRACTOR_MAX_PER_CORRIDOR in
#    .env) -- Groq's free tier caps at 200,000 tokens/day, which the
#    default cap is sized to mostly fit inside.
uv run python agent/extractor.py

# 4. PPAC refinery capacity data (downloads the Ready Reckoner PDF
#    once, ~32MB, cached in data/raw/ which is gitignored).
uv run python ingest/ppac.py

# Then rebuild anything downstream:
uv run python ingest/validate_reference.py   # reference CSV consistency
uv run python core/risk.py                   # CRI, now with fresh data
uv run python core/twin.py                   # digital twin
uv run python core/scenario.py               # full cascade (calls procurement.py + reserve inputs)
```

## Self-checks

Every script has an offline, no-network `--self-check` that exercises
its non-trivial logic (date normalization, baseline math, dedup,
rate-limit handling, graph construction, LP correctness, ...):

```bash
for f in ingest/portwatch.py ingest/gdelt.py ingest/gdelt_bigquery.py ingest/ppac.py \
         agent/llm.py agent/extractor.py agent/provenance.py agent/tools.py agent/loop.py \
         api/main.py core/risk.py core/twin.py core/procurement.py core/scenario.py \
         core/reserve.py core/backtest.py; do
  uv run python "$f" --self-check
done
```

## Repo layout

```
data/
  reference/     hand-built CSVs (refineries, ports, sources, SPR, bypass
                 routes) -- every number cited inline, verified=True/False
                 flags which figures trace to a primary source (PPAC) vs
                 public-knowledge estimates
  snapshots/     committed, frozen data the rest of the build reads from
                 -- this is what makes phases 5+ and any demo work
                 offline/network-free
  raw/           gitignored scratch space for large downloads (PDFs,
                 duckdb files) that get parsed down to a snapshot
ingest/          one script per external data source
core/            risk.py (CRI), twin.py (digital twin), procurement.py
                 (allocation LP), scenario.py (cascade engine),
                 reserve.py (SPR drawdown LP) -- pure computation,
                 no LLM calls
agent/           llm.py (provider-switchable LLM client incl. native
                 function calling), extractor.py (article -> structured
                 event, with a hallucination guard enforced in code),
                 tools.py (the ONLY numeric path the LLM may use),
                 loop.py (bounded tool-calling loop), provenance.py
                 (every number must trace to a tool result),
                 prompts/analyst.md (versioned)
api/             main.py -- FastAPI; REST for the charts, SSE for the
                 agent. Reads snapshots only; no outbound calls except
                 the LLM provider on /api/ask
web/             Next.js 15 dashboard (deck.gl map, recharts, hand-rolled
                 Sankey). public/land-110m.geojson is the offline basemap
```

`PLAN.md` is the phase-by-phase build log with what's done, what's
partial, and why. `CLAUDE.md` has the standing engineering rules this
build follows (commit discipline, snapshot discipline, no-LLM-
arithmetic, etc.) — worth reading if you're extending this.

## Known limitations (read before demoing)

- **PortWatch AIS data has a 2–9 day publish lag** and PortWatch itself
  documents GPS jamming/AIS spoofing in the Hormuz conflict zone. Never
  described as "real-time" anywhere in this build — it isn't.
- **`E` (event severity) is thin.** Only 54 events were extracted
  (MVP-capped run, Groq's daily token quota), 14 of them for Hormuz
  specifically. `core/risk.py` reports `E` as genuinely missing (`NaN`,
  renormalized weights) rather than substituting zero when data is
  short, which is the correct behavior — but a fuller extraction run
  (`EXTRACTOR_MAX_PER_CORRIDOR=0` in `.env`, needs a paid/higher-tier
  LLM key or multiple days of free-tier quota) would sharpen `E`
  materially.
- **`ports.csv` and `sources.csv` have unverified rows by design.**
  PPAC's tables don't cover port draft/SPM specs or global crude assay
  values — those came from public industry knowledge, not a primary
  source, and are flagged `verified=False` accordingly. Run `uv run
  python ingest/validate_reference.py` to see the count and which file.
- **The digital twin has no Reserve or Product nodes.** That's
  deliberate scope discipline (see `core/twin.py`'s docstring) — Phase
  5's `core/reserve.py` and `core/scenario.py` cover that ground
  separately rather than duplicating it as twin nodes.
- **The procurement LP's cost is a distance proxy, not real pricing.**
  No FOB/freight/war-risk data is ingested (Tier 2, deferred), so the
  anti-concentration safeguard is verified correct via synthetic
  self-check but doesn't visibly bind on this build's real numbers — a
  pure-distance model can't reproduce Russia's actual cost-competitiveness,
  which comes from price discount, not proximity. `core/procurement.py`'s
  own demo output explains this rather than hiding it.
- **Scenario cascade demand/yield are simplifications.** Refinery
  "demand" is nameplate capacity (India's refineries run at high
  utilization, but this isn't the same as PPAC reporting an exact
  throughput figure), and product shortfall uses one national-average
  yield mix (PPAC Table 4.5) applied to every refinery rather than
  refinery-specific yields. CPI impact assumes 1:1 crude-to-retail
  pass-through, which ignores India's active fuel-excise-duty cushioning.
  All disclosed in each output's `confidence`/`method` field, not just
  here.
- **The backtest calibrates on one crisis and validates on a different
  one of a different character.** Bab el-Mandeb (Oct 2023–Feb 2024) was
  a rerouting event — ships avoided the strait, but AIS transit counts
  never collapsed the way Hormuz's did — so the fit window's CRI is
  O-only (no GDELT coverage that far back) and uses a much lower
  disruption threshold than the validation window. AUC is real and
  strong at h=7/14 but undefined at h=30 (the validation window becomes
  almost entirely positive-label once the closure is sustained), and the
  reliability curve shows the calibration transferred from Bab
  el-Mandeb's narrower CRI range is under-confident on Hormuz's wider
  one — a genuine cross-corridor transfer limitation, not smoothed over.
