"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ChevronUp, Plus, Sparkles, Trash2, FolderPlus, Loader2 } from "lucide-react";
import type { GeneratedProject } from "@/types/resume";
import { LineEditor } from "@/components/LineEditor";
import { EntryAiChat } from "@/components/EntryAiChat";
import { SkillsRegenStep } from "@/components/SkillsRegenStep";

// Types live in types/resume.ts — re-exported here for backward compat.
export type {
  Suggestion,
  ContactInfo,
  ExperienceEntry,
  EducationEntry,
  ProjectEntry,
  SkillCategory,
  ResumeData,
} from "@/types/resume";
import type {
  Suggestion,
  ContactInfo,
  ExperienceEntry,
  EducationEntry,
  ProjectEntry,
  ResumeData,
} from "@/types/resume";

interface ResumeEditorProps {
  /** The tailored resume (after applying accepted suggestions). Read-only source of truth. */
  resume: ResumeData;
  /** Suggestions still pending from the LLM — used to render the ✨ AI badge on matched lines. */
  pendingSuggestions: Suggestion[];
  /** All accepted suggestions for revert UI. */
  accepted: Suggestion[];
  /** Submit a new suggestion (CRUD action emits one). Parent is responsible for assigning an id. */
  onEmit: (s: Omit<Suggestion, "id">) => void;
  /** Emit a batch of new suggestions at once (entry-level AI chat). Parent assigns ids. */
  onEmitBatch?: (suggestions: Array<Omit<Suggestion, "id">>) => void;
  /** Undo a previously accepted suggestion. */
  onRevert: (id: number) => void;
  /** Accept a pending LLM suggestion. */
  onAcceptPending: (id: number, edited: string) => void;
  /** Reject a pending LLM suggestion. */
  onRejectPending: (id: number) => void;
  /** RAG-style chat fetcher — returns rewritten line text. */
  onAiChat: (section: string, originalLine: string, instruction: string) => Promise<string>;
  /** Context for entry-level AI chat (subsection rewrites). Optional — if omitted, the affordance is hidden. */
  apiUrl?: string;
  resumeId?: string | null;
  jdText?: string;
  newProjects?: Array<{ name: string; tech: string; bullets: string[] }>;
  /** Next id the parent will assign to emitted suggestions — used by Skills re-tailor for id seeding. */
  nextSuggestionId?: number;
  /** Per-section match scores (0-100) from /api/match/tailored. */
  sectionScores?: Record<string, number> | null;
  /** Props for project generation and management in the Projects section. */
  keptProjects?: GeneratedProject[];
  projectCount?: number;
  projectNames?: string[];
  onKeptChange?: (projects: GeneratedProject[]) => void;
}

const SECTION_ORDER: Array<keyof ResumeData | "contact"> = [
  "summary",
  "experience",
  "projects",
  "education",
  "skills",
  "certifications",
];

const SECTION_LABEL: Record<string, string> = {
  summary: "Summary",
  experience: "Experience",
  projects: "Projects",
  education: "Education",
  skills: "Skills",
  certifications: "Certifications",
};

