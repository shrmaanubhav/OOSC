"""FastAPI backend (design doc §3.3, PLAN.md Phase 7).

Serves the frontend everything it needs, reading only from committed
snapshots + reference CSVs -- no outbound network calls at request time
(CLAUDE.md rule 3, and Phase 8's airplane-mode exit criterion). The one
exception is POST /api/ask, which calls the configured LLM provider; the
whole rest of the dashboard works with the network unplugged.

Two deliberately distinct paths to the same core/ modules:
  - these REST endpoints return FULL-fidelity series for charts, and never
    involve the model at all;
  - agent/tools.py returns compact summaries for the model's context.
Same computation underneath, different shape for a different consumer.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent import llm, loop  # noqa: E402
from agent import tools as agent_tools  # noqa: E402
from core import backtest, procurement, reserve, risk, scenario, twin  # noqa: E402

REF_DIR = ROOT / "data" / "reference"
SNAP_DIR = ROOT / "data" / "snapshots"

app = FastAPI(title="Project Sentinel API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_cache: dict = {}


def _clean(obj):
    """NaN/Inf are not valid JSON. Missing data must cross the wire as null
    so the UI can render 'no data' rather than a fabricated zero."""
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean(v) for v in obj]
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        return None if not np.isfinite(obj) else float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return str(obj.date())
    return obj


@app.get("/api/health")
def health() -> dict:
    return {
        "ok": True,
        "llm_provider": llm.provider(),
        "llm_model": llm.model(),
        "llm_key_present": llm.available(),
    }


@app.get("/api/corridors")
def corridors() -> dict:
    return _clean(agent_tools.list_corridors())


@app.get("/api/cri/{corridor_id}")
def cri(corridor_id: str, start: str = "2026-01-01", end: str | None = None) -> dict:
    """Full daily CRI series with all four components -- drives the timeline
    chart and the map's time scrubber."""
    key = f"cri:{corridor_id}"
    if key not in _cache:
        _cache[key] = risk.compute_cri(corridor_id)
    df = _cache[key].loc[start:end]
    return _clean({
        "corridor_id": corridor_id,
        "weights": risk.WEIGHTS,
        "as_of": str(df.index[-1].date()) if len(df) else None,
        "series": [
            {
                "date": str(idx.date()),
                "CRI": row["CRI"], "O": row["O"], "S": row["S"], "E": row["E"], "X": row["X"],
                "components_used": row["components_used"],
            }
            for idx, row in df.iterrows()
        ],
    })


@app.get("/api/twin")
def twin_graph() -> dict:
    """Nodes with lat/lon + edges, for the deck.gl flow map."""
    if "twin" not in _cache:
        snapshot = SNAP_DIR / "twin.json"
        data = json.loads(snapshot.read_text()) if snapshot.exists() else twin.to_json(twin.build_twin())
        _cache["twin"] = data
    return _clean(_cache["twin"])


@app.get("/api/procurement")
def procurement_endpoint(
    corridor_id: str | None = None,
    severity: float = 0.0,
    lambda_risk: float = 0.0,
    anti_concentration: bool = True,
    compliance_mode: bool = False,
) -> dict:
    """The lambda slider drives this. Returns the full allocation table for
    the Sankey plus country shares."""
    sev = {corridor_id: severity} if corridor_id else {}
    cri_now = {
        c: float(_cache.setdefault(f"cri:{c}", risk.compute_cri(c))["CRI"].iloc[-1])
        for c in ("chokepoint6", "chokepoint4")
    }
    r = procurement.solve(
        severity=sev, lambda_risk=lambda_risk,
        mu_concentration=1.0 if anti_concentration else 0.0,
        compliance_mode=compliance_mode, corridor_cri=cri_now,
    )
    alloc = r["allocation"]
    return _clean({
        "status": r["status"],
        "lambda_risk": lambda_risk,
        "total_allocated_kbd": r["total_allocated_kbd"],
        "total_shortfall_kbd": r["total_shortfall_kbd"],
        "corridor_cri_used": cri_now,
        "concentration_cap_pct": (
            procurement.DEFAULT_CONCENTRATION_CAP * 100 if anti_concentration else None
        ),
        "country_shares": procurement.country_shares(r).to_dict(),
        "allocation": alloc.to_dict("records") if not alloc.empty else [],
        "shortfall_by_refinery": r["shortfall_by_refinery"],
        "caveat": "cost is a searoute distance proxy, not real FOB+freight+war-risk pricing.",
    })


