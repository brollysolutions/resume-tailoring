"use client";

/**
 * Skills section — replaces the inline Skills editor in ResumeEditor.
 *
 * Behavior:
 * - Default state is collapsed. The user sees a CTA encouraging them to
 *   regenerate the Skills section from the JD + their tailored content
 *   after finishing the other sections.
 * - "Generate Skills" calls POST /api/tailor/generate-skills which returns a
 *   wholesale Skills section grounded in the JD + tailored evidence.
 *   The user reviews the proposal side-by-side and Accepts (emits a
 *   replace_section pseudo-suggestion) or Rejects.
 * - "Edit manually" expands the inline editor with full CRUD: rename
 *   category, delete category, add skill, remove skill, edit skill name,
 *   move skill between categories, add new category. Every operation emits
 *   a Skills-mode pseudo-suggestion so the preview + score stay in sync.
 */

import { useMemo, useState } from "react";
import {
  Sparkles, Loader2, Plus, Pencil, Trash2, Check, X,
  ChevronDown, ChevronUp, ArrowRightLeft, FolderPlus,
} from "lucide-react";
import type { ResumeData, SkillCategory, Suggestion } from "@/types/resume";

interface Props {
  resume: ResumeData;
  apiUrl: string;
  resumeId: string;
  jdText: string;
  newProjects?: Array<{ name: string; tech: string; bullets: string[] }>;
  onEmit: (s: Omit<Suggestion, "id">) => void;
  sectionScore?: number;
  editCount?: number;
  headerExtras?: React.ReactNode;
}

type Phase = "collapsed" | "expanded" | "regenerating" | "reviewing";

interface RegenResult {
  skills: SkillCategory[];
  reasoning?: string;
}

