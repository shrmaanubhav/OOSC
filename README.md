# Project Sentinel

AI-driven energy supply-chain resilience system for India. Backtested
against a real event: the Strait of Hormuz closure that began 28 Feb 2026
and was still ongoing as of this build (19-20 Aug 2026). Architecture
notes and formulas are in `PLAN.md`; this file covers running it and
what's currently working (Phases 0-8 complete).

## Quick start (judges, 2 minutes)

```bash
uv sync && cp .env.example .env
./run.sh          # or run.ps1 on Windows
```

Open http://localhost:3000. No API keys or internet connection required —
the dashboard reads from `data/snapshots/` (frozen 2026-08-20) and the
map's coastlines are a local file, not a tile server. The only exception
is the Analyst chat panel, which needs a live LLM key (see
`.env.example`). Everything else works offline. Data-quality caveats are
in `docs/methodology.md`, also linked from the dashboard header.

### Or: Docker

```bash
cp .env.example .env   # required even with every key left blank
docker compose up --build
```

Same two services as `run.sh` (API on `:8000`, dashboard on `:3000`),
each in its own multi-stage image (`Dockerfile` for the API,
`python:3.12-slim` + `uv`; `web/Dockerfile` for the dashboard, Next.js
`output: "standalone"`). `data/reference/` and `data/snapshots/` are
baked into the API image at build time, so no volume is needed for the
default demo path.

Two things to know:
- `NEXT_PUBLIC_API_BASE` is a build-time value, not runtime — Next.js
  inlines `NEXT_PUBLIC_*` vars into the client bundle at `next build`.
  It's set to `http://localhost:8000` in `docker-compose.yml` (the
  browser hits the API directly, not through the compose network).
  Rebuild the `web` image if you change it.
- Re-running ingestion inside the container (GDELT/PPAC/sanctions)
  needs a bind mount for `data/snapshots/` and, for
  `ingest/gdelt_bigquery.py`, a GCP service-account JSON mounted in with
  `GOOGLE_APPLICATION_CREDENTIALS` pointed at it — neither is set up by
  default since the judged demo path doesn't need them.

## What's built

Real AIS data from IMF PortWatch shows the Hormuz collapse. On top of
that sits a Corridor Risk Index (CRI) that combines AIS with GDELT news
volume/tone and LLM-extracted events; news turns out to lead AIS by
about a week, which lines up with the actual timeline. The dashboard's
Risk index chart shows this back to 2025-01-01, so the pre-war baseline
(CRI ~14) and the closure (CRI ~69) are both on screen at once, not just
the closure in isolation.

There's a digital twin (crude sources -> corridor -> Indian port ->
refinery) built from PPAC's refinery capacity data, plus a procurement
LP that allocates crude to refineries with an anti-concentration
safeguard, a scenario cascade that turns a corridor shock into
run-cuts / product shortfalls / price impact / India-macro numbers
(import bill, %GDP, CPI), and a reserve drawdown LP for days-of-cover.
The flow map's arcs and the procurement solve they're drawn from switch
regime at the scrubbed date too — dragging across 28 Feb 2026 shows
crude actually leaving Hormuz for Bab el-Mandeb/Suez/Malacca/Cape,
instead of one solve pinned to every date.

`core/backtest.py` calibrates the CRI against a different crisis (Red
Sea/Bab el-Mandeb, Oct 2023-Feb 2024) and validates out-of-sample
against Hormuz. `agent/provenance.py` catches any number an agent
response can't trace back to a tool result. `agent/loop.py` is the
agent itself, and `web/` is the dashboard that runs all of this
offline.

The dashboard itself is five scrubbable/interactive panels (Flow map,
Risk index, Reallocation, Impact cascade, Strategic reserve) behind a
left-hand tab rail, with the Analyst chat docked on the right at all
times. Backtest results and bypass-route data are reference material,
not something you scrub — they're one click away from the footer
instead of taking up a permanent tab. That same footer also explains
whatever jargon (CRI, λ, kbd, SPR...) is relevant to whichever tab is
currently open, keyed off the same glossary the in-panel tooltips use.

Phase 9 (demo rehearsal + polish) isn't done yet.

## For judges — quick answers

Four questions this build gets asked a lot, with exactly where to verify
each answer.

**Where's the data actually from?**

