"""Cross-checks the hand-built data/reference/*.csv tables for internal
consistency -- every port/refinery cross-reference must resolve to a real
row. Run standalone; also worth re-running whenever a reference CSV changes
(e.g. once Phase 4 replaces unverified figures with PPAC-confirmed ones).
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

    port_ids = set(ports["portid"])
    errors: list[str] = []

    for _, row in refineries.iterrows():
        cell = row.get("connected_ports")
        if pd.isna(cell) or not str(cell).strip():
            continue
        for pid in str(cell).split(","):
            if pid.strip() not in port_ids:
                errors.append(f"refineries.csv: {row['name']} references unknown port {pid!r}")

    known_corridors = {"chokepoint6", "chokepoint4", "none"}
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
        "-- pending PPAC cross-check in Phase 4, not yet primary-sourced"
    )


if __name__ == "__main__":
    validate()