export function SkillsRegenStep({
  resume,
  apiUrl,
  resumeId,
  jdText,
  newProjects,
  onEmit,
  sectionScore,
  editCount,
  headerExtras,
}: Props) {
  const [phase, setPhase] = useState<Phase>("collapsed");
  const [regen, setRegen] = useState<RegenResult | null>(null);
  const [regenError, setRegenError] = useState<string | null>(null);

  const currentSkills: SkillCategory[] = resume.skills || [];

  const handleGenerate = async () => {
    setPhase("regenerating");
    setRegenError(null);
    try {
      const tailored = {
        summary: resume.summary || "",
        experience: (resume.experience || []).map((e) => ({
          title: e.title || "",
          company: e.company || "",
          bullets: e.bullets || [],
        })),
        projects: [
          ...(resume.projects || []).map((p) => ({
            name: p.name || "",
            tech: p.tech || "",
            bullets: p.bullets || [],
          })),
          ...(newProjects || []).map((p) => ({
            name: p.name,
            tech: p.tech,
            bullets: p.bullets,
          })),
        ],
        education: (resume.education || []).map((ed) => ({
          institution: ed.institution || "",
          degree: ed.degree || "",
          field: ed.field || "",
          details: ed.details || [],
        })),
      };

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
      const res = await fetch(`${apiUrl}/api/tailor/generate-skills`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: resumeId,
          jd_text: jdText,
          tailored,
          intensity,
          section_intensities: sectionIntensities,
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || "Failed to generate skills.");
      }
      const data = (await res.json()) as RegenResult;
      if (!data.skills || data.skills.length === 0) {
        throw new Error("The model returned no skills — try regenerating after accepting more bullet edits.");
      }
      setRegen(data);
      setPhase("reviewing");
    } catch (err) {
      setRegenError(err instanceof Error ? err.message : "Generation failed.");
      setPhase(currentSkills.length > 0 ? "expanded" : "collapsed");
    }
  };

  const handleAcceptRegen = () => {
    if (!regen) return;
    onEmit({
      section: "Skills",
      mode: "replace_section",
      new_skills: regen.skills,
      reasoning: regen.reasoning || "AI-regenerated skills section",
    });
    setRegen(null);
    setPhase("expanded");
  };

  const handleRejectRegen = () => {
    setRegen(null);
    setPhase(currentSkills.length > 0 ? "expanded" : "collapsed");
  };

  // --- COLLAPSED ---
  if (phase === "collapsed") {
    return (
      <section className="card p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <button
            onClick={() => setPhase("expanded")}
            className="flex items-center gap-2 min-w-0 flex-1 text-left group"
          >
            <ChevronDown className="w-3.5 h-3.5 text-muted shrink-0" />
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted group-hover:text-foreground transition-colors">Skills</h3>
            {editCount ? (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-success/10 text-success border border-success/30">
                {editCount} edited
              </span>
            ) : null}
          </button>
          {headerExtras}
        </div>
      </section>
    );
  }

  // --- REGENERATING ---
  if (phase === "regenerating") {
    return (
      <section className="card p-3 space-y-3 animate-pulse select-none">
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0 flex-1 text-left group">
            <ChevronUp className="w-3.5 h-3.5 text-muted shrink-0" />
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted transition-colors">Skills</h3>
          </div>
          {headerExtras}
        </div>
        <div className="space-y-3 mt-1 pl-5">
          <div className="h-3.5 bg-muted/60 rounded w-1/4" />
          <div className="flex flex-wrap gap-2">
            <div className="h-6 bg-muted/40 rounded-full w-16" />
            <div className="h-6 bg-muted/40 rounded-full w-24" />
            <div className="h-6 bg-muted/40 rounded-full w-20" />
            <div className="h-6 bg-muted/40 rounded-full w-14" />
            <div className="h-6 bg-muted/40 rounded-full w-18" />
          </div>
        </div>
      </section>
    );
  }

  // --- REVIEWING (proposed vs current) ---
  if (phase === "reviewing" && regen) {
    return (
      <section className="card p-3 space-y-2">
        <div className="flex items-center justify-between gap-2">
          <button
            onClick={() => setPhase("collapsed")}
            className="flex items-center gap-2 min-w-0 flex-1 text-left group"
          >
            <ChevronUp className="w-3.5 h-3.5 text-muted shrink-0" />
            <h3 className="text-xs font-semibold uppercase tracking-wider text-muted group-hover:text-foreground transition-colors">Skills — review proposal</h3>
          </button>
          <div className="flex items-center gap-1.5">
            <button onClick={handleGenerate} className="btn-ghost text-xs inline-flex items-center gap-1" title="Regenerate">
              <Sparkles className="w-3.5 h-3.5" /> Retry
            </button>
            <button onClick={handleRejectRegen} className="btn-ghost text-xs inline-flex items-center gap-1 text-danger">
              <X className="w-3.5 h-3.5" /> Reject
            </button>
            <button onClick={handleAcceptRegen} className="btn-primary text-xs inline-flex items-center gap-1">
              <Check className="w-3.5 h-3.5" /> Accept
            </button>
            {headerExtras}
          </div>
        </div>
        <div className="space-y-2 mt-2">
          {regen.reasoning && (
            <p className="text-[11px] text-muted italic">{regen.reasoning}</p>
          )}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="space-y-2">
              <p className="text-[10px] font-semibold text-muted uppercase tracking-wide">Current</p>
              <SkillsReadonly skills={currentSkills} emptyText="No skills yet" />
            </div>
            <div className="space-y-2">
              <p className="text-[10px] font-semibold text-success uppercase tracking-wide">Proposed</p>
              <SkillsReadonly skills={regen.skills} emptyText="" />
            </div>
          </div>
        </div>
      </section>
    );
  }

  // --- EXPANDED (manual CRUD editor) ---
  return (
    <section className="card p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <button
          onClick={() => setPhase("collapsed")}
          className="flex items-center gap-2 min-w-0 flex-1 text-left group"
        >
          <ChevronUp className="w-3.5 h-3.5 text-muted shrink-0" />
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted group-hover:text-foreground transition-colors">Skills</h3>
          {editCount ? (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-success/10 text-success border border-success/30">
              {editCount} edited
            </span>
          ) : null}
        </button>
        <div className="flex items-center gap-1.5">
          <button onClick={handleGenerate} className="btn-ghost text-xs inline-flex items-center gap-1" title="Regenerate from JD + tailored content">
            <Sparkles className="w-3.5 h-3.5" /> Generate
          </button>
          {headerExtras}
        </div>
      </div>

      <div className="space-y-2 mt-2">
        <div className="mt-1 px-3 py-2 rounded-md bg-amber-50 border border-amber-200 text-amber-800 text-[11px] flex items-start gap-2">
          <Sparkles className="w-3.5 h-3.5 text-amber-600 shrink-0 mt-0.5" />
          <div>
            <span className="font-semibold text-amber-900">Recommended Workflow:</span> For best results, generate your Skills <strong>after</strong> tailoring and accepting changes in other sections. The generator scans your accepted updates to capture and extract newly added technical keywords!
          </div>
        </div>

        {currentSkills.length === 0 ? (
          <p className="text-xs text-muted">No skills yet. Add a category below or click <b>Generate</b>.</p>
        ) : (
          currentSkills.map((cat, i) => (
            <SkillCategoryEditor
              key={`scat-${cat.category}-${i}`}
              category={cat}
              allCategories={currentSkills.map((c) => c.category)}
              onEmit={onEmit}
            />
          ))
        )}

        <AddCategoryRow onAdd={(name) => onEmit({
          section: "Skills",
          mode: "add_skill",
          target_category: name,
          is_new_category: true,
          // Empty placeholder skill so the category is created in the store —
          // we immediately remove it. This is a tiny hack: applySkillsMode's
          // add_skill ignores empty skills, so instead we add a sentinel then
          // remove. Simpler path: emit a single add_skill with a sentinel
          // "(add a skill)" placeholder the user can rename right away.
          skill: "(add a skill)",
          reasoning: "User created new skill category",
        })} />

        {regenError && <p className="text-xs text-danger">{regenError}</p>}
      </div>
    </section>
  );
}

