"""Tool registry -- the ONLY numeric path the LLM is allowed to use
(CLAUDE.md rule 4: "the LLM extracts, routes, narrates -- never
computes"). Every function here is a thin wrapper over `core/`; none of
them do arithmetic the LLM could have influenced, and every number they
return traces to a deterministic computation on committed snapshot data.

Returns are deliberately COMPACT dicts, not full tables: the whole result
is pasted into the model's context on every subsequent loop step, so a
200-row CRI series would blow the token budget and bury the signal. The
API (api/main.py) reads core/ directly for the full-fidelity series the
frontend charts need -- that path doesn't go through the model at all.

Everything returned here also becomes agent/provenance.py's source pool,
so a number the agent is expected to be ABLE to cite must appear in a
tool result verbatim -- that's why summaries carry explicit min/max/mean
rather than leaving the model to derive them (deriving = computing =
banned).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import backtest, procurement, reserve, risk, scenario  # noqa: E402

REF_DIR = Path(__file__).resolve().parent.parent / "data" / "reference"

_cri_cache: dict[str, pd.DataFrame] = {}


def _cri(corridor_id: str) -> pd.DataFrame:
    """compute_cri re-reads parquet + recomputes the seasonal baseline on
    every call; the API re-solves on every slider drag, so cache it."""
    if corridor_id not in _cri_cache:
        _cri_cache[corridor_id] = risk.compute_cri(corridor_id)
    return _cri_cache[corridor_id]


def list_corridors() -> dict:
    """What corridors this system models, and India's exposure to each."""
    exposure = pd.read_csv(REF_DIR / "corridor_exposure.csv")
    catalog = pd.read_parquet(
        Path(__file__).resolve().parent.parent
        / "data" / "snapshots" / "portwatch" / "chokepoints_catalog.parquet"
    )
    names = dict(zip(catalog["portid"], catalog["portname"]))
    return {
        "corridors": [
            {
                "corridor_id": row["corridor_id"],
                "name": names.get(row["corridor_id"], row["corridor_id"]),
                "india_crude_import_share_pct": (
                    None if pd.isna(row["india_share_pct"]) else float(row["india_share_pct"])
                ),
                "normal_capacity_kbd": (
                    None if pd.isna(row["normal_capacity_kbd"]) else float(row["normal_capacity_kbd"])
                ),
                "note": row["note"],
            }
            for _, row in exposure.iterrows()
        ]
    }


def get_cri(corridor_id: str, days: int = 30) -> dict:
    """Current Corridor Risk Index and its four components for one corridor."""
    df = _cri(corridor_id).tail(int(days))
    if df.empty:
        return {"error": f"no CRI data for {corridor_id}"}
    latest = df.iloc[-1]
    return {
        "corridor_id": corridor_id,
        "as_of": str(df.index[-1].date()),
        "window_days": int(days),
        "cri_latest": round(float(latest["CRI"]), 2),
        "cri_min_in_window": round(float(df["CRI"].min()), 2),
        "cri_max_in_window": round(float(df["CRI"].max()), 2),
        "cri_mean_in_window": round(float(df["CRI"].mean()), 2),
        "components_latest": {
            c: (None if pd.isna(latest[c]) else round(float(latest[c]), 3)) for c in "OSEX"
        },
        "components_used": latest["components_used"],
        "component_meaning": {
            "O": "observed AIS transit deficit vs seasonal baseline (lagging, 2-9 day publish lag)",
            "S": "GDELT news volume x negative tone (leading)",
            "E": "decayed severity of LLM-extracted discrete events (leading)",
            "X": "India's structural crude-import exposure to this corridor (slow-moving)",
        },
        "weights": risk.WEIGHTS,
        "caveat": "components reported as null are genuinely missing data, not zero -- "
                  "CRI renormalizes its weights over whatever is available.",
    }


def get_bypass_routes(corridor_id: str | None = None) -> dict:
    """Pipeline/route alternatives that bypass a corridor -- INCLUDING which
    corridor each one's cargo has to transit AFTER the bypass. A bypass whose
    discharge_corridor is itself degraded is not a real bypass."""
    df = pd.read_csv(REF_DIR / "bypass_routes.csv")
    if corridor_id:
        df = df[df["origin_corridor"] == corridor_id]
    return {
        "routes": [
            {
                "route_name": r["route_name"],
                "bypasses_corridor": r["origin_corridor"],
                "capacity_kbd": None if pd.isna(r["capacity_kbd"]) else float(r["capacity_kbd"]),
                "discharge_corridor": r["discharge_corridor"],
                "status": r["status"],
                "note": r["note"],
            }
            for _, r in df.iterrows()
        ]
    }


