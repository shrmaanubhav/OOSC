"""Scenario Cascade Engine (design doc §2.4).

    1. BLOCKED VOLUME + 2. REROUTE FEASIBILITY
       -> handed entirely to core/procurement.py's LP. Its shortfall_j
       slack variable IS the "could this be rerouted/substituted" check:
       the LP already tries every compatible source, respects corridor
       capacity, and only reports a refinery shortfall when nothing else
       could cover it. The Yanbu bypass's recursive discharge-corridor
       risk is modeled structurally, not as a separate lookup: "Arab
       Light (via Yanbu)" is tagged corridor_transited=chokepoint4 in
       sources.csv (not chokepoint6), so passing severity for BOTH
       corridors in one call demonstrates the coupling the design doc
       calls its best insight -- routing via Yanbu doesn't buy safety
       if Bab el-Mandeb is also degraded.
    3. REFINERY IMPACT -- run_cut_pct = shortfall_j / demand_j, capped at
       MAX_RUN_CUT (refineries don't run below ~60-70% of nameplate).
    4. PRODUCT SHORTFALL -- run_cut x national yield mix (PPAC Ready
       Reckoner Table 4.5, FY2025-26 -- a single national-average vector
       applied to every refinery; this build has no refinery-specific
       yield data).
    5. PRICE -- calibrated on the real Feb-Mar 2026 event, not invented.
       See calibrate_elasticity().
    6. MACRO -- import bill delta, %GDP, CPI impact. GDP and CPI weight
       are real MoSPI figures (see constants below); pass-through
       assumed 1:1 crude-to-CPI-fuel-subindex, which is a real
       simplification -- India's fuel excise duty is actively adjusted
       to cushion retail prices, which this model does not capture.

Every returned field is {value, unit, method, sources, as_of, confidence}
-- never a bare number. That's non-negotiable per the design doc, and
it's what agent/provenance.py (Phase 6) will check outputs against.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import procurement  # noqa: E402

MAX_RUN_CUT = 0.40  # refineries don't stably run below ~60% of nameplate capacity

# PPAC Ready Reckoner FY2025-26, Table 4.5 "Production of Petroleum
# Products: All sources", percentage column for 2025-26 (parsed 2026-08-20,
# see data/snapshots/ppac/ -- this specific table wasn't re-extracted to a
# CSV since only Table 4.1 was needed for Phase 4; the percentages below
# are transcribed from the same PDF page already fetched for that phase).
NATIONAL_YIELD_MIX = {
    "HSD": 0.424, "MS": 0.175, "Naphtha": 0.064, "ATF": 0.058, "LPG": 0.046,
    "SKO": 0.004, "Bitumen": 0.019, "FO/LSHS": 0.036, "Lubes": 0.005,
    "LDO": 0.002, "RPC/Petcoke": 0.052, "Others": 0.115,
}

# Design doc §2.4 calibration instructions, given directly as known
# reference points (not independently re-derived here):
#   ΔQ: Hormuz normal flow ~20 mb/d, global liquids consumption ~103 mb/d
#   ΔP: Indian crude basket $65/bbl (pre-crisis) -> $113.57/bbl (11 Mar 2026)
#   Real-world severity at that date: near-total closure (transits <10%
#   of baseline by 8 Mar per the Phase 1 PortWatch data) -> severity~1.0
HORMUZ_NORMAL_FLOW_MBD = 20.0
GLOBAL_LIQUIDS_MBD = 103.0
CALIBRATION_P0_USD_BBL = 65.0
CALIBRATION_P1_USD_BBL = 113.57
CALIBRATION_SEVERITY = 1.0

# MoSPI Provisional Estimates (released ~June 2026): nominal GDP FY2025-26
# = Rs 346.36 lakh crore (~$3.91 trillion). Verified live 2026-08-20.
INDIA_GDP_USD = 3.91e12
# CPI-Combined "Fuel & Light" group weight, 2012-base series = 6.84%.
# A NEW CPI series (2024 base year) launched 12 Feb 2026 -- its fuel
# weight was not found in this build's research and may differ; flagged
# explicitly rather than silently assumed unchanged.
CPI_FUEL_LIGHT_WEIGHT = 0.0684

INDIA_IMPORTS_MBD = 5.0  # design doc appendix, Kpler, Jul 2026


def calibrate_elasticity() -> dict:
    """Solve |eps| from ΔP/P = (ΔQ/Q) / |eps| using the real Feb-Mar 2026
    data point. Reported, not hidden -- including how it compares to
    published short-run oil demand elasticity literature (typically
    0.02-0.1; a higher implied value here suggests the 11 Mar price also
    carried a speculative/panic premium beyond physical scarcity, not
    pure elasticity)."""
    dq_over_q = (HORMUZ_NORMAL_FLOW_MBD * CALIBRATION_SEVERITY) / GLOBAL_LIQUIDS_MBD
    dp_over_p = (CALIBRATION_P1_USD_BBL - CALIBRATION_P0_USD_BBL) / CALIBRATION_P0_USD_BBL
    eps = dq_over_q / dp_over_p
    return {
        "value": eps,
        "unit": "dimensionless (short-run demand elasticity magnitude)",
        "method": "|eps| = (ΔQ_global/Q_global) / (ΔP/P), calibrated on the real Feb-Mar 2026 "
                  "Hormuz closure -- not an invented/textbook elasticity",
        "sources": ["design doc §2.4 calibration inputs", "PPAC Indian Basket price series"],
        "as_of": "2026-03-11",
        "confidence": "medium -- single calibration point, not cross-validated against the "
                       "Nov 2023 Red Sea event (no historical Brent/Indian-basket price series "
                       "ingested for that window in this build; flagged as a gap, not silently "
                       "skipped). Published short-run oil demand elasticity is typically 0.02-0.1; "
                       f"the calibrated {eps:.3f} sitting above that range suggests the real 11 Mar "
                       "spike included a speculative premium this simple model attributes entirely "
                       "to elasticity.",
        "dq_over_q": dq_over_q,
        "dp_over_p": dp_over_p,
    }


def run_scenario(
    corridor_id: str,
    severity: float,
    duration_days: int,
    other_severity: dict[str, float] | None = None,
    compliance_mode: bool = False,
    as_of: date | None = None,
) -> dict:
    """other_severity lets a caller shock a second corridor in the same
    call (e.g. {"chokepoint4": 0.6}) to demonstrate the bypass-coupling
    insight -- routing around chokepoint6 via Yanbu doesn't help if
    chokepoint4 is degraded too."""
    as_of = as_of or date.today()
    severity_map = {corridor_id: severity, **(other_severity or {})}

    proc = procurement.solve(severity=severity_map, compliance_mode=compliance_mode, mu_concentration=1.0)

    import pandas as pd
    refineries = pd.read_csv(procurement.REF_DIR / "refineries.csv")
    demand_by_refinery = dict(zip(refineries["name"], refineries["capacity_kbd"]))

    run_cuts = {}
    for name, demand in demand_by_refinery.items():
        shortfall = proc["shortfall_by_refinery"].get(name, 0.0)
        run_cut = min(shortfall / demand, MAX_RUN_CUT) if demand else 0.0
        run_cuts[name] = run_cut

    avg_run_cut = (
        sum(run_cuts[n] * demand_by_refinery[n] for n in run_cuts) / sum(demand_by_refinery.values())
    )

    product_shortfall_kbd = {
        product: avg_run_cut * frac * sum(demand_by_refinery.values())
        for product, frac in NATIONAL_YIELD_MIX.items()
    }

    calibration = calibrate_elasticity()
    eps = calibration["value"]
    dq_over_q = (HORMUZ_NORMAL_FLOW_MBD * severity) / GLOBAL_LIQUIDS_MBD if corridor_id == "chokepoint6" else 0.0
    dp_over_p = dq_over_q / eps if eps else 0.0
    price_usd_bbl = CALIBRATION_P0_USD_BBL * (1 + dp_over_p)

    delta_p = price_usd_bbl - CALIBRATION_P0_USD_BBL
    # INDIA_IMPORTS_MBD is millions of bbl/day -> *1e6 for bbl/day, *days for
    # total barrels, *$/bbl for USD. (A prior version used *1000, which only
    # converts mbd->kbd and silently understated every downstream USD figure
    # by 1000x -- caught by comparing against a hand-computed sanity check.)
    import_bill_delta_annual_usd = INDIA_IMPORTS_MBD * 1e6 * 365 * delta_p
    import_bill_delta_scenario_usd = INDIA_IMPORTS_MBD * 1e6 * duration_days * delta_p
    pct_gdp = import_bill_delta_annual_usd / INDIA_GDP_USD
    cpi_impact_pct = dp_over_p * CPI_FUEL_LIGHT_WEIGHT

    return {
        "scenario": {"corridor_id": corridor_id, "severity": severity, "duration_days": duration_days,
                     "other_severity": other_severity, "compliance_mode": compliance_mode},
        "procurement": {
            "value": proc["allocation"],
            "unit": "kbd allocation table (source x refinery)",
            "method": "procurement LP shortfall slack under shocked corridor capacity -- the LP's "
                      "own reallocation IS the reroute-feasibility check",
            "sources": ["core/procurement.py"],
            "as_of": str(as_of), "confidence": "high (deterministic LP solve)",
            "total_shortfall_kbd": proc["total_shortfall_kbd"],
        },
        "refinery_impact": {
            "value": run_cuts,
            "unit": "fraction of nameplate capacity cut (0-1)",
            "method": f"shortfall_j/demand_j, capped at {MAX_RUN_CUT} (refineries don't stably run "
                      "below ~60% of capacity)",
            "sources": ["core/procurement.py shortfall", "data/reference/refineries.csv capacity_kbd"],
            "as_of": str(as_of), "confidence": "medium (capacity used as demand proxy, see module docstring)",
        },
        "product_shortfall": {
            "value": product_shortfall_kbd,
            "unit": "kbd shortfall per product",
            "method": "avg_run_cut x national yield-mix fraction x total refinery capacity",
            "sources": ["PPAC Ready Reckoner FY2025-26 Table 4.5"],
            "as_of": "2026-08-20", "confidence": "low (single national-average yield vector, not per-refinery)",
        },
        "price": {
            "value": price_usd_bbl,
            "unit": "USD/bbl (Indian crude basket)",
            "method": "ΔP/P = (ΔQ_global/Q_global)/|eps|, eps calibrated on the real Feb-Mar 2026 event",
            "sources": ["design doc §2.4 calibration inputs"],
            "as_of": str(as_of), "confidence": calibration["confidence"],
            "calibration": calibration,
        },
        "macro": {
            "value": {
                "import_bill_delta_annualized_usd": import_bill_delta_annual_usd,
                "import_bill_delta_over_scenario_usd": import_bill_delta_scenario_usd,
                "pct_of_gdp": pct_gdp,
                "cpi_impact_pct": cpi_impact_pct,
            },
            "unit": "USD, fraction of GDP, CPI percentage points",
            "method": "import_bill_delta = imports_mbd*1e6*days*ΔP_usd_bbl; "
                      "pct_gdp = annualized_delta/GDP; "
                      "cpi_impact = ΔP/P * CPI fuel&light weight (assumes 1:1 pass-through, which "
                      "is a real simplification -- India actively adjusts fuel excise duty to "
                      "cushion retail prices, not modeled here)",
            "sources": [
                "design doc appendix (India imports ~5.0 mb/d, Jul 2026, Kpler)",
                "MoSPI Provisional Estimates ~Jun 2026 (nominal GDP FY2025-26 = Rs 346.36 lakh crore / $3.91T)",
                "MoSPI CPI-Combined 2012-base series (Fuel & Light weight 6.84%) -- a new 2024-base "
                "series launched 12 Feb 2026 with a weight not confirmed in this build's research",
            ],
            "as_of": str(as_of), "confidence": "low (GDP/CPI figures are real; the pass-through "
                                                "assumption and demand-as-capacity proxy are not)",
        },
    }


def _print_result(result: dict) -> None:
    print(f"  Procurement: {result['procurement']['total_shortfall_kbd']:.0f} kbd shortfall")
    cuts = [v for v in result["refinery_impact"]["value"].values() if v > 0]
    print(f"  Refineries with a run cut: {len(cuts)} (avg cut where >0: "
          f"{sum(cuts)/len(cuts):.1%})" if cuts else "  Refineries with a run cut: 0")
    if any(v > 0 for v in result["product_shortfall"]["value"].values()):
        print("  Product shortfall (top 3):")
        for product, kbd in sorted(result["product_shortfall"]["value"].items(), key=lambda kv: -kv[1])[:3]:
            print(f"    {product}: {kbd:.0f} kbd")
    print(f"  Price: ${result['price']['value']:.2f}/bbl (calibrated eps={result['price']['calibration']['value']:.3f})")
    macro = result["macro"]["value"]
    print(f"  Import bill delta (annualized): ${macro['import_bill_delta_annualized_usd']/1e9:.1f}B "
          f"({macro['pct_of_gdp']*100:.2f}% of GDP)")
    print(f"  CPI impact: {macro['cpi_impact_pct']*100:.2f} pp")


def main() -> None:
    print("[scenario] run_scenario('chokepoint6', 1.0, 90) -- full Hormuz closure, 90 days...")
    result = run_scenario("chokepoint6", 1.0, 90)
    _print_result(result)
    print(
        "  (0 shortfall here is a real finding, not a bug -- see core/procurement.py's own "
        "demo output for why, and the harder shortfall-triggering scenario below.)"
    )

    print("\n[scenario] same shock + sanctions compliance mode (no Russia/Venezuela substitution)...")
    hard = run_scenario("chokepoint6", 1.0, 90, compliance_mode=True)
    _print_result(hard)

    print("\n[scenario] compound: chokepoint6 severity=1.0 AND chokepoint4 severity=0.6 "
          "(the Yanbu-bypass-isn't-safe demo)...")
    compound = run_scenario("chokepoint6", 1.0, 90, other_severity={"chokepoint4": 0.6})
    print(f"  shortfall: {compound['procurement']['total_shortfall_kbd']:.0f} kbd "
          f"(vs {result['procurement']['total_shortfall_kbd']:.0f} kbd with chokepoint4 unaffected)")


def _self_check() -> None:
    """No network beyond searoute's bundled offline data."""
    calib = calibrate_elasticity()
    assert calib["value"] > 0
    assert abs(calib["dp_over_p"] - (113.57 - 65) / 65) < 1e-6

    result = run_scenario("chokepoint6", 0.0, 30)  # zero severity -> no shock
    assert result["procurement"]["total_shortfall_kbd"] < 1e-3
    assert abs(result["price"]["value"] - CALIBRATION_P0_USD_BBL) < 1e-6  # no ΔQ -> no ΔP

    result_full = run_scenario("chokepoint6", 1.0, 90)
    assert result_full["price"]["value"] > CALIBRATION_P0_USD_BBL  # severity -> price rises

    # magnitude sanity check on the macro USD figures -- catches unit-
    # conversion bugs (a prior version was off by exactly 1000x here: it
    # multiplied mbd by 1000 to get kbd and then never re-scaled to bbl,
    # so every downstream USD figure was silently 1000x too small)
    hand_calc_annual_usd = INDIA_IMPORTS_MBD * 1e6 * 365 * (result_full["price"]["value"] - CALIBRATION_P0_USD_BBL)
    macro = result_full["macro"]["value"]
    assert abs(macro["import_bill_delta_annualized_usd"] - hand_calc_annual_usd) < 1.0
    # a near-total closure of a corridor carrying ~41% of India's crude
    # imports should move the annualized import bill by tens of billions
    # of dollars, not millions -- if this fails, a unit conversion broke
    assert macro["import_bill_delta_annualized_usd"] > 1e9, macro["import_bill_delta_annualized_usd"]

    for section in ("procurement", "refinery_impact", "product_shortfall", "price", "macro"):
        for key in ("value", "unit", "method", "sources", "as_of", "confidence"):
            assert key in result_full[section], f"{section} missing {key}"

    print("[scenario] self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        main()
