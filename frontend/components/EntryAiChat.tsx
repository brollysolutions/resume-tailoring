"use client";

import { useRef, useState } from "react";
import { Sparkles, Loader2, Check, X, RefreshCw } from "lucide-react";
import type { Suggestion } from "@/types/resume";

type Section = "Experience" | "Projects";

interface EntryAiChatProps {
  section: Section;
  entryIndex: number;
  originalBullets: string[];
  /** Read-only header fields the LLM uses for grounding (not edited here). */
  headerContext: Record<string, string | undefined>;
  apiUrl: string;
  resumeId: string | null;
  jdText: string;
  acceptedSuggestions: Suggestion[];
  newProjects?: Array<{ name: string; tech: string; bullets: string[] }>;
  /** Parent emits a batch of replace suggestions and assigns IDs. */
  onEmitBatch: (suggestions: Array<Omit<Suggestion, "id">>) => void;
}

type Mode = "closed" | "prompt" | "pending" | "result";

/**
 * Sparkles affordance on the header of an Experience/Project entry. Opens a
 * chat panel where the user describes how to rewrite ALL bullets of the entry
 * as a coherent unit. On apply, emits one mode="replace" suggestion per pair
 * whose text actually changed.
 */
export function EntryAiChat({
  section,
  entryIndex,
  originalBullets,
  headerContext,
  apiUrl,
  resumeId,
  jdText,
  acceptedSuggestions,
  newProjects,
  onEmitBatch,
}: EntryAiChatProps) {
  const [mode, setMode] = useState<Mode>("closed");
  const [instruction, setInstruction] = useState("");
  const [rewritten, setRewritten] = useState<string[]>([]);
  const [selected, setSelected] = useState<boolean[]>([]);
  const [error, setError] = useState<string | null>(null);
  const lastInstructionRef = useRef("");

  const open = () => {
    setInstruction("");
    setRewritten([]);
    setSelected([]);
    setError(null);
    setMode("prompt");
  };
  const close = () => {
    setMode("closed");
    setError(null);
  };

  const submit = async (retry = false) => {
    const prompt = retry ? lastInstructionRef.current : instruction.trim();
    if (!prompt) return;
    if (!resumeId) {
      setError("No resume loaded.");
      return;
    }
    lastInstructionRef.current = prompt;
    setMode("pending");
    setError(null);
    try {
      const res = await fetch(`${apiUrl}/api/tailor/chat-entry`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: resumeId,
          jd_text: jdText,
          section,
          entry_index: entryIndex,
          original_bullets: originalBullets,
          header_context: headerContext,
          user_prompt: prompt,
          accepted_suggestions: acceptedSuggestions.map((s) => ({
            id: s.id,
            section: s.section,
            mode: s.mode,
            original: s.original,
            suggested: s.suggested,
            category: s.category,
            skill: s.skill,
            target_category: s.target_category,
            is_new_category: s.is_new_category,
          })),
          ...(newProjects && newProjects.length > 0 ? { new_projects: newProjects } : {}),
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || "Rewrite failed.");
      }
      const data = await res.json();
      const bullets: string[] = data.rewritten_bullets || [];
      // Default-checked any pair that actually changed.
      const changed = bullets.map(
        (b, i) => (b || "").trim() !== (originalBullets[i] || "").trim(),
      );
      setRewritten(bullets);
      setSelected(changed);
      setMode("result");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Rewrite failed.");
      setMode("prompt");
    }
  };

  const apply = () => {
    // We emit a single "replace_bullets" suggestion for the whole entry
    // using the user-selected subset of rewritten bullets.
    const finalBullets = rewritten.filter((_, i) => selected[i]);

    const batch: Array<Omit<Suggestion, "id">> = [
      {
        section,
        mode: "replace_bullets" as any, // Cast to any because types might not have it yet
        original: `${section}::${entryIndex}`,
        suggested: JSON.stringify(finalBullets),
        reasoning: `Coherent entry rewrite — "${lastInstructionRef.current.slice(0, 80)}"`,
      },
    ];

    onEmitBatch(batch);
    close();
  };

  const toggle = (i: number) =>
    setSelected((prev) => prev.map((v, idx) => (idx === i ? !v : v)));

  if (mode === "closed") {
    return (
      <button
        onClick={open}
        title={`AI chat — rewrite all ${section.toLowerCase()} bullets in this entry`}
        className="p-1 rounded hover:bg-primary/10 text-primary"
      >
        <Sparkles className="w-3.5 h-3.5" />
      </button>
    );
  }

  return (
    <div className="mt-1.5 border border-primary/30 bg-primary/5 rounded p-2 space-y-1.5">
      {mode === "prompt" && (
        <>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-primary">
            AI chat — rewrite this {section === "Projects" ? "project" : "role"} as a unit
          </p>
          <textarea
            autoFocus
            value={instruction}
            onChange={(e) => setInstruction(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Escape") { e.preventDefault(); close(); }
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(false); }
            }}
            rows={2}
            placeholder={
              section === "Projects"
                ? "e.g. 'emphasize distributed systems and throughput numbers'"
                : "e.g. 'tighten and focus on platform/infra ownership'"
            }
            className="w-full bg-white border border-border rounded px-2 py-1 text-xs resize-none focus:outline-none focus:border-primary"
          />
          {error && <p className="text-[11px] text-danger">{error}</p>}
          <div className="flex items-center justify-end gap-2">
            <button onClick={close} className="text-[11px] text-muted hover:text-foreground">
              Cancel
            </button>
            <button
              onClick={() => submit(false)}
              disabled={!instruction.trim()}
              className="btn-primary py-1 px-2.5 text-[11px] disabled:opacity-40"
            >
              Ask
            </button>
          </div>
        </>
      )}

      {mode === "pending" && (
        <div className="flex items-center gap-2 text-[11px] text-muted py-1">
          <Loader2 className="w-3 h-3 animate-spin" />
          Rewriting {originalBullets.length} bullets with resume + JD as context…
        </div>
      )}

      {mode === "result" && (
        <>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-primary">
            Coherent rewrite — pick which bullets to apply
          </p>
          <div className="space-y-1.5">
            {rewritten.map((b, i) => {
              const orig = originalBullets[i] || "";
              const changed = (b || "").trim() !== orig.trim();
              return (
                <div
                  key={i}
                  className={`rounded border px-2 py-1.5 text-xs ${
                    selected[i] ? "border-success/40 bg-success/5" : "border-border bg-white"
                  } ${!changed ? "opacity-60" : ""}`}
                >
                  <label className="flex items-start gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={!!selected[i]}
                      onChange={() => toggle(i)}
                      disabled={!changed}
                      className="mt-0.5"
                    />
                    <div className="min-w-0 flex-1 space-y-0.5">
                      <p className="text-muted line-through decoration-1 text-[11px]">{orig}</p>
                      <p className={changed ? "text-foreground" : "text-muted"}>
                        {b}{!changed && " (unchanged)"}
                      </p>
                    </div>
                  </label>
                </div>
              );
            })}
          </div>
          <div className="flex items-center justify-between gap-2 pt-1">
            <button
              onClick={() => submit(true)}
              className="text-[11px] text-muted hover:text-foreground inline-flex items-center gap-1"
            >
              <RefreshCw className="w-3 h-3" /> Try again
            </button>
            <div className="flex items-center gap-2">
              <button onClick={close} className="btn-ghost py-1 px-2.5 text-[11px]">
                <X className="w-3 h-3" /> Discard
              </button>
              <button
                onClick={apply}
                disabled={!selected.some(Boolean)}
                className="btn-primary py-1 px-2.5 text-[11px] disabled:opacity-40"
              >
                <Check className="w-3 h-3" /> Apply {selected.filter(Boolean).length} change{selected.filter(Boolean).length !== 1 ? "s" : ""}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