def get_sanctions_evidence() -> dict:
    """Real, dated evidence backing sources.csv's per-grade sanctions_flag
    (Urals/ESPO/Sokol/Merey): counts of OFAC-designated VESSELS under the
    relevant sanctions programs, pulled from OFAC's SDN list via
    OpenSanctions (ingest/sanctions.py). This is evidence the sanctions
    regime is real and actively enforced -- NOT proof any specific cargo
    was carried by a specific listed vessel (no primary source in this
    build resolves a crude grade to an individual tanker)."""
    path = Path(__file__).resolve().parent.parent / "data" / "snapshots" / "sanctions" / "ofac_sdn_vessels.csv"
    if not path.exists():
        return {"error": "sanctions snapshot not found -- run ingest/sanctions.py"}
    df = pd.read_csv(path)
    return {
        "as_of": str(df["last_seen"].max())[:10] if len(df) else None,
        "source": "OFAC Specially Designated Nationals list, via OpenSanctions bulk distribution "
                  "(ingest/sanctions.py, data/snapshots/sanctions/ofac_sdn_vessels.csv)",
        "designated_vessel_counts_by_program": df["program_label"].value_counts().to_dict(),
        "total_designated_vessels": len(df),
        "caveat": "Vessel-level designations under the sanctions programs relevant to sources.csv's "
                  "flagged grades (Russia/US-RUSHAR, Venezuela/US-VEN) -- not a crude-grade-to-vessel "
                  "resolution. Confirms the sanctions regime is real and populated, not that any "
                  "specific cargo used a specific listed tanker.",
    }


def run_scenario(
    corridor_id: str,
    severity: float,
    duration_days: int = 90,
    second_corridor_id: str | None = None,
    second_severity: float | None = None,
    compliance_mode: bool = False,
) -> dict:
    """Full cascade: corridor shock -> reroute attempt (procurement LP) ->
    refinery run cuts -> product shortfall -> crude price -> India macro
    impact. severity is 0-1 (1.0 = full closure). Pass second_corridor_id
    + second_severity to shock two corridors at once."""
    other = (
        {second_corridor_id: float(second_severity)}
        if second_corridor_id and second_severity is not None
        else None
    )
    r = scenario.run_scenario(
        corridor_id, float(severity), int(duration_days),
        other_severity=other, compliance_mode=compliance_mode,
    )
    cuts = {k: v for k, v in r["refinery_impact"]["value"].items() if v > 0}
    macro = r["macro"]["value"]
    return {
        "scenario": r["scenario"],
        "total_shortfall_kbd": round(float(r["procurement"]["total_shortfall_kbd"]), 1),
        "refineries_with_run_cut": len(cuts),
        "run_cuts_pct": {k: round(v * 100, 1) for k, v in sorted(cuts.items(), key=lambda kv: -kv[1])[:5]},
        "product_shortfall_kbd": {
            k: round(v, 1)
            for k, v in sorted(r["product_shortfall"]["value"].items(), key=lambda kv: -kv[1])[:5]
            if v > 0
        },
        "crude_price_usd_bbl": round(float(r["price"]["value"]), 2),
        "crude_price_baseline_usd_bbl": scenario.CALIBRATION_P0_USD_BBL,
        "import_bill_delta_annualized_usd_bn": round(macro["import_bill_delta_annualized_usd"] / 1e9, 2),
        "import_bill_delta_over_scenario_usd_bn": round(macro["import_bill_delta_over_scenario_usd"] / 1e9, 2),
        "pct_of_gdp": round(macro["pct_of_gdp"] * 100, 3),
        "cpi_impact_pp": round(macro["cpi_impact_pct"] * 100, 3),
        "method": {k: r[k]["method"] for k in ("refinery_impact", "price", "macro")},
        "confidence": {k: r[k]["confidence"] for k in ("refinery_impact", "product_shortfall", "macro")},
    }


