"""Unified LLM client -- provider switchable via .env, one call site.

Every caller in this codebase (agent/extractor.py now, agent/loop.py in
Phase 7) goes through `chat()` here rather than importing a provider SDK
directly, so swapping providers is a .env edit, not a code change.

    LLM_PROVIDER=groq|openai|gemini   (default: groq)
    LLM_MODEL=<override>              (optional; sensible default per provider)
    GROQ_API_KEY / OPENAI_API_KEY / GEMINI_API_KEY

See .env.example for the full list and where to get each key.
"""

from __future__ import annotations

import os
import re
import time

from dotenv import load_dotenv

load_dotenv()

DEFAULT_MODELS = {
    "groq": "openai/gpt-oss-20b",  # llama-3.1-8b-instant was retired; verified live 2026-08-20
    "openai": "gpt-4.1-mini",
    "gemini": "gemini-3.6-flash",  # gemini-2.0-flash retired; verified live 2026-08-20
}
API_KEY_ENV_VARS = {
    "groq": "GROQ_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
}


def provider() -> str:
    p = os.environ.get("LLM_PROVIDER", "groq").lower()
    if p not in DEFAULT_MODELS:
        raise ValueError(f"Unknown LLM_PROVIDER={p!r} -- expected one of {list(DEFAULT_MODELS)}")
    return p


def model() -> str:
    return os.environ.get("LLM_MODEL") or DEFAULT_MODELS[provider()]


def api_key_env_var() -> str:
    return API_KEY_ENV_VARS[provider()]


def available() -> bool:
    return bool(os.environ.get(api_key_env_var()))


def chat(system: str, user: str, max_tokens: int = 300) -> str:
    """One system+user turn, plain text out. Strips markdown code fences some
    providers wrap JSON responses in, since callers here expect raw JSON."""
    p = provider()
    if p == "groq":
        text = _chat_groq(system, user, max_tokens)
    elif p == "openai":
        text = _chat_openai(system, user, max_tokens)
    else:
        text = _chat_gemini(system, user, max_tokens)
    return _strip_code_fence(text)


def _strip_code_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
    return text.strip()


def _chat_groq(system: str, user: str, max_tokens: int, retries: int = 5) -> str:
    from groq import Groq, RateLimitError

    client = Groq()
    for attempt in range(retries):
        try:
            resp = client.chat.completions.create(
                model=model(),
                max_tokens=max_tokens,
                # the default model (openai/gpt-oss-20b) is a reasoning model
                # that otherwise burns its whole token budget on chain-of-
                # thought and returns empty content with finish_reason=
                # "length" -- verified live, this single param fixed it
                # (298 reasoning tokens -> 44)
                reasoning_effort="low",
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            )
            return resp.choices[0].message.content or ""
        except RateLimitError as exc:
            # free-tier TPM limits are low (8000 TPM observed for
            # openai/gpt-oss-20b) and shared across concurrent callers --
            # Groq's error message includes a "try again in Xs" hint
            wait = _parse_retry_seconds(str(exc)) or (2**attempt)
            if attempt == retries - 1:
                raise
            time.sleep(wait)
    return ""  # unreachable, satisfies type checkers


def _parse_retry_seconds(message: str) -> float | None:
    match = re.search(r"try again in ([\d.]+)s", message)
    return float(match.group(1)) + 0.5 if match else None


def _chat_openai(system: str, user: str, max_tokens: int) -> str:
    from openai import OpenAI

    client = OpenAI()
    resp = client.chat.completions.create(
        model=model(),
        max_completion_tokens=max_tokens,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
    )
    return resp.choices[0].message.content or ""


def _chat_gemini(system: str, user: str, max_tokens: int) -> str:
    from google import genai
    from google.genai import types

    client = genai.Client()
    resp = client.models.generate_content(
        model=model(),
        contents=user,
        config=types.GenerateContentConfig(
            system_instruction=system, max_output_tokens=max_tokens
        ),
    )
    return resp.text or ""


def _self_check() -> None:
    """No network, no key: dispatch/config logic only."""
    import sys

    os.environ["LLM_PROVIDER"] = "groq"
    os.environ.pop("LLM_MODEL", None)
    assert provider() == "groq"
    assert model() == "openai/gpt-oss-20b"
    assert api_key_env_var() == "GROQ_API_KEY"

    os.environ["LLM_PROVIDER"] = "openai"
    assert model() == "gpt-4.1-mini"
    assert api_key_env_var() == "OPENAI_API_KEY"

    os.environ["LLM_MODEL"] = "gpt-4.1-mini-custom"
    assert model() == "gpt-4.1-mini-custom"
    os.environ.pop("LLM_MODEL", None)

    os.environ["LLM_PROVIDER"] = "not-a-real-provider"
    try:
        provider()
        raise AssertionError("expected ValueError for unknown provider")
    except ValueError:
        pass

    assert _strip_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert _strip_code_fence('{"a": 1}') == '{"a": 1}'

    os.environ["LLM_PROVIDER"] = "groq"
    print("[llm] self-check passed", file=sys.stderr)


if __name__ == "__main__":
    import sys

    if "--self-check" in sys.argv:
        _self_check()
