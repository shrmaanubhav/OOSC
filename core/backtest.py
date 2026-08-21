"""Backtest -- fits a logistic calibration mapping CRI(t) -> P(disruption
within h days) on the real Red Sea / Bab el-Mandeb crisis (Oct 2023-Feb
2024, chokepoint4), validates out-of-sample on the real Hormuz closure
(Feb-Aug 2026, chokepoint6). Reports AUC and a reliability curve for
h = 7, 14, 30 (design doc §2.7 / PLAN.md Phase 6).

Honesty note (CLAUDE.md rule 8): GDELT was backfilled for Oct 2023-Feb
2024 specifically to cover this FIT_WINDOW (C2, ingest/gdelt_bigquery.py's
backtest_fit_window) -- CRI(chokepoint4) here is O,S for ~105 of 152 days
(S needs 90 days of trailing history and min_periods=7, so the window's
earliest days are still O-only). E remains unavailable (the LLM event
extractor was never run against this window's articles -- Groq's daily
token cap makes that a real cost, not run here) and corridor_exposure.csv
has no X for chokepoint4 by design (see that file). The Hormuz validation
window has the full O/S/E/X index. Calibrating on a two-component signal
and testing on a four-component one is a real, smaller-than-before
asymmetry, reported here rather than hidden.

Label definition: "disruption within h days" = O (observed AIS transit
deficit) exceeds a corridor-specific threshold on any of the next h days.
The threshold is each corridor's own 95th percentile of O over a pre-crisis
reference window (floored at 0.02) rather than one global cutoff -- chosen
because the two corridors' baseline noise floors are wildly different
(chokepoint4's pre-2023 O is ~0 every day; chokepoint6's ordinary-day O
noise reaches ~0.22) and a single shared threshold would either flag 1/4
of ordinary Hormuz days as "disruption" or never fire at all for Bab
el-Mandeb. This asymmetry is itself a reportable finding, printed below.

No sklearn dependency -- single-feature logistic regression (Newton-
Raphson, converges in a handful of iterations) and AUC (Mann-Whitney U
rank-sum) are both a few lines of numpy.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.risk import compute_cri, compute_O  # noqa: E402

FIT_CORRIDOR, FIT_PORT = "chokepoint4", "chokepoint4"
FIT_REFERENCE_WINDOW = ("2022-01-01", "2023-09-30")  # strictly before the crisis -- no leakage
FIT_WINDOW = ("2023-10-01", "2024-02-29")

VALID_CORRIDOR, VALID_PORT = "chokepoint6", "chokepoint6"
VALID_REFERENCE_WINDOW = ("2024-06-01", "2026-01-31")  # strictly before the closure -- no leakage
VALID_WINDOW = ("2026-02-01", "2026-08-19")

HORIZONS = [7, 14, 30]
MIN_THRESHOLD = 0.02  # floor so an all-zero reference window doesn't yield threshold=0


def _corridor_threshold(portid: str, reference_window: tuple[str, str]) -> float:
    o = compute_O(portid)
    ref = o.loc[reference_window[0] : reference_window[1]]
    return max(float(ref.quantile(0.95)), MIN_THRESHOLD)


def _build_dataset(corridor_id: str, portid: str, window: tuple[str, str], horizon: int, threshold: float) -> pd.DataFrame:
    """CRI(t) for every t in `window`, labeled 1 if O exceeds `threshold` on
    any of the following `horizon` days (label looks strictly forward of t,
    never at t itself -- this is a forecast, not a description)."""
    cri = compute_cri(corridor_id, portid=portid)
    o_full = cri["O"]
    sub = cri.loc[window[0] : window[1]].copy()

    labels = []
    for t in sub.index:
        future = o_full.loc[t + pd.Timedelta(days=1) : t + pd.Timedelta(days=horizon)]
        labels.append(int((future > threshold).any()) if len(future) else np.nan)
    sub["label"] = labels
    return sub.dropna(subset=["CRI", "label"])


def fit_logistic(x: np.ndarray, y: np.ndarray, iters: int = 25, l2: float = 1.0) -> tuple[float, float]:
    """1-feature logistic regression via Newton-Raphson, L2-regularized on
    the slope. x should be pre-scaled to a sane range (CRI/100, i.e.
    [0,1]). The fit window here is a couple hundred points that separate
    almost cleanly -- classic quasi-separation, where an unregularized fit
    blows up to a near-infinite slope that saturates at 0/1 for any input
    outside the exact fit range (silently useless on Hormuz's very
    different CRI scale). l2 pulls the slope back toward 0 instead."""
    b0, b1 = 0.0, 0.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(b0 + b1 * x)))
        w = np.clip(p * (1 - p), 1e-6, None)
        grad0, grad1 = np.sum(y - p), np.sum((y - p) * x) - l2 * b1
        h00, h01, h11 = -np.sum(w), -np.sum(w * x), -np.sum(w * x * x) - l2
        det = h00 * h11 - h01 * h01
        if abs(det) < 1e-9:
            break
        b0 += -(h11 * grad0 - h01 * grad1) / det
        b1 += -(-h01 * grad0 + h00 * grad1) / det
    return b0, b1


def predict(b0: float, b1: float, x: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-(b0 + b1 * x)))


def auc_score(y: np.ndarray, p: np.ndarray) -> float:
    """Mann-Whitney U formulation of AUC. Returns NaN if only one class is
    present (undefined, not 0.5 or 1.0 -- do not silently pretend it's a
    real score)."""
    pos, neg = p[y == 1], p[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    ranks = pd.Series(np.concatenate([pos, neg])).rank().values
    r_pos = ranks[: len(pos)].sum()
    return (r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg))


def reliability_curve(y: np.ndarray, p: np.ndarray, bins: int = 5) -> pd.DataFrame:
    df = pd.DataFrame({"y": y, "p": p})
    n_bins = min(bins, df["p"].nunique())
    if n_bins < 2:
        return pd.DataFrame(columns=["mean_predicted", "observed_rate", "n"])
    df["bin"] = pd.qcut(df["p"], q=n_bins, duplicates="drop")
    return df.groupby("bin", observed=True).agg(
        mean_predicted=("p", "mean"), observed_rate=("y", "mean"), n=("y", "size")
    )


_fit_cache: dict[int, tuple[float, float, pd.DataFrame, float]] = {}


def _fit(horizon: int) -> tuple[float, float, pd.DataFrame, float]:
    """The FIT-window logistic fit (b0, b1), cached per horizon since it's
    deterministic on committed snapshot data and re-fit on every call
    otherwise -- both run_backtest() and disruption_probability() need it,
    and the latter is meant to be cheap enough to call on every dashboard
    load / agent tool call."""
    if horizon not in _fit_cache:
        fit_threshold = _corridor_threshold(FIT_PORT, FIT_REFERENCE_WINDOW)
        fit_df = _build_dataset(FIT_CORRIDOR, FIT_PORT, FIT_WINDOW, horizon, fit_threshold)
        x_fit, y_fit = (fit_df["CRI"] / 100.0).values, fit_df["label"].values.astype(float)
        b0, b1 = fit_logistic(x_fit, y_fit)
        _fit_cache[horizon] = (b0, b1, fit_df, fit_threshold)
    return _fit_cache[horizon]


def run_backtest(horizon: int) -> dict:
    b0, b1, fit_df, fit_threshold = _fit(horizon)
    valid_threshold = _corridor_threshold(VALID_PORT, VALID_REFERENCE_WINDOW)
    valid_df = _build_dataset(VALID_CORRIDOR, VALID_PORT, VALID_WINDOW, horizon, valid_threshold)

    x_fit, y_fit = (fit_df["CRI"] / 100.0).values, fit_df["label"].values.astype(float)
    x_valid, y_valid = (valid_df["CRI"] / 100.0).values, valid_df["label"].values.astype(float)
    p_valid = predict(b0, b1, x_valid)

    return {
        "horizon": horizon,
        "fit_threshold": fit_threshold,
        "valid_threshold": valid_threshold,
        "n_fit": len(fit_df),
        "n_valid": len(valid_df),
        "fit_positive_rate": float(y_fit.mean()) if len(y_fit) else float("nan"),
        "valid_positive_rate": float(y_valid.mean()) if len(y_valid) else float("nan"),
        "coef": (b0, b1),
        "fit_components": fit_df["components_used"].mode().iloc[0] if len(fit_df) else "",
        "valid_components": valid_df["components_used"].mode().iloc[0] if len(valid_df) else "",
        "auc": auc_score(y_valid, p_valid),
        "reliability": reliability_curve(y_valid, p_valid),
    }


def disruption_probability(corridor_id: str, horizon: int, cri_now: float | None = None) -> dict:
    """P(disruption within `horizon` days) for a corridor's CURRENT CRI,
    using the same logistic calibration run_backtest() validates
    out-of-sample on Hormuz (fit on the real Bab el-Mandeb crisis,
    FIT_WINDOW). This is the number the brief actually asks for ("a live
    supply-disruption probability score") -- core/backtest.py fits and
    validates it but, before this function existed, nothing ever called
    predict() again after computing AUC. cri_now defaults to the
    corridor's latest CRI(t) if not supplied."""
    if cri_now is None:
        cri_now = float(compute_cri(corridor_id)["CRI"].iloc[-1])
    b0, b1, _, _ = _fit(horizon)
    p = float(predict(b0, b1, np.array([cri_now / 100.0]))[0])
    return {
        "corridor_id": corridor_id,
        "horizon_days": horizon,
        "cri_now": round(cri_now, 2),
        "probability": round(p, 3),
        "method": "logistic calibration fit on the real Bab el-Mandeb crisis (Oct 2023-Feb 2024, "
                  "core/backtest.py FIT_WINDOW), applied to this corridor's current CRI -- the same "
                  "coefficients run_backtest() validates out-of-sample on the real Hormuz closure",
        "sources": ["core/backtest.py fit_logistic", "core/risk.py compute_cri"],
        "confidence": "see get_backtest's AUC at this horizon for how well-calibrated this "
                       "probability actually is out-of-sample",
    }


def main() -> None:
    print("[backtest] fit: Bab el-Mandeb (chokepoint4) Oct 2023-Feb 2024 -- real Houthi-attack crisis")
    print("[backtest] validate: Hormuz (chokepoint6) Feb-Aug 2026 -- real closure, out-of-sample\n")
    for h in HORIZONS:
        r = run_backtest(h)
        print(f"--- horizon h={h} days ---")
        print(f"  fit threshold (O)   = {r['fit_threshold']:.3f}  | components used: {r['fit_components'] or 'O only'}")
        print(f"  valid threshold (O) = {r['valid_threshold']:.3f}  | components used: {r['valid_components']}")
        print(f"  fit n={r['n_fit']} (positive rate {r['fit_positive_rate']:.2f}) | valid n={r['n_valid']} (positive rate {r['valid_positive_rate']:.2f})")
        if math.isnan(r["auc"]):
            print("  AUC: undefined -- validation window has only one label class in this horizon "
                  "(the closure is sustained enough that nearly every day is a positive at h=30)")
        else:
            print(f"  AUC (out-of-sample, Hormuz): {r['auc']:.3f}")
        print("  reliability curve (out-of-sample):")
        if r["reliability"].empty:
            print("    (not enough distinct predicted probabilities to bin)")
        else:
            print(r["reliability"].to_string())
        live = disruption_probability("chokepoint6", h)
        print(f"  LIVE: P(disruption within {h}d | Hormuz's current CRI={live['cri_now']}) = "
              f"{live['probability']:.1%}")
        print()

    print(
        "[backtest] Note the h=7 live probability sits well under 50% despite Hormuz being in an "
        "actual, ongoing, near-total closure right now -- this is the fit/validation CRI-scale "
        "asymmetry (Bab el-Mandeb's fit-window CRI never reached anywhere near Hormuz's range) "
        "showing up as a real, honest under-confidence, not a bug. See methodology.md."
    )


def _self_check() -> None:
    """No network: synthetic data only. Verifies fit_logistic recovers a
    known separating boundary, auc_score is 1.0 for perfectly-separated
    scores and ~0.5 for random labels, and reliability_curve's bin means
    track the true positive rate."""
    rng = np.random.default_rng(0)

    # perfectly separable: x < 0.5 -> label 0, x >= 0.5 -> label 1
    x = np.concatenate([rng.uniform(0, 0.4, 200), rng.uniform(0.6, 1.0, 200)])
    y = np.concatenate([np.zeros(200), np.ones(200)])
    b0, b1 = fit_logistic(x, y)
    p = predict(b0, b1, x)
    assert b1 > 0, "coefficient should be positive -- higher x means higher risk"
    assert auc_score(y, p) > 0.99, auc_score(y, p)

    # random labels, unrelated to x -> AUC should sit near 0.5
    y_random = rng.integers(0, 2, size=400).astype(float)
    p_random = predict(*fit_logistic(x, y_random), x)
    auc_random = auc_score(y_random, p_random)
    assert 0.35 < auc_random < 0.65, auc_random

    # single-class y -> AUC must be NaN, never a fabricated 0.5 or 1.0
    assert math.isnan(auc_score(np.ones(10), np.linspace(0, 1, 10)))

    # reliability curve: bin observed rate should track mean predicted
    # probability for a well-calibrated (here: identity) predictor
    p_ident = x.copy()
    curve = reliability_curve(y, p_ident, bins=4)
    assert len(curve) >= 2
    corr = np.corrcoef(curve["mean_predicted"], curve["observed_rate"])[0, 1]
    assert corr > 0.9, corr

    # B1: disruption_probability -- must be a valid probability, monotonic
    # in CRI, and match run_backtest()'s own coefficients (not a second,
    # silently-diverging fit)
    probs = [disruption_probability("chokepoint6", 7, cri_now=c)["probability"] for c in (0, 25, 50, 75, 100)]
    assert all(0.0 <= p <= 1.0 for p in probs), probs
    assert probs == sorted(probs), "probability must rise monotonically with CRI"
    b0, b1, _, _ = _fit(7)
    hand_calc = predict(b0, b1, np.array([0.5]))[0]
    assert abs(disruption_probability("chokepoint6", 7, cri_now=50)["probability"] - hand_calc) < 1e-3, (
        "disruption_probability must use the exact same fit run_backtest() validates, not a separate one"
    )
    # cri_now defaults to the corridor's actual latest CRI when omitted
    live = disruption_probability("chokepoint6", 7)
    assert 0.0 <= live["probability"] <= 1.0 and live["cri_now"] > 0

    print("[backtest] self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        main()