def solve_procurement(
    corridor_id: str | None = None,
    severity: float = 0.0,
    lambda_risk: float = 0.0,
    anti_concentration: bool = True,
    compliance_mode: bool = False,
) -> dict:
    """Allocation LP: which crude sources feed which refineries, minimizing
    cost + lambda_risk * corridor CRI, with an optional per-country
    concentration cap."""
    sev = {corridor_id: float(severity)} if corridor_id else {}
    cri = {c: float(_cri(c)["CRI"].iloc[-1]) for c in ("chokepoint6", "chokepoint4")}
    r = procurement.solve(
        severity=sev,
        lambda_risk=float(lambda_risk),
        mu_concentration=1.0 if anti_concentration else 0.0,
        compliance_mode=compliance_mode,
        corridor_cri=cri,
    )
    shares = procurement.country_shares(r)
    return {
        "status": r["status"],
        "total_allocated_kbd": round(float(r["total_allocated_kbd"]), 1),
        "total_shortfall_kbd": round(float(r["total_shortfall_kbd"]), 1),
        "country_shares_pct": {k: round(v * 100, 1) for k, v in shares.items()},
        "corridor_cri_used": {k: round(v, 2) for k, v in cri.items()},
        "concentration_cap_pct": procurement.DEFAULT_CONCENTRATION_CAP * 100 if anti_concentration else None,
        "caveat": "cost is a real searoute distance proxy, NOT real FOB+freight+war-risk pricing "
                  "(no primary source ingested for those in this build).",
    }


def run_reserve(daily_gap_kbd: float, duration_days: int = 90) -> dict:
    """India's strategic petroleum reserve drawdown schedule against a
    sustained daily supply gap. NOTE: this is the 5.33 MMT SPR only
    (~9.5 days of cover), NOT India's ~74 days of total national storage."""
    r = reserve.run_reserve(float(daily_gap_kbd), int(duration_days))
    sched = r["schedule"]
    return {
        "daily_gap_kbd": float(daily_gap_kbd),
        "duration_days": int(duration_days),
        "spr_capacity_million_bbl": round(r["capacity_bbl"] / 1e6, 1),
        "max_pumpout_rate_kbd": round(r["max_pumpout_rate_kbd"], 1),
        "days_to_exhaustion": r["days_to_exhaustion"],
        "total_unserved_kbd_days": round(float(r["total_unserved_kbd_days"]), 1),
        "days_of_cover_at_start": reserve.DESIGN_DOC_DAYS_OF_COVER,
        "schedule_first_5_days": sched.head(5).round(1).to_dict("records"),
        "caveat": "SPR strategic reserve only (5.33 MMT, ~9.5 days). India's ~74 days of total "
                  "national storage is a different, larger figure -- do not conflate them.",
    }


def get_backtest(horizon_days: int = 7) -> dict:
    """How well does CRI actually predict disruption? Calibrated on the real
    Bab el-Mandeb crisis (Oct 2023-Feb 2024), validated out-of-sample on the
    real Hormuz closure (Feb-Aug 2026)."""
    r = backtest.run_backtest(int(horizon_days))
    return {
        "horizon_days": r["horizon"],
        "auc_out_of_sample": None if pd.isna(r["auc"]) else round(float(r["auc"]), 3),
        "fit_window": "Bab el-Mandeb (chokepoint4) Oct 2023 - Feb 2024",
        "validation_window": "Hormuz (chokepoint6) Feb - Aug 2026",
        "n_fit_days": r["n_fit"],
        "n_validation_days": r["n_valid"],
        "validation_positive_rate": round(r["valid_positive_rate"], 3),
        "caveat": "AUC is null at long horizons because the sustained closure makes nearly every "
                  "validation day a positive label -- undefined, not zero. The fit window's CRI has "
                  "O,S (GDELT was backfilled for Oct 2023-Feb 2024 specifically to cover this "
                  "window) but not E (LLM event extraction never ran against it) or X, while "
                  "validation has all four components.",
    }


def get_disruption_probability(corridor_id: str, horizon_days: int = 7) -> dict:
    """LIVE probability that this corridor is disrupted within horizon_days,
    from the corridor's current CRI run through the same logistic
    calibration get_backtest validates out-of-sample. This is the number
    the brief means by 'a live supply-disruption probability score' --
    prefer it over quoting a bare CRI figure when asked about risk or
    likelihood. Call get_backtest at the same horizon_days to see how
    reliable this probability actually is out-of-sample (AUC) before
    treating it as precise."""
    cri = _cri(corridor_id)
    cri_now = float(cri["CRI"].iloc[-1])
    r = backtest.disruption_probability(corridor_id, int(horizon_days), cri_now=cri_now)
    return {
        "corridor_id": r["corridor_id"],
        "horizon_days": r["horizon_days"],
        "cri_now": r["cri_now"],
        "probability": r["probability"],
        "method": r["method"],
        "caveat": "This calibration was fit on Bab el-Mandeb's CRI range (Oct 2023-Feb 2024), which "
                  "never reached anywhere near Hormuz's current levels -- applied to a high-CRI "
                  "corridor like an active Hormuz closure, it is measurably UNDER-confident (a "
                  "near-total real closure can still show well under 50% here). Call get_backtest "
                  "for this horizon's out-of-sample AUC before treating this number as precise.",
    }


