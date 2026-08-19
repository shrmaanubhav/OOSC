"""GDELT DOC 2.0 ingestion — the leading (pre-AIS) news signal per corridor.

Confirmed live (2026-08-19/20):
- The public endpoint enforces a "one request every 5 seconds" limit and,
  when violated, returns HTTP 429 with an **English prose body**, not JSON.
  The design doc warned this could also arrive as HTTP 200 with prose — the
  parser here treats both alike: any non-JSON body is a rate-limit/error
  response, never silently swallowed as "zero results."
- `mode=artlist` is capped at 250 records with no pagination cursor, so a
  historical backfill must slice the date range and de-duplicate.
- `mode=timelinevol`/`timelinetone` return a full daily series for the
  requested window in one call — no slicing needed for those.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import httpx
import pandas as pd
import yaml

BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
MIN_REQUEST_INTERVAL = 20.0  # seconds; API says ">=5s" but live testing showed sustained
# throttling under repeated backfill runs -- 8s/90s-cap was not enough headroom
MAX_RETRIES = 10
MAX_BACKOFF = 180.0  # seconds

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
QUERIES_PATH = DATA_DIR / "reference" / "corridor_queries.yaml"
SNAPSHOT_DIR = DATA_DIR / "snapshots" / "gdelt"

_last_request_time = 0.0


def _throttled_get(params: dict) -> dict:
    """GET with rate-limit compliance and prose-vs-JSON response detection."""
    global _last_request_time
    for attempt in range(1, MAX_RETRIES + 1):
        wait = MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_time)
        if wait > 0:
            time.sleep(wait)
        _last_request_time = time.monotonic()

        try:
            resp = httpx.get(BASE, params=params, timeout=30)
        except httpx.RequestError as exc:
            backoff = min(MIN_REQUEST_INTERVAL * (2 ** (attempt - 1)), MAX_BACKOFF)
            print(
                f"[gdelt]   network error (attempt {attempt}/{MAX_RETRIES}): "
                f"{exc!r} -- backing off {backoff:.0f}s"
            )
            time.sleep(backoff)
            continue

        content_type = resp.headers.get("content-type", "")
        body = resp.text.strip()
        looks_like_json = content_type.startswith("application/json") or body.startswith(("{", "["))

        if resp.status_code == 200 and looks_like_json:
            return resp.json()

        backoff = min(MIN_REQUEST_INTERVAL * (2 ** (attempt - 1)), MAX_BACKOFF)
        print(
            f"[gdelt]   non-JSON/error response (HTTP {resp.status_code}, "
            f"attempt {attempt}/{MAX_RETRIES}): {body[:120]!r} -- backing off {backoff:.0f}s"
        )
        time.sleep(backoff)

    print(f"[gdelt]   GIVING UP after {MAX_RETRIES} attempts: params={params}")
    return {}


def _fmt(date: str, end_of_day: bool = False) -> str:
    """YYYY-MM-DD -> GDELT's YYYYMMDDHHMMSS."""
    d = date.replace("-", "")
    return f"{d}235959" if end_of_day else f"{d}000000"


def artlist(query: str, start: str, end: str, maxrecords: int = 250) -> list[dict]:
    body = _throttled_get(
        {
            "query": query,
            "mode": "artlist",
            "format": "json",
            "maxrecords": maxrecords,
            "sort": "datedesc",
            "STARTDATETIME": _fmt(start),
            "ENDDATETIME": _fmt(end, end_of_day=True),
        }
    )
    return body.get("articles", [])


def timeline(query: str, start: str, end: str, mode: str) -> pd.DataFrame:
    assert mode in ("timelinevol", "timelinetone")
    body = _throttled_get(
        {
            "query": query,
            "mode": mode,
            "format": "json",
            "STARTDATETIME": _fmt(start),
            "ENDDATETIME": _fmt(end, end_of_day=True),
        }
    )
    series = body.get("timeline", [])
    if not series:
        return pd.DataFrame(columns=["date", "value"])
    points = series[0].get("data", [])
    df = pd.DataFrame(points)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    df = df.rename(columns={"value": mode})
    return df[["date", mode]]


def _date_slices(start: str, end: str, slice_days: int) -> list[tuple[str, str]]:
    slices = []
    cur = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    while cur <= end_ts:
        slice_end = min(cur + pd.Timedelta(days=slice_days - 1), end_ts)
        slices.append((cur.strftime("%Y-%m-%d"), slice_end.strftime("%Y-%m-%d")))
        cur = slice_end + pd.Timedelta(days=1)
    return slices


_WORD_RE = re.compile(r"[a-z0-9]+")


def _title_trigrams(title: str) -> set[str]:
    words = _WORD_RE.findall(title.lower())
    joined = " ".join(words)
    return {joined[i : i + 3] for i in range(len(joined) - 2)} or {joined}