@app.get("/api/scenario")
def scenario_endpoint(
    corridor_id: str = "chokepoint6",
    severity: float = 1.0,
    duration_days: int = 90,
    second_corridor_id: str | None = None,
    second_severity: float | None = None,
    compliance_mode: bool = False,
) -> dict:
    """Full cascade -- drives the impact waterfall."""
    other = (
        {second_corridor_id: second_severity}
        if second_corridor_id and second_severity is not None else None
    )
    r = scenario.run_scenario(
        corridor_id, severity, duration_days,
        other_severity=other, compliance_mode=compliance_mode,
    )
    macro = r["macro"]["value"]
    return _clean({
        "scenario": r["scenario"],
        "total_shortfall_kbd": r["procurement"]["total_shortfall_kbd"],
        "run_cuts": {k: v for k, v in r["refinery_impact"]["value"].items() if v > 0},
        "product_shortfall_kbd": {k: v for k, v in r["product_shortfall"]["value"].items() if v > 0},
        "price_usd_bbl": r["price"]["value"],
        "price_baseline_usd_bbl": scenario.CALIBRATION_P0_USD_BBL,
        "macro": macro,
        # the waterfall reads this directly -- each step is one bar
        "waterfall": [
            {"label": "Baseline crude", "value": scenario.CALIBRATION_P0_USD_BBL, "unit": "USD/bbl"},
            {"label": "Price impact", "value": r["price"]["value"] - scenario.CALIBRATION_P0_USD_BBL,
             "unit": "USD/bbl"},
            {"label": "Scenario crude", "value": r["price"]["value"], "unit": "USD/bbl", "total": True},
        ],
        "method": {k: r[k]["method"] for k in ("refinery_impact", "price", "macro")},
        "confidence": {k: r[k]["confidence"] for k in ("refinery_impact", "product_shortfall", "macro")},
        "calibration": r["price"]["calibration"],
    })


@app.get("/api/reserve")
def reserve_endpoint(daily_gap_kbd: float = 500.0, duration_days: int = 90) -> dict:
    """Days-of-cover gauge + drawdown curve."""
    r = reserve.run_reserve(daily_gap_kbd, duration_days)
    return _clean({
        "daily_gap_kbd": daily_gap_kbd,
        "duration_days": duration_days,
        "capacity_bbl": r["capacity_bbl"],
        "max_pumpout_rate_kbd": r["max_pumpout_rate_kbd"],
        "days_to_exhaustion": r["days_to_exhaustion"],
        "days_of_cover_at_start": reserve.DESIGN_DOC_DAYS_OF_COVER,
        "total_unserved_kbd_days": r["total_unserved_kbd_days"],
        "schedule": r["schedule"].to_dict("records"),
        "caveat": "SPR strategic reserve only (5.33 MMT, ~9.5 days) -- NOT India's ~74 days of "
                  "total national storage.",
    })


@app.get("/api/backtest")
def backtest_endpoint() -> dict:
    """AUC + reliability curve per horizon."""
    if "backtest" not in _cache:
        out = []
        for h in backtest.HORIZONS:
            r = backtest.run_backtest(h)
            rel = r["reliability"]
            out.append({
                "horizon": h,
                "auc": r["auc"],
                "n_fit": r["n_fit"],
                "n_valid": r["n_valid"],
                "fit_positive_rate": r["fit_positive_rate"],
                "valid_positive_rate": r["valid_positive_rate"],
                "fit_components": r["fit_components"],
                "valid_components": r["valid_components"],
                "reliability": [
                    {"mean_predicted": row["mean_predicted"],
                     "observed_rate": row["observed_rate"], "n": int(row["n"])}
                    for _, row in rel.iterrows()
                ] if not rel.empty else [],
            })
        _cache["backtest"] = {
            "fit_window": "Bab el-Mandeb (chokepoint4), Oct 2023 - Feb 2024",
            "validation_window": "Hormuz (chokepoint6), Feb - Aug 2026",
            "horizons": out,
            "caveat": "AUC is null where the sustained closure leaves only one label class in the "
                      "validation window -- undefined, not zero.",
        }
    return _clean(_cache["backtest"])


@app.get("/api/bypass_routes")
def bypass_routes() -> dict:
    return _clean(agent_tools.get_bypass_routes())