// --- Subcomponents ---

function SkillsReadonly({ skills, emptyText }: { skills: SkillCategory[]; emptyText: string }) {
  if (!skills || skills.length === 0) {
    return <p className="text-xs text-muted italic">{emptyText}</p>;
  }
  return (
    <div className="space-y-2">
      {skills.map((cat, i) => (
        <div key={`ro-${cat.category}-${i}`} className="border-l-2 border-border pl-2 py-1">
          <p className="text-xs font-semibold">{cat.category}</p>
          <div className="flex flex-wrap gap-1 mt-1">
            {cat.skills.map((sk, j) => (
              <span key={`ro-sk-${j}-${sk}`} className="px-2 py-0.5 rounded text-[11px] bg-subtle border border-border">
                {sk}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function SkillCategoryEditor({
  category,
  allCategories,
  onEmit,
}: {
  category: SkillCategory;
  allCategories: string[];
  onEmit: (s: Omit<Suggestion, "id">) => void;
}) {
  const [renaming, setRenaming] = useState(false);
  const [catDraft, setCatDraft] = useState(category.category);
  const [adding, setAdding] = useState(false);
  const [skillDraft, setSkillDraft] = useState("");

  const handleRenameCat = () => {
    const name = catDraft.trim();
    setRenaming(false);
    if (name && name !== category.category) {
      onEmit({
        section: "Skills",
        mode: "rename_category",
        category: category.category,
        target_category: name,
        reasoning: "User renamed category",
      });
    }
  };

  return (
    <div className="border-l-2 border-border pl-3 py-1 space-y-1 group/cat">
      <div className="flex items-center justify-between gap-2">
        {renaming ? (
          <input
            autoFocus
            value={catDraft}
            onChange={(e) => setCatDraft(e.target.value)}
            onBlur={handleRenameCat}
            onKeyDown={(e) => {
              if (e.key === "Escape") { setCatDraft(category.category); setRenaming(false); }
              if (e.key === "Enter") handleRenameCat();
            }}
            className="flex-1 bg-subtle/60 border border-border rounded px-2 py-0.5 text-sm font-semibold focus:outline-none focus:border-primary"
          />
        ) : (
          <p className="text-sm font-semibold">{category.category}</p>
        )}
        <div className="flex items-center gap-1 opacity-0 group-hover/cat:opacity-100 transition-opacity">
          <button
            onClick={() => { setCatDraft(category.category); setRenaming(true); }}
            title="Rename category"
            className="p-1 rounded hover:bg-subtle text-muted hover:text-foreground"
          >
            <Pencil className="w-3 h-3" />
          </button>
          <button
            onClick={() => onEmit({
              section: "Skills",
              mode: "delete_category",
              category: category.category,
              reasoning: "User deleted category",
            })}
            title="Delete category"
            className="p-1 rounded hover:bg-danger/10 text-muted hover:text-danger"
          >
            <Trash2 className="w-3 h-3" />
          </button>
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {category.skills.map((sk, i) => (
          <SkillChip
            key={`schip-${category.category}-${i}-${sk}`}
            skill={sk}
            categoryName={category.category}
            otherCategories={allCategories.filter((c) => c !== category.category)}
            onEmit={onEmit}
          />
        ))}
        {adding ? (
          <input
            autoFocus
            value={skillDraft}
            onChange={(e) => setSkillDraft(e.target.value)}
            onBlur={() => {
              if (skillDraft.trim()) {
                onEmit({
                  section: "Skills",
                  mode: "add_skill",
                  category: category.category,
                  skill: skillDraft.trim(),
                  reasoning: "User added skill",
                });
              }
              setSkillDraft("");
              setAdding(false);
            }}
            onKeyDown={(e) => {
              if (e.key === "Escape") { setSkillDraft(""); setAdding(false); }
              if (e.key === "Enter") {
                if (skillDraft.trim()) {
                  onEmit({
                    section: "Skills",
                    mode: "add_skill",
                    category: category.category,
                    skill: skillDraft.trim(),
                    reasoning: "User added skill",
                  });
                }
                setSkillDraft("");
                setAdding(false);
              }
            }}
            placeholder="new skill"
            className="bg-subtle/60 border border-dashed border-border rounded px-2 py-0.5 text-xs w-28 focus:outline-none focus:border-primary"
          />
        ) : (
          <button
            onClick={() => setAdding(true)}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs border border-dashed border-border text-muted hover:text-foreground hover:border-foreground/40"
          >
            <Plus className="w-3 h-3" /> skill
          </button>
        )}
      </div>
    </div>
  );
}

function SkillChip({
  skill,
  categoryName,
  otherCategories,
  onEmit,
}: {
  skill: string;
  categoryName: string;
  otherCategories: string[];
  onEmit: (s: Omit<Suggestion, "id">) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(skill);
  const [movePickerOpen, setMovePickerOpen] = useState(false);

  if (editing) {
    return (
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          const next = draft.trim();
          setEditing(false);
          if (next && next !== skill) {
            // Atomic rename = remove old + add new.
            onEmit({
              section: "Skills",
              mode: "remove_skill",
              category: categoryName,
              skill,
              reasoning: "User renamed skill",
            });
            onEmit({
              section: "Skills",
              mode: "add_skill",
              category: categoryName,
              skill: next,
              reasoning: "User renamed skill",
            });
          } else {
            setDraft(skill);
          }
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") { setDraft(skill); setEditing(false); }
          if (e.key === "Enter") (e.target as HTMLInputElement).blur();
        }}
        className="bg-subtle/60 border border-border rounded px-2 py-0.5 text-xs w-28 focus:outline-none focus:border-primary"
      />
    );
  }

  return (
    <span className="relative inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs bg-subtle border border-border group/chip">
      <span onClick={() => { setDraft(skill); setEditing(true); }} className="cursor-text">
        {skill}
      </span>
      {otherCategories.length > 0 && (
        <button
          onClick={() => setMovePickerOpen((o) => !o)}
          title="Move to another category"
          className="text-muted hover:text-foreground opacity-0 group-hover/chip:opacity-100"
        >
          <ArrowRightLeft className="w-3 h-3" />
        </button>
      )}
      <button
        onClick={() => onEmit({
          section: "Skills",
          mode: "remove_skill",
          category: categoryName,
          skill,
          reasoning: "User removed skill",
        })}
        title="Remove skill"
        className="text-muted hover:text-danger ml-0.5"
      >
        ×
      </button>
      {movePickerOpen && otherCategories.length > 0 && (
        <div className="absolute top-full right-0 mt-1 z-20 bg-background border border-border rounded shadow-md py-1 min-w-[140px] max-h-48 overflow-y-auto">
          {otherCategories.map((target) => (
            <button
              key={`move-${target}`}
              onClick={() => {
                onEmit({
                  section: "Skills",
                  mode: "move_skill",
                  category: categoryName,
                  skill,
                  target_category: target,
                  reasoning: "User moved skill",
                });
                setMovePickerOpen(false);
              }}
              className="block w-full text-left px-3 py-1 text-xs hover:bg-subtle"
            >
              → {target}
            </button>
          ))}
        </div>
      )}
    </span>
  );
}

function AddCategoryRow({ onAdd }: { onAdd: (name: string) => void }) {
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState("");

  if (!adding) {
    return (
      <button
        onClick={() => setAdding(true)}
        className="inline-flex items-center gap-1 text-xs text-muted hover:text-foreground"
      >
        <FolderPlus className="w-3 h-3" /> Add category
      </button>
    );
  }

  return (
    <input
      autoFocus
      value={draft}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={() => {
        const name = draft.trim();
        if (name) onAdd(name);
        setDraft("");
        setAdding(false);
      }}
      onKeyDown={(e) => {
        if (e.key === "Escape") { setDraft(""); setAdding(false); }
        if (e.key === "Enter") {
          const name = draft.trim();
          if (name) onAdd(name);
          setDraft("");
          setAdding(false);
        }
      }}
      placeholder="New category name"
      className="bg-subtle/60 border border-dashed border-border rounded px-2 py-0.5 text-xs w-48 focus:outline-none focus:border-primary"
    />
  );
}
