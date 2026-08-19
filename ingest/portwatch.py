"""IMF PortWatch ingestion — chokepoint + Indian port daily AIS-derived activity.

Endpoint names below were confirmed live on 2026-08-19 by listing
https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services?f=json
and probing schemas. They differ from the design doc's guessed names in one
place: the daily port dataset is `Daily_Ports_Data`, not `Daily_Trade_Data`.

Known data-quality caveats (surface these, don't hide them):
- PortWatch itself documents AIS spoofing / GPS jamming / transponder
  "going dark" in conflict zones (Hormuz, Red Sea, sanctioned actors).
- Publish lag is ~2-9 days depending on the weekly Tuesday refresh cycle.
- This is daily-resolution, weekly-refreshed data. Never call it real-time.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import duckdb
import httpx
import pandas as pd

BASE = "https://services9.arcgis.com/weJ1QsnbMYJlCHdG/arcgis/rest/services"
CHOKEPOINTS_CATALOG = f"{BASE}/PortWatch_chokepoints_database/FeatureServer/0/query"
PORTS_CATALOG = f"{BASE}/PortWatch_ports_database/FeatureServer/0/query"
CHOKEPOINTS_DAILY = f"{BASE}/Daily_Chokepoints_Data/FeatureServer/0/query"
PORTS_DAILY = f"{BASE}/Daily_Ports_Data/FeatureServer/0/query"

PAGE_SIZE = 1000  # server-enforced max (maxRecordCount)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_DB = DATA_DIR / "raw" / "portwatch.duckdb"
SNAPSHOT_DIR = DATA_DIR / "snapshots" / "portwatch"

BASELINE_START = "2024-01-01"
BASELINE_END = "2026-02-27"  # day before the Hormuz closure began — fixed, never trailing


def _get_with_retries(client: httpx.Client, url: str, params: dict, retries: int = 3):
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = client.get(url, params=params)
            resp.raise_for_status()
            return resp
        except (httpx.TimeoutException, httpx.HTTPStatusError) as exc:
            last_exc = exc
            print(f"[portwatch]   request failed (attempt {attempt + 1}/{retries}): {exc}")
    raise RuntimeError(f"giving up on {url} after {retries} attempts") from last_exc


def _paginated_query(
    url: str,
    where: str,
    out_fields: str = "*",
    return_geometry: bool = False,
    client: httpx.Client | None = None,
    progress_label: str | None = None,
) -> list[dict]:
    """Page through an ArcGIS FeatureServer query, 1000 rows at a time."""
    features: list[dict] = []
    offset = 0
    owns_client = client is None
    client = client or httpx.Client(timeout=60)
    try:
        while True:
            resp = _get_with_retries(
                client,
                url,
                {
                    "where": where,
                    "outFields": out_fields,
                    "outSR": 4326,
                    "f": "json",
                    "resultOffset": offset,
                    "resultRecordCount": PAGE_SIZE,
                    "returnGeometry": str(return_geometry).lower(),
                },
            )
            body = resp.json()
            if "error" in body:
                raise RuntimeError(f"ArcGIS error querying {url}: {body['error']}")
            batch = [f["attributes"] for f in body.get("features", [])]
            features.extend(batch)
            if progress_label:
                print(f"[portwatch]   {progress_label}: {len(features)} rows so far...")
            if len(batch) < PAGE_SIZE:
                break
            offset += PAGE_SIZE
    finally:
        if owns_client:
            client.close()
    return features


def normalize_dates(df: pd.DataFrame) -> pd.DataFrame:
    """Derive a clean `date` column, validated against year/month/day.

    The design doc warns PortWatch dates can arrive as offset epoch-ms
    integers. Live testing (2026-08-19) showed clean ISO date strings for
    this account's `date` field (esriFieldTypeDateOnly), but this stays
    defensive since ArcGIS date serialization is a per-deployment setting.
    """
    df = df.copy()
    if pd.api.types.is_numeric_dtype(df["date"]):
        parsed = pd.to_datetime(df["date"], unit="ms", utc=True).dt.date
    else:
        parsed = pd.to_datetime(df["date"]).dt.date
    authoritative = pd.to_datetime(
        dict(year=df["year"], month=df["month"], day=df["day"])
    ).dt.date
    mismatches = (parsed != authoritative).sum()
    if mismatches:
        print(
            f"[portwatch] {mismatches}/{len(df)} rows: parsed `date` disagreed with "
            "year/month/day — using year/month/day as authoritative."
        )
    df["date"] = authoritative
    return df


def fetch_chokepoints_catalog() -> pd.DataFrame:
    rows = _paginated_query(CHOKEPOINTS_CATALOG, "1=1", return_geometry=True)
    df = pd.DataFrame(rows)
    assert len(df) == 28, f"expected 28 chokepoints, got {len(df)}"
    return df


def fetch_indian_ports_catalog() -> pd.DataFrame:
    rows = _paginated_query(PORTS_CATALOG, "country = 'India'")
    return pd.DataFrame(rows)


def fetch_chokepoints_daily() -> pd.DataFrame:
    rows = _paginated_query(CHOKEPOINTS_DAILY, "1=1", progress_label="chokepoints_daily")
    df = pd.DataFrame(rows)
    return normalize_dates(df)


def fetch_indian_ports_daily(portids: list[str]) -> pd.DataFrame:
    """One paginated query per port — a single IN(...) over 37 ports timed
    out server-side (30-60s) against the full 2065-port daily table."""
    rows: list[dict] = []
    with httpx.Client(timeout=60) as client:
        for i, portid in enumerate(portids, 1):
            print(f"[portwatch]   Indian port {i}/{len(portids)}: {portid}")
            rows.extend(
                _paginated_query(PORTS_DAILY, f"portid = '{portid}'", client=client)
            )
    df = pd.DataFrame(rows)
    return normalize_dates(df)


def build_duckdb(
    chokepoints_catalog: pd.DataFrame,
    ports_catalog: pd.DataFrame,
    chokepoints_daily: pd.DataFrame,
    ports_daily: pd.DataFrame,
) -> None:
    RAW_DB.parent.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(RAW_DB))
    con.register("cc", chokepoints_catalog)
    con.register("pc", ports_catalog)
    con.register("cd", chokepoints_daily)
    con.register("pd_", ports_daily)
    con.execute("CREATE OR REPLACE TABLE chokepoints_catalog AS SELECT * FROM cc")
    con.execute("CREATE OR REPLACE TABLE ports_catalog AS SELECT * FROM pc")
    con.execute("CREATE OR REPLACE TABLE chokepoints_daily AS SELECT * FROM cd")
    con.execute("CREATE OR REPLACE TABLE ports_daily AS SELECT * FROM pd_")
    con.close()


def snapshot() -> None:
    """Freeze committed parquet copies — the demo reads these, never the API."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect(str(RAW_DB))
    for table in ("chokepoints_catalog", "ports_catalog", "chokepoints_daily", "ports_daily"):
        con.execute(
            f"COPY {table} TO '{(SNAPSHOT_DIR / f'{table}.parquet').as_posix()}' (FORMAT PARQUET)"
        )
    con.close()


