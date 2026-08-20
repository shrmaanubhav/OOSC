"""Agent loop -- bounded native tool calling, provenance-checked (design
doc §3.2, PLAN.md Phase 7).

Tool calls go through agent/llm.py's chat_tools(), which uses each
provider's native function-calling API. An earlier version of this file
asked the model for a JSON object in prose instead, on the theory that
one contract would work across all three providers -- that failed live:
groq's openai/gpt-oss-20b routes any tool-shaped intent through its own
tool channel and returns HTTP 400 ("Tool choice is none, but model called
a tool") when no schema was supplied. The provider differences now live
in llm.py where they belong, and this file is provider-agnostic.

The loop is bounded at MAX_STEPS tool calls. On the last step the tool
schemas are withheld, which forces a text answer from what it has rather
than letting it burn the budget or truncate silently.

Every answer is run through agent/provenance.py before being returned. A
violation does not raise -- it rides along in the result so the caller
(and the UI's provenance badge) can display it. Hiding it would defeat
the point of having it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from agent import llm, provenance, tools  # noqa: E402

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "analyst.md"
MAX_STEPS = 6
MAX_TOKENS = 4000  # the final answer is a multi-section markdown brief, not a sentence
MAX_OBSERVATION_CHARS = 4000


def system_prompt() -> str:
    text = PROMPT_PATH.read_text(encoding="utf-8")
    body = text.split("---", 2)[-1] if text.startswith("---") else text
    return f"{body.strip()}\n\n## Available tools\n\n{tools.describe()}"


def run(question: str, max_steps: int = MAX_STEPS, verbose: bool = False) -> dict:
    """Returns {answer, steps, tool_results, provenance}. Never raises on a
    model or tool failure -- those become part of the transcript instead."""
    final = None
    for event in run_iter(question, max_steps=max_steps, verbose=verbose):
        if event["type"] == "result":
            final = event["result"]
    assert final is not None, "run_iter must always end with a result event"
    return final


def run_iter(question: str, max_steps: int = MAX_STEPS, verbose: bool = False):
    """Generator form: yields {"type": "tool"|"answer"|"llm_error", ...} as
    each step completes, then a final {"type": "result", "result": {...}}.
    api/main.py streams these over SSE; run() just drains it. Written as a
    generator rather than a callback so the streaming path and the
    synchronous path cannot drift apart."""
    system = system_prompt()
    messages: list[dict] = [{"role": "user", "content": question}]
    steps: list[dict] = []
    tool_results: list[dict] = []
    answer = None

    for step_num in range(max_steps):
        last_step = step_num == max_steps - 1
        if last_step:
            messages.append({
                "role": "user",
                "content": "You have no tool calls left. Give your final answer now, "
                           "in the output-contract format, using only the numbers you "
                           "already received from tools.",
            })

        try:
            # withholding the schemas on the last step is what makes the
            # budget binding -- with them present the model can keep
            # requesting tools forever and never produce prose
            reply = llm.chat_tools(
                system, messages, [] if last_step else tools.schemas(), max_tokens=MAX_TOKENS
            )
        except Exception as exc:
            step = {"step": step_num + 1, "type": "llm_error", "error": str(exc)}
            steps.append(step)
            if verbose:
                print(f"  [{step_num + 1}] LLM ERROR: {exc}")
            yield step
            break

        if "text" in reply:
            answer = reply["text"]
            step = {"step": step_num + 1, "type": "answer"}
            steps.append(step)
            yield step
            break

        name, args = reply["tool"], reply["args"]
        result = tools.call(name, args)
        tool_results.append(result)
        step = {
            "step": step_num + 1, "type": "tool", "tool": name, "args": args, "result": result,
        }
        steps.append(step)
        if verbose:
            print(f"  [{step_num + 1}] {name}({args}) -> {str(result)[:110]}...")
        yield step

        rendered = json.dumps(result, default=str)
        if len(rendered) > MAX_OBSERVATION_CHARS:
            rendered = rendered[:MAX_OBSERVATION_CHARS] + "...(truncated)"
        # pass the whole reply back as the tool_call: it may carry
        # provider-private fields (Gemini's thought_signature) that only
        # llm.py knows how to replay
        messages.append({
            "role": "assistant", "content": "", "tool_call": {**reply, "name": name},
        })
        messages.append({
            "role": "tool", "tool_call_id": reply["id"], "name": name, "content": rendered,
        })

    if not answer:
        answer = "(no answer produced within the step budget)"

    # The question joins the source pool: a number the USER supplied
    # ("what if severity is 0.6") is legitimately citable and is not a
    # fabrication. Everything else must trace to a tool result.
    check = provenance.check_provenance(answer, tool_results + [question])
    yield {
        "type": "result",
        "result": {
            "question": question,
            "answer": answer,
            "steps": steps,
            "n_tool_calls": sum(1 for s in steps if s["type"] == "tool"),
            "tool_results": tool_results,
            "provenance": check,
        },
    }


def main() -> None:
    if not llm.available():
        print(f"[loop] {llm.api_key_env_var()} not set -- cannot run the live agent.")
        print("[loop] run `uv run python agent/loop.py --self-check` for the offline check.")
        return

    question = " ".join(a for a in sys.argv[1:] if not a.startswith("--")) or (
        "Hormuz is already closed. What happens to India if Bab el-Mandeb closes too?"
    )
    print(f"[loop] provider={llm.provider()} model={llm.model()}")
    print(f"[loop] Q: {question}\n")
    result = run(question, verbose=True)
    print(f"\n[loop] {result['n_tool_calls']} tool calls\n")
    print(result["answer"])
    p = result["provenance"]
    print(f"\n[loop] provenance: {p['n_traced']}/{p['n_claimed']} numbers traced to tool results")
    if p["violation"]:
        print(f"[loop] PROVENANCE VIOLATION -- untraceable numbers: {p['orphans']}")
    else:
        print("[loop] no provenance violations")


def _self_check() -> None:
    """No network, no API key: stubs llm.chat_tools with a scripted model to
    exercise the loop's control flow -- tool dispatch, step-budget
    exhaustion, unknown-tool recovery, provider errors, and provenance
    wiring."""
    original = llm.chat_tools
    try:
        real_cri = tools.call("get_cri", {"corridor_id": "chokepoint6"})["cri_latest"]
        call_tool = {"tool": "get_cri", "args": {"corridor_id": "chokepoint6"}, "id": "c1"}

        def script(*replies):
            it = iter(replies)
            llm.chat_tools = lambda system, messages, schemas, max_tokens=0: next(it)

        # 1. normal path: one tool call, then an answer citing a real number
        script(call_tool, {"text": f"CRI is {real_cri}."})
        result = run("what is the risk?")
        assert result["n_tool_calls"] == 1, result["steps"]
        assert not result["provenance"]["violation"], result["provenance"]

        # 2. a fabricated number must surface as a violation, not slip through
        script(call_tool, {"text": "Losses will reach 999.75 billion dollars."})
        bad = run("what is the risk?")
        assert bad["provenance"]["violation"], bad["provenance"]
        assert any(abs(o - 999.75) < 1e-6 for o in bad["provenance"]["orphans"])

        # 3. step budget must bind -- a model that only ever calls tools has
        #    to terminate. The last step withholds schemas, so verify the
        #    loop actually stops requesting tools rather than looping.
        seen_schemas = []

        def always_tool(system, messages, schemas, max_tokens=0):
            seen_schemas.append(len(schemas))
            return call_tool

        llm.chat_tools = always_tool
        capped = run("q", max_steps=3)
        assert capped["n_tool_calls"] == 3, capped["n_tool_calls"]
        assert seen_schemas[-1] == 0, "final step must withhold tool schemas"
        assert seen_schemas[0] > 0

        # 4. an unknown tool must not kill the loop
        script({"tool": "nonexistent", "args": {}, "id": "x"}, {"text": "recovered"})
        recovered = run("q")
        assert recovered["answer"] == "recovered"
        assert "error" in recovered["tool_results"][0]

        # 5. a provider exception must be captured, not propagated -- a
        #    rate-limited demo should degrade, not traceback
        def boom(system, messages, schemas, max_tokens=0):
            raise RuntimeError("rate limited")

        llm.chat_tools = boom
        errored = run("q")
        assert "no answer produced" in errored["answer"]
        assert any(s["type"] == "llm_error" for s in errored["steps"])

        # 6. the streaming path must emit one event per step and end with
        #    exactly one result -- api/main.py's SSE depends on both, and a
        #    drift between run() and run_iter() would only show up in the UI
        script(call_tool, {"text": "streamed"})
        events = list(run_iter("q"))
        assert [e["type"] for e in events] == ["tool", "answer", "result"], events
        assert events[-1]["result"]["answer"] == "streamed"

        # the real prompt file must load and carry the tool catalog
        prompt = system_prompt()
        assert "get_bypass_routes" in prompt and "cannot do arithmetic" in prompt
        # schemas must be well-formed for the provider adapters
        assert all(s["type"] == "function" for s in tools.schemas())
    finally:
        llm.chat_tools = original

    print("[loop] self-check passed")


if __name__ == "__main__":
    if "--self-check" in sys.argv:
        _self_check()
    else:
        main()
