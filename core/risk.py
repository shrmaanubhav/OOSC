"""Corridor Risk Index (CRI) -- four weighted, independently-computed
components. The LLM never touches this file's arithmetic; it only ever
supplies inputs to O/E via upstream ingestion/extraction.

    CRI(c, t) = 100 * (0.40*O + 0.30*S + 0.20*E + 0.10*X)

    O -- Observed disruption (lagging, PortWatch AIS)
    S -- Signal pressure (leading, GDELT timelinevol x tone)
    E -- Event severity (leading, discrete extracted events, 7-day half-life decay)
    X -- Exposure & compliance (slow-moving, India's flow share through c)

As of Phase 3 (2026-08-20): GDELT backfill has not completed (see
data/snapshots/gdelt/NOTE.md) and the event extractor has not run (needs
an LLM API key, Phase 3 stretch). S and E are therefore NaN for every
date right now -- CRI renormalizes weights over whatever components ARE
available rather than silently treating a missing component as zero
(zero would understate risk, not just omit information). This degrades
gracefully and says so; it does not pretend to be the full four-part
index until GDELT/extraction land.
"""

from __future__ import annotations

import sys
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ingest.portwatch import BASELINE_END, BASELINE_START, seasonal_baseline  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
PORTWATCH_SNAPSHOT = DATA_DIR / "snapshots" / "portwatch" / "chokepoints_daily.parquet"
GDELT_TIMELINES = DATA_DIR / "snapshots" / "gdelt" / "timelines.parquet"
GDELT_EVENTS = DATA_DIR / "snapshots" / "events" / "events.parquet"  # written by agent/extractor.py
EXPOSURE_CSV = DATA_DIR / "reference" / "corridor_exposure.csv"

WEIGHTS = {"O": 0.40, "S": 0.30, "E": 0.20, "X": 0.10}
EVENT_HALF_LIFE_DAYS = 7.0
EVENT_DECAY_LAMBDA = np.log(2) / EVENT_HALF_LIFE_DAYS


def compute_O(portid: str, daily: pd.DataFrame | None = None) -> pd.Series:
    """clip(1 - 7dMA(n_total) / seasonal_baseline(doy), 0, 1), indexed by date."""
    if daily is None:
        daily = duckdb.query(f"SELECT * FROM '{PORTWATCH_SNAPSHOT.as_posix()}'").to_df()
    sub = daily[daily["portid"] == portid].copy()
    sub["date"] = pd.to_datetime(sub["date"])
    sub = sub.sort_values("date")
    sub["n_total_7dma"] = sub["n_total"].rolling(7, min_periods=1).mean()

    baseline = seasonal_baseline(daily, portid)
    sub["baseline"] = sub["date"].dt.dayofyear.map(baseline)
    ratio = sub["n_total_7dma"] / sub["baseline"]
    o = (1 - ratio).clip(0, 1)
    return pd.Series(o.values, index=sub["date"].values, name="O")


def compute_S(corridor_id: str, index: pd.DatetimeIndex, window: int = 90) -> pd.Series:
    """sigmoid(z-score of timelinevol x sign-adjusted timelinetone, trailing window)."""
    if not GDELT_TIMELINES.exists():
        print(f"[risk] GDELT timelines not found ({GDELT_TIMELINES}) -- S is NaN for {corridor_id}")
        return pd.Series(np.nan, index=index, name="S")

    tl = pd.read_parquet(GDELT_TIMELINES)
    tl = tl[tl["corridor_id"] == corridor_id]
    if tl.empty:
        print(f"[risk] no GDELT timeline rows for {corridor_id} -- S is NaN")
        return pd.Series(np.nan, index=index, name="S")

    vol = tl[tl["mode"] == "timelinevol"][["date", "timelinevol"]].set_index("date")
    tone = tl[tl["mode"] == "timelinetone"][["date", "timelinetone"]].set_index("date")
    merged = vol.join(tone, how="outer").sort_index()
    merged.index = pd.to_datetime(merged.index)

    # negative tone (bad news) contributes positively to risk; positive-tone
    # coverage (e.g. "reopening", "truce") should not inflate the signal
    composite = merged["timelinevol"] * (-merged["timelinetone"]).clip(lower=0)
    rolling_mean = composite.rolling(window, min_periods=7).mean()
    rolling_std = composite.rolling(window, min_periods=7).std()
    z = (composite - rolling_mean) / rolling_std.replace(0, np.nan)
    s = 1 / (1 + np.exp(-z))
    return s.reindex(index, method=None).rename("S")


