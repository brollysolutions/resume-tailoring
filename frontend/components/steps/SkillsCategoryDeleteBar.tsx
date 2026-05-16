"use client";

import type { Suggestion } from "@/types/resume";

interface SkillsCategoryDeleteBarProps {
  existingCategories: string[];
  approvedDeletes: string[];
  nextSuggestionId: number;
  onDelete: (suggestion: Suggestion) => void;
  onRestore: (category: string) => void;
}

export function SkillsCategoryDeleteBar({
  existingCategories, approvedDeletes, nextSuggestionId, onDelete, onRestore,
}: SkillsCategoryDeleteBarProps) {
  if (existingCategories.length === 0) return null;
  const deletedLower = new Set(approvedDeletes.map((c) => c.toLowerCase()));

  return (
    <div className="card p-3 mb-3">
      <p className="text-[11px] font-semibold uppercase tracking-wider text-muted mb-2">
        Existing skill categories
      </p>
      <div className="flex flex-wrap gap-1.5">
        {existingCategories.map((cat) => {
          const pending = deletedLower.has(cat.toLowerCase());
          if (pending) {
            return (
              <button
                key={cat}
                onClick={() => onRestore(cat)}
                className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs border border-danger/40 bg-danger/10 text-danger line-through hover:bg-danger/20 transition-colors"
                title="Undo delete"
              >
                {cat}
                <span className="no-underline">↺</span>
              </button>
            );
          }
          return (
            <button
              key={cat}
              onClick={() =>
                onDelete({
                  id: nextSuggestionId,
                  section: "Skills",
                  mode: "delete_category",
                  category: cat,
                  reasoning: `Remove the "${cat}" category from the resume.`,
                })
              }
              className="inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs border border-border bg-subtle hover:border-danger/40 hover:text-danger transition-colors"
              title="Delete this category"
            >
              {cat}
              <span className="text-muted">×</span>
            </button>
          );
        })}
      </div>
      <p className="text-[10px] text-muted mt-2">
        Click × to mark a category for removal. The change is applied when you finish tailoring.
      </p>
    </div>
  );
}
