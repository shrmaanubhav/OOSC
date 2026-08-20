"""Batched, cached article -> structured event extraction (design doc §3.1).

Key-gated: real classification calls an LLM (a small, fast model -- this
is high-volume classification, not reasoning) through agent/llm.py's
provider-switchable client (LLM_PROVIDER=groq|openai|gemini in .env, see
.env.example). No key is configured in this environment yet, so `main()`
checks for one and exits cleanly with instructions rather than failing
loudly or blocking the rest of the build (same policy as EIA/data.gov.in:
build against the real interface, wait for the credential, don't stall).

Hard rule enforced here, not just documented: an event with no verbatim
`evidence_span` is discarded. That's the cheapest hallucination guard
available and it happens in code (`_validate`), not by trusting the
model's compliance.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote, urlparse

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import llm  # noqa: E402

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
GDELT_SNAPSHOT_DIR = DATA_DIR / "snapshots" / "gdelt"
# gkg_articles.parquet (ingest/gdelt_bigquery.py, current primary path) takes
# priority; articles.parquet (ingest/gdelt.py's DOC-API path) is the fallback
# if BigQuery access isn't configured. Different schemas -- see _source_text
# and _get_date below for how both are handled.
CACHE_DIR = DATA_DIR / "snapshots" / "events" / "cache"
EVENTS_PATH = DATA_DIR / "snapshots" / "events" / "events.parquet"


def _articles_path() -> Path | None:
    for name in ("gkg_articles.parquet", "articles.parquet"):
        p = GDELT_SNAPSHOT_DIR / name
        if p.exists():
            return p
    return None

EVENT_TYPES = {
    "vessel_attack", "mine_laying", "closure_declared", "reopening",
    "force_majeure", "insurance_withdrawal", "sanction_action", "truce",
    "ceasefire", "naval_escort", "pipeline_outage", "other",
}
DIRECTIONS = {"escalation", "de-escalation"}

SYSTEM_PROMPT = """You are extracting structured events for a maritime chokepoint \
(Strait of Hormuz, Bab el-Mandeb, etc) from a headline and/or URL -- NOT full article \
text, which is not available from GDELT. Respond with ONLY a JSON object matching this \
schema -- no prose, no markdown fences:

{
  "corridors": ["chokepoint6"],
  "actors": ["Iran", "US Navy"],
  "event_type": "vessel_attack | mine_laying | closure_declared | reopening | force_majeure | insurance_withdrawal | sanction_action | truce | ceasefire | naval_escort | pipeline_outage | other",
  "severity": 1,
  "direction": "escalation | de-escalation",
  "confidence": 0.0,
  "evidence_span": "verbatim quote copied from the Title/URL text you were given, <=25 words"
}