def _p(properties: dict, required: list[str] | None = None) -> dict:
    return {"type": "object", "properties": properties, "required": required or []}


STR, NUM, INT, BOOL = "string", "number", "integer", "boolean"

# JSON Schema per tool -- consumed both by the prompt text (describe()) and
# by every provider's native function-calling API (agent/llm.py). One
# definition, so the model's view and the executable signature cannot drift.
REGISTRY = {
    "list_corridors": {
        "fn": list_corridors,
        "description": list_corridors.__doc__,
        "parameters": _p({}),
    },
    "get_cri": {
        "fn": get_cri,
        "description": get_cri.__doc__,
        "parameters": _p(
            {
                "corridor_id": {"type": STR, "description": "e.g. 'chokepoint6' (Hormuz), 'chokepoint4' (Bab el-Mandeb)"},
                "days": {"type": INT, "description": "lookback window, default 30"},
            },
            ["corridor_id"],
        ),
    },
    "get_bypass_routes": {
        "fn": get_bypass_routes,
        "description": get_bypass_routes.__doc__,
        "parameters": _p(
            {"corridor_id": {"type": STR, "description": "corridor to find bypasses for; omit for all"}}
        ),
    },
    "get_sanctions_evidence": {
        "fn": get_sanctions_evidence,
        "description": get_sanctions_evidence.__doc__,
        "parameters": _p({}),
    },
    "run_scenario": {
        "fn": run_scenario,
        "description": run_scenario.__doc__,
        "parameters": _p(
            {
                "corridor_id": {"type": STR, "description": "corridor being shocked"},
                "severity": {"type": NUM, "description": "0-1, where 1.0 is full closure"},
                "duration_days": {"type": INT, "description": "default 90"},
                "second_corridor_id": {"type": STR, "description": "optional second corridor to shock in the same run"},
                "second_severity": {"type": NUM, "description": "0-1 severity for the second corridor"},
                "compliance_mode": {"type": BOOL, "description": "if true, sanctioned crude cannot substitute"},
            },
            ["corridor_id", "severity"],
        ),
    },
    "solve_procurement": {
        "fn": solve_procurement,
        "description": solve_procurement.__doc__,
        "parameters": _p(
            {
                "corridor_id": {"type": STR, "description": "corridor to shock, optional"},
                "severity": {"type": NUM, "description": "0-1, default 0"},
                "lambda_risk": {"type": NUM, "description": "risk-aversion weight, default 0"},
                "anti_concentration": {"type": BOOL, "description": "per-country cap, default true"},
                "compliance_mode": {"type": BOOL, "description": "default false"},
            }
        ),
    },
    "run_reserve": {
        "fn": run_reserve,
        "description": run_reserve.__doc__,
        "parameters": _p(
            {
                "daily_gap_kbd": {"type": NUM, "description": "sustained daily supply shortfall in kbd"},
                "duration_days": {"type": INT, "description": "default 90"},
            },
            ["daily_gap_kbd"],
        ),
    },
    "get_backtest": {
        "fn": get_backtest,
        "description": get_backtest.__doc__,
        "parameters": _p({"horizon_days": {"type": INT, "description": "7, 14 or 30"}}),
    },
    "get_disruption_probability": {
        "fn": get_disruption_probability,
        "description": get_disruption_probability.__doc__,
        "parameters": _p(
            {
                "corridor_id": {"type": STR, "description": "e.g. 'chokepoint6' (Hormuz), 'chokepoint4' (Bab el-Mandeb)"},
                "horizon_days": {"type": INT, "description": "7, 14 or 30, default 7"},
            },
            ["corridor_id"],
        ),
    },
}


def call(name: str, args: dict) -> dict:
    if name not in REGISTRY:
        return {"error": f"unknown tool {name!r}. Available: {list(REGISTRY)}"}
    try:
        return REGISTRY[name]["fn"](**args)
    except TypeError as exc:
        return {
            "error": f"bad arguments for {name}: {exc}. "
                     f"Expected: {list(REGISTRY[name]['parameters']['properties'])}"
        }
    except Exception as exc:  # a tool blowing up must not kill the agent loop
        return {"error": f"{name} failed: {type(exc).__name__}: {exc}"}


