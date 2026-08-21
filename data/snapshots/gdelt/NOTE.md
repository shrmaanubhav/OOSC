# GDELT backfill — resolved via BigQuery (2026-08-20, extended 2026-08-20)

**Status: complete.** `gkg_articles.parquet` (11,046 rows, deduped) and
`timelines.parquet` (910 daily points) exist in this directory, pulled
via `ingest/gdelt_bigquery.py` against the public `gdelt-bq.gdeltv2.
gkg_partitioned` dataset.

**Update:** chokepoint4 now also carries an additional, non-overlapping
backfill window, Oct 2023–Feb 2024 (the real Houthi/Red Sea crisis) --
this is `core/backtest.py`'s `FIT_WINDOW`, which was previously O-only
because the primary backfill never reached back that far. It's a second,
separate query (`backtest_fit_window` in `data/reference/
corridor_queries.yaml`), fetched and merged alongside the primary
2026 window, not a replacement for it -- 2,901 additional GKG rows,
~32.67GB scanned (dry-run confirmed before running). The fit window's
CRI now carries O and S for ~105 of its 152 days (S needs 90 days of
trailing history plus `min_periods=7`, so the earliest days are still
O-only); `E` remains unavailable there since the LLM extractor was never
run against these older articles. Measured effect: the live P(disruption
within 7d) for Hormuz's current CRI moved from 37.5% to 41.0% -- the
transferred calibration is less under-confident with S available in the
fit window, though the out-of-sample AUC on Hormuz barely moved (0.979 at
h=7), since AUC depends on the validation set, not the fit set.

## Why the switch from ingest/gdelt.py (DOC 2.0 API)

Three attempts to backfill via GDELT's DOC 2.0 API (`ingest/gdelt.py`)
all failed on sustained rate limiting well beyond the documented "5s
between requests" -- see git history on this file for the full failure
log (three separate bugs found and fixed along the way: crash-on-
exhausted-retries, an uncaught TLS ConnectTimeout, and finally an
IP-level cooldown that persisted across process restarts). `ingest/
gdelt.py` still works and is kept as a fallback if BigQuery access isn't
available, but it is no longer the primary path.

## How the BigQuery pull works

`gdelt-bq.gdeltv2.gkg` (the bare table) is **not partitioned** -- a
`WHERE DATE BETWEEN ...` filter on it still scans the entire multi-year
history. Verified live: a single corridor query against it estimated
~1TB scanned, most of the monthly free tier in one query.
`gdelt-bq.gdeltv2.gkg_partitioned` is day-partitioned on `_PARTITIONTIME`
(ingestion time); filtering on that column instead prunes the same query
to ~39GB. Both corridors together: ~78GB scanned, comfortably inside the
1TB/month free tier and the client's own 200GB per-query safety check
(`ingest/gdelt_bigquery.py`'s `dry_run_bytes`, which refuses to run
without `--force` past that limit). **This is cloud-side query cost for
Google's billing, not data downloaded locally** -- the actual result
files here total under 500KB.

One real data-quality catch made during setup: the initial chokepoint4
keyword list included bare "Red Sea", which matched 113,856 of 113,864
rows (99.99%) -- GDELT geocodes any article mentioning the region at
all, not just corridor-relevant ones. Dropped it; "Bab el-Mandeb"/"Bab
al-Mandab" alone gives a clean 7,417 rows.

## Known limitation: GKG rows have no article title

Unlike the DOC-API's `artlist` (which returns a real headline), GKG rows
carry only a URL, geocoded locations, and a tone score -- no title.
`agent/extractor.py`'s `_title_from_url` derives a readable title from
the URL slug (e.g. `.../iran-tells-houthis-to-close-red-sea-gateway/` ->
"iran tells houthis to close red sea gateway") since asking the model to
quote a raw hyphenated slug verbatim produced near-zero extracted events
in testing.

## What this means for downstream phases

- **Phase 3 (CRI)**: `S` (signal pressure) can now be computed from
  `timelines.parquet` -- re-run `core/risk.py`. `E` (event severity)
  still depends on `agent/extractor.py` actually running against
  `gkg_articles.parquet`, which needs an LLM key (see `.env.example`).
