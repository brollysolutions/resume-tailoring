"use client";

import { useRef, useState } from "react";
import { Sparkles, Loader2, Check, X, RefreshCw } from "lucide-react";
import type { Suggestion } from "@/types/resume";

interface SkillsAiChatProps {
  apiUrl: string;
  resumeId: string | null;
  jdText: string;
  acceptedSuggestions: Suggestion[];
  newProjects?: Array<{ name: string; tech: string; bullets: string[] }>;
  nextSuggestionId: number;
  onEmitBatch: (suggestions: Array<Omit<Suggestion, "id">>) => void;
}

type Mode = "closed" | "prompt" | "pending" | "result";

interface SkillsSuggestion {
  id?: number;
  section?: string;
  mode?: string;
  category?: string;
  skill?: string;
  target_category?: string;
  is_new_category?: boolean;
  reasoning?: string;
}

/**
 * Header-level affordance for the Skills section. Re-runs the Skills tailor
 * against the LATEST tailored resume (post-accepted-edits + kept projects) with
 * an optional user instruction. Surfaces the returned suggestions as a checklist
 * so the user picks which ones to apply.
 */
export function SkillsAiChat({
  apiUrl,
  resumeId,
  jdText,
  acceptedSuggestions,
  newProjects,
  nextSuggestionId,
  onEmitBatch,
}: SkillsAiChatProps) {
  const [mode, setMode] = useState<Mode>("closed");
  const [instruction, setInstruction] = useState("");
  const [suggestions, setSuggestions] = useState<SkillsSuggestion[]>([]);
  const [selected, setSelected] = useState<boolean[]>([]);
  const [error, setError] = useState<string | null>(null);
  const lastInstructionRef = useRef("");

  const open = () => {
    setInstruction("");
    setSuggestions([]);
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
    if (!resumeId) {
      setError("No resume loaded.");
      return;
    }
    lastInstructionRef.current = prompt;
    setMode("pending");
    setError(null);
    try {
      const res = await fetch(`${apiUrl}/api/tailor/refresh-skills`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: resumeId,
          jd_text: jdText,
          accepted_suggestions: acceptedSuggestions.map((s) => ({
            id: s.id,
            section: s.section,
            mode: s.mode,
            // Non-Skills fields
            original: s.original,
            suggested: s.suggested,
            // Skills explicit-field schema
            category: s.category,
            skill: s.skill,
            target_category: s.target_category,
            is_new_category: s.is_new_category,
          })),
          ...(newProjects && newProjects.length > 0 ? { new_projects: newProjects } : {}),
          next_id: nextSuggestionId,
          user_prompt: prompt || null,
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || "Re-tailor failed.");
      }
      const data = await res.json();
      const list: SkillsSuggestion[] = data.suggestions || [];
      setSuggestions(list);
      setSelected(list.map(() => true));
      setMode("result");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Re-tailor failed.");
      setMode("prompt");
    }
  };

  const apply = () => {
    const batch: Array<Omit<Suggestion, "id">> = [];
    suggestions.forEach((s, i) => {
      if (!selected[i]) return;
      batch.push({
        section: "Skills",
        mode: (s.mode as Suggestion["mode"]) || "add_skill",
        category: s.category,
        skill: s.skill,
        target_category: s.target_category,
        is_new_category: s.is_new_category,
        reasoning: s.reasoning || "Skills re-tailor",
      });
    });
    if (batch.length > 0) onEmitBatch(batch);
    close();
  };

  const toggle = (i: number) =>
    setSelected((prev) => prev.map((v, idx) => (idx === i ? !v : v)));

  const modeLabel = (m?: string) => {
    switch (m) {
      case "add_skill": return "ADD";
      case "remove_skill": return "REMOVE";
      case "delete_category": return "DELETE";
      case "rename_category": return "RENAME";
      case "move_skill": return "MOVE";
      default: return (m || "").toUpperCase();
    }
  };

  const modeClass = (m?: string) => {
    switch (m) {
      case "add_skill": return "bg-success/10 text-success border-success/30";
      case "delete_category": return "bg-danger/10 text-danger border-danger/30";
      case "remove_skill": return "bg-danger/10 text-danger border-danger/30";
      case "move_skill": return "bg-primary/10 text-primary border-primary/30";
      case "rename_category": return "bg-amber-50 text-amber-700 border-amber-200";
      default: return "bg-subtle text-muted border-border";
    }
  };

  const describe = (s: SkillsSuggestion): string => {
    const category = s.category || "";
    const skill = s.skill || "";
    const target = s.target_category || "";
    const isNew = !!s.is_new_category;
    switch (s.mode) {
      case "add_skill":
        return `Add "${skill}"${isNew && target ? ` to new "${target}"` : category ? ` to "${category}"` : ""}`;
      case "remove_skill":
        return `Remove "${skill}" from "${category}"`;
      case "rename_category":
        return `"${category}" → "${target}"`;
      case "delete_category":
        return `Delete "${category}"`;
      case "move_skill":
        return `Move "${skill}": "${category}" → "${target}"${isNew ? " (new)" : ""}`;
      default:
        return `${category || skill}`;
    }
  };

  if (mode === "closed") {
    return (
      <button
        onClick={open}
        title="Re-tailor skills with AI against the latest tailored resume"
        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium text-primary border border-primary/30 hover:bg-primary/10 transition-colors"
      >
        <Sparkles className="w-3 h-3" /> Re-tailor with AI
      </button>
    );
  }

  return (
    <div className="mt-1 border border-primary/30 bg-primary/5 rounded p-2 space-y-1.5">
      {mode === "prompt" && (
        <>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-primary">
            Re-tailor skills against your latest tailored resume
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
            placeholder="Optional steering — e.g. 'focus on data-engineering tools, split frontend off'"
            className="w-full bg-white border border-border rounded px-2 py-1 text-xs resize-none focus:outline-none focus:border-primary"
          />
          {error && <p className="text-[11px] text-danger">{error}</p>}
          <div className="flex items-center justify-end gap-2">
            <button onClick={close} className="text-[11px] text-muted hover:text-foreground">
              Cancel
            </button>
            <button
              onClick={() => submit(false)}
              className="btn-primary py-1 px-2.5 text-[11px]"
            >
              Re-tailor
            </button>
          </div>
        </>
      )}

      {mode === "pending" && (
        <div className="flex items-center gap-2 text-[11px] text-muted py-1">
          <Loader2 className="w-3 h-3 animate-spin" />
          Re-tailoring skills using tailored experience + projects as evidence…
        </div>
      )}

      {mode === "result" && (
        <>
          <p className="text-[10px] font-semibold uppercase tracking-wider text-primary">
            {suggestions.length === 0
              ? "No new skill changes proposed"
              : `Pick which of ${suggestions.length} skill change${suggestions.length !== 1 ? "s" : ""} to apply`}
          </p>
          {suggestions.length === 0 ? (
            <p className="text-[11px] text-muted">
              The model thinks your skills are already JD-aligned. Try a different instruction, or close this panel.
            </p>
          ) : (
            <div className="space-y-1 max-h-64 overflow-y-auto scrollbar-thin">
              {suggestions.map((s, i) => (
                <div
                  key={i}
                  className={`rounded border px-2 py-1.5 text-xs ${
                    selected[i] ? "border-success/40 bg-success/5" : "border-border bg-white"
                  }`}
                >
                  <label className="flex items-start gap-2 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={!!selected[i]}
                      onChange={() => toggle(i)}
                      className="mt-0.5"
                    />
                    <div className="min-w-0 flex-1 space-y-0.5">
                      <div className="flex items-center gap-1.5 flex-wrap">
                        <span className={`inline-block px-1 py-0.5 rounded text-[9px] font-semibold border ${modeClass(s.mode)}`}>
                          {modeLabel(s.mode)}
                        </span>
                        <span className="text-[11px] font-medium">
                          {describe(s)}
                        </span>
                      </div>
                      {s.reasoning && (
                        <p className="text-[10px] text-muted leading-snug">{s.reasoning}</p>
                      )}
                    </div>
                  </label>
                </div>
              ))}
            </div>
          )}
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
              {suggestions.length > 0 && (
                <button
                  onClick={apply}
                  disabled={!selected.some(Boolean)}
                  className="btn-primary py-1 px-2.5 text-[11px] disabled:opacity-40"
                >
                  <Check className="w-3 h-3" /> Apply {selected.filter(Boolean).length}
                </button>
              )}
            </div>
          </div>
        </>
      )}
    </div>
  );
}
