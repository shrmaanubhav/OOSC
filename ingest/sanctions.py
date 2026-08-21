"""OFAC-designated vessel data via OpenSanctions' bulk distribution --
replaces sources.csv's hand-typed sanctions_flag citation ("not backed by
a live sanctioned-vessel or sanctioned-entity list") with a real, dated
primary-source count. One parser for one dataset, snapshotted to CSV.
Never re-parsed at demo time -- run this once, commit the snapshot,
everything downstream reads the CSV.

Live-verified source (2026-08-20):
  https://www.opensanctions.org/datasets/us_ofac_sdn/
  "Targets (Simple CSV)" bulk download -- 20,079 designated targets
  (persons, companies, vessels, aircraft, ...), OFAC's Specially
  Designated Nationals list via OpenSanctions' free non-commercial bulk
  distribution (https://www.opensanctions.org/docs/bulk/).

This build does NOT attempt entity-level resolution from a crude GRADE
(e.g. "Urals", "ESPO") to a specific designated vessel or shipping
company -- crude grades are commodities, not sanctioned parties, and no
primary source in this build links a specific tanker to a specific cargo
grade. What this DOES provide, honestly: real, dated, counted evidence
that the sanctions regime sources.csv's per-grade sanctions_flag reflects
(US-RUSHAR for Russia, US-VEN for Venezuela) actually exists and is
actively populated with vessel designations -- not that any specific
Urals cargo was carried by a specific listed vessel.

The download URL embeds a crawl timestamp that changes each time
OpenSanctions re-crawls (roughly daily) -- it is NOT re-fetched
automatically. Update SANCTIONS_URL by hand when a fresher pull is
needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pandas as pd

SANCTIONS_URL = (
    "https://data.opensanctions.org/artifacts/us_ofac_sdn/20260820141127-lcy/targets.simple.csv"
)

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
RAW_CSV = DATA_DIR / "raw" / "ofac_sdn_targets.csv"
SNAPSHOT_DIR = DATA_DIR / "snapshots" / "sanctions"

# The two OFAC sanctions programs relevant to sources.csv's sanctions_flag
# grades: US-RUSHAR (Russia Harmful Foreign Activities -- the "shadow
# fleet" tanker-designation program, covers Urals/ESPO/Sokol's shipping
# exposure) and US-VEN (Venezuela, covers Merey's).
RELEVANT_PROGRAMS = {"US-RUSHAR": "Russia (Urals/ESPO/Sokol)", "US-VEN": "Venezuela (Merey)"}


def parse_sanctioned_vessels(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path, low_memory=False)
    vessels = df[df["schema"] == "Vessel"].copy()
    pattern = "|".join(RELEVANT_PROGRAMS)
    relevant = vessels[vessels["program_ids"].str.contains(pattern, na=False, regex=True)].copy()
    relevant["program_label"] = relevant["program_ids"].map(
        lambda p: next((label for prog, label in RELEVANT_PROGRAMS.items() if prog in str(p)), p)
    )
    return relevant[["id", "name", "countries", "program_ids", "program_label", "last_seen"]]


def main() -> None:
    RAW_CSV.parent.mkdir(parents=True, exist_ok=True)
    if not RAW_CSV.exists():
        print(f"[sanctions] downloading {SANCTIONS_URL}")
        with httpx.Client(timeout=60, follow_redirects=True) as client:
            resp = client.get(SANCTIONS_URL)
            resp.raise_for_status()
            RAW_CSV.write_bytes(resp.content)
        print(f"[sanctions]   saved {len(resp.content):,} bytes -> {RAW_CSV}")
    else:
        print(f"[sanctions] using cached {RAW_CSV}")

    df = parse_sanctioned_vessels(RAW_CSV)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SNAPSHOT_DIR / "ofac_sdn_vessels.csv"
    df.to_csv(out_path, index=False)
    print(f"[sanctions] {len(df)} OFAC-designated vessels under {'/'.join(RELEVANT_PROGRAMS)} -> {out_path}")
    print(df["program_label"].value_counts().to_string())


def _self_check() -> None:
    """No network: filtering/labeling logic against a synthetic copy of the
    real targets.simple.csv schema (verified live 2026-08-20)."""
    import tempfile

    synthetic = pd.DataFrame({
        "id": ["v1", "v2", "v3", "p1"],
        "schema": ["Vessel", "Vessel", "Vessel", "Person"],
        "name": ["Baltic Leader", "Some Venezuelan Tanker", "Unrelated Ship", "John Doe"],
        "countries": ["ru", "ve", "cn", "us"],
        "program_ids": ["US-RUSHAR", "US-VEN", "US-TERR", "US-RUSHAR"],
        "last_seen": ["2026-08-20"] * 4,
    })
    tmp = Path(tempfile.mktemp(suffix=".csv"))
    synthetic.to_csv(tmp, index=False)
    try:
        result = parse_sanctioned_vessels(tmp)
        # only the 2 Vessel rows under a relevant program survive -- the
        # Person row (wrong schema) and the US-TERR vessel (wrong program)
        # must both be excluded
        assert len(result) == 2, result
        assert set(result["name"]) == {"Baltic Leader", "Some Venezuelan Tanker"}
        assert result[result["name"] == "Baltic Leader"]["program_label"].iloc[0] == "Russia (Urals/ESPO/Sokol)"
        assert result[result["name"] == "Some Venezuelan Tanker"]["program_label"].iloc[0] == "Venezuela (Merey)"
    finally:
        tmp.unlink(missing_ok=True)

    print("[sanctions] self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        main()
