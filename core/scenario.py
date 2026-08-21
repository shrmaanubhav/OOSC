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
       if Bab el-Mandeb is also degraded. This requires chokepoint4 to
       have a real normal_capacity_kbd in corridor_exposure.csv (EIA,
       9.3 mb/d pre-crisis) -- a blank capacity there makes the LP's
       corridor-capacity constraint a no-op for chokepoint4 regardless
       of severity, which is what an earlier build of this file did.
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

import math
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
CORRIDOR_EXPOSURE_CSV = Path(__file__).resolve().parent.parent / "data" / "reference" / "corridor_exposure.csv"
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


PPAC_MONTHLY_PRICE_CSV = (
    Path(__file__).resolve().parent.parent / "data" / "snapshots" / "ppac" / "india_basket_price_monthly_2025_26.csv"
)


def calibrate_price_decay() -> dict:
    """How fast does the Indian crude basket price actually revert toward
    baseline after an acute spike? PLAN.md's own price section previously
    held the peak calibrated price ($113.57/bbl) FLAT for the entire
    scenario duration -- but PPAC's own real monthly averages during this
    exact closure show it didn't stay there: April 2026 (near-peak, closest
    full month after the 11 Mar CALIBRATION_P1 spike) $114.48/bbl -> June
    2026 $83.22/bbl, ~61 days apart (Apr-15 to Jun-15 midpoints, the
    coarsest defensible proxy for two MONTHLY averages -- PPAC doesn't
    publish daily). Holding price flat for a 90-day scenario overstates the
    cumulative import-bill impact; this fits a single exponential half-life
    from the real path instead of inventing a decay rate.

    Also a real cross-validation this build didn't have before: PPAC's own
    March 2026 monthly average ($113.49/bbl) sits within 0.07% of the
    single-day CALIBRATION_P1_USD_BBL ($113.57/bbl, 11 Mar 2026) that
    calibrate_elasticity() uses -- independent confirmation the calibration
    point wasn't a one-day outlier."""
    import math

    import pandas as pd

    monthly = pd.read_csv(PPAC_MONTHLY_PRICE_CSV).set_index("month")["price_usd_bbl"]
    excess_apr = float(monthly["April"]) - CALIBRATION_P0_USD_BBL
    excess_jun = float(monthly["June"]) - CALIBRATION_P0_USD_BBL
    elapsed_days = 61  # April-15 to June-15 midpoints, both PPAC monthly averages

    k = -math.log(excess_jun / excess_apr) / elapsed_days
    half_life_days = math.log(2) / k

    march_avg = float(monthly["March"])
    cross_check_diff_pct = abs(CALIBRATION_P1_USD_BBL - march_avg) / march_avg * 100

    return {
        "value": half_life_days,
        "unit": "days (exponential half-life of price-excess-over-baseline decay)",
        "k": k,
        "method": "fit a single exponential decay from PPAC's real Apr->Jun 2026 monthly-average "
                  "price-excess-over-baseline (not invented): k = -ln(excess_jun/excess_apr)/61, "
                  "half_life = ln(2)/k",
        "sources": ["data/snapshots/ppac/india_basket_price_monthly_2025_26.csv "
                    "(PPAC Ready Reckoner Table 8.1 + Chapter Highlights narrative for June)"],
        "as_of": "2026-06-30",
        "confidence": "medium -- two monthly averages, not daily data, and elapsed_days uses "
                      "mid-month proxy dates rather than exact averaging windows",
        "cross_validation": {
            "note": "PPAC's own March 2026 monthly average vs the single-day calibration point "
                    "calibrate_elasticity() uses -- independent confirmation, not re-derived from it",
            "ppac_march_avg_usd_bbl": march_avg,
            "calibration_p1_usd_bbl": CALIBRATION_P1_USD_BBL,
            "diff_pct": cross_check_diff_pct,
        },
    }