evidence_span MUST be an exact substring of the Title/URL text in this prompt -- you were \
not given the article body, so do not invent a quote from it. If the given text does not \
describe a concrete corridor-relevant event, return {"event_type": "other", \
"evidence_span": ""} -- an empty evidence_span means "no event," and the caller will \
discard it."""


_SLUG_STRIP_EXT = re.compile(r"\.(html?|php|aspx?)$", re.IGNORECASE)
_SLUG_TRAILING_ID = re.compile(r"-[0-9a-f]{8,}$|-\d{6,}$")


def _title_from_url(url: str) -> str:
    """News CMSes commonly encode the headline in the URL path (e.g.
    '.../iran-tells-houthis-to-close-red-sea-gateway/'). GDELT's GKG rows
    carry no title field at all, and asking the model to quote a raw
    hyphenated slug produced near-zero hits in testing -- it reads as
    unnatural, unquotable text. Deriving a real sentence from it here is
    what actually fixed that, verified against a 15-article sample."""
    path = urlparse(url).path.strip("/")
    if not path:
        return ""
    slug = path.rsplit("/", 1)[-1]
    slug = _SLUG_STRIP_EXT.sub("", slug)
    slug = _SLUG_TRAILING_ID.sub("", slug)
    slug = unquote(slug).replace("-", " ").replace("_", " ")
    return slug.strip()


def _source_text(article: dict) -> str:
    """Exactly what the model is shown -- also what evidence_span is checked
    against, so the hallucination guard verifies something real instead of
    trusting an unfalsifiable claim about article text we never provided."""
    title = article.get("title") or _title_from_url(article.get("url", ""))
    return f"Title: {title}\nURL: {article.get('url', '')}"


def _get_date(article: dict):
    """DOC-API rows have 'seendate' (string); BigQuery GKG rows have 'date'
    (Timestamp) instead."""
    return article.get("seendate") or article.get("date")


def _cache_path(url: str) -> Path:
    digest = hashlib.sha256(url.encode()).hexdigest()
    return CACHE_DIR / f"{digest}.json"


def _validate(raw: dict, article: dict) -> dict | None:
    """Enforce the hallucination guard in code: discard anything without a
    verbatim evidence_span actually present in what the model was shown, and
    reject malformed enums rather than passing them through silently."""
    evidence = (raw.get("evidence_span") or "").strip()
    if not evidence:
        return None
    if evidence.lower() not in _source_text(article).lower():
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
        "seen_date": _get_date(article),
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


def _live_classify_fn(article: dict) -> dict:
    text = llm.chat(SYSTEM_PROMPT, _source_text(article), max_tokens=500)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return {"event_type": "other", "evidence_span": ""}


def extract_all(articles: pd.DataFrame, classify_fn, workers: int = 4) -> pd.DataFrame:
    """Concurrent classification -- sequential was ~1.5s/article, which is
    over 3 hours for a full ~8k-article backfill. classify_fn does network
    I/O (or, in the cache-hit case, a small file read), so a thread pool
    is the right tool; ponytail: threads not a job queue, this runs once
    per backfill, not as a service. workers=4 not higher: Groq's free-tier
    TPM cap (8000 tokens/min for the default model, verified live) means
    a wider pool just means more callers queued on 429 retries, not more
    real throughput -- the ceiling is token budget, not connection count."""
    articles_list = [row.to_dict() for _, row in articles.iterrows()]
    give_up = threading.Event()  # tripped once, e.g., a daily token cap is hit --
    # further calls would fail identically, so stop spending network round-trips
    failures = 0

    def _process(article: dict) -> dict | None:
        nonlocal failures
        if give_up.is_set():
            return None
        try:
            event = classify_article(article, classify_fn)
        except Exception as exc:
            failures += 1
            if "tokens per day" in str(exc).lower():
                give_up.set()
                print(f"[extractor]   daily token cap hit -- stopping early: {exc}")
            return None
        if event:
            event["corridor_id"] = article.get("corridor_id")
            event["event_date"] = _get_date(article)
        return event

    events = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for event in pool.map(_process, articles_list):
            if event:
                events.append(event)
    if failures:
        print(f"[extractor]   {failures}/{len(articles_list)} articles failed classification (see above)")
    return pd.DataFrame(events)


def _cap_per_corridor(articles: pd.DataFrame, cap: int) -> pd.DataFrame:
    """MVP scope: Groq's free-tier TPM/TPD caps make an uncapped multi-
    thousand-article backfill impractical (see extract_all). cap=0 means
    no cap. NOT groupby(...).apply(lambda g: g) -- verified live, that
    silently drops the corridor_id grouping column in this pandas
    version, which broke every downstream corridor_id lookup."""
    if not cap or "corridor_id" not in articles.columns:
        return articles
    parts = [
        group if len(group) <= cap else group.sample(cap, random_state=0)
        for _, group in articles.groupby("corridor_id")
    ]
    return pd.concat(parts, ignore_index=True)


def main() -> None:
    articles_path = _articles_path()
    if articles_path is None:
        print(
            f"[extractor] no article snapshot found in {GDELT_SNAPSHOT_DIR} -- "
            "run ingest/gdelt_bigquery.py (or ingest/gdelt.py) first"
        )
        return
    if not llm.available():
        print(
            f"[extractor] {llm.api_key_env_var()} not set (LLM_PROVIDER={llm.provider()}) -- "
            "event extraction needs an LLM call and is key-gated, same policy as "
            "EIA/data.gov.in. Set the key in .env (see .env.example) and re-run "
            "`uv run python agent/extractor.py` when ready; nothing else in the "
            "build is blocked by this."
        )
        return

    articles = pd.read_parquet(articles_path)

    # MVP scope: Groq's free-tier TPM cap makes the full ~8k-article
    # backfill a multi-hour job regardless of concurrency (token budget,
    # not connection count, is the ceiling -- see extract_all). Cap
    # per-corridor volume so a normal run finishes in tens of minutes;
    # override with EXTRACTOR_MAX_PER_CORRIDOR in .env (0 = no cap).
    cap = int(os.environ.get("EXTRACTOR_MAX_PER_CORRIDOR", "500"))
    before = len(articles)
    articles = _cap_per_corridor(articles, cap)
    if len(articles) < before:
        print(
            f"[extractor] capped {before} -> {len(articles)} articles "
            f"({cap}/corridor; set EXTRACTOR_MAX_PER_CORRIDOR=0 for no cap)"
        )

    print(f"[extractor] classifying {len(articles)} articles from {articles_path.name} ({llm.provider()}/{llm.model()})...")
    events = extract_all(articles, _live_classify_fn)
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    events.to_parquet(EVENTS_PATH, index=False)
    print(f"[extractor] {len(events)}/{len(articles)} articles produced a valid event -> {EVENTS_PATH}")


def _self_check() -> None:
    """No network, no key: exercises caching, evidence_span discard, and
    malformed-enum rejection against a stub classifier."""
    import shutil
    import tempfile

    cap_test = pd.DataFrame(
        {"corridor_id": ["a"] * 5 + ["b"] * 3, "url": [f"u{i}" for i in range(8)]}
    )
    capped = _cap_per_corridor(cap_test, cap=3)
    assert "corridor_id" in capped.columns, "corridor_id column was dropped"
    assert capped["corridor_id"].value_counts().to_dict() == {"a": 3, "b": 3}
    assert _cap_per_corridor(cap_test, cap=0) is cap_test  # 0 = no cap, unchanged

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

        assert _title_from_url("https://gcaptain.com/iran-tells-houthis-to-close-red-sea-gateway/") == \
            "iran tells houthis to close red sea gateway"
        assert _title_from_url("https://x.com/oil-prices-spike-after-attack-128934773.html") == \
            "oil prices spike after attack"

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
