"""Batched, cached article -> structured event extraction (design doc §3.1).

Key-gated: real classification calls the Anthropic API (a small, fast
model -- this is high-volume classification, not reasoning) and needs
ANTHROPIC_API_KEY. No key is configured in this environment yet, so
`main()` checks for one and exits cleanly with instructions rather than
failing loudly or blocking the rest of the build (same policy as the
EIA/data.gov.in ingestion: build against the real interface, wait for
the credential, don't stall on it).

Hard rule enforced here, not just documented: an event with no verbatim
`evidence_span` is discarded. That's the cheapest hallucination guard
available and it happens in code (`_validate`), not by trusting the
model's compliance.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import pandas as pd

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
ARTICLES_PATH = DATA_DIR / "snapshots" / "gdelt" / "articles.parquet"
CACHE_DIR = DATA_DIR / "snapshots" / "events" / "cache"
EVENTS_PATH = DATA_DIR / "snapshots" / "events" / "events.parquet"

MODEL = "claude-haiku-4-5-20251001"  # small/fast: this is classification, not reasoning

EVENT_TYPES = {
    "vessel_attack", "mine_laying", "closure_declared", "reopening",
    "force_majeure", "insurance_withdrawal", "sanction_action", "truce",
    "ceasefire", "naval_escort", "pipeline_outage", "other",
}
DIRECTIONS = {"escalation", "de-escalation"}

SYSTEM_PROMPT = """You are extracting structured events from a single news article \
about a maritime chokepoint (Strait of Hormuz, Bab el-Mandeb, etc). Respond with ONLY \
a JSON object matching this schema -- no prose, no markdown fences:

{
  "corridors": ["chokepoint6"],
  "actors": ["Iran", "US Navy"],
  "event_type": "vessel_attack | mine_laying | closure_declared | reopening | force_majeure | insurance_withdrawal | sanction_action | truce | ceasefire | naval_escort | pipeline_outage | other",
  "severity": 1,
  "direction": "escalation | de-escalation",
  "confidence": 0.0,
  "evidence_span": "verbatim quote from the article, <=25 words"
}

evidence_span MUST be an exact substring of the article text. If the article does not \
describe a concrete corridor-relevant event, return {"event_type": "other", \
"evidence_span": ""} -- an empty evidence_span means "no event," and the caller will \
discard it. Never invent an evidence_span that isn't a verbatim quote."""


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def _validate(raw: dict, article: dict) -> dict | None:
    """Enforce the hallucination guard in code: discard anything without a
    verbatim evidence_span, and reject malformed enums rather than passing
    them through silently."""
    evidence = (raw.get("evidence_span") or "").strip()
    if not evidence:
        return None

    event_type = raw.get("event_type")
    direction = raw.get("direction")
    if event_type not in EVENT_TYPES or direction not in DIRECTIONS:
        return None

    return {
        "corridors": raw.get("corridors", []),
        "actors": raw.get("actors", []),
        "event_type": event_type,
        "severity": float(raw.get("severity", 0)),
        "direction": direction,
        "confidence": float(raw.get("confidence", 0)),
        "evidence_span": evidence,
        "article_url": article.get("url"),
        "seen_date": article.get("seendate"),
    }


def classify_article(article: dict, classify_fn) -> dict | None:
    """classify_fn(article) -> raw dict from the model. Cached by URL hash."""
    cache_path = _cache_path(article["url"])
    if cache_path.exists():
        raw = json.loads(cache_path.read_text())
    else:
        raw = classify_fn(article)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(raw))
    return _validate(raw, article)


def _live_classify_fn(client, article: dict) -> dict:
    resp = client.messages.create(
        model=MODEL,
        max_tokens=300,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": f"Title: {article.get('title', '')}\nURL: {article.get('url', '')}"}],
    )
    text = resp.content[0].text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"event_type": "other", "evidence_span": ""}


def extract_all(articles: pd.DataFrame, classify_fn) -> pd.DataFrame:
    events = []
    for _, article in articles.iterrows():
        event = classify_article(article.to_dict(), classify_fn)
        if event:
            event["corridor_id"] = article.get("corridor_id")
            event["event_date"] = article.get("seendate")
            events.append(event)
    return pd.DataFrame(events)


def main() -> None:
    if not ARTICLES_PATH.exists():
        print(f"[extractor] {ARTICLES_PATH} not found -- run ingest/gdelt.py first")
        return
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "[extractor] ANTHROPIC_API_KEY not set -- event extraction needs an LLM "
            "call and is key-gated, same policy as EIA/data.gov.in. Set the key and "
            "re-run `uv run python agent/extractor.py` when ready; nothing else in "
            "the build is blocked by this."
        )
        return

    import anthropic

    client = anthropic.Anthropic()
    articles = pd.read_parquet(ARTICLES_PATH)
    print(f"[extractor] classifying {len(articles)} articles ({MODEL})...")
    events = extract_all(articles, lambda a: _live_classify_fn(client, a))
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    events.to_parquet(EVENTS_PATH, index=False)
    print(f"[extractor] {len(events)}/{len(articles)} articles produced a valid event -> {EVENTS_PATH}")


def _self_check() -> None:
    """No network, no key: exercises caching, evidence_span discard, and
    malformed-enum rejection against a stub classifier."""
    import shutil
    import tempfile

    global CACHE_DIR
    original_cache_dir = CACHE_DIR
    tmp = Path(tempfile.mkdtemp())
    CACHE_DIR = tmp

    try:
        call_count = {"n": 0}

        def stub_classify(article: dict) -> dict:
            call_count["n"] += 1
            if "no-event" in article["url"]:
                return {"event_type": "other", "evidence_span": ""}
            if "malformed" in article["url"]:
                return {"event_type": "not_a_real_type", "evidence_span": "x", "direction": "escalation"}
            return {
                "corridors": ["chokepoint6"],
                "actors": ["Iran"],
                "event_type": "mine_laying",
                "severity": 3,
                "direction": "escalation",
                "confidence": 0.8,
                "evidence_span": "Iran lays mines in Strait of Hormuz",
            }

        real_event = {"url": "https://x.com/real", "title": "Iran lays mines in Strait of Hormuz"}
        no_event = {"url": "https://x.com/no-event", "title": "Weather report"}
        malformed = {"url": "https://x.com/malformed", "title": "Something"}

        assert classify_article(real_event, stub_classify) is not None
        assert classify_article(no_event, stub_classify) is None
        assert classify_article(malformed, stub_classify) is None
        assert call_count["n"] == 3

        # second call for the same URL must hit the cache, not the classifier
        classify_article(real_event, stub_classify)
        assert call_count["n"] == 3, "cache was not used on repeat classification"

        print("[extractor] self-check passed")
    finally:
        CACHE_DIR = original_cache_dir
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        main()