def _decayed_avg_excess(excess0: float, duration_days: float, half_life_days: float) -> float:
    """Time-averaged price-excess-over-baseline over [0, duration_days] for
    exponential decay excess(t) = excess0 * exp(-k*t), continuous-integral
    average = excess0 * (1 - exp(-k*T)) / (k*T). Reduces to excess0 (the
    flat/instantaneous model) as T -> 0, and correctly discounts a longer
    horizon toward the real observed reversion rather than assuming the
    peak price holds for the whole scenario."""
    import math

    if duration_days <= 0 or half_life_days <= 0:
        return excess0
    k = math.log(2) / half_life_days
    kt = k * duration_days
    return excess0 * (1 - math.exp(-kt)) / kt


def _normal_flow_mbd(corridor_id: str) -> float:
    """A corridor's normal oil-transit flow in mb/d, from corridor_exposure.csv
    (kbd -> mbd). 0.0 (not a crash) for a corridor with no sourced capacity --
    matches core/procurement.py's own missing-capacity convention, and means
    an unsourced corridor's severity silently contributes no price impact
    rather than blowing up the calibration."""
    import pandas as pd

    exposure = pd.read_csv(CORRIDOR_EXPOSURE_CSV)
    row = exposure[exposure["corridor_id"] == corridor_id]
    if row.empty or pd.isna(row.iloc[0]["normal_capacity_kbd"]):
        return 0.0
    return float(row.iloc[0]["normal_capacity_kbd"]) / 1000.0


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
    # actual FY2025-26 processing throughput (PPAC Table 4.1), not nameplate
    # capacity -- matches the demand column core/procurement.py's LP itself
    # now solves against, so refinery_impact's run-cut denominator is
    # consistent with the shortfall the LP actually produced
    demand_col = "processing_kbd_2025_26" if "processing_kbd_2025_26" in refineries.columns else "capacity_kbd"
    demand_by_refinery = dict(zip(refineries["name"], refineries[demand_col]))

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
    # Summed across every shocked corridor (not just chokepoint6) -- a
    # compound shock (e.g. Hormuz + Bab el-Mandeb via other_severity) must
    # move price by more than a single-corridor shock of the same severity,
    # or the "Yanbu doesn't buy safety" coupling insight would be invisible
    # in the one number a reader actually looks at.
    dq_over_q = sum(_normal_flow_mbd(c) * s for c, s in severity_map.items()) / GLOBAL_LIQUIDS_MBD
    dp_over_p = dq_over_q / eps if eps else 0.0
    price_usd_bbl = CALIBRATION_P0_USD_BBL * (1 + dp_over_p)

    delta_p = price_usd_bbl - CALIBRATION_P0_USD_BBL
    # INDIA_IMPORTS_MBD is millions of bbl/day -> *1e6 for bbl/day, *days for
    # total barrels, *$/bbl for USD. (A prior version used *1000, which only
    # converts mbd->kbd and silently understated every downstream USD figure
    # by 1000x -- caught by comparing against a hand-computed sanity check.)
    import_bill_delta_annual_usd = INDIA_IMPORTS_MBD * 1e6 * 365 * delta_p

    # Over-the-scenario-duration figure uses the REAL observed decay path
    # (calibrate_price_decay(), fit on PPAC's actual Apr->Jun 2026 monthly
    # averages during this exact closure) instead of holding the peak price
    # flat for the whole horizon -- flat-peak overstates any multi-month
    # scenario's cost, since the real market re-priced within ~6 weeks.
    # import_bill_delta_annual_usd above deliberately keeps the flat/
    # instantaneous convention (it's an extrapolation metric, not a
    # duration-specific one) so it's unaffected by this and needs no
    # self-check changes.
    price_decay = calibrate_price_decay()
    decayed_avg_excess = _decayed_avg_excess(delta_p, duration_days, price_decay["value"])
    import_bill_delta_scenario_usd = INDIA_IMPORTS_MBD * 1e6 * duration_days * decayed_avg_excess
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
            "unit": "fraction of actual FY2025-26 processing throughput cut (0-1)",
            "method": f"shortfall_j/demand_j, capped at {MAX_RUN_CUT} (refineries don't stably run "
                      "below ~60% of capacity)",
            "sources": ["core/procurement.py shortfall",
                        "data/reference/refineries.csv processing_kbd_2025_26 (PPAC Ready Reckoner "
                        "Table 4.1 actual crude-oil-processing throughput, not nameplate capacity)"],
            "as_of": str(as_of), "confidence": "medium-high (demand_j is PPAC's own actual FY2025-26 "
                                                "processing figure, not a nameplate-capacity proxy)",
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
            "method": "ΔQ_global = Sum over every shocked corridor of (its normal_capacity_kbd/1000 * "
                      "severity); ΔP/P = (ΔQ_global/Q_global)/|eps|, eps calibrated on the real "
                      "Feb-Mar 2026 event",
            "sources": ["design doc §2.4 calibration inputs"],
            "as_of": str(as_of), "confidence": calibration["confidence"],
            "calibration": calibration,
            "decay": price_decay,
        },
        "macro": {
            "value": {
                "import_bill_delta_annualized_usd": import_bill_delta_annual_usd,
                "import_bill_delta_over_scenario_usd": import_bill_delta_scenario_usd,
                "pct_of_gdp": pct_gdp,
                "cpi_impact_pct": cpi_impact_pct,
            },
            "unit": "USD, fraction of GDP, CPI percentage points",
            "method": "import_bill_delta_annualized = imports_mbd*1e6*365*ΔP_usd_bbl (flat/instantaneous "
                      "extrapolation, unchanged convention); import_bill_delta_over_scenario = "
                      "imports_mbd*1e6*days*decayed_avg_ΔP, where decayed_avg_ΔP integrates the real "
                      f"observed price-reversion half-life ({price_decay['value']:.0f} days, see price."
                      "decay) over the scenario horizon instead of holding the peak price flat -- a "
                      "flat-peak assumption overstates any multi-month scenario's cost, since the real "
                      "Feb-Aug 2026 closure's price actually decayed from its Apr peak by June; "
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
            "as_of": str(as_of), "confidence": "low-medium (GDP/CPI figures are real, and the "
                                                "over-scenario figure now uses a real observed decay "
                                                "path instead of a flat-peak assumption; the "
                                                "1:1 CPI pass-through assumption is still not sourced)",
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
    diff_pct = result["price"]["decay"]["cross_validation"]["diff_pct"]
    print(f"  Price: ${result['price']['value']:.2f}/bbl (calibrated eps={result['price']['calibration']['value']:.3f}) "
          f"-- cross-checks {diff_pct:.2f}% against PPAC's own March 2026 monthly average")
    macro = result["macro"]["value"]
    print(f"  Import bill delta (annualized, flat): ${macro['import_bill_delta_annualized_usd']/1e9:.1f}B "
          f"({macro['pct_of_gdp']*100:.2f}% of GDP)")
    print(f"  Import bill delta (over {result['scenario']['duration_days']}d, real decay half-life="
          f"{result['price']['decay']['value']:.0f}d): ${macro['import_bill_delta_over_scenario_usd']/1e9:.1f}B")
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
    print(f"  price: ${compound['price']['value']:.2f}/bbl "
          f"(vs ${result['price']['value']:.2f}/bbl with chokepoint4 unaffected -- "
          "the second corridor now visibly adds to the price impact)")
    # 0.6 severity above still leaves chokepoint4 with 9300*(1-0.6)=3720 kbd
    # of capacity, more than the Yanbu route's 1500 kbd demand -- it doesn't
    # visibly bind yet. Using severity=1.0 here (matching --self-check) to
    # actually show the bypass saturate to zero, which 0.6 alone would not.
    hormuz_only_alloc = procurement.solve(severity={"chokepoint6": 1.0}, mu_concentration=1.0)
    both_alloc = procurement.solve(severity={"chokepoint6": 1.0, "chokepoint4": 1.0}, mu_concentration=1.0)
    yanbu = lambda r: r["allocation"][r["allocation"]["corridor_id"] == "chokepoint4"]["kbd"].sum()
    print(f"  Yanbu-route (Arab Light via Yanbu) allocation at chokepoint4 severity=1.0: "
          f"{yanbu(hormuz_only_alloc):.0f} kbd unaffected -> {yanbu(both_alloc):.0f} kbd once "
          "chokepoint4 is also fully closed -- the bypass stops being usable, which is the "
          "coupling insight this scenario exists to demonstrate.")


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

    # A1: the Yanbu bypass ("Arab Light (via Yanbu)", corridor_transited=
    # chokepoint4) must actually lose its allocation when chokepoint4 is
    # shocked too -- if corridor_exposure.csv's chokepoint4 capacity is
    # ever left blank again, core/procurement.py's corridor constraint
    # silently becomes a no-op and this is the only thing that catches it.
    hormuz_only = procurement.solve(severity={"chokepoint6": 1.0}, mu_concentration=1.0)
    both_closed = procurement.solve(severity={"chokepoint6": 1.0, "chokepoint4": 1.0}, mu_concentration=1.0)
    yanbu_alloc = lambda r: r["allocation"][r["allocation"]["corridor_id"] == "chokepoint4"]["kbd"].sum()
    assert yanbu_alloc(hormuz_only) > 0, "Yanbu route should carry flow when chokepoint4 is unaffected"
    assert yanbu_alloc(both_closed) < 1e-6, (
        "Yanbu route still allocated kbd with chokepoint4 severity=1.0 -- the coupling constraint "
        "isn't binding (check corridor_exposure.csv's chokepoint4 normal_capacity_kbd isn't blank)"
    )

    # A2: price impact must account for EVERY shocked corridor, not just
    # the first positional one -- a second corridor passed via
    # other_severity used to be silently dropped from the price calc.
    cp4_only = run_scenario("chokepoint6", 0.0, 90, other_severity={"chokepoint4": 1.0})
    assert cp4_only["price"]["value"] > CALIBRATION_P0_USD_BBL, (
        "shocking chokepoint4 alone (via other_severity) had no price impact"
    )
    compound = run_scenario("chokepoint6", 1.0, 90, other_severity={"chokepoint4": 1.0})
    assert compound["price"]["value"] > result_full["price"]["value"], (
        "compound two-corridor shock did not raise price above the single-corridor shock"
    )

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

    # C1: price decay -- half-life must be positive/finite, and the March
    # PPAC monthly average must cross-validate calibrate_elasticity()'s
    # single-day calibration point to within a couple of percent (this is
    # an independent real-data check, not a re-derivation -- if it drifts
    # far apart something is wrong with one of the two sources)
    decay = calibrate_price_decay()
    assert decay["value"] > 0 and math.isfinite(decay["value"]), decay["value"]
    assert decay["cross_validation"]["diff_pct"] < 2.0, decay["cross_validation"]

    # _decayed_avg_excess must reduce to the flat/instantaneous model as
    # duration -> 0, and must be strictly less than the flat model for a
    # duration much longer than the half-life (that's the whole point --
    # holding the peak price flat for 90 days overstates a shock whose
    # real observed half-life is ~6 weeks)
    excess0 = 48.57
    assert abs(_decayed_avg_excess(excess0, 0.001, decay["value"]) - excess0) < 1e-2
    long_run_avg = _decayed_avg_excess(excess0, 365, decay["value"])
    assert 0 < long_run_avg < excess0, long_run_avg

    # end-to-end: the scenario-duration import bill must be LESS than what
    # the old flat-price model would have produced for a 90-day horizon
    # (proves the decay model is actually wired into run_scenario's output,
    # not just computed and discarded)
    flat_90d_usd = INDIA_IMPORTS_MBD * 1e6 * 90 * (result_full["price"]["value"] - CALIBRATION_P0_USD_BBL)
    assert result_full["macro"]["value"]["import_bill_delta_over_scenario_usd"] < flat_90d_usd, (
        result_full["macro"]["value"]["import_bill_delta_over_scenario_usd"], flat_90d_usd
    )
    assert result_full["macro"]["value"]["import_bill_delta_over_scenario_usd"] > 0

    print("[scenario] self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        main()
