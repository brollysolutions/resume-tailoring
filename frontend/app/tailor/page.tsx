"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { ResumePreview } from "@/components/ResumePreview";
import { ResumeEditor } from "@/components/ResumeEditor";
import { GenerateProjectsStep } from "@/components/StepContent";
import type { ResumeData, Suggestion, GeneratedProject } from "@/types/resume";
type EditorSuggestion = Suggestion;
import { Loader2, ArrowLeft, Sparkles, RefreshCw } from "lucide-react";
import { applySuggestionsClient } from "@/lib/applyResume";
import { ErrorBoundary } from "@/components/ErrorBoundary";

function TailorPageContent() {
  const [originalResume, setOriginalResume] = useState<ResumeData | null>(null);
  const [tailoredResume, setTailoredResume] = useState<ResumeData | null>(null);
  const [pendingSuggestions, setPendingSuggestions] = useState<Suggestion[]>([]);
  const [approved, setApproved] = useState<Suggestion[]>([]);
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [templateId, setTemplateId] = useState<string>("modern");
  const [jdText, setJdText] = useState<string>("");
  const [isLoading, setIsLoading] = useState(true);
  const [isDownloading, setIsDownloading] = useState<"pdf" | "docx" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [matchScore, setMatchScore] = useState<{ original: number; tailored: number } | null>(null);
  const [sectionScores, setSectionScores] = useState<{ original: Record<string, number>; tailored: Record<string, number> } | null>(null);
  const [isScoreLoading, setIsScoreLoading] = useState(false);
  const [staleScore, setStaleScore] = useState(false);
  const [projectNames, setProjectNames] = useState<string[]>([]);
  const [keptProjects, setKeptProjects] = useState<GeneratedProject[]>([]);
  const [nextSuggestionId, setNextSuggestionId] = useState<number>(10000);
  const [showGenerateProjects, setShowGenerateProjects] = useState(false);

  // Draggable divider between editor (left) and preview (right).
  const [leftPct, setLeftPct] = useState(45);
  const isDragging = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const onDividerMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging.current = true;
    const container = containerRef.current;
    if (!container) return;
    const onMove = (ev: MouseEvent) => {
      if (!isDragging.current) return;
      const rect = container.getBoundingClientRect();
      const raw = ((ev.clientX - rect.left) / rect.width) * 100;
      setLeftPct(Math.min(70, Math.max(25, raw)));
    };
    const onUp = () => {
      isDragging.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, []);

  // ----- Initial load -----
  useEffect(() => {
    const run = async () => {
      try {
        const jd = sessionStorage.getItem("tailor_jd_text") || "";
        const rid = sessionStorage.getItem("current_resume_id");
        const tid = sessionStorage.getItem("template_id") || "modern";
        if (!jd) { setError("No job description found. Go back and paste a Job Description first."); return setIsLoading(false); }
        if (!rid) { setError("No resume found. Upload a resume first."); return setIsLoading(false); }
        setResumeId(rid);
        setTemplateId(tid);
        setJdText(jd);

        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";

        // Parallel: fetch resume JSON + suggestions
        const [resumeRes, suggRes] = await Promise.all([
          fetch(`${apiUrl}/api/resume/${rid}/json`),
          fetch(`${apiUrl}/api/tailor/suggestions`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ resume_id: rid, jd_text: jd }),
          }),
        ]);

        if (resumeRes.ok) {
          const rj = (await resumeRes.json()) as ResumeData;
          setOriginalResume(rj);
          setTailoredResume(rj);
        }

        if (!suggRes.ok) {
          const d = await suggRes.json().catch(() => ({}));
          throw new Error(d.detail || "Failed to generate suggestions.");
        }
        const data = await suggRes.json();
        const sugg: Suggestion[] = data.suggestions || [];
        setPendingSuggestions(sugg);
        setProjectNames(data.project_names || []);
        const maxId = sugg.reduce((m: number, s: Suggestion) => Math.max(m, s.id || 0), 0);
        setNextSuggestionId(Math.max(maxId + 1, 10000));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Something went wrong.");
      } finally {
        setIsLoading(false);
      }
    };
    run();
  }, []);

  // ----- Score recalc on demand only -----
  const recalcMatch = useCallback(async () => {
    if (!resumeId || !jdText) return;
    setIsScoreLoading(true);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
      const res = await fetch(`${apiUrl}/api/match/tailored`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: resumeId,
          jd_text: jdText,
          accepted_suggestions: approved.map((s) => ({
            section: s.section, mode: s.mode,
            original: s.original, suggested: s.suggested,
            category: s.category, skill: s.skill,
            target_category: s.target_category, is_new_category: s.is_new_category,
          })),
          new_projects: keptProjects.length > 0 ? keptProjects : [],
        }),
      });
      if (res.ok) {
        const data = await res.json();
        const clamp = (n: number) => Math.max(0, Math.min(100, Number(n) || 0));
        setMatchScore({ original: clamp(data.original?.score), tailored: clamp(data.tailored?.score) });
        if (data.tailored?.section_scores || data.original?.section_scores) {
          setSectionScores({
            original: data.original?.section_scores || {},
            tailored: data.tailored?.section_scores || {},
          });
        }
        setStaleScore(false);
      }
    } catch {
      // non-fatal
    } finally {
      setIsScoreLoading(false);
    }
  }, [resumeId, jdText, approved, keptProjects]);

  // Initial score (no edits)
  useEffect(() => {
    if (resumeId && jdText) {
      recalcMatch();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resumeId, jdText]);

  // ----- Edit emit: append to approved + apply to local resume -----
  const handleEmit = useCallback((sg: Omit<Suggestion, "id">) => {
    const withId: Suggestion = { ...(sg as Suggestion), id: nextSuggestionId, reasoning: sg.reasoning || "User edit" };
    setNextSuggestionId((n) => n + 1);
    setApproved((prev) => [...prev, withId]);
    setTailoredResume((prev) => prev ? applySuggestionsClient(prev, [withId]) : prev);
    setStaleScore(true);
  }, [nextSuggestionId]);

  // Batch emit — entry-level AI rewrite emits N replace suggestions at once.
  const handleEmitBatch = useCallback((batch: Array<Omit<Suggestion, "id">>) => {
    if (batch.length === 0) return;
    setNextSuggestionId((startId) => {
      const withIds: Suggestion[] = batch.map((sg, i) => ({
        ...(sg as Suggestion),
        id: startId + i,
        reasoning: sg.reasoning || "Entry AI rewrite",
      }));
      setApproved((prev) => [...prev, ...withIds]);
      setTailoredResume((prev) => prev ? applySuggestionsClient(prev, withIds) : prev);
      setStaleScore(true);
      return startId + batch.length;
    });
  }, []);

  // Accept an LLM pending suggestion → moves to approved + applies locally.
  const handleAcceptPending = useCallback((id: number, edited: string) => {
    const s = pendingSuggestions.find((x) => x.id === id);
    if (!s) return;
    // Skills uses the explicit-field schema (no `suggested` field). For other
    // sections the `edited` string overrides the suggested text.
    const isSkills = (s.section || "").toLowerCase().startsWith("skill");
    const next: Suggestion = isSkills ? { ...s } : { ...s, suggested: edited };
    setApproved((prev) => [...prev, next]);
    setPendingSuggestions((prev) => prev.filter((x) => x.id !== id));
    setTailoredResume((prev) => prev ? applySuggestionsClient(prev, [next]) : prev);
    setStaleScore(true);
  }, [pendingSuggestions]);

  const handleRejectPending = useCallback((id: number) => {
    setPendingSuggestions((prev) => prev.filter((x) => x.id !== id));
  }, []);

  // Revert: pop from approved, rebuild local resume from original + remaining approved.
  const handleRevert = useCallback((id: number) => {
    setApproved((prev) => {
      const next = prev.filter((x) => x.id !== id);
      setTailoredResume(originalResume ? applySuggestionsClient(originalResume, next) : originalResume);
      setStaleScore(true);
      return next;
    });
  }, [originalResume]);

  // ----- AI chat (per-line) -----
  const handleAiChat = useCallback(async (section: string, originalLine: string, instruction: string): Promise<string> => {
    if (!resumeId) throw new Error("No resume");
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
    const res = await fetch(`${apiUrl}/api/tailor/chat-line`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        resume_id: resumeId,
        jd_text: jdText,
        section,
        original_line: originalLine,
        user_prompt: instruction,
        accepted_suggestions: approved.map((s) => ({
          section: s.section, mode: s.mode,
          original: s.original, suggested: s.suggested,
          category: s.category, skill: s.skill,
          target_category: s.target_category, is_new_category: s.is_new_category,
        })),
        new_projects: keptProjects.length > 0 ? keptProjects : null,
      }),
    });
    if (!res.ok) {
      const d = await res.json().catch(() => ({}));
      throw new Error(d.detail || "AI request failed.");
    }
    const data = await res.json();
    return data.rewritten || originalLine;
  }, [resumeId, jdText, approved, keptProjects]);

  // ----- Project generation kept change -----
  const handleKeptChange = useCallback((next: GeneratedProject[]) => {
    setKeptProjects(next);
    // Fold into tailored resume so editor + preview reflect it
    if (originalResume) {
      const folded: ResumeData = { ...originalResume };
      const existing = [...(folded.projects || [])];
      next.forEach((np, idx) => {
        const proj = {
          name: np.name,
          tech: np.tech,
          bullets: np.bullets,
        };
        if (idx < existing.length) {
          existing[idx] = proj;
        } else {
          existing.push(proj);
        }
      });
      folded.projects = existing;
      setTailoredResume(applySuggestionsClient(folded, approved));
    }
    setStaleScore(true);
  }, [originalResume, approved]);

  // ----- Download -----
  const handleDownload = async (format: "pdf" | "docx") => {
    if (!resumeId) return;
    setIsDownloading(format);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
      const res = await fetch(`${apiUrl}/api/tailor/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: resumeId,
          suggestions: approved,
          format,
          template_id: templateId,
          ...(keptProjects.length > 0 ? { new_projects: keptProjects } : {}),
        }),
      });
      if (!res.ok) throw new Error("Failed to generate tailored document.");
      const disposition = res.headers.get("content-disposition") || "";
      const match = disposition.match(/filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?/i);
      const filename = match ? decodeURIComponent(match[1]) : `Tailored_Resume.${format}`;
      const blob = await res.blob();
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      window.URL.revokeObjectURL(url);
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to download document.");
    } finally {
      setIsDownloading(null);
    }
  };

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-3">
        <Loader2 className="w-5 h-5 animate-spin text-muted" />
        <p className="text-sm text-muted">Loading your resume against the Job Description…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4 px-6 text-center">
        <p className="text-base font-medium">Something went wrong</p>
        <p className="text-sm text-muted max-w-md">{error}</p>
        <button onClick={() => window.history.back()} className="btn-secondary">
          <ArrowLeft className="w-4 h-4" /> Go back
        </button>
      </div>
    );
  }

  const scoreColor =
    !matchScore ? "" :
    matchScore.tailored >= 70 ? "text-success" :
    matchScore.tailored >= 40 ? "text-amber-600" :
    "text-danger";

  return (
    <div className="w-full max-w-[1600px] mx-auto px-6 pt-4 pb-6">
      <div ref={containerRef} className="flex gap-0 lg:h-[calc(100vh_-_2rem)]">
        {/* Left — editor */}
        <div
          className="relative min-w-0 overflow-y-auto scrollbar-thin pr-3 flex-shrink-0"
          style={{ width: `${leftPct}%` }}
        >
          {/* Top bar */}
          <div className="sticky top-0 z-20 bg-background/95 backdrop-blur border-b border-border py-2.5 mb-3">
            <div className="flex items-center gap-3 flex-wrap">
              <button onClick={() => window.history.back()} className="btn-ghost p-1.5" aria-label="Back">
                <ArrowLeft className="w-4 h-4" />
              </button>
              <h1 className="text-base font-semibold tracking-tight leading-tight flex-1">
                Tailor your resume
              </h1>
              {/* Match score pill */}
              {matchScore && (
                <button
                  onClick={recalcMatch}
                  className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border border-border text-[11px] font-medium hover:border-foreground/30 transition-colors`}
                  title="Click to recalculate"
                >
                  Match: <span className={`${scoreColor} ${staleScore ? "opacity-60" : ""}`}>{matchScore.tailored}%</span>
                  {isScoreLoading ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3 text-muted" />}
                </button>
              )}
            </div>
          </div>

          {/* Section match breakdown */}
          {sectionScores?.tailored && Object.keys(sectionScores?.tailored || {}).length > 0 && (
            <div className="mb-3 p-2.5 rounded-md bg-subtle border border-border text-[10px] space-y-1.5">
              <p className="font-semibold text-muted">Match by section:</p>
              <div className="space-y-1">
                {Object.entries(sectionScores?.tailored || {}).map(([section, score]) => {
                  const tailoredScore = Number(score) || 0;
                  if (tailoredScore === 0) return null;
                  const color = tailoredScore >= 75 ? "text-success" : tailoredScore >= 60 ? "text-amber-600" : "text-danger";
                  return (
                    <div key={section} className="flex items-center justify-between gap-2">
                      <span className="text-muted capitalize">{section}</span>
                      <span className={`font-medium ${color}`}>{tailoredScore}%</span>
                    </div>
                  );
                })}
              </div>
              <p className="text-muted pt-1 border-t border-border">
                💡 Sections below 75% need more alignment with the JD.
              </p>
            </div>
          )}

          {/* AI hint banner */}
          {pendingSuggestions.length > 0 && (
            <div className="mb-3 px-3 py-2 rounded-md bg-amber-50 border border-amber-200 text-amber-800 text-[11px] inline-flex items-center gap-2">
              <Sparkles className="w-3 h-3" />
              {pendingSuggestions.length} AI suggestion{pendingSuggestions.length !== 1 ? "s" : ""} available — look for the ✨ icon on lines below.
            </div>
          )}

          {/* The editor */}
          {tailoredResume ? (
            <ResumeEditor
              resume={tailoredResume}
              pendingSuggestions={pendingSuggestions as EditorSuggestion[]}
              accepted={approved as EditorSuggestion[]}
              onEmit={(s) => handleEmit(s as Omit<Suggestion, "id">)}
              onEmitBatch={(batch) => handleEmitBatch(batch as Array<Omit<Suggestion, "id">>)}
              onRevert={handleRevert}
              onAcceptPending={handleAcceptPending}
              onRejectPending={handleRejectPending}
              onAiChat={handleAiChat}
              apiUrl={process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004"}
              resumeId={resumeId}
              jdText={jdText}
              newProjects={keptProjects.length > 0 ? keptProjects : undefined}
              nextSuggestionId={nextSuggestionId}
              sectionScores={sectionScores?.tailored || null}
              keptProjects={keptProjects}
              projectCount={projectNames.length}
              projectNames={projectNames}
              onKeptChange={handleKeptChange}
            />
          ) : (
            <div className="card p-6 text-center">
              <p className="text-sm text-muted">Resume not loaded.</p>
            </div>
          )}
        </div>

        {/* Divider */}
        <div
          onMouseDown={onDividerMouseDown}
          className="w-1.5 flex-shrink-0 cursor-col-resize group relative"
          title="Drag to resize"
        >
          <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-0.5 bg-border transition-colors group-hover:bg-foreground/30 group-active:bg-primary" />
        </div>

        {/* Right — preview */}
        <div className="min-w-0 flex-1 flex flex-col overflow-hidden">
          <div className="flex-1 min-h-0">
            <ResumePreview
              resumeId={resumeId}
              templateId={templateId}
              approvedSuggestions={approved}
              newProjects={keptProjects.length > 0 ? keptProjects : undefined}
              resume={tailoredResume}
              onDownload={handleDownload}
              isDownloading={isDownloading}
            />
          </div>
        </div>
      </div>
    </div>
  );
}

export default function TailorPage() {
  return (
    <ErrorBoundary>
      <TailorPageContent />
    </ErrorBoundary>
  );
}
