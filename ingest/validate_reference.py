"""Cross-checks the hand-built data/reference/*.csv tables for internal
consistency -- every port/refinery cross-reference must resolve to a real
row. Run standalone; also worth re-running whenever a reference CSV changes.

refineries.csv is fully PPAC-verified (Phase 4, ingest/ppac.py). ports.csv
(draft/SPM/VLCC specs) and sources.csv (crude assay API/sulphur values)
are NOT covered by any PPAC table and are expected to stay at public-
knowledge-estimate status unless a primary source (EIA/Argus-type crude
assay data, port authority draft specs) is added -- that's a Tier 2/
stretch source, not a gap in Phase 4.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REF_DIR = Path(__file__).resolve().parent.parent / "data" / "reference"


def validate() -> None:
    ports = pd.read_csv(REF_DIR / "ports.csv")
    refineries = pd.read_csv(REF_DIR / "refineries.csv")
    sources = pd.read_csv(REF_DIR / "sources.csv")
    bypass_routes = pd.read_csv(REF_DIR / "bypass_routes.csv")
    spr = pd.read_csv(REF_DIR / "spr.csv")
    corridor_exposure = pd.read_csv(REF_DIR / "corridor_exposure.csv")

    port_ids = set(ports["portid"])
    errors: list[str] = []

    for _, row in refineries.iterrows():
        cell = row.get("connected_ports")
        if pd.isna(cell) or not str(cell).strip():
            continue
        for pid in str(cell).split(","):
            if pid.strip() not in port_ids:
                errors.append(f"refineries.csv: {row['name']} references unknown port {pid!r}")

    # Derived from corridor_exposure.csv itself, not hardcoded -- a corridor
    # newly added there (e.g. B3: chokepoint1/5/7) is automatically valid
    # here without a second place to remember to update.
    known_corridors = set(corridor_exposure["corridor_id"]) | {"none"}
    for _, row in sources.iterrows():
        if row["corridor_transited"] not in known_corridors:
            errors.append(
                f"sources.csv: {row['grade']} has unrecognised corridor_transited {row['corridor_transited']!r}"
            )
    for _, row in bypass_routes.iterrows():
        for col in ("origin_corridor", "discharge_corridor"):
            if row[col] not in known_corridors:
                errors.append(
                    f"bypass_routes.csv: {row['route_name']} has unrecognised {col} {row[col]!r}"
                )

    if errors:
        raise AssertionError("Reference data inconsistencies:\n" + "\n".join(errors))

    print(
        f"[validate_reference] ok -- {len(ports)} ports, {len(refineries)} refineries, "
        f"{len(sources)} source grades, {len(bypass_routes)} bypass routes, {len(spr)} SPR sites"
    )
    unverified = pd.concat(
        [
            refineries[refineries["verified"] == False][["name"]].rename(columns={"name": "row"}),
            ports[ports["verified"] == False][["portname"]].rename(columns={"portname": "row"}),
            sources[sources["verified"] == False][["grade"]].rename(columns={"grade": "row"}),
        ]
    )
    print(
        f"[validate_reference] {len(unverified)} rows flagged verified=False "
        "-- public-knowledge estimates (ports.csv draft/SPM specs, sources.csv crude "
        "assays), not covered by any PPAC table; see module docstring"
    )


if __name__ == "__main__":
    validate()