def seasonal_baseline(daily: pd.DataFrame, portid: str) -> pd.Series:
    """Mean n_total per day-of-year over the FIXED pre-crisis window.

    Fixed, not trailing: a trailing window collapses to match a sustained
    closure and silently reads "normal" once the closure has lasted longer
    than the window.
    """
    sub = daily[daily["portid"] == portid].copy()
    sub["date"] = pd.to_datetime(sub["date"])
    baseline = sub[(sub["date"] >= BASELINE_START) & (sub["date"] <= BASELINE_END)]
    return baseline.groupby(baseline["date"].dt.dayofyear)["n_total"].mean()


def collapse_table(daily: pd.DataFrame, portid: str = "chokepoint6", last_n_days: int = 200) -> pd.DataFrame:
    sub = daily[daily["portid"] == portid].copy()
    sub["date"] = pd.to_datetime(sub["date"])
    sub = sub.sort_values("date")
    sub["n_total_7dma"] = sub["n_total"].rolling(7, min_periods=1).mean()

    baseline = seasonal_baseline(daily, portid)
    sub["baseline"] = sub["date"].dt.dayofyear.map(baseline)
    sub["pct_of_baseline"] = (sub["n_total_7dma"] / sub["baseline"] * 100).round(1)

    return sub[["date", "n_total", "n_total_7dma", "baseline", "pct_of_baseline"]].tail(last_n_days)


