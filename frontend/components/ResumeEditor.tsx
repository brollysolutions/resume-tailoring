"use client";

import { useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp, Plus, Sparkles, Trash2, FolderPlus, Loader2, GripVertical, Eye, EyeOff, Pencil } from "lucide-react";
import type { GeneratedProject } from "@/types/resume";
import { LineEditor } from "@/components/LineEditor";
import { SkillsRegenStep } from "@/components/SkillsRegenStep";
import { IntensitySelector } from "@/components/IntensitySelector";

/** Payload describing what the Copilot should focus on. */
export type CopilotFocusPayload = {
  section: string;
  targetType: "line" | "entry" | "section";
  original?: string;
  entryIndex?: number;
  label?: string;
};

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
  ResumeData,
} from "@/types/resume";

interface ResumeEditorProps {
  /** The tailored resume (after applying accepted suggestions). Read-only source of truth. */
  resume: ResumeData;
  /** The currently selected template ID. */
  templateId?: string;
  /** Suggestions still pending from the LLM — used to render the ✨ AI badge on matched lines. */
  pendingSuggestions: Suggestion[];
  /** All accepted suggestions for revert UI. */
  accepted: Suggestion[];
  /** Submit a new suggestion (CRUD action emits one). Parent is responsible for assigning an id. */
  onEmit: (s: Omit<Suggestion, "id">) => void;
  /** Undo a previously accepted suggestion. */
  onRevert: (id: number) => void;
  /** Accept a pending LLM suggestion. */
  onAcceptPending: (id: number, edited: string) => void;
  /** Reject a pending LLM suggestion. */
  onRejectPending: (id: number) => void;
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
  onReorderSections?: (newOrder: string[]) => void;
  /** Open the Copilot chat focused on a section / entry / line. */
  onCopilotFocus?: (payload: CopilotFocusPayload) => void;
}

const DEFAULT_SECTION_ORDER: string[] = [
  "summary",
  "experience",
  "projects",
  "education",
  "skills",
  "certifications",
  "publications",
  "awards",
  "languages",
  "volunteer",
  "patents",
  "talks",
  "extra_sections",
];

const SECTION_TITLES: Record<string, string> = {
  summary: "Summary",
  experience: "Experience",
  projects: "Projects",
  education: "Education",
  skills: "Skills",
  certifications: "Certifications",
  publications: "Publications",
  awards: "Awards",
  languages: "Languages",
  volunteer: "Volunteer",
  patents: "Patents",
  talks: "Talks",
  extra_sections: "Extra Sections",
};