@app.get("/api/reference/{name}")
def reference(name: str) -> dict:
    """refineries | ports | sources | spr | bypass_routes | corridor_exposure"""
    path = REF_DIR / f"{name}.csv"
    if not path.exists():
        return {"error": f"no reference table {name!r}"}
    return _clean({"rows": pd.read_csv(path).to_dict("records")})


class Ask(BaseModel):
    question: str


@app.post("/api/ask")
def ask(body: Ask) -> StreamingResponse:
    """SSE stream of the agent loop: one `tool` event per call, then
    `answer`, then `result` (which carries the provenance verdict the UI's
    badge renders)."""

    def stream():
        if not llm.available():
            payload = {"type": "llm_error",
                       "error": f"{llm.api_key_env_var()} not set -- the agent needs an LLM key. "
                                "Every other panel works without one."}
            yield f"data: {json.dumps(payload)}\n\n"
            return
        try:
            for event in loop.run_iter(body.question):
                yield f"data: {json.dumps(_clean(event), default=str)}\n\n"
        except Exception as exc:  # a provider blowing up mid-stream must not hang the UI
            yield f"data: {json.dumps({'type': 'llm_error', 'error': str(exc)})}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _self_check() -> None:
    """No network, no LLM key: exercises every read-only endpoint through
    FastAPI's test client and asserts the payloads are JSON-clean (no NaN,
    which is valid Python but invalid JSON and silently breaks the UI)."""
    from fastapi.testclient import TestClient

    client = TestClient(app)

    for url in (
        "/api/health",
        "/api/corridors",
        "/api/cri/chokepoint6?start=2026-02-01&end=2026-03-15",
        "/api/twin",
        "/api/procurement?corridor_id=chokepoint6&severity=1.0&lambda_risk=0",
        "/api/scenario?corridor_id=chokepoint6&severity=1.0&duration_days=90",
        "/api/reserve?daily_gap_kbd=500&duration_days=90",
        "/api/backtest",
        "/api/bypass_routes",
        "/api/reference/refineries",
    ):
        resp = client.get(url)
        assert resp.status_code == 200, (url, resp.status_code)
        body = resp.text
        assert "NaN" not in body and "Infinity" not in body, f"{url} leaked non-JSON floats"
        assert resp.json(), url

    # CRI must preserve missing components as null, never coerce them to 0 --
    # a fabricated 0 would read as "confirmed calm" in the UI
    series = client.get("/api/cri/chokepoint4?start=2026-01-01").json()["series"]
    assert any(pt["S"] is None or pt["E"] is None for pt in series), \
        "expected at least one genuinely-missing component to survive as null"

    # the lambda slider must actually change the solve, not silently no-op
    a = client.get("/api/procurement?lambda_risk=0&corridor_id=chokepoint6&severity=0.5").json()
    b = client.get("/api/procurement?lambda_risk=50&corridor_id=chokepoint6&severity=0.5").json()
    assert a["status"] == b["status"] == "Optimal"
    assert a["country_shares"] != b["country_shares"] or a["total_allocated_kbd"] != b["total_allocated_kbd"], \
        "lambda_risk had no effect on the allocation -- the slider would be decorative"

    # unknown reference table must not 500
    assert "error" in client.get("/api/reference/nope").json()

    # Concurrency: the dashboard fires ~7 requests in parallel on first
    # load, and FastAPI runs sync endpoints in a threadpool. A shared
    # non-thread-safe handle in the read path (duckdb's default connection
    # was exactly this) only fails under that parallelism -- serial checks
    # above pass right through it. Cleared caches so the threads actually
    # race the underlying reads rather than a warm dict.
    from concurrent.futures import ThreadPoolExecutor

    _cache.clear()
    risk._daily_cache = None
    urls = [
        "/api/cri/chokepoint6", "/api/cri/chokepoint4", "/api/backtest", "/api/twin",
        "/api/scenario?corridor_id=chokepoint6&severity=1.0",
        "/api/procurement?corridor_id=chokepoint6&severity=1.0",
        "/api/reserve?daily_gap_kbd=500",
    ]
    with ThreadPoolExecutor(max_workers=len(urls)) as pool:
        codes = [r.status_code for r in pool.map(client.get, urls)]
    assert all(c == 200 for c in codes), dict(zip(urls, codes))

    print("[api] self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        import uvicorn

        uvicorn.run(app, host="127.0.0.1", port=8000)
