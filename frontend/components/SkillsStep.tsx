"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { ArrowRight, Check, Pencil, Plus, Trash2, X } from "lucide-react";
import type { SkillCategory, SkillSuggestion, SkillSuggestionMode } from "@/lib/skills";

// SkillsStep operates on the explicit-field Skills schema (no original/suggested).
export interface Suggestion {
  id: number;
  section: string;
  reasoning?: string;
  mode?: SkillSuggestionMode;
  category?: string;
  skill?: string;
  target_category?: string;
  is_new_category?: boolean;
}

interface SkillsStepProps {
  resumeSkills: SkillCategory[]; // post-approved state (parent computes)
  pendingSuggestions: Suggestion[]; // section === "Skills" not yet approved
  nextSuggestionId: number;
  onAcceptPending: (id: number, edited: string) => void;
  onRejectPending: (id: number) => void;
  onAddApproved: (s: Suggestion) => void;
  onContinue: () => void;
  onSkip: () => void;
  continueLabel: string;
}

const sameCat = (a: string, b: string) =>
  (a || "").trim().toLowerCase() === (b || "").trim().toLowerCase();

export function SkillsStep({
  resumeSkills,
  pendingSuggestions,
  nextSuggestionId,
  onAcceptPending,
  onRejectPending,
  onAddApproved,
  onContinue,
  onSkip,
  continueLabel,
}: SkillsStepProps) {
  const [renamingCat, setRenamingCat] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [addingSkillFor, setAddingSkillFor] = useState<string | null>(null);
  const [skillDraft, setSkillDraft] = useState("");
  const [showNewCatForm, setShowNewCatForm] = useState(false);
  const [newCatName, setNewCatName] = useState("");
  const [newCatSkill, setNewCatSkill] = useState("");

  // ID factory — ref so synchronous loop calls each get a unique id.
  const idSeedRef = useRef<number>(nextSuggestionId);
  useEffect(() => {
    idSeedRef.current = Math.max(idSeedRef.current, nextSuggestionId);
  }, [nextSuggestionId]);
  const nextId = () => idSeedRef.current++;

  // Bucket pending suggestions by destination:
  //   - buckets[catLower]    suggestions on an EXISTING resume category
  //   - newCatGroups[name]   add_skill with is_new_category=true, grouped by
  //                          target_category so the user sees a whole proposed
  //                          subsection as one recommendation
  //   - other                anything that doesn't bind to a known category
  const suggestionsByCat = useMemo(() => {
    const buckets: Record<string, Suggestion[]> = {};
    const newCatGroups: Record<string, Suggestion[]> = {};
    const other: Suggestion[] = [];
    const existingLower = new Set(resumeSkills.map((c) => c.category.toLowerCase()));

    for (const s of pendingSuggestions) {
      const mode = s.mode;
      const category = (s.category || "").trim();
      const targetCategory = (s.target_category || "").trim();

      // add_skill with new category → grouped as new subsection.
      if (mode === "add_skill" && s.is_new_category && targetCategory) {
        (newCatGroups[targetCategory] ||= []).push(s);
        continue;
      }

      // Source category we should bucket against.
      let cat: string | null = null;
      if (
        mode === "add_skill" ||
        mode === "remove_skill" ||
        mode === "rename_category" ||
        mode === "delete_category" ||
        mode === "move_skill"
      ) {
        cat = category;
      }

      if (cat && existingLower.has(cat.toLowerCase())) {
        (buckets[cat.toLowerCase()] ||= []).push(s);
      } else {
        other.push(s);
      }
    }
    return { buckets, newCatGroups, other };
  }, [pendingSuggestions, resumeSkills]);

  // ---- direct-edit actions emit pre-approved Suggestion objects ----

  const emitRemoveSkill = (category: string, skill: string) => {
    onAddApproved({
      id: nextId(),
      section: "Skills",
      mode: "remove_skill",
      category,
      skill,
      reasoning: "User removed.",
    });
  };

  const emitRenameCategory = (oldName: string, newName: string) => {
    if (!newName.trim() || sameCat(oldName, newName)) return;
    onAddApproved({
      id: nextId(),
      section: "Skills",
      mode: "rename_category",
      category: oldName,
      target_category: newName.trim(),
      reasoning: "User renamed category.",
    });
  };

  const emitDeleteCategory = (category: string) => {
    onAddApproved({
      id: nextId(),
      section: "Skills",
      mode: "delete_category",
      category,
      reasoning: "User deleted category.",
    });
  };

  const emitAddSkill = (category: string, skill: string, isNew = false) => {
    if (!skill.trim()) return;
    onAddApproved({
      id: nextId(),
      section: "Skills",
      mode: "add_skill",
      skill: skill.trim(),
      category: isNew ? "" : category,
      target_category: isNew ? category : "",
      is_new_category: isNew,
      reasoning: "User added.",
    });
  };

  // ---- handlers ----

  const startRename = (cat: string) => {
    setRenamingCat(cat);
    setRenameDraft(cat);
  };

  const commitRename = () => {
    if (renamingCat) emitRenameCategory(renamingCat, renameDraft);
    setRenamingCat(null);
    setRenameDraft("");
  };

  const startAddSkill = (cat: string) => {
    setAddingSkillFor(cat);
    setSkillDraft("");
  };

  const commitAddSkill = (cat: string) => {
    if (skillDraft.trim()) emitAddSkill(cat, skillDraft);
    setAddingSkillFor(null);
    setSkillDraft("");
  };

  const commitNewCategory = () => {
    const name = newCatName.trim();
    const skill = newCatSkill.trim();
    if (!name || !skill) return;
    emitAddSkill(name, skill, true);
    setShowNewCatForm(false);
    setNewCatName("");
    setNewCatSkill("");
  };

  // ---- render ----

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">
          Skills
        </h3>
        <button
          onClick={() => setShowNewCatForm((x) => !x)}
          className="inline-flex items-center gap-1 text-xs text-muted hover:text-foreground transition-colors"
        >
          <Plus className="w-3 h-3" /> Add category
        </button>
      </div>

      {showNewCatForm && (
        <div className="card p-3 space-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
            New category
          </p>
          <div className="flex gap-2 flex-wrap">
            <input
              autoFocus
              value={newCatName}
              onChange={(e) => setNewCatName(e.target.value)}
              placeholder="Category name (e.g. Cloud & DevOps)"
              className="input text-sm py-1 px-2 flex-1 min-w-[12rem]"
            />
            <input
              value={newCatSkill}
              onChange={(e) => setNewCatSkill(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && commitNewCategory()}
              placeholder="First skill"
              className="input text-sm py-1 px-2 flex-1 min-w-[10rem]"
            />
            <button onClick={commitNewCategory} className="btn-primary py-1.5 px-3 text-xs">
              <Check className="w-3.5 h-3.5" /> Create
            </button>
            <button
              onClick={() => {
                setShowNewCatForm(false);
                setNewCatName("");
                setNewCatSkill("");
              }}
              className="btn-ghost py-1.5 px-2 text-xs"
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {resumeSkills.length === 0 ? (
        <div className="card p-6 text-center">
          <p className="text-sm text-muted">No skill categories yet. Add one above.</p>
        </div>
      ) : (
        resumeSkills.map((cat) => {
          const isRenaming = renamingCat === cat.category;
          const isAdding = addingSkillFor === cat.category;
          const catSuggestions =
            suggestionsByCat.buckets[cat.category.toLowerCase()] || [];

          return (
            <div key={cat.category} className="card p-3 space-y-2">
              <div className="flex items-start justify-between gap-2">
                {isRenaming ? (
                  <div className="flex items-center gap-1 flex-1">
                    <input
                      autoFocus
                      value={renameDraft}
                      onChange={(e) => setRenameDraft(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === "Enter") commitRename();
                        if (e.key === "Escape") {
                          setRenamingCat(null);
                          setRenameDraft("");
                        }
                      }}
                      onBlur={commitRename}
                      className="input text-sm font-semibold py-1 px-2 flex-1"
                    />
                  </div>
                ) : (
                  <p className="text-sm font-semibold flex-1">{cat.category}</p>
                )}
                <div className="flex items-center gap-1 shrink-0">
                  {!isRenaming && (
                    <button
                      onClick={() => startRename(cat.category)}
                      className="btn-ghost p-1.5"
                      title="Rename category"
                    >
                      <Pencil className="w-3 h-3" />
                    </button>
                  )}
                  <button
                    onClick={() => emitDeleteCategory(cat.category)}
                    className="btn-ghost p-1.5 hover:text-danger"
                    title="Delete entire category"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              </div>

              <div className="flex flex-wrap gap-1.5">
                {cat.skills.map((skill) => (
                  <span
                    key={skill}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-subtle border border-border"
                  >
                    {skill}
                    <button
                      onClick={() => emitRemoveSkill(cat.category, skill)}
                      className="text-muted hover:text-danger ml-0.5"
                      title="Remove skill"
                    >
                      <X className="w-3 h-3" />
                    </button>
                  </span>
                ))}
                {isAdding ? (
                  <input
                    autoFocus
                    value={skillDraft}
                    onChange={(e) => setSkillDraft(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter") commitAddSkill(cat.category);
                      if (e.key === "Escape") {
                        setAddingSkillFor(null);
                        setSkillDraft("");
                      }
                    }}
                    onBlur={() => commitAddSkill(cat.category)}
                    placeholder="New skill"
                    className="input text-xs py-0.5 px-2 w-32"
                  />
                ) : (
                  <button
                    onClick={() => startAddSkill(cat.category)}
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs border border-dashed border-border text-muted hover:text-foreground hover:border-foreground/40"
                  >
                    <Plus className="w-3 h-3" /> skill
                  </button>
                )}
              </div>

              {catSuggestions.length > 0 && (() => {
                const adds = catSuggestions.filter((s) => s.mode === "add_skill");
                const others = catSuggestions.filter((s) => s.mode !== "add_skill");
                return (
                  <div className="border-t border-border/60 pt-2 space-y-2">
                    {adds.length > 0 && (
                      <div className="space-y-1">
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted">
                          Suggested to add — based on your tailored resume + Job Description
                        </p>
                        <div className="flex flex-wrap gap-1.5">
                          {adds.map((s) => (
                            <button
                              key={s.id}
                              onClick={() => {
                                onAcceptPending(s.id, "");
                              }}
                              title={`Add "${s.skill}" to ${cat.category}`}
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] border border-dashed border-primary/50 text-primary bg-primary/5 hover:bg-primary/10 hover:border-primary transition-colors"
                            >
                              <Plus className="w-2.5 h-2.5" />
                              {s.skill}
                              <button
                                onClick={(e) => { e.stopPropagation(); onRejectPending(s.id); }}
                                className="ml-0.5 text-muted hover:text-danger"
                                title="Dismiss"
                              >
                                <X className="w-2.5 h-2.5" />
                              </button>
                            </button>
                          ))}
                        </div>
                      </div>
                    )}
                    {others.length > 0 && (
                      <div className="space-y-1.5">
                        <p className="text-[10px] font-semibold uppercase tracking-wider text-muted">
                          Other suggestions
                        </p>
                        {others.map((s) => (
                          <SuggestionRow
                            key={s.id}
                            s={s}
                            onAccept={() => onAcceptPending(s.id, "")}
                            onReject={() => onRejectPending(s.id)}
                          />
                        ))}
                      </div>
                    )}
                  </div>
                );
              })()}
            </div>
          );
        })
      )}

      {Object.keys(suggestionsByCat.newCatGroups).length > 0 && (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
            Recommended new subsections
          </p>
          {Object.entries(suggestionsByCat.newCatGroups).map(([name, items]) => (
            <div key={name} className="card p-3 space-y-2 border-success/30 bg-success/5">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold">
                  + {name}{" "}
                  <span className="text-[11px] font-normal text-muted">
                    ({items.length} skill{items.length !== 1 ? "s" : ""})
                  </span>
                </p>
                <div className="flex items-center gap-1">
                  <button
                    onClick={() => items.forEach((s) => onAcceptPending(s.id, ""))}
                    className="btn-primary py-1 px-2 text-[11px]"
                  >
                    <Check className="w-3 h-3" /> Accept all
                  </button>
                  <button
                    onClick={() => items.forEach((s) => onRejectPending(s.id))}
                    className="btn-ghost py-1 px-2 text-[11px]"
                  >
                    <X className="w-3 h-3" /> Dismiss
                  </button>
                </div>
              </div>
              <ul className="space-y-1">
                {items.map((s) => (
                  <li key={s.id} className="flex items-center justify-between gap-2 text-xs">
                    <span className="font-mono">{s.skill}</span>
                    <div className="flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => onRejectPending(s.id)}
                        className="btn-ghost py-0.5 px-1.5 text-[10px]"
                        title="Reject this skill"
                      >
                        <X className="w-3 h-3" />
                      </button>
                      <button
                        onClick={() => onAcceptPending(s.id, "")}
                        className="btn-primary py-0.5 px-1.5 text-[10px]"
                      >
                        <Check className="w-3 h-3" />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
              {items[0]?.reasoning && (
                <p className="text-[10px] text-muted">{items[0].reasoning}</p>
              )}
            </div>
          ))}
        </div>
      )}

      {suggestionsByCat.other.length > 0 && (
        <div className="card p-3 space-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">
            Other suggestions
          </p>
          {suggestionsByCat.other.map((s) => (
            <SuggestionRow
              key={s.id}
              s={s}
              onAccept={() => onAcceptPending(s.id, "")}
              onReject={() => onRejectPending(s.id)}
            />
          ))}
        </div>
      )}

      <div className="flex items-center justify-between pt-2">
        <button onClick={onSkip} className="text-xs text-muted hover:text-foreground transition-colors">
          Skip section
        </button>
        <button onClick={onContinue} className="btn-primary">
          {continueLabel}
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

function SuggestionRow({
  s,
  onAccept,
  onReject,
}: {
  s: Suggestion;
  onAccept: () => void;
  onReject: () => void;
}) {
  const mode = s.mode;
  const category = s.category || "";
  const skill = s.skill || "";
  const target = s.target_category || "";
  const isNew = !!s.is_new_category;
  const label =
    mode === "add_skill"
      ? `Add "${skill}"${isNew && target ? ` to new "${target}"` : category ? ` to "${category}"` : ""}`
      : mode === "remove_skill"
      ? `Remove "${skill}" from "${category}"`
      : mode === "rename_category"
      ? `Rename category "${category}" → "${target}"`
      : mode === "delete_category"
      ? `Delete category "${category}"`
      : mode === "move_skill"
      ? `Move "${skill}" from "${category}" → "${target}"${isNew ? " (new)" : ""}`
      : `${category || skill}`;

  return (
    <div className="flex items-center justify-between gap-2 text-xs">
      <div className="min-w-0 flex-1">
        <p className="truncate">{label}</p>
        {s.reasoning && (
          <p className="text-[10px] text-muted truncate" title={s.reasoning}>
            {s.reasoning}
          </p>
        )}
      </div>
      <div className="flex items-center gap-1 shrink-0">
        <button onClick={onReject} className="btn-ghost py-1 px-2 text-[11px]">
          <X className="w-3 h-3" /> Reject
        </button>
        <button onClick={onAccept} className="btn-primary py-1 px-2 text-[11px]">
          <Check className="w-3 h-3" /> Accept
        </button>
      </div>
    </div>
  );
}

export type { SkillSuggestion };