export function ResumeEditor({
  resume,
  templateId,
  pendingSuggestions,
  accepted,
  onEmit,
  onRevert,
  onAcceptPending,
  onRejectPending,
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
  onReorderSections,
  onCopilotFocus,
}: ResumeEditorProps) {
  const skillsReady = !!apiUrl && !!resumeId && !!jdText;
  const [acceptedOpen, setAcceptedOpen] = useState(false);

  // Filter out reorder_sections from history
  const visibleAccepted = useMemo(() => {
    return accepted.filter(a => a.mode !== "reorder_sections");
  }, [accepted]);

  // Merge incoming section_order with the full default list so newly-added
  // sections (publications, awards, …) still appear when the saved order is older.
  const isSectionPopulated = (key: string, res: ResumeData) => {
    if (key === "summary") return !!res.summary;
    if (key === "experience") return !!(res.experience && res.experience.length > 0);
    if (key === "projects") return !!(res.projects && res.projects.length > 0);
    if (key === "education") return !!(res.education && res.education.length > 0);
    if (key === "skills") return !!(res.skills && res.skills.length > 0);
    if (key === "certifications") return !!(res.certifications && res.certifications.length > 0);
    if (key === "publications") return !!(res.publications && res.publications.length > 0);
    if (key === "awards") return !!(res.awards && res.awards.length > 0);
    if (key === "languages") return !!(res.languages && res.languages.length > 0);
    if (key === "volunteer") return !!(res.volunteer && res.volunteer.length > 0);
    if (key === "patents") return !!(res.patents && res.patents.length > 0);
    if (key === "talks") return !!(res.talks && res.talks.length > 0);
    if (key === "extra_sections") return !!(res.extra_sections && res.extra_sections.length > 0);
    return false;
  };

  const mergeOrder = (incoming: string[] | undefined, res: ResumeData): string[] => {
    const have = (incoming || []).filter((s) => DEFAULT_SECTION_ORDER.includes(s));
    const missing = DEFAULT_SECTION_ORDER.filter((s) => !have.includes(s));
    const combined = have.length ? [...have, ...missing] : DEFAULT_SECTION_ORDER;
    
    const populated = combined.filter((s) => isSectionPopulated(s, res));
    const empty = combined.filter((s) => !isSectionPopulated(s, res));
    
    return [...populated, ...empty];
  };

  // Local section order state for drag and drop
  const [localOrder, setLocalOrder] = useState<string[]>(() => mergeOrder(resume.section_order, resume));
  const [lastSyncedOrder, setLastSyncedOrder] = useState(resume.section_order);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);

  // Sync localOrder if resume.section_order changes from an external source (e.g. revert).
  // Pattern: adjust state while rendering instead of useEffect → avoids cascading renders.
  if (resume.section_order !== lastSyncedOrder) {
    setLastSyncedOrder(resume.section_order);
    if (resume.section_order?.length) {
      setLocalOrder(mergeOrder(resume.section_order, resume));
    }
  }

  const onDragStart = (e: React.DragEvent, idx: number) => {
    setDragIndex(idx);
    if (e.dataTransfer) {
      e.dataTransfer.effectAllowed = "move";
      // Set the drag ghost to the full section card, not just the grip icon.
      const card = (e.currentTarget as HTMLElement).closest(".drag-section") as HTMLElement | null;
      if (card) {
        const rect = card.getBoundingClientRect();
        e.dataTransfer.setDragImage(card, e.clientX - rect.left, e.clientY - rect.top);
      }
    }
  };

  const onDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    setDragOverIndex(idx);
  };

  const onDrop = (e: React.DragEvent, idx: number) => {
    if (dragIndex === null || dragIndex === idx) {
      setDragIndex(null);
      setDragOverIndex(null);
      return;
    }
    const next = [...localOrder];
    const [moved] = next.splice(dragIndex, 1);
    next.splice(idx, 0, moved);
    setLocalOrder(next);
    setDragIndex(null);
    setDragOverIndex(null);
    onReorderSections?.(next);
  };

  const onDragEnd = () => {
    setDragIndex(null);
    setDragOverIndex(null);
  };

  const moveSection = (from: number, to: number) => {
    if (to < 0 || to >= localOrder.length || to === from) return;
    const next = [...localOrder];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setLocalOrder(next);
    onReorderSections?.(next);
  };

  const onGripKeyDown = (e: React.KeyboardEvent, index: number) => {
    const meta = e.ctrlKey || e.metaKey;
    if (!meta) return;
    if (e.key === "ArrowUp") {
      e.preventDefault();
      moveSection(index, index - 1);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      moveSection(index, index + 1);
    }
  };

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

  const hiddenSet = useMemo(
    () => new Set((resume.hidden_sections || []).map((s) => s.toLowerCase())),
    [resume.hidden_sections],
  );

  const titleOf = (key: string) => SECTION_TITLES[key] || key;

  const emitField = (sec: string, idx: number | "", field: string, value: string, display?: string) =>
    onEmit({
      section: display || titleOf(sec),
      mode: "replace_field",
      original: `${sec}::${idx}::${field}`,
      suggested: value,
    });

  const emitTopLevel = (field: string, value: string) =>
    onEmit({
      section: "Header",
      mode: "replace_field",
      original: `resume::0::${field}`,
      suggested: value,
    });

  const emitContact = (field: string, value: string) =>
    onEmit({
      section: "Header",
      mode: "replace_field",
      original: `contact::0::${field}`,
      suggested: value,
    });

  const emitAddEntry = (sec: string) =>
    onEmit({
      section: titleOf(sec),
      mode: "add_entry",
      original: sec,
      suggested: "{}",
    });

  const emitDeleteEntry = (sec: string, idx: number) =>
    onEmit({
      section: titleOf(sec),
      mode: "delete_entry",
      original: `${sec}::${idx}`,
      suggested: "",
    });

  const emitToggleHidden = (sec: string) =>
    onEmit({
      section: titleOf(sec),
      mode: "toggle_hidden",
      original: sec,
      suggested: hiddenSet.has(sec) ? "show" : "hide",
    });

  const hideToggleFor = (sec: string) => (
    <HideToggle
      sectionKey={titleOf(sec)}
      isHidden={hiddenSet.has(sec)}
      onToggle={() => emitToggleHidden(sec)}
    />
  );

  return (
    <div className="space-y-3">

      {/* Accepted-edits banner with collapsible undo list */}
      {visibleAccepted.length > 0 && (
        <div className="card p-2.5 border-success/20 bg-success/5">
          <button
            onClick={() => setAcceptedOpen((v) => !v)}
            className="w-full flex items-center justify-between text-xs"
          >
            <div className="flex items-center gap-2">
              <div className="w-5 h-5 rounded-full bg-success/10 text-success flex items-center justify-center">
                <Sparkles className="w-3 h-3" />
              </div>
              <span className="font-medium text-success">
                {visibleAccepted.length} tailoring suggestion{visibleAccepted.length !== 1 ? "s" : ""} applied
              </span>
            </div>
            <div className="flex items-center gap-1.5 text-muted hover:text-foreground transition-colors px-1">
              <span className="text-[10px] uppercase font-semibold tracking-wider">
                {acceptedOpen ? "Hide History" : "View & Undo"}
              </span>
              {acceptedOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </div>
          </button>

          {acceptedOpen && (
            <div className="mt-2.5 pt-2.5 border-t border-success/20 space-y-1.5 max-h-60 overflow-y-auto scrollbar-thin pr-1">
              {visibleAccepted.slice().reverse().map((a) => (
                <div key={a.id} className="flex items-start justify-between gap-3 text-[11px] py-1 px-1.5 rounded hover:bg-success/10 transition-colors group">
                  <div className="min-w-0">
                    <p className="font-semibold text-foreground/80 leading-tight mb-0.5">
                      {a.section}: {a.mode === "replace" ? "Edited line" : a.mode?.replace("_", " ")}
                    </p>
                    {a.suggested && (
                      <p className="text-muted italic truncate" title={a.suggested}>
                        &ldquo;{a.suggested}&rdquo;
                      </p>
                    )}
                  </div>
                  <button
                    onClick={() => onRevert(a.id)}
                    className="shrink-0 text-success hover:text-danger hover:bg-danger/5 p-1 rounded transition-colors opacity-0 group-hover:opacity-100"
                    title="Undo this change"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Header — name + contact info. Always at the top, not part of section_order. */}
      <SectionCard
        title="Header"
        editCount={editCountBySection["Header"] || 0}
        headerExtras={null}
      >
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <ScalarField
            label="Name"
            value={resume.name}
            placeholder="Full name"
            hideLabel
            valueClassName="text-base font-bold"
            onCommit={(v) => emitTopLevel("name", v)}
          />
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
            <ScalarField
              label="Email"
              value={resume.contact?.email}
              placeholder="you@example.com"
              hideLabel
              onCommit={(v) => emitContact("email", v)}
            />
            <span>•</span>
            <ScalarField
              label="Phone"
              value={resume.contact?.phone}
              placeholder="+1 555 555 5555"
              hideLabel
              onCommit={(v) => emitContact("phone", v)}
            />
            <span>•</span>
            <ScalarField
              label="Location"
              value={resume.contact?.location}
              placeholder="City, ST"
              hideLabel
              onCommit={(v) => emitContact("location", v)}
            />
            <span>•</span>
            <ScalarField
              label="LinkedIn"
              value={resume.contact?.linkedin}
              placeholder="linkedin.com/in/…"
              hideLabel
              onCommit={(v) => emitContact("linkedin", v)}
            />
            <span>•</span>
            <ScalarField
              label="GitHub"
              value={resume.contact?.github}
              placeholder="github.com/…"
              hideLabel
              onCommit={(v) => emitContact("github", v)}
            />
            <span>•</span>
            <ScalarField
              label="Website"
              value={resume.contact?.website}
              placeholder="example.com"
              hideLabel
              onCommit={(v) => emitContact("website", v)}
            />
            {(resume.custom_links || []).map((link, i) => (
              <span key={`CustomLink::${i}`} className="flex items-center gap-1">
                <span>•</span>
                <ScalarField
                  label="Label"
                  value={link.label}
                  placeholder="Link"
                  hideLabel
                  valueClassName="font-medium"
                  onCommit={(v) => onEmit({ section: "Header", mode: "replace_field", original: `custom_links::${i}::label`, suggested: v })}
                />
                <ScalarField
                  label="URL"
                  value={link.url}
                  placeholder="https://…"
                  hideLabel
                  onCommit={(v) => onEmit({ section: "Header", mode: "replace_field", original: `custom_links::${i}::url`, suggested: v })}
                />
                <button
                  onClick={() => onEmit({ section: "Header", mode: "delete_entry", original: `custom_links::${i}` })}
                  className="text-muted hover:text-danger p-0.5"
                  title="Remove link"
                >
                  <Trash2 className="w-2.5 h-2.5" />
                </button>
              </span>
            ))}
            <button
              onClick={() => onEmit({ section: "Header", mode: "add_entry", original: "custom_links" })}
              className="inline-flex items-center gap-1 text-[10px] text-primary hover:text-primary-dark ml-1 border border-primary/20 hover:border-primary/40 rounded px-1.5 py-0.5 transition-colors"
            >
              <Plus className="w-2.5 h-2.5" /> Add Link
            </button>
          </div>
        </div>
      </SectionCard>

      {localOrder.map((sectionKey, index) => {
        const isDraggingThis = dragIndex === index;
        const isOver = dragOverIndex === index && dragIndex !== index;
        
        const anyDragging = dragIndex !== null;
        const isSectionHidden = hiddenSet.has(sectionKey);

        const dragHandle = (
          <div
            draggable
            tabIndex={0}
            role="button"
            aria-label={`Reorder ${titleOf(sectionKey)} section. Use Ctrl Arrow Up or Down.`}
            onDragStart={(e) => onDragStart(e, index)}
            onDragOver={(e) => onDragOver(e, index)}
            onDrop={(e) => onDrop(e, index)}
            onDragEnd={onDragEnd}
            onKeyDown={(e) => onGripKeyDown(e, index)}
            title="Drag to reorder · Ctrl+↑/↓ to move with keyboard"
            className={`p-1.5 rounded transition-colors cursor-grab active:cursor-grabbing select-none ${
              isDraggingThis
                ? "text-primary bg-primary/10"
                : anyDragging
                ? "text-primary/50 bg-primary/5"
                : "text-muted hover:text-foreground hover:bg-subtle"
            }`}
          >
            <GripVertical className="w-4 h-4" />
          </div>
        );

        const cardClasses = `drag-section transition-all duration-150 border-t-2 ${
          isSectionHidden ? "opacity-50 saturate-0" : ""
        } ${
          isDraggingThis ? "opacity-40" : ""
        } ${
          isOver ? "border-primary" : "border-transparent"
        }`;

        if (sectionKey === "summary") {
          return (
            <div key="summary" className={cardClasses} onDragOver={(e) => onDragOver(e, index)} onDrop={(e) => onDrop(e, index)}>
              <SectionCard
                title="Summary"
                editCount={editCountBySection["Summary"] || 0}
                sectionScore={sectionScores?.["Summary"]}
                headerExtras={
                  <div className="flex items-center gap-1">
                    <IntensitySelector sectionKey="summary" />
                    {hideToggleFor("summary")}
                    {dragHandle}
                  </div>
                }
              >
                {resume.summary ? (
                  <LineEditor
                    section="Summary"
                    text={resume.summary}
                    wasEdited={wasEdited(resume.summary)}
                    hideAdd
                    onCopilot={onCopilotFocus ? () => onCopilotFocus({ section: "Summary", targetType: "line", original: resume.summary || "" }) : undefined}
                    onEdit={(newText) => onEmit({
                      section: "Summary",
                      mode: "replace",
                      original: resume.summary || "",
                      suggested: newText,
                    })}
                    onDelete={() => onEmit({
                      section: "Summary",
                      mode: "remove_line",
                      original: resume.summary || "",
                      suggested: "",
                    })}
                    badge={lineSuggestion(resume.summary) && (
                      <AiPendingActions
                        s={lineSuggestion(resume.summary)!}
                        onAccept={onAcceptPending}
                        onReject={onRejectPending}
                      />
                    )}
                  />
                ) : (
                  <AddFirstLine
                    label="summary"
                    onAdd={(t) => emitTopLevel("summary", t)}
                  />
                )}
              </SectionCard>
            </div>
          );
        }

        if (sectionKey === "experience") {
          return (
            <div key="experience" className={cardClasses} onDragOver={(e) => onDragOver(e, index)} onDrop={(e) => onDrop(e, index)}>
              <SectionCard
                title="Experience"
                editCount={editCountBySection["Experience"] || 0}
                sectionScore={sectionScores?.["Experience"]}
                headerExtras={
                  <div className="flex items-center gap-1">
                    <IntensitySelector sectionKey="experience" />
                    {hideToggleFor("experience")}
                    {dragHandle}
                  </div>
                }
              >
                {(resume.experience || []).map((exp, i) => (
                  <EntryBlock
                    key={`Experience::${i}`}
                    header={
                      <div className="flex flex-col gap-1 w-full">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <ScalarField label="Title" value={exp.title} placeholder="(role)" hideLabel valueClassName="text-sm font-semibold" onCommit={(v) => emitField("experience", i, "title", v, "Experience")} />
                          {(exp.title || exp.company) && <span className="text-muted text-xs font-medium">at</span>}
                          <ScalarField label="Company" value={exp.company} placeholder="(company)" hideLabel valueClassName="text-sm font-semibold text-primary" onCommit={(v) => emitField("experience", i, "company", v, "Experience")} />
                          <ScalarField label="URL" value={exp.company_url} placeholder="https://…" hideLabel onCommit={(v) => emitField("experience", i, "company_url", v, "Experience")} />
                        </div>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                          <ScalarField label="Start" value={exp.start_date} placeholder="YYYY-MM" hideLabel onCommit={(v) => emitField("experience", i, "start_date", v, "Experience")} />
                          <span>–</span>
                          <ScalarField label="End" value={exp.end_date} placeholder="Present" hideLabel onCommit={(v) => emitField("experience", i, "end_date", v, "Experience")} />
                          <span>|</span>
                          <ScalarField label="Location" value={exp.location} placeholder="City, ST" hideLabel onCommit={(v) => emitField("experience", i, "location", v, "Experience")} />
                        </div>
                      </div>
                    }
                    actions={
                      <div className="flex items-center gap-2">
                        <DeleteEntryButton onClick={() => emitDeleteEntry("experience", i)} title="Delete this experience entry" />
                      </div>
                    }
                  >
                    {(exp.bullets || []).map((b, j) => (
                      <LineEditor
                        key={`Experience::${i}::${j}`}
                        section="Experience"
                        ownerId={`Experience::${i}`}
                        text={b}
                        wasEdited={wasEdited(b)}
                        onCopilot={onCopilotFocus ? () => onCopilotFocus({ section: "Experience", targetType: "line", original: b }) : undefined}
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
                <AddEntryButton label="experience entry" onClick={() => emitAddEntry("experience")} />
              </SectionCard>
            </div>
          );
        }

        if (sectionKey === "projects") {
          return (
            <div key="projects" className={cardClasses} onDragOver={(e) => onDragOver(e, index)} onDrop={(e) => onDrop(e, index)}>
              <SectionCard
                title="Projects"
                editCount={editCountBySection["Projects"] || 0}
                sectionScore={sectionScores?.["Projects"]}
                headerExtras={
                  <div className="flex items-center gap-2">
                    <IntensitySelector sectionKey="projects" />
                    {onKeptChange && apiUrl && resumeId && jdText && (
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
                    )}
                    {hideToggleFor("projects")}
                    {dragHandle}
                  </div>
                }
              >
                {(resume.projects || []).map((p, i) => (
                  <EntryBlock
                    key={`Projects::${i}`}
                    header={
                      <div className="flex flex-col gap-1 w-full">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <ScalarField label="Name" value={p.name} placeholder="(project)" hideLabel valueClassName="text-sm font-semibold" onCommit={(v) => emitField("projects", i, "name", v, "Projects")} />
                          <ScalarField label="Link" value={p.url} placeholder="repo / site" hideLabel onCommit={(v) => emitField("projects", i, "url", v, "Projects")} />
                          <ScalarField label="Demo" value={p.demo_url} placeholder="live demo" hideLabel onCommit={(v) => emitField("projects", i, "demo_url", v, "Projects")} />
                        </div>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                          <ScalarField label="Tech" value={p.tech} placeholder="stack…" hideLabel onCommit={(v) => emitField("projects", i, "tech", v, "Projects")} />
                          {(p.tech || p.date) && <span>|</span>}
                          <ScalarField label="Date" value={p.date} placeholder="YYYY-MM" hideLabel onCommit={(v) => emitField("projects", i, "date", v, "Projects")} />
                        </div>
                      </div>
                    }
                    actions={
                      <div className="flex items-center gap-2">
                        <DeleteEntryButton onClick={() => emitDeleteEntry("projects", i)} title="Delete this project" />
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
                        onCopilot={onCopilotFocus ? () => onCopilotFocus({ section: "Projects", targetType: "line", original: b }) : undefined}
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
                <AddEntryButton label="project" onClick={() => emitAddEntry("projects")} />
              </SectionCard>
            </div>
          );
        }

        if (sectionKey === "education") {
          return (
            <div key="education" className={cardClasses} onDragOver={(e) => onDragOver(e, index)} onDrop={(e) => onDrop(e, index)}>
              <SectionCard
                title="Education"
                editCount={editCountBySection["Education"] || 0}
                sectionScore={sectionScores?.["Education"]}
                headerExtras={
                  <div className="flex items-center gap-1">
                    <IntensitySelector sectionKey="education" />
                    {hideToggleFor("education")}
                    {dragHandle}
                  </div>
                }
              >
                {(resume.education || []).map((ed, i) => (
                  <EntryBlock
                    key={`Education::${i}`}
                    header={
                      <div className="flex flex-col gap-1 w-full">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <ScalarField label="Institution" value={ed.institution} placeholder="(school)" hideLabel valueClassName="text-sm font-semibold" onCommit={(v) => emitField("education", i, "institution", v, "Education")} />
                          <ScalarField label="Degree" value={ed.degree} placeholder="B.S." hideLabel onCommit={(v) => emitField("education", i, "degree", v, "Education")} />
                          <ScalarField label="Field" value={ed.field} placeholder="Computer Science" hideLabel onCommit={(v) => emitField("education", i, "field", v, "Education")} />
                        </div>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                          <ScalarField label="Start" value={ed.start_date} placeholder="YYYY" hideLabel onCommit={(v) => emitField("education", i, "start_date", v, "Education")} />
                          <span>–</span>
                          <ScalarField label="End" value={ed.end_date} placeholder="YYYY" hideLabel onCommit={(v) => emitField("education", i, "end_date", v, "Education")} />
                          <span>|</span>
                          <ScalarField label="Location" value={ed.location} placeholder="City, ST" hideLabel onCommit={(v) => emitField("education", i, "location", v, "Education")} />
                          {ed.gpa && (
                            <>
                              <span>|</span>
                              <ScalarField label="GPA" value={ed.gpa} placeholder="3.8/4.0" hideLabel onCommit={(v) => emitField("education", i, "gpa", v, "Education")} />
                            </>
                          )}
                        </div>
                      </div>
                    }
                    actions={
                      <DeleteEntryButton onClick={() => emitDeleteEntry("education", i)} title="Delete this education entry" />
                    }
                  >
                    {(ed.details || []).map((d, j) => (
                      <LineEditor
                        key={`Education::${i}::${j}`}
                        section="Education"
                        ownerId={`Education::${i}`}
                        text={d}
                        wasEdited={wasEdited(d)}
                        onCopilot={onCopilotFocus ? () => onCopilotFocus({ section: "Education", targetType: "line", original: d }) : undefined}
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
                <AddEntryButton label="education entry" onClick={() => emitAddEntry("education")} />
              </SectionCard>
            </div>
          );
        }

        if (sectionKey === "skills" && skillsReady) {
          return (
            <div key="skills" className={cardClasses} onDragOver={(e) => onDragOver(e, index)} onDrop={(e) => onDrop(e, index)}>
              <SkillsRegenStep
                resume={resume}
                templateId={templateId}
                apiUrl={apiUrl!}
                resumeId={resumeId!}
                jdText={jdText!}
                newProjects={newProjects}
                onEmit={onEmit}
                sectionScore={sectionScores?.["Skills"]}
                editCount={editCountBySection["Skills"] || 0}
                headerExtras={
                  <div className="flex items-center gap-1">
                    <IntensitySelector sectionKey="skills" />
                    {hideToggleFor("skills")}
                    {dragHandle}
                  </div>
                }
              />
            </div>
          );
        }

        if (sectionKey === "certifications") {
          const certs = resume.certifications || [];
          return (
            <div key="certifications" className={cardClasses} onDragOver={(e) => onDragOver(e, index)} onDrop={(e) => onDrop(e, index)}>
              <SectionCard
                title="Certifications"
                editCount={editCountBySection["Certifications"] || 0}
                headerExtras={
                  <div className="flex items-center gap-1">
                    {hideToggleFor("certifications")}
                    {dragHandle}
                  </div>
                }
              >
                {certs.map((c, i) => (
                  <EntryBlock
                    key={`Certifications::${i}`}
                    header={
                      <div className="flex flex-col gap-1 w-full">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <ScalarField label="Name" value={c.name} placeholder="(cert)" hideLabel valueClassName="text-sm font-semibold" onCommit={(v) => emitField("certifications", i, "name", v, "Certifications")} />
                          {(c.name && c.issuer) && <span className="text-muted text-xs font-medium">from</span>}
                          <ScalarField label="Issuer" value={c.issuer} placeholder="(org)" hideLabel valueClassName="text-sm font-semibold" onCommit={(v) => emitField("certifications", i, "issuer", v, "Certifications")} />
                          {c.credential_url && <ScalarField label="Link" value={c.credential_url} placeholder="https://…" hideLabel onCommit={(v) => emitField("certifications", i, "credential_url", v, "Certifications")} />}
                        </div>
                        <div className="text-xs text-muted">
                          <ScalarField label="Date" value={c.date} placeholder="YYYY" hideLabel onCommit={(v) => emitField("certifications", i, "date", v, "Certifications")} />
                        </div>
                      </div>
                    }
                    actions={<DeleteEntryButton onClick={() => emitDeleteEntry("certifications", i)} title="Delete this certification" />}
                  >
                    <span />
                  </EntryBlock>
                ))}
                {certs.length === 0 && <EmptyHint text="No certifications yet." />}
                <AddEntryButton label="certification" onClick={() => emitAddEntry("certifications")} />
              </SectionCard>
            </div>
          );
        }

        if (sectionKey === "publications") {
          const items = resume.publications || [];
          return (
            <div key="publications" className={cardClasses} onDragOver={(e) => onDragOver(e, index)} onDrop={(e) => onDrop(e, index)}>
              <SectionCard
                title="Publications"
                editCount={editCountBySection["Publications"] || 0}
                headerExtras={
                  <div className="flex items-center gap-1">
                    {hideToggleFor("publications")}
                    {dragHandle}
                  </div>
                }
              >
                {items.map((p, i) => (
                  <EntryBlock
                    key={`Publications::${i}`}
                    header={
                      <div className="flex flex-col gap-1 w-full">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <ScalarField label="Title" value={p.title} placeholder="(title)" hideLabel valueClassName="text-sm font-semibold" onCommit={(v) => emitField("publications", i, "title", v, "Publications")} />
                          {p.authors && <ScalarField label="Authors" value={p.authors} placeholder="Last, F.; …" hideLabel onCommit={(v) => emitField("publications", i, "authors", v, "Publications")} />}
                        </div>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                          <ScalarField label="Venue" value={p.venue} placeholder="Conf / Journal" hideLabel onCommit={(v) => emitField("publications", i, "venue", v, "Publications")} />
                          <span>|</span>
                          <ScalarField label="Year" value={p.year} placeholder="YYYY" hideLabel onCommit={(v) => emitField("publications", i, "year", v, "Publications")} />
                          {p.doi && (
                            <>
                              <span>|</span>
                              <ScalarField label="DOI" value={p.doi} placeholder="10.xxxx/…" hideLabel onCommit={(v) => emitField("publications", i, "doi", v, "Publications")} />
                            </>
                          )}
                          {p.url && (
                            <>
                              <span>|</span>
                              <ScalarField label="URL" value={p.url} placeholder="https://…" hideLabel onCommit={(v) => emitField("publications", i, "url", v, "Publications")} />
                            </>
                          )}
                        </div>
                      </div>
                    }
                    actions={<DeleteEntryButton onClick={() => emitDeleteEntry("publications", i)} title="Delete this publication" />}
                  >
                    <span />
                  </EntryBlock>
                ))}
                {items.length === 0 && <EmptyHint text="No publications yet." />}
                <AddEntryButton label="publication" onClick={() => emitAddEntry("publications")} />
              </SectionCard>
            </div>
          );
        }

        if (sectionKey === "awards") {
          const items = resume.awards || [];
          return (
            <div key="awards" className={cardClasses} onDragOver={(e) => onDragOver(e, index)} onDrop={(e) => onDrop(e, index)}>
              <SectionCard
                title="Awards"
                editCount={editCountBySection["Awards"] || 0}
                headerExtras={
                  <div className="flex items-center gap-1">
                    {hideToggleFor("awards")}
                    {dragHandle}
                  </div>
                }
              >
                {items.map((a, i) => (
                  <EntryBlock
                    key={`Awards::${i}`}
                    header={
                      <div className="flex flex-col gap-1 w-full">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <ScalarField label="Title" value={a.title} placeholder="(award)" hideLabel valueClassName="text-sm font-semibold" onCommit={(v) => emitField("awards", i, "title", v, "Awards")} />
                          {(a.title && a.issuer) && <span className="text-muted text-xs font-medium">from</span>}
                          <ScalarField label="Issuer" value={a.issuer} placeholder="(org)" hideLabel valueClassName="text-sm font-semibold text-primary" onCommit={(v) => emitField("awards", i, "issuer", v, "Awards")} />
                        </div>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                          <ScalarField label="Date" value={a.date} placeholder="YYYY-MM" hideLabel onCommit={(v) => emitField("awards", i, "date", v, "Awards")} />
                          {a.description && (
                            <>
                              <span>|</span>
                              <ScalarField label="Description" value={a.description} placeholder="One-line context" hideLabel onCommit={(v) => emitField("awards", i, "description", v, "Awards")} />
                            </>
                          )}
                        </div>
                      </div>
                    }
                    actions={<DeleteEntryButton onClick={() => emitDeleteEntry("awards", i)} title="Delete this award" />}
                  >
                    <span />
                  </EntryBlock>
                ))}
                {items.length === 0 && <EmptyHint text="No awards yet." />}
                <AddEntryButton label="award" onClick={() => emitAddEntry("awards")} />
              </SectionCard>
            </div>
          );
        }

        if (sectionKey === "languages") {
          const items = resume.languages || [];
          return (
            <div key="languages" className={cardClasses} onDragOver={(e) => onDragOver(e, index)} onDrop={(e) => onDrop(e, index)}>
              <SectionCard
                title="Languages"
                editCount={editCountBySection["Languages"] || 0}
                headerExtras={
                  <div className="flex items-center gap-1">
                    {hideToggleFor("languages")}
                    {dragHandle}
                  </div>
                }
              >
                {items.map((l, i) => (
                  <EntryBlock
                    key={`Languages::${i}`}
                    header={
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <ScalarField label="Language" value={l.name} placeholder="English" hideLabel valueClassName="text-sm font-semibold" onCommit={(v) => emitField("languages", i, "name", v, "Languages")} />
                        <ScalarField
                          label="Proficiency"
                          value={l.proficiency}
                          options={["Native", "Fluent", "Conversational", "Basic"]}
                          hideLabel
                          valueClassName="text-xs text-muted italic"
                          onCommit={(v) => emitField("languages", i, "proficiency", v, "Languages")}
                        />
                      </div>
                    }
                    actions={<DeleteEntryButton onClick={() => emitDeleteEntry("languages", i)} title="Delete this language" />}
                  >
                    <span />
                  </EntryBlock>
                ))}
                {items.length === 0 && <EmptyHint text="No languages yet." />}
                <AddEntryButton label="language" onClick={() => emitAddEntry("languages")} />
              </SectionCard>
            </div>
          );
        }

        if (sectionKey === "volunteer") {
          const items = resume.volunteer || [];
          return (
            <div key="volunteer" className={cardClasses} onDragOver={(e) => onDragOver(e, index)} onDrop={(e) => onDrop(e, index)}>
              <SectionCard
                title="Volunteer"
                editCount={editCountBySection["Volunteer"] || 0}
                headerExtras={
                  <div className="flex items-center gap-1">
                    {hideToggleFor("volunteer")}
                    {dragHandle}
                  </div>
                }
              >
                {items.map((v, i) => (
                  <EntryBlock
                    key={`Volunteer::${i}`}
                    header={
                      <div className="flex flex-col gap-1 w-full">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <ScalarField label="Role" value={v.role} placeholder="(role)" hideLabel valueClassName="text-sm font-semibold" onCommit={(val) => emitField("volunteer", i, "role", val, "Volunteer")} />
                          {(v.role && v.organization) && <span className="text-muted text-xs font-medium">at</span>}
                          <ScalarField label="Organization" value={v.organization} placeholder="(org)" hideLabel valueClassName="text-sm font-semibold text-primary" onCommit={(val) => emitField("volunteer", i, "organization", val, "Volunteer")} />
                        </div>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                          <ScalarField label="Start" value={v.start_date} placeholder="YYYY-MM" hideLabel onCommit={(val) => emitField("volunteer", i, "start_date", val, "Volunteer")} />
                          <span>–</span>
                          <ScalarField label="End" value={v.end_date} placeholder="Present" hideLabel onCommit={(val) => emitField("volunteer", i, "end_date", val, "Volunteer")} />
                          <span>|</span>
                          <ScalarField label="Location" value={v.location} placeholder="City, ST" hideLabel onCommit={(val) => emitField("volunteer", i, "location", val, "Volunteer")} />
                        </div>
                      </div>
                    }
                    actions={<DeleteEntryButton onClick={() => emitDeleteEntry("volunteer", i)} title="Delete this volunteer entry" />}
                  >
                    {(v.bullets || []).map((b, j) => (
                      <LineEditor
                        key={`Volunteer::${i}::${j}`}
                        section="Volunteer"
                        ownerId={`Volunteer::${i}`}
                        text={b}
                        wasEdited={wasEdited(b)}
                        onEdit={(newText) => onEmit({ section: "Volunteer", mode: "replace", original: b, suggested: newText })}
                        onDelete={() => onEmit({ section: "Volunteer", mode: "remove_line", original: b, suggested: "" })}
                        onAddBelow={(newText) => onEmit({ section: "Volunteer", mode: "add_line", original: `Volunteer::${i}`, suggested: newText })}
                      />
                    ))}
                    {(!v.bullets || v.bullets.length === 0) && (
                      <AddFirstLine
                        label="bullet"
                        onAdd={(t) => onEmit({ section: "Volunteer", mode: "add_line", original: `Volunteer::${i}`, suggested: t })}
                      />
                    )}
                  </EntryBlock>
                ))}
                {items.length === 0 && <EmptyHint text="No volunteer entries yet." />}
                <AddEntryButton label="volunteer entry" onClick={() => emitAddEntry("volunteer")} />
              </SectionCard>
            </div>
          );
        }

        if (sectionKey === "patents") {
          const items = resume.patents || [];
          return (
            <div key="patents" className={cardClasses} onDragOver={(e) => onDragOver(e, index)} onDrop={(e) => onDrop(e, index)}>
              <SectionCard
                title="Patents"
                editCount={editCountBySection["Patents"] || 0}
                headerExtras={
                  <div className="flex items-center gap-1">
                    {hideToggleFor("patents")}
                    {dragHandle}
                  </div>
                }
              >
                {items.map((p, i) => (
                  <EntryBlock
                    key={`Patents::${i}`}
                    header={
                      <div className="flex flex-col gap-1 w-full">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <ScalarField label="Title" value={p.title} placeholder="(title)" hideLabel valueClassName="text-sm font-semibold" onCommit={(v) => emitField("patents", i, "title", v, "Patents")} />
                          <ScalarField label="Number" value={p.number} placeholder="US 11,123,456" hideLabel valueClassName="text-xs font-medium text-primary" onCommit={(v) => emitField("patents", i, "number", v, "Patents")} />
                        </div>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                          <ScalarField label="Date" value={p.date} placeholder="YYYY-MM" hideLabel onCommit={(v) => emitField("patents", i, "date", v, "Patents")} />
                          <span>|</span>
                          <ScalarField label="Status" value={p.status} options={["Pending", "Granted"]} hideLabel onCommit={(v) => emitField("patents", i, "status", v, "Patents")} />
                          <span>|</span>
                          <ScalarField label="Authors" value={p.authors} placeholder="Inventors" hideLabel onCommit={(v) => emitField("patents", i, "authors", v, "Patents")} />
                        </div>
                      </div>
                    }
                    actions={<DeleteEntryButton onClick={() => emitDeleteEntry("patents", i)} title="Delete this patent" />}
                  >
                    <span />
                  </EntryBlock>
                ))}
                {items.length === 0 && <EmptyHint text="No patents yet." />}
                <AddEntryButton label="patent" onClick={() => emitAddEntry("patents")} />
              </SectionCard>
            </div>
          );
        }

        if (sectionKey === "talks") {
          const items = resume.talks || [];
          return (
            <div key="talks" className={cardClasses} onDragOver={(e) => onDragOver(e, index)} onDrop={(e) => onDrop(e, index)}>
              <SectionCard
                title="Talks"
                editCount={editCountBySection["Talks"] || 0}
                headerExtras={
                  <div className="flex items-center gap-1">
                    {hideToggleFor("talks")}
                    {dragHandle}
                  </div>
                }
              >
                {items.map((t, i) => (
                  <EntryBlock
                    key={`Talks::${i}`}
                    header={
                      <div className="flex flex-col gap-1 w-full">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                          <ScalarField label="Title" value={t.title} placeholder="(title)" hideLabel valueClassName="text-sm font-semibold" onCommit={(v) => emitField("talks", i, "title", v, "Talks")} />
                          {(t.title && t.venue) && <span className="text-muted text-xs font-medium">at</span>}
                          <ScalarField label="Venue" value={t.venue} placeholder="(venue)" hideLabel valueClassName="text-sm font-semibold text-primary" onCommit={(v) => emitField("talks", i, "venue", v, "Talks")} />
                        </div>
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
                          <ScalarField label="Date" value={t.date} placeholder="YYYY-MM" hideLabel onCommit={(v) => emitField("talks", i, "date", v, "Talks")} />
                          <span>|</span>
                          <ScalarField label="Type" value={t.type} options={["Conference", "Workshop", "Seminar"]} hideLabel onCommit={(v) => emitField("talks", i, "type", v, "Talks")} />
                        </div>
                      </div>
                    }
                    actions={<DeleteEntryButton onClick={() => emitDeleteEntry("talks", i)} title="Delete this talk" />}
                  >
                    <span />
                  </EntryBlock>
                ))}
                {items.length === 0 && <EmptyHint text="No talks yet." />}
                <AddEntryButton label="talk" onClick={() => emitAddEntry("talks")} />
              </SectionCard>
            </div>
          );
        }

        if (sectionKey === "extra_sections") {
          const items = resume.extra_sections || [];
          return (
            <div key="extra_sections" className={cardClasses} onDragOver={(e) => onDragOver(e, index)} onDrop={(e) => onDrop(e, index)}>
              <SectionCard
                title="Extra Sections"
                editCount={editCountBySection["Extra Sections"] || 0}
                headerExtras={
                  <div className="flex items-center gap-1">
                    {hideToggleFor("extra_sections")}
                    {dragHandle}
                  </div>
                }
              >
                {items.map((xs, i) => (
                  <EntryBlock
                    key={`ExtraSection::${i}`}
                    header={
                      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                        <ScalarField label="Title" value={xs.title} placeholder="Section name" hideLabel valueClassName="text-sm font-semibold" onCommit={(v) => emitField("extra_sections", i, "title", v, "Extra Sections")} />
                        <ScalarField
                          label="Type"
                          value={xs.content_type}
                          options={["entries", "text", "list"]}
                          hideLabel
                          valueClassName="text-xs text-muted italic"
                          onCommit={(v) => emitField("extra_sections", i, "content_type", v, "Extra Sections")}
                        />
                      </div>
                    }
                    actions={<DeleteEntryButton onClick={() => emitDeleteEntry("extra_sections", i)} title="Delete this extra section" />}
                  >
                    {(xs.items || []).map((it, j) => (
                      <div key={`ExtraSection::${i}::${j}`} className="border-l border-border/60 pl-2 mt-1 space-y-1">
                        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs">
                          <ScalarField label="Header" value={it.header} placeholder="(header)" hideLabel valueClassName="font-medium" onCommit={() => { /* item-level fields not yet supported */ }} />
                          <ScalarField label="Subheader" value={it.subheader} placeholder="(subheader)" hideLabel onCommit={() => { /* item-level fields not yet supported */ }} />
                        </div>
                        {it.text && (
                          <LineEditor
                            section="Extra Sections"
                            text={it.text}
                            marker=""
                            hideAdd
                            wasEdited={wasEdited(it.text)}
                            onEdit={(newText) => onEmit({ section: "Extra Sections", mode: "replace", original: it.text || "", suggested: newText })}
                            onDelete={() => onEmit({ section: "Extra Sections", mode: "remove_line", original: it.text || "", suggested: "" })}
                          />
                        )}
                        {(it.bullets || []).map((b, k) => (
                          <LineEditor
                            key={`ExtraSection::${i}::${j}::${k}`}
                            section="Extra Sections"
                            text={b}
                            wasEdited={wasEdited(b)}
                            onEdit={(newText) => onEmit({ section: "Extra Sections", mode: "replace", original: b, suggested: newText })}
                            onDelete={() => onEmit({ section: "Extra Sections", mode: "remove_line", original: b, suggested: "" })}
                          />
                        ))}
                      </div>
                    ))}
                  </EntryBlock>
                ))}
                {items.length === 0 && <EmptyHint text="No extra sections yet." />}
                <AddEntryButton label="extra section" onClick={() => emitAddEntry("extra_sections")} />
              </SectionCard>
            </div>
          );
        }

        return null;
      })}
    </div>
  );
}

function SectionCard({
  title,
  editCount = 0,
  headerExtras,
  defaultOpen = false,
  children,
}: {
  title: string;
  editCount?: number;
  headerExtras?: React.ReactNode;
  sectionScore?: number;
  defaultOpen?: boolean;
  children: React.ReactNode;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className={`card p-3 space-y-2 transition-all duration-200 ${open ? "shadow-sm" : "hover:shadow-sm hover:border-foreground/20 hover:bg-subtle/20"}`}>
      <div className="flex items-center justify-between gap-2 group">
        <button
          onClick={() => setOpen((v) => !v)}
          className="flex items-center gap-2 min-w-0 flex-1 text-left"
        >
          {open ? <ChevronUp className="w-3.5 h-3.5 text-muted shrink-0" /> : <ChevronDown className="w-3.5 h-3.5 text-muted shrink-0" />}
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted group-hover:text-foreground transition-colors truncate">{title}</h3>
          {editCount > 0 && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-success/10 text-success border border-success/30 shrink-0">
              {editCount} edited
            </span>
          )}
        </button>
        {headerExtras && (
          <div className="shrink-0 flex items-center">
            {headerExtras}
          </div>
        )}
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
        <div className="text-sm min-w-0 flex-1">{header}</div>
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
          <div className="absolute right-0 top-full mt-1 z-20 w-[min(20rem,90vw)] max-w-[20rem] p-3 card shadow-xl">
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
  resumeId, jdText, apiUrl, projectCount, onKeptChange, projectScore,
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
    } catch {
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
              <span>Generate projects to improve</span>
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

/** Inline edit-on-click for a single string/enum field. Emits a `replace_field` suggestion. */
function ScalarField({
  label,
  value,
  placeholder,
  options,
  onCommit,
  multiline,
  className,
  hideLabel,
  valueClassName,
}: {
  label: string;
  value: string | undefined;
  placeholder?: string;
  options?: string[];
  onCommit: (next: string) => void;
  multiline?: boolean;
  className?: string;
  hideLabel?: boolean;
  valueClassName?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || "");
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement | null>(null);

  const start = () => {
    setDraft(value || "");
    setEditing(true);
    setTimeout(() => inputRef.current?.focus(), 0);
  };

  const commit = () => {
    const next = (draft || "").trim();
    if (next !== (value || "").trim()) onCommit(next);
    setEditing(false);
  };

  const cancel = () => {
    setDraft(value || "");
    setEditing(false);
  };

  if (editing) {
    if (options && options.length > 0) {
      return (
        <span className={`inline-flex items-center gap-1 ${className || ""}`}>
          <span className="text-[10px] uppercase tracking-wider text-muted">{label}</span>
          <select
            ref={(el) => { inputRef.current = el; }}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Escape") { e.preventDefault(); cancel(); }
              if (e.key === "Enter") { e.preventDefault(); commit(); }
            }}
            className="bg-subtle/60 border border-border rounded px-1.5 py-0.5 text-xs focus:outline-none focus:border-primary"
          >
            <option value="">—</option>
            {options.map((opt) => (
              <option key={opt} value={opt}>{opt}</option>
            ))}
          </select>
        </span>
      );
    }
    if (multiline) {
      return (
        <span className={`inline-block ${className || ""}`}>
          <span className="block text-[10px] uppercase tracking-wider text-muted mb-0.5">{label}</span>
          <textarea
            ref={(el) => { inputRef.current = el; }}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Escape") { e.preventDefault(); cancel(); }
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commit(); }
            }}
            rows={Math.max(1, Math.min(4, draft.split("\n").length))}
            placeholder={placeholder}
            className="w-full bg-subtle/60 border border-border rounded px-2 py-1 text-sm resize-none focus:outline-none focus:border-primary"
          />
        </span>
      );
    }
    return (
      <span className={`inline-flex items-center gap-1 ${className || ""}`}>
        <span className="text-[10px] uppercase tracking-wider text-muted">{label}</span>
        <input
          ref={(el) => { inputRef.current = el; }}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Escape") { e.preventDefault(); cancel(); }
            if (e.key === "Enter") { e.preventDefault(); commit(); }
          }}
          placeholder={placeholder}
          className="bg-subtle/60 border border-border rounded px-1.5 py-0.5 text-xs focus:outline-none focus:border-primary min-w-[8rem]"
        />
      </span>
    );
  }

  const hasValue = !!(value && value.trim());
  return (
    <button
      onClick={start}
      title={`Edit ${label}`}
      className={`group/sf inline-flex items-center gap-1 hover:bg-subtle/60 rounded px-1 py-0.5 transition-colors ${className || ""}`}
    >
      {!hideLabel && <span className="text-[10px] uppercase tracking-wider text-muted">{label}</span>}
      <span className={`${valueClassName || "text-xs"} ${hasValue ? "text-foreground" : "text-muted italic"}`}>
        {hasValue ? value : (placeholder || "—")}
      </span>
      <Pencil className="w-2.5 h-2.5 text-muted opacity-0 group-hover/sf:opacity-100 transition-opacity" />
    </button>
  );
}

/** Per-section visibility toggle. Emits `toggle_hidden`. */
function HideToggle({
  sectionKey,
  isHidden,
  onToggle,
}: {
  sectionKey: string;
  isHidden: boolean;
  onToggle: () => void;
}) {
  return (
    <button
      onClick={onToggle}
      title={isHidden ? `Show ${sectionKey} in preview` : `Hide ${sectionKey} from preview`}
      className={`p-1.5 rounded transition-colors ${isHidden ? "bg-warning/10 text-warning hover:bg-warning/20" : "hover:bg-subtle text-muted hover:text-foreground"}`}
    >
      {isHidden ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
    </button>
  );
}

/** "+ Add <label>" button at section footer. Emits `add_entry`. */
function AddEntryButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className="mt-2 inline-flex items-center gap-1 text-[11px] text-muted hover:text-foreground border border-dashed border-border hover:border-foreground/40 rounded px-2 py-1 transition-colors"
    >
      <Plus className="w-3 h-3" /> Add {label}
    </button>
  );
}

/** Small delete-entry button for entry headers. Emits `delete_entry`. */
function DeleteEntryButton({ onClick, title }: { onClick: () => void; title: string }) {
  return (
    <button
      onClick={onClick}
      title={title}
      className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium text-danger border border-danger/30 hover:bg-danger/10 transition-colors"
    >
      <Trash2 className="w-3 h-3" /> Delete
    </button>
  );
}
