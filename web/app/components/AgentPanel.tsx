"use client";

import { useRef, useState } from "react";
import { API_BASE } from "../lib/api";
import Panel from "./Panel";

type Step = { type: string; step?: number; tool?: string; args?: Record<string, unknown>; error?: string };
type Provenance = { n_claimed: number; n_traced: number; orphans: number[]; violation: boolean };

const SUGGESTIONS = [
  "Hormuz is already closed. What happens to India if Bab el-Mandeb closes too?",
  "How much would a 60% Hormuz closure cost India over 90 days?",
  "Does the CRI actually predict disruption, or is it hindsight?",
];

/** Streams the agent loop over SSE. The provenance badge is the point of
 *  the panel: every number in the answer is checked in code against the
 *  tool results that produced it, and a failure is shown, not swallowed. */
export default function AgentPanel() {
  const [question, setQuestion] = useState(SUGGESTIONS[0]);
  const [steps, setSteps] = useState<Step[]>([]);
  const [answer, setAnswer] = useState("");
  const [prov, setProv] = useState<Provenance | null>(null);
  const [running, setRunning] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  async function ask() {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setRunning(true);
    setSteps([]);
    setAnswer("");
    setProv(null);

    try {
      const res = await fetch(`${API_BASE}/api/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
        signal: ctrl.signal,
      });
      const reader = res.body?.getReader();
      if (!reader) throw new Error("no stream");
      const dec = new TextDecoder();
      let buf = "";

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const chunks = buf.split("\n\n");
        buf = chunks.pop() ?? "";
        for (const chunk of chunks) {
          const line = chunk.split("\n").find((l) => l.startsWith("data: "));
          if (!line) continue;
          const evt = JSON.parse(line.slice(6));
          if (evt.type === "result") {
            setAnswer(evt.result.answer);
            setProv(evt.result.provenance);
          } else {
            setSteps((s) => [...s, evt]);
          }
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setSteps((s) => [...s, { type: "llm_error", error: String(e) }]);
      }
    } finally {
      setRunning(false);
    }
  }

  const badge = !prov ? null : prov.violation ? (
    <span className="text-[11px] px-2 py-0.5 rounded-full bg-[#e5484d1f] text-[var(--bad)] border border-[#e5484d55]">
      ✕ {prov.orphans.length} untraceable
    </span>
  ) : (
    <span className="text-[11px] px-2 py-0.5 rounded-full bg-[#2dd4a71f] text-[var(--ok)] border border-[#2dd4a755]">
      ✓ {prov.n_traced}/{prov.n_claimed} traced
    </span>
  );

  return (
    <Panel
      title="Analyst"
      subtitle="Bounded tool-calling loop · every number checked against tool output in code"
      right={badge}
      className="min-h-[420px]"
      caveat={
        prov?.violation
          ? `Untraceable numbers: ${prov.orphans.join(", ")} — these did not match any tool result and should not be trusted.`
          : undefined
      }
    >
      <div className="flex flex-col h-full gap-2.5">
        <div className="flex gap-2">
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && !running && ask()}
            placeholder="Ask about corridor risk, reallocation, or macro impact…"
            className="flex-1 bg-[var(--panel-2)] border border-[var(--border)] rounded-md px-3 py-2 text-[12.5px] outline-none focus:border-[var(--accent)] transition-colors"
          />
          <button
            onClick={ask}
            disabled={running}
            className="px-3.5 py-2 rounded-md text-[12px] font-medium bg-[var(--accent)] text-[#06121f] disabled:opacity-40 hover:brightness-110 transition"
          >
            {running ? "…" : "Ask"}
          </button>
        </div>

        <div className="flex flex-wrap gap-1.5">
          {SUGGESTIONS.map((s) => (
            <button
              key={s}
              onClick={() => setQuestion(s)}
              className="text-[10.5px] px-2 py-1 rounded border border-[var(--border)] text-[var(--muted)] hover:border-[var(--accent)] hover:text-[var(--foreground)] transition-colors text-left"
            >
              {s.length > 46 ? s.slice(0, 46) + "…" : s}
            </button>
          ))}
        </div>

        {steps.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {steps.map((s, i) =>
              s.type === "tool" ? (
                <span
                  key={i}
                  title={JSON.stringify(s.args)}
                  className="mono text-[10px] px-2 py-1 rounded bg-[var(--panel-2)] border border-[var(--border)] text-[var(--accent)]"
                >
                  {s.step}. {s.tool}()
                </span>
              ) : s.type === "llm_error" ? (
                <span
                  key={i}
                  className="text-[10px] px-2 py-1 rounded bg-[#e5484d1f] border border-[#e5484d55] text-[var(--bad)] max-w-full truncate"
                  title={s.error}
                >
                  {s.error?.slice(0, 120)}
                </span>
              ) : null
            )}
          </div>
        )}

        <div className="flex-1 min-h-0 overflow-y-auto bg-[var(--panel-2)] border border-[var(--border)] rounded-md p-3">
          {answer ? (
            <Markdown text={answer} />
          ) : (
            <p className="text-[12px] text-[var(--muted)]">
              {running
                ? "Working…"
                : "Answers are grounded: the loop may only cite numbers returned by the tools it called."}
            </p>
          )}
        </div>
      </div>
    </Panel>
  );
}

/** Minimal markdown: bold, bullets, paragraphs. The model's output contract
 *  only uses those three, so a full parser would be dead weight. */
function Markdown({ text }: { text: string }) {
  const bold = (s: string) =>
    s.split(/(\*\*[^*]+\*\*)/g).map((part, i) =>
      part.startsWith("**") && part.endsWith("**") ? (
        <strong key={i} className="text-[var(--foreground)] font-semibold">
          {part.slice(2, -2)}
        </strong>
      ) : (
        <span key={i}>{part}</span>
      )
    );

  return (
    <div className="text-[12.5px] leading-relaxed text-[#c2cfe0] space-y-1.5">
      {text.split("\n").map((line, i) => {
        const t = line.trim();
        if (!t) return <div key={i} className="h-1" />;
        if (/^[-*]\s/.test(t))
          return (
            <div key={i} className="flex gap-2 pl-1">
              <span className="text-[var(--accent)] mt-[3px]">·</span>
              <span>{bold(t.replace(/^[-*]\s/, ""))}</span>
            </div>
          );
        return <p key={i}>{bold(t)}</p>;
      })}
    </div>
  );
}
