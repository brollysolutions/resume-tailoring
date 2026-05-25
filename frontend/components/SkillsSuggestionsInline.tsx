"use client";

import { useState } from "react";
import { Sparkles, Loader2, Plus, X, ChevronDown, ChevronUp } from "lucide-react";
import type { Suggestion } from "@/types/resume";

interface SkillsSuggestionsInlineProps {
  apiUrl: string;
  resumeId: string | null;
  jdText: string;
  acceptedSuggestions: Suggestion[];
  newProjects?: Array<{ name: string; tech: string; bullets: string[] }>;
  nextSuggestionId: number;
  onEmitBatch: (suggestions: Array<Omit<Suggestion, "id">>) => void;
}

interface SkillItem {
  mode: "add_skill" | "delete_category";
  // For add_skill: skill = what to add, category = existing dest (or empty if new),
  //                target_category + is_new_category for new-cat adds.
  // For delete_category: category = which category to drop.
  category?: string;
  skill?: string;
  target_category?: string;
  is_new_category?: boolean;
  reasoning: string;
  applied?: boolean;
}

export function SkillsSuggestionsInline({
  apiUrl,
  resumeId,
  jdText,
  acceptedSuggestions,
  newProjects,
  nextSuggestionId,
  onEmitBatch,
}: SkillsSuggestionsInlineProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [items, setItems] = useState<SkillItem[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState(false);

  const load = async () => {
    if (loaded) {
      setOpen((v) => !v);
      return;
    }
    if (!resumeId) return;
    setOpen(true);
    setLoading(true);
    setError(null);
    try {
      let intensity = "balanced";
      let sectionIntensities = null;
      if (typeof window !== "undefined") {
        intensity = localStorage.getItem("tailor_intensity") || "balanced";
        const saved = localStorage.getItem("tailor_section_intensities");
        if (saved) {
          try {
            sectionIntensities = JSON.parse(saved);
          } catch (e) {}
        }
      }
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
            original: s.original,
            suggested: s.suggested,
            category: s.category,
            skill: s.skill,
            target_category: s.target_category,
            is_new_category: s.is_new_category,
            new_skills: s.new_skills,
          })),
          ...(newProjects && newProjects.length > 0 ? { new_projects: newProjects } : {}),
          next_id: nextSuggestionId,
          user_prompt: null,
          intensity,
          section_intensities: sectionIntensities,
        }),
      });
      if (!res.ok) throw new Error("Failed to load skills.");
      const data = await res.json();
      const raw = data.suggestions || [];
      // Only keep add_skill and delete_category — no rename/move for this UI
      const filtered: SkillItem[] = raw
        .filter((s: any) => s.mode === "add_skill" || s.mode === "delete_category")
        .map((s: any) => ({
          mode: s.mode,
          category: s.category || "",
          skill: s.skill || "",
          target_category: s.target_category || "",
          is_new_category: !!s.is_new_category,
          reasoning: s.reasoning || "",
          applied: false,
        }));
      setItems(filtered);
      setLoaded(true);
    } catch (e: any) {
      setError(e.message || "Something went wrong.");
    } finally {
      setLoading(false);
    }
  };

  const applyOne = (idx: number) => {
    const item = items[idx];
    if (!item || item.applied) return;
    onEmitBatch([{
      section: "Skills",
      mode: item.mode,
      category: item.category,
      skill: item.skill,
      target_category: item.target_category,
      is_new_category: item.is_new_category,
      reasoning: item.reasoning,
    }]);
    setItems((prev) => prev.map((it, i) => i === idx ? { ...it, applied: true } : it));
  };

  const toAdd = items.filter((it) => it.mode === "add_skill");
  const toRemove = items.filter((it) => it.mode === "delete_category");
  const toAddIdx = (localIdx: number) => items.indexOf(toAdd[localIdx]);
  const toRemoveIdx = (localIdx: number) => items.indexOf(toRemove[localIdx]);

  return (
    <div>
      <button
        onClick={load}
        className="inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-primary border border-primary/30 hover:bg-primary/10 transition-colors"
      >
        {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : <Sparkles className="w-3 h-3" />}
        AI Skills
        {open && !loading ? <ChevronUp className="w-3 h-3 ml-0.5" /> : <ChevronDown className="w-3 h-3 ml-0.5" />}
      </button>

      {open && (
        <div className="mt-2 border border-border rounded-md p-3 bg-subtle/30 space-y-3">
          {loading ? (
            <div className="space-y-3 animate-pulse select-none">
              <div>
                <div className="h-3 bg-muted/40 rounded w-1/3 mb-2" />
                <div className="flex flex-wrap gap-1.5">
                  {[1, 2, 3, 4, 5].map((i) => (
                    <div key={i} className="h-6 bg-muted/20 rounded w-16" />
                  ))}
                </div>
              </div>
            </div>
          ) : (
            <>
              {error && <p className="text-xs text-danger">{error}</p>}

              {!error && items.length === 0 && loaded && (
                <p className="text-xs text-success">Skills already aligned with the JD.</p>
              )}

          {toAdd.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-success mb-1.5">
                Add to resume — JD requires these:
              </p>
              <div className="flex flex-wrap gap-1.5">
                {toAdd.map((it, i) => {
                  const dest = it.is_new_category && it.target_category ? it.target_category : it.category;
                  return (
                    <button
                      key={`add-${i}-${it.skill}`}
                      onClick={() => applyOne(toAddIdx(i))}
                      disabled={it.applied}
                      title={it.applied ? "Added" : `Add "${it.skill}" to ${dest}${it.is_new_category ? " (new)" : ""}`}
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs border transition-colors ${
                        it.applied
                          ? "bg-success/10 text-success border-success/30 opacity-60 cursor-default"
                          : "bg-white text-foreground border-border hover:border-success hover:text-success hover:bg-success/5 cursor-pointer"
                      }`}
                    >
                      {it.applied ? "✓" : <Plus className="w-3 h-3" />}
                      {it.skill}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {toRemove.length > 0 && (
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-danger mb-1.5">
                Remove from resume — not needed for this JD:
              </p>
              <div className="flex flex-wrap gap-1.5">
                {toRemove.map((it, i) => (
                  <button
                    key={`del-${i}-${it.category}`}
                    onClick={() => applyOne(toRemoveIdx(i))}
                    disabled={it.applied}
                    title={it.applied ? "Removed" : `Remove "${it.category}" category`}
                    className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs border transition-colors ${
                      it.applied
                        ? "bg-danger/10 text-danger border-danger/30 opacity-60 cursor-default line-through"
                        : "bg-white text-foreground border-border hover:border-danger hover:text-danger hover:bg-danger/5 cursor-pointer"
                    }`}
                  >
                    {it.applied ? "✓" : <X className="w-3 h-3" />}
                    {it.category}
                  </button>
                ))}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )}
</div>
  );
}
