# Project Sentinel

AI-driven energy supply-chain resilience system for India — built and
backtested against a real event, not a hypothetical: the Strait of Hormuz
closure that began 28 Feb 2026 and was still ongoing as of this build
(19–20 Aug 2026). Full background, architecture rationale, and formulas
live in `PLAN.md` (phase index) and the design doc referenced there;
this file is about running and understanding what exists **right now**
(Phases 0–4 complete).

## What's built so far

1. **Real AIS data** (IMF PortWatch) showing the Hormuz collapse.
2. **A Corridor Risk Index (CRI)** combining that AIS signal with news
   volume/tone (GDELT) and LLM-extracted discrete events, with a
   verified "news leads AIS by about a week" result.
3. **A digital twin** (crude sources → corridor → Indian port →
   refinery) built from PPAC's authoritative refinery capacity data.

Phases 5–9 (scenario cascade, procurement optimizer, backtest,
agent/chat layer, frontend) are not built yet.

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
its four components (`O` observed/AIS, `S` news signal, `E` event
severity, `E` extracted events, `X` exposure) and which ones had data
on each day. To see the headline result — news leading AIS by about a
week around the actual closure — inspect the Feb–Mar 2026 window:

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
```

## Self-checks

Every script has an offline, no-network `--self-check` that exercises
its non-trivial logic (date normalization, baseline math, dedup,
rate-limit handling, graph construction, ...):

```bash
for f in ingest/portwatch.py ingest/gdelt.py ingest/gdelt_bigquery.py \
         ingest/ppac.py agent/llm.py agent/extractor.py core/risk.py core/twin.py; do
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
core/            risk.py (CRI), twin.py (digital twin) -- pure computation,
                 no LLM calls
agent/           llm.py (provider-switchable LLM client), extractor.py
                 (article -> structured event, with a hallucination
                 guard enforced in code)
web/             Next.js 15 scaffold, untouched until Phase 8
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
  deliberate scope discipline (see `core/twin.py`'s docstring) — those
  belong to Phase 5's `core/reserve.py` and `core/scenario.py`.
