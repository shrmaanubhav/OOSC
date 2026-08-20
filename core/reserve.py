"""Reserve Optimiser -- multi-period SPR drawdown LP (design doc §2.6).

Deliberately thin per project scope: correct shape and constraints, no
UI polish, no refill logic (this build only models a sustained-closure
drawdown scenario, not a full replenishment cycle -- refill would need
a CRI-forecast and price-ceiling input this build doesn't have wired up
yet). Only the three OPERATIONAL SPR sites from spr.csv are modeled
(Visakhapatnam, Mangaluru, Padur -- "Phase 1" in spr.csv); the "Phase 2"
sites (Chandikhol, Padur-II, Mangaluru-II, Bina/Bikaner) are proposed/
under-construction, not fillable reserve capacity today.

    minimise  Sum_t [ unserved_t * VOLL + alpha * draw_t ] - beta * stock_T
    s.t.  stock_{t+1} = stock_t - draw_t                (no refill, see above)
          draw_t <= max_pumpout_rate_kbd
          stock_t >= 0
          unserved_t >= daily_gap_kbd - draw_t
          unserved_t >= 0

Two modeling choices worth being explicit about:
  - Reserve sites are aggregated into one national pool, not modeled
    per-site with individual pumpout rates (no primary source for
    site-level pumpout physical limits) -- "thin" per scope.
  - max_pumpout_rate_kbd defaults to total_capacity / 9.5 days. This is
    not an independently-sourced physical pumpout rate; it's set so
    that a full-rate, uninterrupted drawdown reproduces the design doc's
    own authoritative "9.5 days of cover" figure by construction, rather
    than letting this module's own MMT->barrel conversion produce a
    silently different headline number than the one already cited
    elsewhere in this build.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pulp

REF_DIR = Path(__file__).resolve().parent.parent / "data" / "reference"
MMT_TO_BBL = 7.33e6  # standard industry conversion, ~7.33 bbl/tonne average crude density
DESIGN_DOC_DAYS_OF_COVER = 9.5  # design doc appendix: 5.33 MMT / ~9.5 days at full national demand
VOLL = 1e6  # value of lost load -- must dominate any real drawdown-cost term
ALPHA_DRAWDOWN_COST = 1.0  # small preference for not drawing when unnecessary
BETA_TERMINAL_VALUE = 2.0  # small preference for preserving reserve at the horizon


def _operational_capacity_bbl() -> float:
    spr = pd.read_csv(REF_DIR / "spr.csv")
    operational = spr[spr["phase"] == "Phase 1"]
    return operational["capacity_mmt"].sum() * MMT_TO_BBL


def run_reserve(
    daily_gap_kbd: float,
    duration_days: int,
    max_pumpout_rate_kbd: float | None = None,
) -> dict:
    """daily_gap_kbd: the supply shortfall the reserve is being asked to
    cover each day (e.g. from core/scenario.py's procurement shortfall).
    Constant across the horizon -- this build doesn't model a shortfall
    that varies day to day within one scenario call."""
    capacity_bbl = _operational_capacity_bbl()
    capacity_kbd_equivalent = capacity_bbl / 1000  # thousand barrels, for kbd-unit consistency
    if max_pumpout_rate_kbd is None:
        max_pumpout_rate_kbd = capacity_kbd_equivalent / DESIGN_DOC_DAYS_OF_COVER

    prob = pulp.LpProblem("reserve_drawdown", pulp.LpMinimize)
    T = duration_days
    stock = [pulp.LpVariable(f"stock_{t}", lowBound=0) for t in range(T + 1)]
    draw = [pulp.LpVariable(f"draw_{t}", lowBound=0, upBound=max_pumpout_rate_kbd) for t in range(T)]
    unserved = [pulp.LpVariable(f"unserved_{t}", lowBound=0) for t in range(T)]

    # Tie-breaker: weight unserved_t slightly higher in earlier periods.
    # Without this the LP is genuinely degenerate here -- total unserved
    # over the horizon is invariant to WHEN draws happen (bounded by fixed
    # total capacity), so CBC can return any of many equally-optimal but
    # erratic draw orderings. Serving today's demand before tomorrow's is
    # the economically sensible tie-break absent an explicit refill/hedge
    # signal (deliberately out of scope, see module docstring).
    urgency = {t: 1.0 + 1e-3 * (T - t) for t in range(T)}
    prob += (
        pulp.lpSum(unserved[t] * VOLL * urgency[t] + draw[t] * ALPHA_DRAWDOWN_COST for t in range(T))
        - stock[T] * BETA_TERMINAL_VALUE
    )

    prob += stock[0] == capacity_kbd_equivalent, "initial_stock"
    for t in range(T):
        prob += stock[t + 1] == stock[t] - draw[t], f"balance_{t}"
        prob += unserved[t] >= daily_gap_kbd - draw[t], f"unserved_{t}"

    prob.solve(pulp.PULP_CBC_CMD(msg=0))

    schedule = pd.DataFrame(
        {
            "day": range(T),
            "stock_kbd_equiv": [stock[t].value() for t in range(T)],
            "draw_kbd": [draw[t].value() for t in range(T)],
            "unserved_kbd": [unserved[t].value() for t in range(T)],
        }
    )
    schedule["days_of_cover_remaining"] = schedule["stock_kbd_equiv"] / max_pumpout_rate_kbd

    exhausted_at = schedule[schedule["stock_kbd_equiv"] < 1e-3]["day"]
    days_to_exhaustion = int(exhausted_at.iloc[0]) if not exhausted_at.empty else None

    return {
        "status": pulp.LpStatus[prob.status],
        "capacity_bbl": capacity_bbl,
        "capacity_kbd_equivalent": capacity_kbd_equivalent,
        "max_pumpout_rate_kbd": max_pumpout_rate_kbd,
        "schedule": schedule,
        "days_to_exhaustion": days_to_exhaustion,
        "total_unserved_kbd_days": schedule["unserved_kbd"].sum(),
    }


def main() -> None:
    print("[reserve] 90-day drawdown, daily_gap=500 kbd (matches core/scenario.py's "
          "Hormuz-closed + sanctions-compliance shortfall)...")
    result = run_reserve(daily_gap_kbd=500, duration_days=90)
    print(f"  capacity: {result['capacity_bbl']/1e6:.1f}M bbl "
          f"({result['capacity_kbd_equivalent']:.0f} kbd-equivalent)")
    print(f"  max pumpout rate: {result['max_pumpout_rate_kbd']:.0f} kbd "
          f"(sized so full-rate drawdown = design doc's {DESIGN_DOC_DAYS_OF_COVER} days)")
    if result["days_to_exhaustion"] is not None:
        print(f"  reserve EXHAUSTED at day {result['days_to_exhaustion']}")
    else:
        print("  reserve NOT exhausted within the 90-day horizon")
    print(f"  total unserved: {result['total_unserved_kbd_days']:.0f} kbd-days")
    print("\n  first 12 days:")
    print(result["schedule"].head(12).to_string(index=False))

    print("\n[reserve] under a harder 90-day dual-corridor-closure daily gap (2000 kbd)...")
    hard = run_reserve(daily_gap_kbd=2000, duration_days=90)
    print(f"  days to exhaustion: {hard['days_to_exhaustion']}")


def _self_check() -> None:
    """No network. Verifies the LP reproduces the design doc's 9.5-day
    cover figure by construction, and that a small gap never exhausts
    the reserve within the horizon."""
    import tempfile

    global REF_DIR
    original = REF_DIR
    tmp = Path(tempfile.mkdtemp())
    pd.DataFrame(
        {"site": ["A", "B"], "capacity_mmt": [1.0, 1.0], "phase": ["Phase 1", "Phase 1"]}
    ).to_csv(tmp / "spr.csv", index=False)
    REF_DIR = tmp
    try:
        cap_bbl = _operational_capacity_bbl()
        assert abs(cap_bbl - 2 * MMT_TO_BBL) < 1.0

        # daily_gap == max_pumpout_rate -> reserve should hit exactly zero
        # right at day 9.5 (rounds to day 9 or 10 given integer day steps),
        # not earlier or later
        result = run_reserve(daily_gap_kbd=cap_bbl / 1000 / DESIGN_DOC_DAYS_OF_COVER, duration_days=20)
        assert result["days_to_exhaustion"] is not None
        assert 9 <= result["days_to_exhaustion"] <= 10, result["days_to_exhaustion"]

        # a gap far below the pumpout rate should never exhaust the reserve
        # within a short horizon
        tiny = run_reserve(daily_gap_kbd=1.0, duration_days=30)
        assert tiny["days_to_exhaustion"] is None
        assert tiny["total_unserved_kbd_days"] < 1e-3
    finally:
        REF_DIR = original

    print("[reserve] self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        main()
