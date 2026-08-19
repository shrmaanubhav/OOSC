# GDELT backfill — incomplete, blocked on rate limiting

**Status as of 2026-08-20: no data pulled yet.** `articles.parquet` and
`timelines.parquet` do not exist in this directory. This is a known gap,
not an oversight — resume with `uv run python ingest/gdelt.py` once the
rate-limit situation below has cooled off.

## What happened

`ingest/gdelt.py` backfills `data/reference/corridor_queries.yaml`'s two
corridors (Hormuz, Bab el-Mandeb) over Jan 2026 - Aug 2026, sliced into
~88 `artlist` requests (weekly, daily during the Feb-Mar 2026 onset) plus
4 `timelinevol`/`timelinetone` calls. Three attempts were made:

1. **First run**: `MIN_REQUEST_INTERVAL=5.5s`, `MAX_RETRIES=5`. Got 4
   slices in (55, 84, 62, 95 articles), then a slice exhausted all 5
   retries against sustained HTTP 429 ("Please limit requests to one
   every 5 seconds...") and crashed the whole process. Fixed: per-slice
   failures now degrade to an empty batch and log a warning instead of
   crashing; added per-corridor checkpointing so partial progress
   survives a later failure.
2. **Second run**: `MIN_REQUEST_INTERVAL=8.0s`, `MAX_RETRIES=8`,
   `MAX_BACKOFF=90s`. Got past slice 4 successfully, then died on a
   `httpx.ConnectTimeout` (TLS handshake) that wasn't caught by the
   retry loop at all — it only guarded against non-JSON/429 responses,
   not network-level errors. Fixed: `_throttled_get` now catches
   `httpx.RequestError` and retries those too.
3. **Third run**: restarted from a cold process. **Every single attempt
   on slice 1 got HTTP 429**, all 8 retries, even with 8-20s spacing.
   This means the throttling is not purely request-cadence-based --
   GDELT appears to be applying a longer, IP-level cooldown after the
   volume of requests from runs 1-2. Stopped rather than keep hammering
   it. Current code (`MIN_REQUEST_INTERVAL=20.0s`, `MAX_RETRIES=10`,
   `MAX_BACKOFF=180s`) has not been re-tried live yet.

## What this means for downstream phases

- **Phase 3 (CRI)**: the `S` (signal pressure) and `E` (event severity)
  components both depend on this data. Until it lands, CRI can only be
  computed from `O` (observed, PortWatch) and `X` (exposure) -- do not
  present a "full" CRI to the user until GDELT is backfilled. Say so
  explicitly if Phase 3 starts before this is resolved.
- Everything else in Phase 2 (the five `data/reference/*.csv` tables,
  `ingest/validate_reference.py`) is unaffected and complete.

## How to resume

Just re-run `uv run python -u ingest/gdelt.py`. It's idempotent and
checkpoints per corridor, so a partial prior run's `data/snapshots/gdelt/
*.parquet` (if any exist) gets overwritten with a fresh, more-complete
pull rather than merged -- that's fine at this data volume. Before
re-running, prefer waiting at least 30-60 minutes since the last attempt
given the IP-level cooldown observed above. If it fails on the very
first slice again immediately, stop again rather than retrying blindly --
the fix at that point is patience, not more code.