export function ResumeEditor({
  resume,
  pendingSuggestions,
  accepted,
  onEmit,
  onEmitBatch,
  onRevert,
  onAcceptPending,
  onRejectPending,
  onAiChat,
  apiUrl,
  resumeId,
  jdText,
  newProjects,
  nextSuggestionId,
  sectionScores,
  keptProjects = [],
  projectCount = 0,
  projectNames = [],
  onKeptChange,
}: ResumeEditorProps) {
  const entryChatReady =
    !!onEmitBatch && !!apiUrl && !!resumeId && !!jdText;
  const [acceptedOpen, setAcceptedOpen] = useState(false);

  // Map normalised line text → pending Suggestion (for the ✨ AI badge).
  const pendingByLine = useMemo(() => {
    const map = new Map<string, Suggestion>();
    for (const s of pendingSuggestions) {
      if (!s.original) continue;
      map.set(s.original.trim().toLowerCase(), s);
    }
    return map;
  }, [pendingSuggestions]);

  const lineSuggestion = (text: string) =>
    pendingByLine.get(text.trim().toLowerCase()) || null;

  // Set of line texts that were produced by accepted suggestions. Used to render
  // a per-line "Edited" marker so the user can see at a glance what changed.
  const editedTextSet = useMemo(() => {
    const s = new Set<string>();
    for (const a of accepted) {
      if (a.suggested) s.add(a.suggested.trim().toLowerCase());
    }
    return s;
  }, [accepted]);

  const wasEdited = (text: string) =>
    !!text && editedTextSet.has(text.trim().toLowerCase());

  // Per-section accepted-edit counts shown as a small badge in each section header.
  const editCountBySection = useMemo(() => {
    const m: Record<string, number> = {};
    for (const a of accepted) {
      if (!a.section) continue;
      m[a.section] = (m[a.section] || 0) + 1;
    }
    return m;
  }, [accepted]);

  return (
    <div className="space-y-3">
      {/* Accepted-edits banner with collapsible undo list */}
      {accepted.length > 0 && (
        <div className="card p-2.5 border-success/20 bg-success/5">
          <button
            onClick={() => setAcceptedOpen((v) => !v)}
            className="w-full flex items-center justify-between text-xs"
          >
            <span className="font-semibold text-success">
              {accepted.length} edit{accepted.length !== 1 ? "s" : ""} applied
            </span>
            {acceptedOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          </button>
          {acceptedOpen && (
            <div className="mt-2 space-y-1.5 max-h-48 overflow-y-auto scrollbar-thin">
              {accepted.map((s) => (
                <div key={s.id} className="flex items-start justify-between gap-2 text-[11px]">
                  <div className="min-w-0 flex-1">
                    <p className="text-muted">{s.section} · {s.mode || "replace"}</p>
                    <p className="truncate text-muted line-through">{s.original}</p>
                    {s.suggested && <p className="truncate">{s.suggested}</p>}
                  </div>
                  <button
                    onClick={() => onRevert(s.id)}
                    className="shrink-0 text-[10px] text-muted hover:text-danger border border-border rounded px-1.5 py-0.5"
                  >
                    Undo
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* SECTION: Summary */}
      {resume.summary && resume.summary.trim() && (
        <SectionCard title="Summary" editCount={editCountBySection["Summary"] || 0} sectionScore={sectionScores?.["Summary"]}>
          <LineEditor
            section="Summary"
            marker=""
            text={resume.summary}
            hideAdd
            hideDelete
            wasEdited={wasEdited(resume.summary)}
            onAiChat={(prompt) => onAiChat("Summary", resume.summary || "", prompt)}
            onEdit={(newText) => onEmit({
              section: "Summary",
              mode: "replace",
              original: resume.summary || "",
              suggested: newText,
            })}
            onDelete={() => { /* hidden */ }}
            onAddBelow={() => { /* hidden */ }}
            badge={lineSuggestion(resume.summary) && (
              <AiPendingActions
                s={lineSuggestion(resume.summary)!}
                onAccept={onAcceptPending}
                onReject={onRejectPending}
              />
            )}
          />
        </SectionCard>
      )}

      {/* SECTION: Experience */}
      {resume.experience && resume.experience.length > 0 && (
        <SectionCard title="Experience" editCount={editCountBySection["Experience"] || 0} sectionScore={sectionScores?.["Experience"]}>
          {resume.experience.map((exp, i) => (
            <EntryBlock
              key={`Experience::${i}`}
              header={
                <>
                  <span className="font-semibold">{exp.title || "(role)"}</span>
                  {exp.company && <span className="text-muted"> @ {exp.company}</span>}
                  {(exp.start_date || exp.end_date) && (
                    <span className="text-muted text-[11px] ml-1">
                      · {exp.start_date || ""}{exp.end_date ? ` – ${exp.end_date}` : ""}
                    </span>
                  )}
                  {exp.location && <span className="text-muted text-[11px] ml-1">· {exp.location}</span>}
                </>
              }
              actions={
                entryChatReady && (exp.bullets || []).length > 0 ? (
                  <EntryAiChat
                    section="Experience"
                    entryIndex={i}
                    originalBullets={exp.bullets || []}
                    headerContext={{
                      title: exp.title,
                      company: exp.company,
                      start_date: exp.start_date,
                      end_date: exp.end_date,
                    }}
                    apiUrl={apiUrl!}
                    resumeId={resumeId!}
                    jdText={jdText!}
                    acceptedSuggestions={accepted}
                    newProjects={newProjects}
                    onEmitBatch={onEmitBatch!}
                  />
                ) : undefined
              }
            >
              {(exp.bullets || []).map((b, j) => (
                <LineEditor
                  key={`Experience::${i}::${j}`}
                  section="Experience"
                  ownerId={`Experience::${i}`}
                  text={b}
                  wasEdited={wasEdited(b)}
                  onAiChat={(prompt) => onAiChat("Experience", b, prompt)}
                  onEdit={(newText) => onEmit({
                    section: "Experience",
                    mode: "replace",
                    original: b,
                    suggested: newText,
                  })}
                  onDelete={() => onEmit({
                    section: "Experience",
                    mode: "remove_line",
                    original: b,
                    suggested: "",
                  })}
                  onAddBelow={(newText) => onEmit({
                    section: "Experience",
                    mode: "add_line",
                    original: `Experience::${i}`,
                    suggested: newText,
                  })}
                  badge={lineSuggestion(b) && (
                    <AiPendingActions
                      s={lineSuggestion(b)!}
                      onAccept={onAcceptPending}
                      onReject={onRejectPending}
                    />
                  )}
                />
              ))}
              {(!exp.bullets || exp.bullets.length === 0) && (
                <AddFirstLine
                  label="bullet"
                  onAdd={(t) => onEmit({
                    section: "Experience",
                    mode: "add_line",
                    original: `Experience::${i}`,
                    suggested: t,
                  })}
                />
              )}
            </EntryBlock>
          ))}
        </SectionCard>
      )}

      {/* SECTION: Projects */}
      {(resume.projects && resume.projects.length > 0) || onKeptChange ? (
        <SectionCard
          title="Projects"
          editCount={editCountBySection["Projects"] || 0}
          sectionScore={sectionScores?.["Projects"]}
          headerExtras={
            onKeptChange && apiUrl && resumeId && jdText ? (
              <GenerateProjectsInlineButton
                resumeId={resumeId!}
                jdText={jdText!}
                apiUrl={apiUrl!}
                keptProjects={keptProjects}
                projectCount={projectCount}
                projectNames={projectNames}
                onKeptChange={onKeptChange}
                nextSuggestionId={nextSuggestionId ?? 1}
                projectScore={sectionScores?.["Projects"]}
              />
            ) : null
          }
        >
          {(resume.projects || []).map((p, i) => (
            <EntryBlock
              key={`Projects::${i}`}
              header={
                <>
                  <span className="font-semibold">{p.name || "(project)"}</span>
                  {p.tech && <span className="text-muted text-[11px] ml-1">· {p.tech}</span>}
                </>
              }
              actions={
                <div className="flex items-center gap-2">
                  {entryChatReady && (p.bullets || []).length > 0 && (
                    <EntryAiChat
                      section="Projects"
                      entryIndex={i}
                      originalBullets={p.bullets || []}
                      headerContext={{ name: p.name, tech: p.tech }}
                      apiUrl={apiUrl!}
                      resumeId={resumeId!}
                      jdText={jdText!}
                      acceptedSuggestions={accepted}
                      newProjects={newProjects}
                      onEmitBatch={onEmitBatch!}
                    />
                  )}
                  <button
                    onClick={() => onEmit({
                      section: "Projects",
                      mode: "delete_project",
                      original: p.name || "",
                      suggested: "",
                    })}
                    title="Delete this project"
                    className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium text-danger border border-danger/30 hover:bg-danger/10 transition-colors"
                  >
                    <Trash2 className="w-3 h-3" /> Delete
                  </button>
                </div>
              }
            >
              {(p.bullets || []).map((b, j) => (
                <LineEditor
                  key={`Projects::${i}::${j}`}
                  section="Projects"
                  ownerId={`Projects::${i}`}
                  text={b}
                  wasEdited={wasEdited(b)}
                  onAiChat={(prompt) => onAiChat("Projects", b, prompt)}
                  onEdit={(newText) => onEmit({
                    section: "Projects",
                    mode: "replace",
                    original: b,
                    suggested: newText,
                  })}
                  onDelete={() => onEmit({
                    section: "Projects",
                    mode: "remove_line",
                    original: b,
                    suggested: "",
                  })}
                  onAddBelow={(newText) => onEmit({
                    section: "Projects",
                    mode: "add_line",
                    original: `Projects::${i}`,
                    suggested: newText,
                  })}
                  badge={lineSuggestion(b) && (
                    <AiPendingActions
                      s={lineSuggestion(b)!}
                      onAccept={onAcceptPending}
                      onReject={onRejectPending}
                    />
                  )}
                />
              ))}
              {(!p.bullets || p.bullets.length === 0) && (
                <AddFirstLine
                  label="bullet"
                  onAdd={(t) => onEmit({
                    section: "Projects",
                    mode: "add_line",
                    original: `Projects::${i}`,
                    suggested: t,
                  })}
                />
              )}
            </EntryBlock>
          ))}
          {(!resume.projects || resume.projects.length === 0) && (
            <EmptyHint text="No projects yet — generate some below." />
          )}
        </SectionCard>
      ) : null}

      {/* SECTION: Education */}
      {resume.education && resume.education.length > 0 && (
        <SectionCard title="Education" editCount={editCountBySection["Education"] || 0} sectionScore={sectionScores?.["Education"]}>
          {resume.education.map((ed, i) => (
            <EntryBlock
              key={`Education::${i}`}
              header={
                <>
                  <span className="font-semibold">
                    {ed.degree || ""}{ed.field ? ` in ${ed.field}` : ""}
                  </span>
                  {ed.institution && <span className="text-muted"> @ {ed.institution}</span>}
                  {(ed.start_date || ed.end_date) && (
                    <span className="text-muted text-[11px] ml-1">
                      · {ed.start_date || ""}{ed.end_date ? ` – ${ed.end_date}` : ""}
                    </span>
                  )}
                  {ed.gpa && <span className="text-muted text-[11px] ml-1">· GPA {ed.gpa}</span>}
                </>
              }
            >
              {(ed.details || []).map((d, j) => (
                <LineEditor
                  key={`Education::${i}::${j}`}
                  section="Education"
                  ownerId={`Education::${i}`}
                  text={d}
                  wasEdited={wasEdited(d)}
                  onAiChat={(prompt) => onAiChat("Education", d, prompt)}
                  onEdit={(newText) => onEmit({
                    section: "Education",
                    mode: "replace",
                    original: d,
                    suggested: newText,
                  })}
                  onDelete={() => onEmit({
                    section: "Education",
                    mode: "remove_line",
                    original: d,
                    suggested: "",
                  })}
                  onAddBelow={(newText) => onEmit({
                    section: "Education",
                    mode: "add_line",
                    original: `Education::${i}`,
                    suggested: newText,
                  })}
                  badge={lineSuggestion(d) && (
                    <AiPendingActions
                      s={lineSuggestion(d)!}
                      onAccept={onAcceptPending}
                      onReject={onRejectPending}
                    />
                  )}
                />
              ))}
              {(!ed.details || ed.details.length === 0) && (
                <AddFirstLine
                  label="coursework / detail line"
                  onAdd={(t) => onEmit({
                    section: "Education",
                    mode: "add_line",
                    original: `Education::${i}`,
                    suggested: t,
                  })}
                />
              )}
            </EntryBlock>
          ))}
        </SectionCard>
      )}

      {/* SECTION: Skills — regen-first flow with full manual CRUD */}
      {entryChatReady && (
        <SkillsRegenStep
          resume={resume}
          apiUrl={apiUrl!}
          resumeId={resumeId!}
          jdText={jdText!}
          newProjects={newProjects}
          onEmit={onEmit}
          sectionScore={sectionScores?.["Skills"]}
          editCount={editCountBySection["Skills"] || 0}
        />
      )}

      {/* SECTION: Certifications */}
      {resume.certifications && resume.certifications.length > 0 && (
        <SectionCard title="Certifications" editCount={editCountBySection["Certifications"] || 0}>
          {resume.certifications.map((c, i) => (
            <LineEditor
              key={`Certifications::${i}`}
              section="Certifications"
              ownerId={`Certifications::${i}`}
              text={c}
              wasEdited={wasEdited(c)}
              onAiChat={(prompt) => onAiChat("Certifications", c, prompt)}
              onEdit={(newText) => onEmit({
                section: "Certifications",
                mode: "replace",
                original: c,
                suggested: newText,
              })}
              onDelete={() => onEmit({
                section: "Certifications",
                mode: "remove_line",
                original: c,
                suggested: "",
              })}
              onAddBelow={(newText) => onEmit({
                section: "Certifications",
                mode: "add_line",
                original: `Certifications::${i}`,
                suggested: newText,
              })}
            />
          ))}
        </SectionCard>
      )}
    </div>
  );
}

function SectionCard({
  title,
  editCount = 0,
  headerExtras,
  sectionScore,
  children,
}: {
  title: string;
  editCount?: number;
  headerExtras?: React.ReactNode;
  sectionScore?: number;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(true);
  const scoreColor = sectionScore == null ? "" : sectionScore >= 70 ? "text-success" : sectionScore >= 40 ? "text-amber-600" : "text-danger";

  return (
    <div className="card p-3 space-y-2">
      <div className="flex items-center justify-between gap-2">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 min-w-0 flex-1 text-left group"
        >
          {open ? <ChevronUp className="w-3.5 h-3.5 text-muted shrink-0" /> : <ChevronDown className="w-3.5 h-3.5 text-muted shrink-0" />}
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted group-hover:text-foreground transition-colors">{title}</h3>
          {editCount > 0 && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-success/10 text-success border border-success/30">
              {editCount} edited
            </span>
          )}
          {sectionScore != null && (
            <span className={`text-[10px] font-medium tabular-nums ${scoreColor}`}>{sectionScore}%</span>
          )}
        </button>
        {headerExtras}
      </div>
      {open && <div className="space-y-2">{children}</div>}
    </div>
  );
}

function EntryBlock({
  header,
  actions,
  children,
}: {
  header: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <div className="group/entry border-l-2 border-border pl-3 py-1 space-y-0.5">
      <div className="flex items-start justify-between gap-2">
        <p className="text-sm min-w-0 flex-1">{header}</p>
        {actions && (
          <div className="shrink-0 opacity-0 group-hover/entry:opacity-100 transition-opacity">
            {actions}
          </div>
        )}
      </div>
      <div>{children}</div>
    </div>
  );
}

function EmptyHint({ text }: { text: string }) {
  return <p className="text-xs text-muted italic">{text}</p>;
}

function AddFirstLine({ label, onAdd }: { label: string; onAdd: (text: string) => void }) {
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="text-[11px] text-muted hover:text-foreground inline-flex items-center gap-1 mt-1"
      >
        <Plus className="w-3 h-3" /> Add {label}
      </button>
    );
  }
  return (
    <div className="flex items-start gap-2 mt-1">
      <span className="text-muted shrink-0 select-none">• </span>
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          if (draft.trim()) onAdd(draft.trim());
          setDraft("");
          setOpen(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Escape") { setDraft(""); setOpen(false); }
          if (e.key === "Enter") {
            if (draft.trim()) onAdd(draft.trim());
            setDraft("");
            setOpen(false);
          }
        }}
        placeholder={`New ${label}`}
        className="flex-1 bg-subtle/60 border border-border rounded px-2 py-1 text-sm focus:outline-none focus:border-primary"
      />
    </div>
  );
}

function AiPendingActions({
  s,
  onAccept,
  onReject,
}: {
  s: Suggestion;
  onAccept: (id: number, edited: string) => void;
  onReject: (id: number) => void;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        title="View AI suggestion"
        className="p-1 rounded hover:bg-amber-100 text-amber-600"
      >
        <Sparkles className="w-3 h-3" />
      </button>
      {open && (
        <>
          <div className="fixed inset-0 z-10" onClick={() => setOpen(false)} />
          <div className="absolute right-0 top-full mt-1 z-20 w-80 p-3 card shadow-xl">
            <p className="text-[10px] font-bold uppercase tracking-wider text-amber-600 mb-1">
              AI suggests
            </p>
            <p className="text-xs text-muted line-through mb-1">{s.original}</p>
            <p className="text-xs mb-2">{s.suggested}</p>
            {s.reasoning && <p className="text-[10px] text-muted mb-2">Why: {s.reasoning}</p>}
            <div className="flex items-center justify-end gap-2">
              <button
                onClick={() => { onReject(s.id); setOpen(false); }}
                className="btn-ghost py-1 px-2 text-[10px]"
              >
                Reject
              </button>
              <button
                onClick={() => { onAccept(s.id, s.suggested ?? ""); setOpen(false); }}
                className="btn-primary py-1 px-2 text-[10px]"
              >
                Accept
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
}

function GenerateProjectsInlineButton({
  resumeId, jdText, apiUrl, keptProjects, projectCount, projectNames, onKeptChange, nextSuggestionId, projectScore,
}: {
  resumeId: string;
  jdText: string;
  apiUrl: string;
  keptProjects: GeneratedProject[];
  projectCount: number;
  projectNames: string[];
  onKeptChange: (projects: GeneratedProject[]) => void;
  nextSuggestionId: number;
  projectScore?: number;
}) {
  const [isGenerating, setIsGenerating] = useState(false);
  const scoreColor = projectScore == null ? "" : projectScore >= 70 ? "text-success" : projectScore >= 40 ? "text-amber-600" : "text-danger";

  const handleGenerate = async () => {
    if (!resumeId || !jdText.trim()) return;
    setIsGenerating(true);
    try {
      const res = await fetch(`${apiUrl}/api/tailor/generate-projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: resumeId,
          jd_text: jdText,
          count: projectCount > 0 ? projectCount : 3,
          exclude_names: [],
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || "Generation failed.");
      }
      const data = await res.json();
      const projects: GeneratedProject[] = data.projects || [];
      if (projects.length > 0) {
        onKeptChange(projects);
      }
    } catch (err) {
      // silently fail
    } finally {
      setIsGenerating(false);
    }
  };

  return (
    <div>
      {projectScore != null && projectScore < 70 && (
        <button
          onClick={handleGenerate}
          disabled={isGenerating}
          className="inline-flex items-center gap-1 text-[10px] text-amber-700 bg-amber-50 border border-amber-200 rounded px-2 py-0.5 hover:bg-amber-100 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isGenerating ? (
            <>
              <Loader2 className="w-3 h-3 animate-spin" />
              Generating…
            </>
          ) : (
            <>
              <FolderPlus className="w-3 h-3" />
              <span className={`font-medium ${scoreColor}`}>{projectScore}%</span>
              — Generate projects to improve
            </>
          )}
        </button>
      )}
      {(projectScore == null || projectScore >= 70) && (
        <button
          onClick={handleGenerate}
          disabled={isGenerating}
          className="inline-flex items-center gap-1 text-[10px] text-muted hover:text-foreground border border-border rounded px-2 py-0.5 hover:border-foreground/40 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {isGenerating ? (
            <>
              <Loader2 className="w-3 h-3 animate-spin" />
              Generating…
            </>
          ) : (
            <>
              <FolderPlus className="w-3 h-3" /> Generate projects
            </>
          )}
        </button>
      )}
    </div>
  );
}