def main() -> None:
    print("[portwatch] fetching chokepoint catalog (expect 28 rows)...")
    chokepoints_catalog = fetch_chokepoints_catalog()
    print(f"[portwatch]   got {len(chokepoints_catalog)} chokepoints")

    print("[portwatch] fetching Indian ports catalog...")
    ports_catalog = fetch_indian_ports_catalog()
    print(f"[portwatch]   got {len(ports_catalog)} Indian ports")

    print("[portwatch] fetching full chokepoint daily history (2019-01-01 -> today)...")
    chokepoints_daily = fetch_chokepoints_daily()
    print(f"[portwatch]   got {len(chokepoints_daily)} rows")

    print("[portwatch] fetching Indian port daily history...")
    ports_daily = fetch_indian_ports_daily(list(ports_catalog["portid"]))
    print(f"[portwatch]   got {len(ports_daily)} rows")

    print(f"[portwatch] writing DuckDB at {RAW_DB}")
    build_duckdb(chokepoints_catalog, ports_catalog, chokepoints_daily, ports_daily)

    print(f"[portwatch] snapshotting to {SNAPSHOT_DIR}")
    snapshot()

    print("\n[portwatch] chokepoint6 (Strait of Hormuz) — last 200 days vs fixed pre-crisis baseline:\n")
    table = collapse_table(chokepoints_daily, "chokepoint6", 200)
    with pd.option_context("display.max_rows", 200, "display.width", 120):
        print(table.to_string(index=False))


def _self_check() -> None:
    """No network: validates date normalization and baseline math on synthetic data."""
    synthetic = pd.DataFrame(
        {
            "date": ["2026-01-01", "2026-01-02"],
            "year": [2026, 2026],
            "month": [1, 1],
            "day": [1, 2],
            "portid": ["chokepointX", "chokepointX"],
            "n_total": [10, 20],
        }
    )
    normalized = normalize_dates(synthetic)
    assert list(normalized["date"]) == [dt.date(2026, 1, 1), dt.date(2026, 1, 2)]

    baseline_rows = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", "2026-02-27", freq="D"),
        }
    )
    baseline_rows["year"] = baseline_rows["date"].dt.year
    baseline_rows["month"] = baseline_rows["date"].dt.month
    baseline_rows["day"] = baseline_rows["date"].dt.day
    baseline_rows["portid"] = "chokepointX"
    baseline_rows["n_total"] = 100  # flat baseline
    baseline_rows["date"] = baseline_rows["date"].dt.strftime("%Y-%m-%d")

    crisis_rows = pd.DataFrame(
        {
            "date": pd.date_range("2026-03-01", periods=10, freq="D"),
        }
    )
    crisis_rows["year"] = crisis_rows["date"].dt.year
    crisis_rows["month"] = crisis_rows["date"].dt.month
    crisis_rows["day"] = crisis_rows["date"].dt.day
    crisis_rows["portid"] = "chokepointX"
    crisis_rows["n_total"] = 1  # collapse
    crisis_rows["date"] = crisis_rows["date"].dt.strftime("%Y-%m-%d")

    daily = pd.concat([baseline_rows, crisis_rows], ignore_index=True)
    table = collapse_table(daily, "chokepointX", last_n_days=10)
    # baseline is a flat 100 for every day-of-year in the window; crisis days
    # sit at 1/100 = 1% once the 7dMA rolls fully into the crisis window —
    # the collapse must show up, not get smoothed away.
    assert (table["pct_of_baseline"].tail(3) < 5).all(), table

    print("[portwatch] self-check passed")


if __name__ == "__main__":
    import sys

    if "--self-check" in sys.argv:
        _self_check()
    else:
        main()
