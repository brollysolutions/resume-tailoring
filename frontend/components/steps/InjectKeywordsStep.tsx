"use client";

import { useState } from "react";
import { ArrowRight, Check } from "lucide-react";
import type { Suggestion } from "@/types/resume";

const NEW_CATEGORY_SENTINEL = "__NEW__";

interface InjectKeywordsStepProps {
  fallbackKeywords: string[];
  existingCategories: string[];
  nextSuggestionId: number;
  onInject: (skillSuggestions: Suggestion[]) => void;
  onContinue: () => void;
  onSkip: () => void;
  continueLabel: string;
}

export function InjectKeywordsStep({
  fallbackKeywords, existingCategories, nextSuggestionId,
  onInject, onContinue, onSkip, continueLabel,
}: InjectKeywordsStepProps) {
  const [selected, setSelected] = useState<Record<string, boolean>>({});
  const [routes, setRoutes] = useState<Record<string, { category: string; newName: string }>>({});
  const [injected, setInjected] = useState(false);

  const defaultCategory = existingCategories[0] || NEW_CATEGORY_SENTINEL;

  const toggle = (kw: string) => {
    setSelected((prev) => {
      const next = { ...prev, [kw]: !prev[kw] };
      if (next[kw] && !routes[kw]) {
        setRoutes((r) => ({ ...r, [kw]: { category: defaultCategory, newName: "Additional Skills" } }));
      }
      return next;
    });
  };

  const setRouteCategory = (kw: string, value: string) => {
    setRoutes((prev) => ({ ...prev, [kw]: { category: value, newName: prev[kw]?.newName || "Additional Skills" } }));
  };

  const setRouteNewName = (kw: string, value: string) => {
    setRoutes((prev) => ({ ...prev, [kw]: { category: prev[kw]?.category || NEW_CATEGORY_SENTINEL, newName: value } }));
  };

  const selectedCount = Object.values(selected).filter(Boolean).length;

  const handleInject = () => {
    let id = nextSuggestionId;
    const skillSuggestions: Suggestion[] = fallbackKeywords
      .filter((kw) => selected[kw])
      .map((kw) => {
        const route = routes[kw] || { category: defaultCategory, newName: "Additional Skills" };
        const isNew = route.category === NEW_CATEGORY_SENTINEL;
        const catName = isNew ? (route.newName.trim() || "Additional Skills") : route.category;
        return {
          id: id++,
          section: "Skills",
          mode: "add_skill" as const,
          skill: kw,
          category: isNew ? "" : catName,
          target_category: isNew ? catName : "",
          is_new_category: isNew,
          reasoning: `Job Description keyword missing from resume — adding to "${catName}".`,
        };
      });
    if (skillSuggestions.length > 0) {
      onInject(skillSuggestions);
    }
    setInjected(true);
  };

  if (fallbackKeywords.length === 0) {
    return (
      <div className="space-y-3">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Missing keywords</h3>
        <div className="card p-6 text-center">
          <p className="text-sm text-muted">No leftover Job Description keywords — the tailored sections covered everything.</p>
        </div>
        <div className="flex justify-end pt-2">
          <button onClick={onContinue} className="btn-primary">
            {continueLabel}<ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Inject missing keywords</h3>
        <span className="text-xs text-muted tabular-nums">{selectedCount} / {fallbackKeywords.length} selected</span>
      </div>

      <p className="text-xs text-muted">
        Job Description-required hard skills missing from your resume. Pick the ones you actually
        have experience with and route each to an existing Skills category or create a new one.
      </p>

      <div className="card p-3 space-y-2">
        {fallbackKeywords.map((kw) => {
          const isSelected = !!selected[kw];
          const route = routes[kw] || { category: defaultCategory, newName: "Additional Skills" };
          const isNew = route.category === NEW_CATEGORY_SENTINEL;
          return (
            <div
              key={kw}
              className={`flex items-center gap-2 flex-wrap rounded border px-2 py-1.5 ${
                isSelected ? "border-success/40 bg-success/5" : "border-border bg-subtle/30"
              } ${injected ? "opacity-60" : ""}`}
            >
              <button
                type="button"
                onClick={() => toggle(kw)}
                disabled={injected}
                className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-mono border transition-colors ${
                  isSelected
                    ? "bg-success/15 text-success border-success/40"
                    : "bg-white text-muted border-border hover:border-foreground/40"
                }`}
              >
                {isSelected && <Check className="w-3 h-3" />}
                {kw}
              </button>
              {isSelected && (
                <>
                  <span className="text-[11px] text-muted">→</span>
                  <select
                    value={route.category}
                    onChange={(e) => setRouteCategory(kw, e.target.value)}
                    disabled={injected}
                    className="input text-xs py-1 px-2 min-w-[10rem]"
                  >
                    {existingCategories.map((c) => (
                      <option key={c} value={c}>{c}</option>
                    ))}
                    <option value={NEW_CATEGORY_SENTINEL}>+ Create new category…</option>
                  </select>
                  {isNew && (
                    <input
                      type="text"
                      value={route.newName}
                      onChange={(e) => setRouteNewName(kw, e.target.value)}
                      disabled={injected}
                      placeholder="New category name"
                      className="input text-xs py-1 px-2 min-w-[10rem]"
                    />
                  )}
                </>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex items-center justify-between pt-2 gap-3 flex-wrap">
        <button onClick={onSkip} className="text-xs text-muted hover:text-foreground transition-colors">
          Skip — don&apos;t inject any
        </button>
        <div className="flex items-center gap-2">
          {!injected && (
            <button onClick={handleInject} disabled={selectedCount === 0} className="btn-secondary">
              Inject {selectedCount} skill{selectedCount !== 1 ? "s" : ""}
            </button>
          )}
          <button onClick={onContinue} className="btn-primary">
            {continueLabel}<ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