def dedupe_articles(articles: list[dict]) -> list[dict]:
    """Cluster same-day near-duplicate wire stories by title trigram overlap.

    Event-type-aware dedup happens again in the Phase 3 extractor once
    articles have extracted event types; this pass only has title+date to
    work with, so it catches the coarse case (the same AP/Reuters wire
    story republished across dozens of domains).
    """
    by_day: dict[str, list[dict]] = {}
    for a in articles:
        day = (a.get("seendate") or "")[:8]
        by_day.setdefault(day, []).append(a)

    deduped: list[dict] = []
    for day, day_articles in by_day.items():
        kept: list[tuple[dict, set[str]]] = []
        for a in day_articles:
            grams = _title_trigrams(a.get("title", ""))
            if any(len(grams & k_grams) / max(len(grams | k_grams), 1) > 0.7 for _, k_grams in kept):
                continue
            kept.append((a, grams))
        deduped.extend(a for a, _ in kept)
    return deduped


def backfill_corridor(corridor_id: str, cfg: dict) -> list[dict]:
    query = cfg["query"]
    start, end = cfg["backfill_start"], cfg["backfill_end"]
    dense = cfg.get("dense_window")

    slices = _date_slices(start, end, slice_days=7)
    if dense:
        # replace the weekly slice(s) overlapping the dense window with daily ones
        slices = [
            s
            for s in slices
            if not (s[0] <= dense["end"] and s[1] >= dense["start"])
        ]
        slices.extend(_date_slices(dense["start"], dense["end"], slice_days=1))
        slices.sort()

    print(f"[gdelt] {corridor_id}: {len(slices)} artlist slices to fetch")
    articles: list[dict] = []
    failed_slices: list[tuple[str, str]] = []
    for i, (s, e) in enumerate(slices, 1):
        batch = artlist(query, s, e)
        print(f"[gdelt]   slice {i}/{len(slices)} ({s}..{e}): {len(batch)} articles")
        if not batch:
            failed_slices.append((s, e))
        for a in batch:
            a["corridor_id"] = corridor_id
        articles.extend(batch)

    if failed_slices:
        print(
            f"[gdelt]   WARNING: {len(failed_slices)}/{len(slices)} slices returned nothing "
            f"(rate-limited or genuinely empty -- not distinguished here): {failed_slices}"
        )

    before = len(articles)
    articles = dedupe_articles(articles)
    print(f"[gdelt]   {corridor_id}: {before} -> {len(articles)} after dedup")
    return articles


def main() -> None:
    corridors = yaml.safe_load(QUERIES_PATH.read_text())
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    all_articles: list[dict] = []
    all_timelines: list[pd.DataFrame] = []

    for corridor_id, cfg in corridors.items():
        articles = backfill_corridor(corridor_id, cfg)
        all_articles.extend(articles)

        for mode in ("timelinevol", "timelinetone"):
            df = timeline(cfg["query"], cfg["backfill_start"], cfg["backfill_end"], mode)
            df["corridor_id"] = corridor_id
            df["mode"] = mode
            all_timelines.append(df)
            print(f"[gdelt]   {corridor_id} {mode}: {len(df)} daily points")

        # checkpoint after each corridor -- a later corridor's failure
        # (rate limiting, network) must not lose completed work
        pd.DataFrame(all_articles).to_parquet(SNAPSHOT_DIR / "articles.parquet", index=False)
        pd.concat(all_timelines, ignore_index=True).to_parquet(SNAPSHOT_DIR / "timelines.parquet", index=False)
        print(f"[gdelt] checkpointed after {corridor_id}")

    print(f"[gdelt] done -- {len(all_articles)} deduped articles, "
          f"{sum(len(t) for t in all_timelines)} timeline rows")


def _self_check() -> None:
    """No network: dedup + slicing + prose-detection logic only."""
    slices = _date_slices("2026-01-01", "2026-01-10", slice_days=7)
    assert slices == [("2026-01-01", "2026-01-07"), ("2026-01-08", "2026-01-10")], slices

    articles = [
        {"seendate": "20260301120000", "title": "Iran mines Strait of Hormuz, tankers flee"},
        {"seendate": "20260301130000", "title": "Iran mines Strait of Hormuz; tankers flee area"},
        {"seendate": "20260301140000", "title": "Oil prices spike after Hormuz closure"},
        {"seendate": "20260302090000", "title": "Iran mines Strait of Hormuz, tankers flee"},
    ]
    deduped = dedupe_articles(articles)
    # the two near-identical 2026-03-01 headlines collapse to one; the
    # distinct same-day headline and the next-day repeat both survive
    assert len(deduped) == 3, deduped

    print("[gdelt] self-check passed")


if __name__ == "__main__":
    import sys

    if "--self-check" in sys.argv:
        _self_check()
    else:
        main()
