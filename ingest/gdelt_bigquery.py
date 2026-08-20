"""GDELT via the public BigQuery dataset (gdelt-bq.gdeltv2.gkg) -- replaces
the rate-limited DOC 2.0 API from ingest/gdelt.py for the historical
backfill. One SQL query gets the whole Jan-Aug 2026 window instead of ~88
sequential rate-limited HTTP calls.

GKG (Global Knowledge Graph) rows are per-article, one row per 15-minute
update batch, with geocoded locations, themes, and a tone score -- no raw
article text, so corridor relevance is matched against V2Locations
(GDELT's geocoded place names), not full text.

Needs GOOGLE_APPLICATION_CREDENTIALS (service account JSON path) and
GCP_PROJECT_ID in .env. Every real query does a dry run first and prints
the bytes that would be scanned -- gdeltv2.gkg is NOT partitioned, so a
DATE-range WHERE clause does not prune the scan the way it would on a
partitioned table. Free tier is 1TB/month; this script refuses to run
a query estimated over BYTES_SAFETY_LIMIT without --force.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

load_dotenv()

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
QUERIES_PATH = DATA_DIR / "reference" / "corridor_queries.yaml"
SNAPSHOT_DIR = DATA_DIR / "snapshots" / "gdelt"

BYTES_SAFETY_LIMIT = 200 * 1024**3  # 200 GB -- ~1/5 of the free monthly tier, per query

CORRIDOR_KEYWORDS = {
    "chokepoint6": ["Strait of Hormuz", "Hormuz"],
    # "Red Sea" deliberately excluded: verified live it matches 113,856 of
    # 113,864 rows for a Jan-Aug 2026 pull (99.99%) -- GDELT geocodes any
    # article mentioning the region at all (tourism, unrelated Egypt/Saudi
    # news, ...), not just corridor-relevant ones. The named strait alone
    # gives a clean 7,417 rows with no such flood.
    "chokepoint4": ["Bab el-Mandeb", "Bab al-Mandab"],
}


def _client():
    from google.cloud import bigquery

    project = os.environ.get("GCP_PROJECT_ID")
    if not project:
        raise RuntimeError("GCP_PROJECT_ID not set in .env")
    if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS not set in .env")
    return bigquery.Client(project=project)


def _build_query(keywords: list[str], start: str, end: str) -> str:
    """Queries gkg_partitioned, not the bare gkg table -- gkg is NOT
    partitioned, so a WHERE on its DATE column scans the entire multi-year
    history regardless (verified live: ~1TB for one corridor, over the
    whole monthly free tier). gkg_partitioned is day-partitioned on
    _PARTITIONTIME (ingestion time, not the DATE column), which prunes
    the same query down to ~39GB -- filter on _PARTITIONTIME, and keep
    the DATE filter too since ingestion time isn't exactly the article date.
    """
    pattern = "|".join(k.replace(" ", r"\s+") for k in keywords)
    start_int = int(start.replace("-", "") + "000000")
    end_int = int(end.replace("-", "") + "235959")
    return f"""
        SELECT
          DATE AS date,
          DocumentIdentifier AS url,
          V2Tone AS tone_raw,
          V2Locations AS locations
        FROM `gdelt-bq.gdeltv2.gkg_partitioned`
        WHERE _PARTITIONTIME BETWEEN TIMESTAMP('{start}') AND TIMESTAMP('{end}')
          AND DATE BETWEEN {start_int} AND {end_int}
          AND REGEXP_CONTAINS(V2Locations, r'(?i)({pattern})')
    """


def dry_run_bytes(query: str) -> int:
    from google.cloud import bigquery

    client = _client()
    job = client.query(query, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False))
    return job.total_bytes_processed


def fetch_corridor(corridor_id: str, start: str, end: str, force: bool = False) -> pd.DataFrame:
    keywords = CORRIDOR_KEYWORDS[corridor_id]
    query = _build_query(keywords, start, end)

    est_bytes = dry_run_bytes(query)
    est_gb = est_bytes / 1024**3
    print(f"[gdelt_bq] {corridor_id}: dry run estimates {est_gb:.2f} GB scanned")
    if est_bytes > BYTES_SAFETY_LIMIT and not force:
        raise RuntimeError(
            f"{corridor_id} query would scan {est_gb:.1f} GB, over the "
            f"{BYTES_SAFETY_LIMIT / 1024**3:.0f} GB safety limit. Re-run with force=True "
            "if this is intentional (e.g. you've confirmed budget with your GCP project)."
        )

    client = _client()
    df = client.query(query).to_dataframe()
    df["corridor_id"] = corridor_id

    # V2Tone is "tone,positive,negative,polarity,activityrefdensity,groupslang,wordcount"
    tone_split = df["tone_raw"].str.split(",", expand=True)
    df["tone"] = pd.to_numeric(tone_split[0], errors="coerce")
    df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d%H%M%S")
    return df[["date", "url", "tone", "corridor_id"]]


def to_daily_timeline(df: pd.DataFrame, corridor_id: str) -> pd.DataFrame:
    """Collapse per-article GKG rows into the same daily timelinevol/
    timelinetone shape ingest/gdelt.py produces, so core/risk.py's
    compute_S doesn't care which ingestion path populated it."""
    daily = df.groupby(df["date"].dt.date).agg(
        timelinevol=("url", "count"), timelinetone=("tone", "mean")
    )
    vol = daily[["timelinevol"]].reset_index().rename(columns={"date": "date"})
    vol["corridor_id"] = corridor_id
    vol["mode"] = "timelinevol"
    vol = vol.rename(columns={"timelinevol": "timelinevol"})

    tone = daily[["timelinetone"]].reset_index().rename(columns={"date": "date"})
    tone["corridor_id"] = corridor_id
    tone["mode"] = "timelinetone"

    return vol, tone