def compute_E(corridor_id: str, index: pd.DatetimeIndex, scale: float = 5.0) -> pd.Series:
    """Sum of signed event severities decayed with a 7-day half-life, squashed to [0,1].

    `scale` sets how much cumulative decayed severity saturates E near 1 --
    a modeling choice (not sourced), documented here rather than buried.
    """
    if not GDELT_EVENTS.exists():
        print(f"[risk] no extracted events found ({GDELT_EVENTS}) -- E is NaN for {corridor_id}")
        return pd.Series(np.nan, index=index, name="E")

    events = pd.read_parquet(GDELT_EVENTS)
    events = events[events["corridor_id"] == corridor_id]
    if events.empty:
        return pd.Series(np.nan, index=index, name="E")

    events = events.copy()
    events["event_date"] = pd.to_datetime(events["event_date"])
    signed_severity = events["severity"] * events["direction"].map(
        {"escalation": 1, "de-escalation": -1}
    )

    e_raw = pd.Series(0.0, index=index)
    for t, s_val in zip(events["event_date"], signed_severity):
        days_since = (index - t).days.astype(float)
        decay = np.exp(-EVENT_DECAY_LAMBDA * days_since)
        decay = np.where(days_since >= 0, decay, 0.0)  # events can't affect the past
        e_raw += decay * s_val

    e = (1 + np.tanh(e_raw / scale)) / 2
    return pd.Series(e.values, index=index, name="E")


def compute_X(corridor_id: str) -> float:
    exposure = pd.read_csv(EXPOSURE_CSV)
    row = exposure[exposure["corridor_id"] == corridor_id]
    if row.empty or pd.isna(row.iloc[0]["india_share_pct"]):
        return np.nan
    return float(row.iloc[0]["india_share_pct"]) / 100.0


def compute_cri(corridor_id: str, portid: str | None = None) -> pd.DataFrame:
    """Full CRI table for one corridor. Renormalizes WEIGHTS over whatever
    components aren't NaN on a given day, and reports how many/which
    components were actually used -- never silently substitutes 0 for
    missing data.
    """
    portid = portid or corridor_id
    o = compute_O(portid)
    index = o.index

    s = compute_S(corridor_id, index)
    e = compute_E(corridor_id, index)
    x_val = compute_X(corridor_id)
    x = pd.Series(x_val, index=index, name="X")

    df = pd.concat([o, s, e, x], axis=1)

    weight_matrix = pd.DataFrame(
        {comp: np.where(df[comp].notna(), WEIGHTS[comp], 0.0) for comp in WEIGHTS}, index=df.index
    )
    weight_sum = weight_matrix.sum(axis=1)
    filled = df.fillna(0.0)
    weighted = sum(filled[c] * weight_matrix[c] for c in WEIGHTS)
    df["CRI"] = np.where(weight_sum > 0, 100 * weighted / weight_sum, np.nan)
    df["components_used"] = weight_matrix.apply(
        lambda r: ",".join(c for c in WEIGHTS if r[c] > 0), axis=1
    )
    return df


def _self_check() -> None:
    """No network: verifies renormalization degrades gracefully when S/E
    are entirely missing, and that O alone still drives a sane CRI shape."""
    idx = pd.date_range("2026-02-20", periods=20, freq="D")
    o = pd.Series(np.linspace(0.0, 1.0, len(idx)), index=idx, name="O")  # rising risk
    s = pd.Series(np.nan, index=idx, name="S")
    e = pd.Series(np.nan, index=idx, name="E")
    x = pd.Series(0.41, index=idx, name="X")

    df = pd.concat([o, s, e, x], axis=1)
    weight_matrix = pd.DataFrame(
        {comp: np.where(df[comp].notna(), WEIGHTS[comp], 0.0) for comp in WEIGHTS}, index=df.index
    )
    weight_sum = weight_matrix.sum(axis=1)
    filled = df.fillna(0.0)
    weighted = sum(filled[c] * weight_matrix[c] for c in WEIGHTS)
    cri = np.where(weight_sum > 0, 100 * weighted / weight_sum, np.nan)

    # with only O and X available, weight renormalizes over 0.40+0.10=0.50;
    # CRI must still rise monotonically with O and never exceed 100
    assert np.all(np.diff(cri) >= -1e-9), cri
    assert np.all(cri <= 100.0 + 1e-9), cri
    # at O=0, CRI should equal the X-only contribution: 100 * (0.10*0.41)/0.50 = 8.2
    assert abs(cri[0] - 8.2) < 1e-6, cri[0]

    print("[risk] self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        df = compute_cri("chokepoint6")
        with pd.option_context("display.max_rows", 30, "display.width", 120):
            print(df.tail(30))
        print(f"\n[risk] components used (most recent day): {df['components_used'].iloc[-1] or 'NONE'}")
