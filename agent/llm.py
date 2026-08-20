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

import json
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


def chat_tools(
    system: str, messages: list[dict], tool_schemas: list[dict], max_tokens: int = 1200
) -> dict:
    """Multi-turn turn with native function calling. Returns either
    {"tool": name, "args": {...}, "id": str} or {"text": "..."}.

    `messages` is a provider-neutral transcript of
    {"role": "user"|"assistant"|"tool", "content": str, ...} -- each
    provider adapter below translates it. Native function calling is used
    rather than asking for JSON in prose because some models (verified
    live: groq's openai/gpt-oss-20b) route any tool-shaped intent through
    their own tool channel regardless of instructions, and error out with
    'Tool choice is none, but model called a tool' when no schema was
    supplied. Fighting that with prompt wording is fragile; giving the
    model the channel it expects is not.

    `tool_schemas` is OpenAI-shaped (agent/tools.py's schemas()); the
    Gemini adapter converts it.
    """
    p = provider()
    if p in ("groq", "openai"):
        return _chat_tools_openai_shaped(p, system, messages, tool_schemas, max_tokens)
    return _chat_tools_gemini(system, messages, tool_schemas, max_tokens)


def _chat_tools_openai_shaped(
    p: str, system: str, messages: list[dict], tool_schemas: list[dict], max_tokens: int
) -> dict:
    if p == "groq":
        from groq import Groq

        client, extra = Groq(), {"reasoning_effort": "low"}
        token_arg = "max_tokens"
    else:
        from openai import OpenAI

        client, extra = OpenAI(), {}
        token_arg = "max_completion_tokens"

    payload = [{"role": "system", "content": system}]
    for m in messages:
        if m["role"] == "tool":
            payload.append(
                {"role": "tool", "tool_call_id": m["tool_call_id"], "content": m["content"]}
            )
        elif m["role"] == "assistant" and m.get("tool_call"):
            tc = m["tool_call"]
            payload.append({
                "role": "assistant",
                "content": m.get("content") or None,
                "tool_calls": [{
                    "id": tc["id"], "type": "function",
                    "function": {"name": tc["name"], "arguments": json.dumps(tc["args"])},
                }],
            })
        else:
            payload.append({"role": m["role"], "content": m["content"]})

    resp = client.chat.completions.create(
        model=model(), messages=payload, tools=tool_schemas,
        **{token_arg: max_tokens}, **extra,
    )
    choice = resp.choices[0].message
    if getattr(choice, "tool_calls", None):
        tc = choice.tool_calls[0]
        try:
            args = json.loads(tc.function.arguments or "{}")
        except json.JSONDecodeError:
            args = {}
        return {"tool": tc.function.name, "args": args, "id": tc.id}
    return {"text": choice.content or ""}


def _chat_tools_gemini(
    system: str, messages: list[dict], tool_schemas: list[dict], max_tokens: int
) -> dict:
    from google import genai
    from google.genai import types

    declarations = [
        types.FunctionDeclaration(
            name=s["function"]["name"],
            description=s["function"]["description"],
            parameters=s["function"]["parameters"],
        )
        for s in tool_schemas
    ]

    contents = []
    for m in messages:
        if m["role"] == "tool":
            contents.append(
                types.Content(role="user", parts=[types.Part.from_function_response(
                    name=m["name"], response={"result": m["content"]}
                )])
            )
        elif m["role"] == "assistant" and m.get("tool_call"):
            tc = m["tool_call"]
            # Replay the model's ORIGINAL part, not a reconstruction.
            # Gemini 3.x rejects a rebuilt functionCall that has lost its
            # thought_signature ("Function call is missing a
            # thought_signature in functionCall parts", verified live).
            part = tc.get("_raw") or types.Part.from_function_call(
                name=tc["name"], args=tc["args"]
            )
            contents.append(types.Content(role="model", parts=[part]))
        else:
            role = "model" if m["role"] == "assistant" else "user"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m["content"])]))

    # bind the client to a name -- an inlined genai.Client().models.…
    # call can have the temporary client closed out from under the request
    # ("Cannot send a request, as the client has been closed", seen live)
    client = genai.Client()
    resp = client.models.generate_content(
        model=model(),
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=system,
            max_output_tokens=max_tokens,
            tools=[types.Tool(function_declarations=declarations)] if declarations else None,
            # this module runs the tool loop itself (agent/loop.py enforces
            # the step budget and provenance check); letting the SDK also
            # auto-execute would bypass both
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        ),
    )
    for part in (resp.candidates[0].content.parts or []):
        if getattr(part, "function_call", None):
            fc = part.function_call
            # Gemini namespaces declared tools ("default_api:get_cri");
            # strip it so callers see the name they registered.
            name = fc.name.split(":")[-1]
            return {"tool": name, "args": dict(fc.args or {}), "id": fc.name, "_raw": part}
    return {"text": resp.text or ""}


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
            # two distinct free-tier ceilings observed live for
            # openai/gpt-oss-20b: 8000 TPM (worth backing off and
            # retrying) and 200,000 TPD (a daily cap -- retrying within
            # the same process cannot help, the wait is hours not
            # seconds, so fail fast and let the caller decide whether to
            # skip this item rather than burn the whole retry budget)
            if "tokens per day" in str(exc).lower():
                raise
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