def main() -> None:
    import yaml

    force = "--force" in sys.argv
    corridors = yaml.safe_load(QUERIES_PATH.read_text())
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    all_articles = []
    all_vol = []
    all_tone = []

    for corridor_id, cfg in corridors.items():
        df = fetch_corridor(corridor_id, cfg["backfill_start"], cfg["backfill_end"], force=force)
        print(f"[gdelt_bq] {corridor_id}: {len(df)} GKG rows")
        all_articles.append(df)
        vol, tone = to_daily_timeline(df, corridor_id)
        all_vol.append(vol)
        all_tone.append(tone)

    articles_df = pd.concat(all_articles, ignore_index=True) if all_articles else pd.DataFrame()
    articles_df.to_parquet(SNAPSHOT_DIR / "gkg_articles.parquet", index=False)
    print(f"[gdelt_bq] wrote {len(articles_df)} rows -> {SNAPSHOT_DIR / 'gkg_articles.parquet'}")

    vol_df = pd.concat(all_vol, ignore_index=True) if all_vol else pd.DataFrame()
    tone_df = pd.concat(all_tone, ignore_index=True) if all_tone else pd.DataFrame()
    vol_df = vol_df.rename(columns={"timelinevol": "timelinevol"})
    tone_df = tone_df.rename(columns={"timelinetone": "timelinetone"})
    timelines_df = pd.concat(
        [
            vol_df.rename(columns={"timelinevol": "value"}).assign(mode="timelinevol"),
            tone_df.rename(columns={"timelinetone": "value"}).assign(mode="timelinetone"),
        ],
        ignore_index=True,
    )
    # match ingest/gdelt.py's timelines.parquet shape: one value column named
    # after the mode, not a generic "value" column -- core/risk.py reads timelinevol/timelinetone
    timelines_df = pd.concat([vol_df.assign(**{}), tone_df], ignore_index=True)
    timelines_df.to_parquet(SNAPSHOT_DIR / "timelines.parquet", index=False)
    print(f"[gdelt_bq] wrote {len(timelines_df)} timeline rows -> {SNAPSHOT_DIR / 'timelines.parquet'}")


def _self_check() -> None:
    """No network, no credentials: query construction and daily-aggregation
    logic only."""
    q = _build_query(["Strait of Hormuz", "Hormuz"], "2026-01-01", "2026-01-07")
    assert "20260101000000" in q
    assert "20260107235959" in q
    assert "Strait\\s+of\\s+Hormuz" in q

    df = pd.DataFrame(
        {
            "date": pd.to_datetime(
                ["2026-03-01 01:00", "2026-03-01 14:00", "2026-03-02 09:00"]
            ),
            "url": ["a", "b", "c"],
            "tone": [-5.0, -3.0, -1.0],
            "corridor_id": ["chokepoint6"] * 3,
        }
    )
    vol, tone = to_daily_timeline(df, "chokepoint6")
    assert vol.set_index("date")["timelinevol"].to_dict() == {
        pd.Timestamp("2026-03-01").date(): 2,
        pd.Timestamp("2026-03-02").date(): 1,
    }
    assert abs(tone.set_index("date")["timelinetone"][pd.Timestamp("2026-03-01").date()] - (-4.0)) < 1e-9

    print("[gdelt_bq] self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        main()