| Source | What it provides | Live/real? |
|---|---|---|
| [IMF PortWatch](https://portwatch.imf.org/) | Daily AIS ship-tracking per chokepoint/port, 2019-2026 | Real public API, no key. 2-9 day publish lag, documents AIS spoofing/GPS jamming in the conflict zone — not real-time, disclosed everywhere it's used |
| [GDELT](https://www.gdeltproject.org/) (via BigQuery) | News coverage volume + tone per corridor | Real, live-queryable. Backfilled for the windows this build needs (see `data/reference/corridor_queries.yaml`) |
| PPAC Ready Reckoner | Refinery capacity, crude throughput, Indian Basket price | Real Government of India PDF (`ingest/ppac.py`), parsed once and snapshotted |
| OFAC SDN list via OpenSanctions | Sanctioned-vessel counts (439 Russia-program, 60 Venezuela-program, pulled 2026-08-20) | Real, live pull (`ingest/sanctions.py`) |
| `data/reference/*.csv` (chokepoint capacities, SPR, bypass routes) | Reference figures the models run on | Hand-cited — every number has an inline source comment and a `verified=True/False` flag; run `uv run python ingest/validate_reference.py` to see the count |

Everything is frozen to `data/snapshots/` before the demo runs — the
dashboard makes **zero network calls** except the Analyst chat panel.
Full caveats are in `docs/methodology.md` and the dashboard's own
"methodology & limitations" toggle.

**What have we backtested, and what did we find?**

Fit a disruption-probability calibration on one real crisis (Bab
el-Mandeb/Red Sea, Oct 2023-Feb 2024), then validated it **out-of-sample**
on a different real crisis (Hormuz, Feb-Aug 2026) — data the fit step
never saw. Result: **AUC 0.979 at 7 days, 0.919 at 14 days** (undefined
at 30 days — once the closure is sustained, almost every validation day
is a "disruption" day, so there's no negative class left to separate
against; that's a property of the data, not a broken score). Every
asymmetry between the two windows (the fit window has a thinner CRI —
no LLM-extracted events, no exposure figure) is disclosed rather than
smoothed over. Run `uv run python core/backtest.py`, or click "ⓘ
backtest results" in the dashboard footer.

**Is there a trained model?**

Yes, one — and it's deliberately small and fully inspectable, not a
black box. `core/backtest.py` fits a **2-parameter logistic regression**
(`P(disruption) = sigmoid(b0 + b1·CRI/100)`, hand-rolled Newton-Raphson,
no sklearn/PyTorch) mapping CRI to disruption probability. The question
it answers is "does CRI itself carry real predictive signal", not
"can we fit something fancy" — the backtest above is the evidence.
Everything else in `core/` (the CRI composite, the procurement LP, the
cascade, the reserve drawdown) is deterministic computation — a
weighted formula or a linear program, not a trained model.

**How does the AI chat panel answer, and how do we stop it hallucinating?**

`agent/loop.py` is a bounded tool-calling loop (max 6 steps): the LLM
can only pull numbers by calling real functions in `agent/tools.py`
(CRI lookup, scenario solve, procurement solve, reserve solve, backtest
results, sanctions evidence, bypass routes...) — it never computes or
invents a figure itself (CLAUDE.md rule 4, enforced in code, not just
prompted). Every response is then run through `agent/provenance.py`,
which checks that every number in the answer text traces back to an
actual tool result before it reaches the user; a violation is shown,
not hidden, via the dashboard's provenance badge. The LLM provider is
swappable (`agent/llm.py` — Groq default, OpenAI, Gemini) and only this
one panel touches the network.

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
offline — the backend reads only from `data/snapshots/`, and the map's
coastlines are a local GeoJSON rather than a tile server.

Three controls to try in a demo:

- **The Flow map's date scrubber**, dragged across 28 Feb 2026 — arcs
  swing from Hormuz to Bab el-Mandeb/Suez/Malacca/Cape mid-drag, with a
  per-corridor kbd readout under the map quantifying the shift. This is
  two solves (pre/post-closure), not an animation — the underlying LP
  is a cliff, not a ramp, so nothing in between is invented.
- **λ (risk aversion)** in the procurement panel re-solves the LP
  server-side on every drag and shifts allocation away from high-CRI
  corridors.
- **Hormuz severity** + **"+ Bab el-Mandeb closed"** in the impact panel
  re-runs the full cascade — this is where the bypass-coupling point
  lands: the Saudi East-West pipeline stops being an escape route once
  its discharge corridor is also shut.

## Prerequisites

- Python 3.12+ and [uv](https://docs.astral.sh/uv/)
- Node 22+ and npm (only for the frontend, not required for anything
  below the "Run the dashboard" section)
- A free [Groq](https://console.groq.com/keys) API key (or OpenAI/Gemini
  — see `.env.example`) to re-run event extraction
- A Google Cloud project with the BigQuery API enabled, to re-run the
  GDELT backfill (see `.env.example`) — not needed to explore the data
  already committed

## Setup

```bash
uv sync
cp .env.example .env
```

Fill in `.env` with whichever keys you have — nothing below requires a
key against the data already in `data/snapshots/`. Keys only matter for
re-running ingestion from scratch.

## Quick start — see the CRI in under a minute

Everything below reads from `data/snapshots/`, already committed. No
network calls, no keys needed.

```bash
uv run python core/risk.py
```

Prints the last 30 days of `CRI(chokepoint6)` (Strait of Hormuz) with
its four components (`O` observed/AIS, `S` news signal, `E` extracted
event severity, `X` exposure) and which had data on each day. For the
headline result — news leading AIS by about a week around the actual
closure — check the Feb-Mar 2026 window:

```bash
uv run python -c "
from core.risk import compute_cri
import pandas as pd
df = compute_cri('chokepoint6')
with pd.option_context('display.max_rows', 40, 'display.width', 140):
    print(df.loc['2026-02-20':'2026-03-15'])
"
```

`S` spikes to ~0.7-0.97 on 28 Feb-1 Mar while `O` is still 0 — AIS data
(2-9 day lag by nature) doesn't confirm the collapse until `O` starts
climbing on 2-4 Mar.

## Explore the digital twin

```bash
uv run python core/twin.py
```

Builds the twin from `data/reference/*.csv` + `data/snapshots/portwatch/`
(no network — `searoute`'s routing data ships with the package) and
prints a sample path: crude grade → corridor → Indian discharge port →
refinery, with real maritime distances.

## Run a scenario

```bash
uv run python core/scenario.py
```

Runs `run_scenario('chokepoint6', 1.0, 90)` — a full Hormuz closure for
90 days — through the cascade: the procurement LP's reroute attempt,
refinery run-cuts, product shortfall (PPAC's yield mix), a price impact
calibrated on the actual Feb-Mar 2026 $65→$113.57/bbl move, and
India-macro impact. Also runs a sanctions-compliance variant (blocks
Russia/Venezuela substitution) that actually triggers a refinery
shortfall — the base scenario finds enough non-Hormuz capacity to fully
reroute, matching what MoPNG reported.

```bash
uv run python core/procurement.py   # just the allocation LP, incl. the λ/μ mechanics
uv run python core/reserve.py       # SPR drawdown schedule under a supply gap
```

## Backtest and provenance

```bash
uv run python core/backtest.py
```

Fits a logistic CRI-to-disruption-probability calibration on the Red
Sea/Bab el-Mandeb crisis (Oct 2023-Feb 2024) and validates it
out-of-sample on the Hormuz closure (Feb-Aug 2026), reporting AUC and a
reliability curve for h=7/14/30 days (AUC 0.979 at h=7, 0.919 at h=14,
undefined at h=30 once the closure makes almost every validation day a
positive). Caveats: the fit window's CRI has O and S (GDELT was
backfilled for Oct 2023-Feb 2024) but not E or X, while validation has
all four; each corridor uses its own noise-floor-calibrated disruption
threshold.

```bash
uv run python agent/provenance.py
```

Runs the provenance validator against a grounded response (zero
violations) and an adversarial one with a fabricated figure (a named
violation) — the agent loop runs every response through this before it
reaches the user, and the dashboard's provenance badge shows the
verdict.

## Ask the agent

```bash
uv run python agent/loop.py "what happens if Bab el-Mandeb closes too?"
```

Needs a live LLM key (`.env`, default provider `groq`; `LLM_PROVIDER=gemini`
and `openai` also work). The loop calls tools from `agent/tools.py` — the
only numeric path it's allowed to use — and prints how many of the
numbers in its answer traced back to an actual tool result.

Groq's free tier caps at 200,000 tokens/day, separate from its
per-minute limit. When that's exhausted the loop degrades gracefully
rather than crashing; switch to `LLM_PROVIDER=gemini` to keep going.

## Re-running ingestion (optional)

Each script is independently runnable and idempotent. Run in this order
if starting from nothing (later ones depend on earlier snapshot output):

```bash
# 1. IMF PortWatch — AIS chokepoint + Indian port data. No key needed.
uv run python ingest/portwatch.py

# 2. GDELT news signal, via BigQuery (primary path — needs
#    GOOGLE_APPLICATION_CREDENTIALS + GCP_PROJECT_ID in .env).
#    Does a dry-run cost check before every real query and refuses to
#    run past 200GB without --force -- verified live cost is ~78GB for
#    the primary Jan-Aug 2026 window (both corridors) plus ~33GB for
#    chokepoint4's additional backtest_fit_window (Oct 2023-Feb 2024,
#    see data/reference/corridor_queries.yaml), well under the 1TB/month
#    free tier.
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

Every script has an offline, no-network `--self-check` covering its
non-trivial logic (date normalization, baseline math, dedup, rate-limit
handling, graph construction, LP correctness, ...):

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
Dockerfile, docker-compose.yml, web/Dockerfile
                 optional containerized path (`docker compose up
                 --build`) -- alternative to run.sh/run.ps1, not a
                 replacement; see "Or: Docker" above
```

`PLAN.md` is the phase-by-phase build log: what's done, what's partial,
and why. `CLAUDE.md` has the engineering rules the build follows
(commit discipline, snapshot discipline, no-LLM-arithmetic, etc.) if
you're extending this.

## Known limitations 

- PortWatch AIS data has a 2-9 day publish lag, and PortWatch itself
  documents GPS jamming/AIS spoofing in the Hormuz conflict zone. Not
  described as "real-time" anywhere in this build.
- `E` (event severity) is thin — only 54 events extracted (MVP-capped
  run, Groq's daily token quota), 14 of them for Hormuz specifically.
  `core/risk.py` reports `E` as missing (`NaN`, renormalized weights)
  rather than substituting zero, which is the right call but a fuller
  extraction run (`EXTRACTOR_MAX_PER_CORRIDOR=0` in `.env`, needs a
  paid/higher-tier LLM key or several days of free-tier quota) would
  sharpen it.
- `ports.csv` and `sources.csv` have unverified rows by design. PPAC's
  tables don't cover port draft/SPM specs or global crude assay values
  — those came from public industry knowledge rather than a primary
  source, and are flagged `verified=False`. Run
  `uv run python ingest/validate_reference.py` for the count and file.
- The digital twin has no Reserve or Product nodes — deliberate scope
  discipline (see `core/twin.py`'s docstring); `core/reserve.py` and
  `core/scenario.py` cover that ground separately.
- The procurement LP's cost is a distance proxy, not real pricing. No
  FOB/freight/war-risk data is ingested (deferred), so the
  anti-concentration safeguard is verified via synthetic self-check but
  doesn't visibly bind on this build's real numbers — a pure-distance
  model can't reproduce Russia's actual cost-competitiveness, which
  comes from price discount rather than proximity.
  `core/procurement.py`'s own demo output explains this.
- Scenario cascade demand/yield are simplifications. Refinery "demand"
  is nameplate capacity (India's refineries run at high utilization, but
  that's not the same as an exact PPAC throughput figure), and product
  shortfall uses one national-average yield mix (PPAC Table 4.5) applied
  to every refinery rather than refinery-specific yields. CPI impact
  assumes 1:1 crude-to-retail pass-through, ignoring India's fuel-excise
  cushioning. All disclosed in each output's `confidence`/`method`
  field, not just here.
- The backtest calibrates on one crisis and validates on a different one
  of a different character. Bab el-Mandeb (Oct 2023-Feb 2024) was a
  rerouting event — ships avoided the strait, but AIS transit counts
  never collapsed the way Hormuz's did — so the fit window's CRI has O
  and S (GDELT was backfilled for Oct 2023-Feb 2024) but not E
  (extraction never ran against it) or X, and uses a lower disruption
  threshold than the validation window. AUC is strong at h=7/14 but
  undefined at h=30 (the validation window becomes almost entirely
  positive-label once the closure is sustained), and the reliability
  curve shows the calibration transferred from Bab el-Mandeb's narrower
  CRI range under-confident on Hormuz's wider one — a real cross-corridor
  transfer limitation.