def schemas() -> list[dict]:
    """OpenAI/Groq-style function schemas. agent/llm.py translates these for
    providers whose shape differs (Gemini)."""
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": " ".join((spec["description"] or "").split()),
                "parameters": spec["parameters"],
            },
        }
        for name, spec in REGISTRY.items()
    ]


def describe() -> str:
    """Tool catalog as prompt text."""
    lines = []
    for name, spec in REGISTRY.items():
        props = spec["parameters"]["properties"]
        doc = " ".join((spec["description"] or "").split())
        lines.append(f"- {name}({', '.join(props)}): {doc}")
        for arg, meta in props.items():
            req = "" if arg in spec["parameters"]["required"] else " (optional)"
            lines.append(f"    {arg}: {meta['type']}{req} -- {meta['description']}")
    return "\n".join(lines)


def _self_check() -> None:
    """Runs every tool against the committed snapshots and asserts each
    returns something JSON-serializable, non-empty, and free of the
    error key -- a tool that silently returns {'error': ...} would let the
    agent narrate around missing data instead of failing visibly."""
    import json

    results = {
        "list_corridors": call("list_corridors", {}),
        "get_cri": call("get_cri", {"corridor_id": "chokepoint6", "days": 30}),
        "get_bypass_routes": call("get_bypass_routes", {"corridor_id": "chokepoint6"}),
        "get_sanctions_evidence": call("get_sanctions_evidence", {}),
        "run_reserve": call("run_reserve", {"daily_gap_kbd": 500, "duration_days": 90}),
        "get_backtest": call("get_backtest", {"horizon_days": 7}),
        "get_disruption_probability": call("get_disruption_probability", {"corridor_id": "chokepoint6", "horizon_days": 7}),
        "solve_procurement": call("solve_procurement", {"corridor_id": "chokepoint6", "severity": 1.0}),
        "run_scenario": call("run_scenario", {"corridor_id": "chokepoint6", "severity": 1.0, "duration_days": 90}),
    }
    for name, out in results.items():
        assert "error" not in out, f"{name} -> {out['error']}"
        json.dumps(out)  # must be serializable for both the LLM and the SSE API

    # the probability must actually be a probability, and must move with CRI
    # (not a constant stub) -- Bab el-Mandeb (currently much lower CRI) and
    # Hormuz (an active near-total closure) must not report the same figure
    prob6 = results["get_disruption_probability"]["probability"]
    assert 0.0 <= prob6 <= 1.0, prob6
    prob4 = call("get_disruption_probability", {"corridor_id": "chokepoint4", "horizon_days": 7})["probability"]
    assert prob6 != prob4, "probability didn't vary with corridor -- looks like a stub"

    # the bypass coupling that Phase 7's exit criterion depends on must
    # actually be reachable through the tool, not just present in the CSV
    routes = results["get_bypass_routes"]["routes"]
    yanbu = [r for r in routes if "Yanbu" in r["route_name"]]
    assert yanbu and yanbu[0]["discharge_corridor"] == "chokepoint4", yanbu

    # C3: the sanctions evidence tool must report real, non-trivial counts
    # for both relevant programs, not an empty/stub snapshot
    counts = results["get_sanctions_evidence"]["designated_vessel_counts_by_program"]
    assert counts.get("Russia (Urals/ESPO/Sokol)", 0) > 100, counts
    assert counts.get("Venezuela (Merey)", 0) > 0, counts

    # unknown tool / bad args must return a usable error, never raise --
    # the loop has to be able to show the model what it did wrong
    assert "error" in call("nope", {})
    assert "error" in call("get_cri", {"wrong_arg": 1})

    # every schema must be well-formed and cover exactly the callable's own
    # parameters -- a drifted schema means the model is told to pass an
    # argument that no longer exists (or is never told about a required one)
    import inspect

    for spec in schemas():
        fn_name = spec["function"]["name"]
        params = spec["function"]["parameters"]
        assert params["type"] == "object" and isinstance(params["properties"], dict)
        assert spec["function"]["description"], f"{fn_name} has no description"
        sig = inspect.signature(REGISTRY[fn_name]["fn"])
        assert set(params["properties"]) == set(sig.parameters), (
            fn_name, set(params["properties"]) ^ set(sig.parameters)
        )
        for required in params["required"]:
            assert sig.parameters[required].default is inspect.Parameter.empty, (fn_name, required)

    # CRI caching must not change the answer
    assert results["get_cri"]["cri_latest"] == call("get_cri", {"corridor_id": "chokepoint6"})["cri_latest"]

    print("[tools] self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        print(describe())
