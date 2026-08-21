"""Digital twin -- a networkx.MultiDiGraph built from the hand-built
reference tables + real PortWatch corridor data + searoute distances.

Kept deliberately thin per project scope (Risk Intelligence, Scenario
Modeller, and Procurement Orchestrator are the three deep pillars; the
twin only needs to be correct-shaped and queryable, not polished).

Simplification from the design doc's Source-SHIPS_VIA->Route-TRANSITS->
Corridor chain: Route is not a separate node type here. Its attributes
(distance_km, transit_days) live directly on the SHIPS_VIA edge instead
-- a Route node would only earn its keep if multiple distinct routes
existed between the same Source/Corridor pair, which nothing in this
build's data models yet. Reserve and Product nodes are deliberately
NOT included: reserve drawdown is core/reserve.py's job (Phase 5) and
product yields are core/scenario.py's (Phase 5) -- duplicating them
here as twin nodes would be unused decoration, not signal.

Edge types:
  Source  --SHIPS_VIA--> Corridor   (grades with a modeled corridor)
  Source  --SHIPS_VIA--> Port       (grades with corridor_transited=none:
                                      no modeled chokepoint risk, ships
                                      straight to the nearest discharge port)
  Corridor --ARRIVES_AT--> Port     (every corridor connects to every
                                      modeled Indian discharge port --
                                      cargo can head to any coast after
                                      clearing the strait)
  Port    --FEEDS--> Refinery       (from refineries.csv's connected_ports)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import networkx as nx
import pandas as pd

REF_DIR = Path(__file__).resolve().parent.parent / "data" / "reference"
PORTWATCH_CATALOG = (
    Path(__file__).resolve().parent.parent
    / "data" / "snapshots" / "portwatch" / "chokepoints_catalog.parquet"
)
TWIN_SNAPSHOT = Path(__file__).resolve().parent.parent / "data" / "snapshots" / "twin.json"

AVG_TANKER_SPEED_KMH = 14 * 1.852  # 14 knots, typical laden VLCC transit speed


def _searoute_km(a: tuple[float, float], b: tuple[float, float]) -> float | None:
    """(lon, lat) -> (lon, lat) great-circle-avoiding-land distance in km.
    Returns None if searoute can't find a sea route (e.g. landlocked-ish
    coordinate pairs) rather than crashing twin construction."""
    import searoute as sr

    try:
        route = sr.searoute(a, b)
        return float(route["properties"]["length"])
    except Exception:
        return None


def build_twin() -> nx.MultiDiGraph:
    sources = pd.read_csv(REF_DIR / "sources.csv")
    ports = pd.read_csv(REF_DIR / "ports.csv")
    refineries = pd.read_csv(REF_DIR / "refineries.csv")
    corridors = pd.read_parquet(PORTWATCH_CATALOG)
    # Derived from sources.csv itself, not hardcoded -- a corridor newly
    # tagged there (e.g. B3: chokepoint1/5/7) is picked up automatically.
    # A hardcoded list here previously meant a grade retagged to a new
    # corridor_transited value would silently fail the `in g` check below
    # and fall through to the "no modeled corridor" branch -- present in
    # sources.csv but invisible in the twin.
    modeled_corridors = set(sources["corridor_transited"]) - {"none"}
    corridors = corridors[corridors["portid"].isin(modeled_corridors)]

    g = nx.MultiDiGraph()

    for _, c in corridors.iterrows():
        g.add_node(c["portid"], kind="Corridor", name=c["portname"], lat=c["lat"], lon=c["lon"])

    for _, p in ports.iterrows():
        g.add_node(p["portid"], kind="Port", name=p["portname"], lat=p["lat"], lon=p["lon"], locode=p["locode"])

    for _, r in refineries.iterrows():
        g.add_node(r["name"], kind="Refinery", operator=r["operator"], capacity_kbd=r["capacity_kbd"])

    for _, s in sources.iterrows():
        source_id = s["grade"]
        g.add_node(
            source_id, kind="Source", country=s["country"], api=s["api"], sulphur_pct=s["sulphur_pct"]
        )
        load_pt = (s["load_port_lon"], s["load_port_lat"])

        if s["corridor_transited"] != "none" and s["corridor_transited"] in g:
            corridor = corridors[corridors["portid"] == s["corridor_transited"]].iloc[0]
            dist_km = _searoute_km(load_pt, (corridor["lon"], corridor["lat"]))
            g.add_edge(
                source_id, s["corridor_transited"], key="SHIPS_VIA",
                distance_km=dist_km,
                transit_days=round(dist_km / AVG_TANKER_SPEED_KMH / 24, 1) if dist_km else None,
            )
        else:
            # no modeled corridor -- ship straight to the nearest discharge port
            nearest = _nearest_port(load_pt, ports)
            dist_km = _searoute_km(load_pt, (nearest["lon"], nearest["lat"]))
            g.add_edge(
                source_id, nearest["portid"], key="SHIPS_VIA",
                distance_km=dist_km,
                transit_days=round(dist_km / AVG_TANKER_SPEED_KMH / 24, 1) if dist_km else None,
            )

    for _, c in corridors.iterrows():
        for _, p in ports.iterrows():
            dist_km = _searoute_km((c["lon"], c["lat"]), (p["lon"], p["lat"]))
            g.add_edge(c["portid"], p["portid"], key="ARRIVES_AT", distance_km=dist_km)

    for _, r in refineries.iterrows():
        if pd.isna(r["connected_ports"]) or not str(r["connected_ports"]).strip():
            continue
        for portid in str(r["connected_ports"]).split(","):
            portid = portid.strip()
            if portid in g:
                g.add_edge(portid, r["name"], key="FEEDS")

    return g


def _nearest_port(point: tuple[float, float], ports: pd.DataFrame) -> pd.Series:
    """Straight-line nearest (not searoute -- this only picks a candidate
    port; the actual edge distance is still computed via searoute)."""
    lon, lat = point
    dist2 = (ports["lon"] - lon) ** 2 + (ports["lat"] - lat) ** 2
    return ports.loc[dist2.idxmin()]


def to_json(g: nx.MultiDiGraph) -> dict:
    return nx.node_link_data(g, edges="edges")


def sample_path(g: nx.MultiDiGraph, source_grade: str, refinery_name: str) -> list[dict] | None:
    """One source -> corridor/port -> ... -> refinery path, for sanity
    checking the twin (Phase 4 exit criterion)."""
    try:
        path = nx.shortest_path(g, source_grade, refinery_name)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return None
    steps = []
    for i in range(len(path) - 1):
        u, v = path[i], path[i + 1]
        edge_data = g.get_edge_data(u, v)
        # MultiDiGraph: take the first (only, in this twin) parallel edge
        edge_key, attrs = next(iter(edge_data.items()))
        steps.append(
            {"from": u, "from_kind": g.nodes[u]["kind"], "to": v, "to_kind": g.nodes[v]["kind"],
             "key": edge_key, **attrs}
        )
    return steps


def main() -> None:
    g = build_twin()
    print(f"[twin] {g.number_of_nodes()} nodes, {g.number_of_edges()} edges")
    kinds = pd.Series([d["kind"] for _, d in g.nodes(data=True)]).value_counts()
    print(kinds.to_string())

    TWIN_SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    TWIN_SNAPSHOT.write_text(json.dumps(to_json(g), default=str))
    print(f"[twin] serialized -> {TWIN_SNAPSHOT}")

    print("\n[twin] sample path: Murban -> Mangalore (MRPL (ONGC subsidiary))")
    path = sample_path(g, "Murban", "Mangalore")
    if path is None:
        print("[twin]   NO PATH FOUND")
    else:
        for step in path:
            print(f"  {step['from']} ({step['from_kind']}) --{step.get('key','?')}--> "
                  f"{step['to']} ({step['to_kind']})"
                  + (f"  [{step['distance_km']:.0f} km]" if step.get("distance_km") else ""))


def _self_check() -> None:
    """No network beyond searoute's own bundled offline routing data
    (verified elsewhere it needs no API key/live call): builds a tiny
    2-node twin by hand and checks sample_path walks it correctly."""
    g = nx.MultiDiGraph()
    g.add_node("TestGrade", kind="Source")
    g.add_node("chokepoint6", kind="Corridor")
    g.add_node("port1199", kind="Port")
    g.add_node("TestRefinery", kind="Refinery")
    g.add_edge("TestGrade", "chokepoint6", key="SHIPS_VIA", distance_km=1000)
    g.add_edge("chokepoint6", "port1199", key="ARRIVES_AT", distance_km=2000)
    g.add_edge("port1199", "TestRefinery", key="FEEDS")

    path = sample_path(g, "TestGrade", "TestRefinery")
    assert path is not None
    assert [s["to"] for s in path] == ["chokepoint6", "port1199", "TestRefinery"]
    assert [s["key"] for s in path] == ["SHIPS_VIA", "ARRIVES_AT", "FEEDS"]
    assert path[0]["distance_km"] == 1000

    assert sample_path(g, "TestGrade", "NoSuchRefinery") is None

    # B3: real data -- Urals (corridor_transited=chokepoint1 in sources.csv)
    # must actually reach a Corridor node in the built twin, not silently
    # fall through to the "no modeled corridor" branch because chokepoint1
    # wasn't in a hardcoded corridor list
    real = build_twin()
    urals_path = sample_path(real, "Urals", "Jamnagar (DTA)")
    assert urals_path is not None, "no path from Urals to Jamnagar (DTA) in the real twin"
    assert urals_path[0]["to"] == "chokepoint1", (
        f"Urals should SHIPS_VIA chokepoint1, went to {urals_path[0]['to']!r} instead -- "
        "a modeled corridor is being silently dropped"
    )
    assert real.nodes["chokepoint1"]["kind"] == "Corridor"

    print("[twin] self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        main()
