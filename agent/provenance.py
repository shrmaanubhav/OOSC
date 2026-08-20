"""Provenance validator (design doc §3.x, PLAN.md Phase 6, CLAUDE.md rule
4: "every number in agent-facing output must trace to a tool result...
never computes"). This is the code-level enforcement of that rule -- not
an LLM call, a plain check. agent/loop.py (Phase 7) will run every agent
response through check_provenance() against the tool results it was given
before the response reaches the user.

Known false-positive source (not worth solving here -- Phase 7's real
tool_results dwarf plausible coincidental collisions, and can pass an
allowlist later if small ordinals like "3 tool calls" or "step 1 of 3"
turn out to matter in practice): a flagged orphan is a genuine finding
only when the LLM asserts it as fact with nothing backing it -- inspect
the orphan list, don't treat a nonzero count as automatic proof.
"""

from __future__ import annotations

import math
import re
from typing import Any

NUMBER_RE = re.compile(r"-?\d[\d,]*(?:\.\d+)?")


def extract_numbers(text: str) -> list[float]:
    out = []
    for m in NUMBER_RE.finditer(text):
        try:
            out.append(float(m.group().replace(",", "")))
        except ValueError:
            continue
    return out


def _flatten_numbers(obj: Any) -> list[float]:
    """Recursively pull every numeric leaf out of a tool result -- dict,
    list, DataFrame/Series, scalar, or string with numbers embedded."""
    if isinstance(obj, bool):
        return []
    if isinstance(obj, (int, float)):
        return [float(obj)]
    if isinstance(obj, str):
        return extract_numbers(obj)
    if isinstance(obj, dict):
        return [n for v in obj.values() for n in _flatten_numbers(v)]
    if isinstance(obj, (list, tuple, set)):
        return [n for v in obj for n in _flatten_numbers(v)]
    if hasattr(obj, "to_dict"):  # pandas DataFrame/Series
        return _flatten_numbers(obj.to_dict())
    return []


def check_provenance(
    response_text: str,
    tool_results: list[Any],
    rel_tol: float = 1e-3,
    abs_tol: float = 1e-2,
) -> dict:
    """Every number the agent wrote must be within tolerance of *some*
    number that appeared in tool_results (math.isclose semantics --
    generous enough to survive the LLM rounding 113.57 to "113.6" in
    prose, tight enough to catch a fabricated figure)."""
    claimed = extract_numbers(response_text)
    source_pool = _flatten_numbers(tool_results)

    traced, orphans = [], []
    for n in claimed:
        if any(math.isclose(n, s, rel_tol=rel_tol, abs_tol=abs_tol) for s in source_pool):
            traced.append(n)
        else:
            orphans.append(n)

    return {
        "n_claimed": len(claimed),
        "n_traced": len(traced),
        "orphans": orphans,
        "violation": len(orphans) > 0,
    }


def _self_check() -> None:
    """No network. Verifies the exit criterion directly: a grounded
    response (every number traces to tool_results) produces zero
    violations; a response with a fabricated figure produces a visible
    violation naming exactly that figure."""
    tool_results = [
        {"cri": 87.3, "components_used": "O,S,X"},
        {"schedule": [{"day": 0, "draw_kbd": 500.0}, {"day": 1, "draw_kbd": 500.0}]},
    ]

    grounded = "CRI is currently 87.3, driven by O/S/X, with reserve drawdown of 500 kbd/day."
    result = check_provenance(grounded, tool_results)
    assert not result["violation"], result
    assert result["n_traced"] == result["n_claimed"]

    adversarial = "CRI is 87.3 but total economic losses will hit $42 billion by next week."
    result2 = check_provenance(adversarial, tool_results)
    assert result2["violation"], result2
    assert any(abs(o - 42.0) < 1e-6 for o in result2["orphans"]), result2["orphans"]

    print("[provenance] self-check passed")


def main() -> None:
    tool_results = [{"cri": 87.3, "days_to_exhaustion": 42}]
    grounded = "CRI has reached 87.3 and the reserve is projected to hit zero at day 42."
    adversarial = "CRI has reached 87.3 and the reserve will last 500 more days."
    print("[provenance] grounded response  ->", check_provenance(grounded, tool_results))
    print("[provenance] adversarial response ->", check_provenance(adversarial, tool_results))


if __name__ == "__main__":
    import sys

    if "--self-check" in sys.argv:
        _self_check()
    else:
        main()
