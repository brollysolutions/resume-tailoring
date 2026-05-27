"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { ResumePreview } from "@/components/ResumePreview";
import { ResumeEditor } from "@/components/ResumeEditor";
import type { ResumeData, Suggestion, GeneratedProject } from "@/types/resume";
type EditorSuggestion = Suggestion;
import { Loader2, ArrowLeft, Sparkles, RefreshCw } from "lucide-react";
import { applySuggestionsClient } from "@/lib/applyResume";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import { CopilotChat, type CopilotFocus } from "@/components/CopilotChat";





/** Merge button-replacement projects and chat-appended projects into the payload
 *  expected by backend's _replace_projects(). keptProjects replace by index;
 *  appendedProjects come after all originals. */
function buildMergedProjectPayload(
  keptProjects: GeneratedProject[],
  appendedProjects: GeneratedProject[],
  origProjects: Array<{ name?: string; tech?: string | null; bullets?: string[] }>,
): GeneratedProject[] | undefined {
  if (keptProjects.length === 0 && appendedProjects.length === 0) return undefined;
  const merged: GeneratedProject[] = [];
  const baseLen = Math.max(origProjects.length, keptProjects.length);
  for (let i = 0; i < baseLen; i++) {
    if (i < keptProjects.length) {
      merged.push(keptProjects[i]);
    } else {
      const o = origProjects[i];
      merged.push({ name: o.name || "", tech: o.tech || undefined, bullets: o.bullets || [] } as GeneratedProject);
    }
  }
  return [...merged, ...appendedProjects];
}

function TailorPageContent() {
  const [originalResume, setOriginalResume] = useState<ResumeData | null>(null);
  const [tailoredResume, setTailoredResume] = useState<ResumeData | null>(null);
  const [approved, setApproved] = useState<Suggestion[]>([]);
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [templateId, setTemplateId] = useState<string>("standard");
  const [jdText, setJdText] = useState<string>("");
  const [isInitialLoading, setIsInitialLoading] = useState(true);
  const [isDownloading, setIsDownloading] = useState<"pdf" | "docx" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [matchScore, setMatchScore] = useState<{ original: number; tailored: number } | null>(null);
  const [sectionScores, setSectionScores] = useState<{ original: Record<string, number>; tailored: Record<string, number> } | null>(null);
  const [isScoreLoading, setIsScoreLoading] = useState(false);
  const [staleScore, setStaleScore] = useState(false);
  const [projectNames, setProjectNames] = useState<string[]>([]);
  const initialSuggestionCount = 0;
  const [keptProjects, setKeptProjects] = useState<GeneratedProject[]>([]);
  // Chat-accepted projects appended additively (after originals; separate from button replacements)
  const [appendedProjects, setAppendedProjects] = useState<GeneratedProject[]>([]);
  // Projects generated via chat copilot — reviewed per-card, appended additively
  const [chatGenProjects, setChatGenProjects] = useState<GeneratedProject[]>([]);
  const [nextSuggestionId, setNextSuggestionId] = useState<number>(10000);
  const [showChat, setShowChat] = useState(false);
  const [copilotFocus, setCopilotFocus] = useState<CopilotFocus | null>(null);
  // Version counter — increments on every accepted edit (copilot or manual) so
  // ResumePreview always re-fetches even if React batches state updates.
  const [previewKey, setPreviewKey] = useState(0);

  // Draggable editor width (leftPct %). Copilot panel is fixed at 380px. Preview fills the rest.
  const [leftPct, setLeftPct] = useState(38);
  const isDragging1 = useRef(false);
  const containerRef = useRef<HTMLDivElement>(null);

  const onDivider1MouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    isDragging1.current = true;
    const container = containerRef.current;
    if (!container) return;
    const onMove = (ev: MouseEvent) => {
      if (!isDragging1.current) return;
      const rect = container.getBoundingClientRect();
      const raw = ((ev.clientX - rect.left) / rect.width) * 100;
      setLeftPct(Math.min(showChat ? 60 : 80, Math.max(20, raw)));
    };
    const onUp = () => {
      isDragging1.current = false;
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  }, [showChat]);

  // ----- Persistence Helpers -----
  const getSessionKey = useCallback((rid: string | null, jd: string | null) => {
    if (!rid || !jd) return null;
    return `tailor_v1_${rid}_${jd.length}_${jd.slice(0, 32)}`;
  }, []);

  // Sync state to localStorage whenever it changes
  useEffect(() => {
    if (isInitialLoading || !resumeId || !jdText) return;
    const key = getSessionKey(resumeId, jdText);
    if (!key) return;
    localStorage.setItem(key, JSON.stringify({
      approved,
      keptProjects,
      appendedProjects,
      nextSuggestionId
    }));
  }, [approved, keptProjects, appendedProjects, nextSuggestionId, resumeId, jdText, isInitialLoading, getSessionKey]);

  // Stable initial score function for the loader
  const initialScore = useCallback(async (rid: string, jd: string, apprv: Suggestion[], projs: GeneratedProject[]) => {
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
      const res = await fetch(`${apiUrl}/api/match/tailored`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: rid,
          jd_text: jd,
          accepted_suggestions: apprv.map((s) => ({
            section: s.section, mode: s.mode,
            original: s.original, suggested: s.suggested,
            category: s.category, skill: s.skill,
            target_category: s.target_category, is_new_category: s.is_new_category,
            new_skills: s.new_skills,
          })),
          new_projects: projs.length > 0 ? projs : [],
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
    } catch { /* ignore */ }
  }, []);



  // ----- Initial load -----
  useEffect(() => {
    const run = async () => {
      try {
        const jd = localStorage.getItem("tailor_jd_text") || "";
        const rid = localStorage.getItem("current_resume_id");
        const storedTid = localStorage.getItem("template_id");
        const tid = storedTid && storedTid !== "mimic" ? storedTid : "standard";
        if (!jd) { setError("No job description found. Go back and paste a Job Description first."); return setIsInitialLoading(false); }
        if (!rid) { setError("No resume found. Upload a resume first."); return setIsInitialLoading(false); }
        setResumeId(rid);
        setTemplateId(tid);
        setJdText(jd);

        // Check for persisted state
        const sessionKey = getSessionKey(rid, jd);
        let restoredApproved: Suggestion[] = [];
        let restoredProjects: GeneratedProject[] = [];
        let restoredAppended: GeneratedProject[] = [];
        let restoredNextId: number | null = null;
        if (sessionKey) {
          const saved = localStorage.getItem(sessionKey);
          if (saved) {
            try {
              const parsed = JSON.parse(saved);
              restoredApproved = parsed.approved || [];
              restoredProjects = parsed.keptProjects || [];
              restoredAppended = parsed.appendedProjects || [];
              restoredNextId = parsed.nextSuggestionId;
              setApproved(restoredApproved);
              setKeptProjects(restoredProjects);
              setAppendedProjects(restoredAppended);
              if (restoredNextId) setNextSuggestionId(restoredNextId);
            } catch (e) { console.warn("Failed to restore session", e); }
          }
        }

        const applyPersistence = (rj: ResumeData) => {
          let current = { ...rj };
          // Fold in button-replaced projects (index-based)
          if (restoredProjects.length > 0) {
            const existing = [...(current.projects || [])];
            restoredProjects.forEach((np, idx) => {
              const proj = { name: np.name, tech: np.tech, bullets: np.bullets };
              if (idx < existing.length) existing[idx] = proj;
              else existing.push(proj);
            });
            current.projects = existing;
          }
          // Append chat-accepted projects after all existing/replaced
          if (restoredAppended.length > 0) {
            current.projects = [
              ...(current.projects || []),
              ...restoredAppended.map((np) => ({ name: np.name, tech: np.tech, bullets: np.bullets })),
            ];
          }
          // Apply suggestions
          if (restoredApproved.length > 0) {
            current = applySuggestionsClient(current, restoredApproved);
          }
          return current;
        };

        // Use pre-fetched data from job-search page overlay if available
        const prefetchStr = sessionStorage.getItem("tailor_prefetch");
        if (prefetchStr) {
          sessionStorage.removeItem("tailor_prefetch");
          try {
            const pf = JSON.parse(prefetchStr);
            if (pf.resume) {
              const rj = pf.resume as ResumeData;
              setOriginalResume(rj);
              setTailoredResume(applyPersistence(rj));
              setProjectNames((rj.projects || []).map((p) => p.name || ""));
            }
            if (pf.project_names) {
              setProjectNames(pf.project_names);
            }
            // Skip network fetch — data already here
            if (rid && jd) {
              const origProjs = (pf.resume as ResumeData)?.projects || [];
              const mergedProjs = buildMergedProjectPayload(restoredProjects, restoredAppended, origProjs) ?? [];
              await initialScore(rid, jd, restoredApproved, mergedProjs);
            }
            return; 
          } catch { /* fall through to normal fetch */ }
        }

        const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";

        const resumeRes = await fetch(`${apiUrl}/api/resume/${rid}/json`);

        let fetchedResume: ResumeData | null = null;
        if (resumeRes.ok) {
          const rj = (await resumeRes.json()) as ResumeData;
          fetchedResume = rj;
          setOriginalResume(rj);
          setTailoredResume(applyPersistence(rj));
          setProjectNames((rj.projects || []).map((p) => p.name || ""));
        } else {
          throw new Error("Failed to load resume JSON.");
        }

        // Ensure score is fetched before resolving isLoading
        if (rid && jd) {
          const mergedProjs = buildMergedProjectPayload(restoredProjects, restoredAppended, fetchedResume?.projects || []) ?? [];
          await initialScore(rid, jd, restoredApproved, mergedProjs);
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Something went wrong.");
      } finally {
        setIsInitialLoading(false);
      }
    };

    run();
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

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
            new_skills: s.new_skills,
          })),
          new_projects: buildMergedProjectPayload(keptProjects, appendedProjects, originalResume?.projects || []) ?? [],
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
  }, [resumeId, jdText, approved, keptProjects, appendedProjects, originalResume]);

  // Refs to avoid stale closure issues in debounced recalc
  const recalcMatchRef = useRef(recalcMatch);
  useEffect(() => {
    recalcMatchRef.current = recalcMatch;
  }, [recalcMatch]);

  const recalcTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const scheduleRecalc = useCallback(() => {
    if (recalcTimerRef.current) {
      clearTimeout(recalcTimerRef.current);
    }
    recalcTimerRef.current = setTimeout(() => {
      recalcMatchRef.current();
    }, 700);
  }, []);

  // Clear pending timer on unmount
  useEffect(() => {
    return () => {
      if (recalcTimerRef.current) {
        clearTimeout(recalcTimerRef.current);
      }
    };
  }, []);

  // ----- Edit emit: append to approved + apply to local resume -----
  const handleEmit = useCallback((sg: Omit<Suggestion, "id">) => {
    const withId: Suggestion = { ...(sg as Suggestion), id: nextSuggestionId, reasoning: sg.reasoning || "User edit" };
    setNextSuggestionId((n) => n + 1);
    setApproved((prev) => [...prev, withId]);
    setTailoredResume((prev) => prev ? applySuggestionsClient(prev, [withId]) : prev);
    setPreviewKey((k) => k + 1);
    setStaleScore(true);
    scheduleRecalc();
  }, [nextSuggestionId, scheduleRecalc]);

  // No-op stubs kept for ResumeEditor prop compatibility (AI suggestions removed).
  const handleAcceptPending = useCallback(() => {}, []);
  const handleRejectPending = useCallback(() => {}, []);

  const handleReorderSections = useCallback((newOrder: string[]) => {
    const withId: Suggestion = {
      section: "Global",
      mode: "reorder_sections",
      suggested: JSON.stringify(newOrder),
      reasoning: "User reordered sections",
      id: nextSuggestionId,
    };
    setNextSuggestionId((n) => n + 1);
    // Replace any prior reorder suggestion so the approved list doesn't grow unboundedly.
    setApproved((prev) => [...prev.filter((s) => s.mode !== "reorder_sections"), withId]);
    setTailoredResume((prev) => prev ? applySuggestionsClient(prev, [withId]) : prev);
    setPreviewKey((k) => k + 1);
    setStaleScore(true);
    scheduleRecalc();
  }, [nextSuggestionId, scheduleRecalc]);

  // Revert: pop from approved, rebuild local resume from original + remaining approved.
  const handleRevert = useCallback((id: number) => {
    setApproved((prev) => {
      const next = prev.filter((x) => x.id !== id);
      setTailoredResume(originalResume ? applySuggestionsClient(originalResume, next) : originalResume);
      setPreviewKey((k) => k + 1);
      setStaleScore(true);
      scheduleRecalc();
      return next;
    });
  }, [originalResume, scheduleRecalc]);



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
    setPreviewKey((k) => k + 1);
    setStaleScore(true);
    scheduleRecalc();
  }, [originalResume, approved, scheduleRecalc]);

  // ----- Copilot: generate projects on directive -----
  const runGenerateProjects = useCallback(async (opts: { count?: number | null; more?: boolean } = {}) => {
    if (!resumeId || !jdText) return;
    const count = opts.count ?? (projectNames.length > 0 ? projectNames.length : 3);
    // Build exclude list: when appending, exclude all names already on the resume + already kept/appended/pending
    const excludeNames = opts.more
      ? [
          ...projectNames,
          ...keptProjects.map((p) => p.name),
          ...appendedProjects.map((p) => p.name),
          ...chatGenProjects.map((p) => p.name),
        ]
      : [];
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
      const res = await fetch(`${apiUrl}/api/tailor/generate-projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: resumeId,
          jd_text: jdText,
          count,
          exclude_names: excludeNames,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        const newProjects: GeneratedProject[] = data.projects || [];
        if (newProjects.length > 0) {
          // Do NOT auto-apply — surface as reviewable cards in chat
          setChatGenProjects((prev) => (opts.more ? [...prev, ...newProjects] : newProjects));
        }
      }
    } catch { /* non-fatal */ }
  }, [resumeId, jdText, projectNames, keptProjects, appendedProjects, chatGenProjects]);

  // ----- Copilot: accept one proposed suggestion -----
  const handleAcceptCopilot = useCallback((s: Suggestion) => {
    setApproved((prev) => (prev.some((x) => x.id === s.id) ? prev : [...prev, s]));
    setTailoredResume((prev) => (prev ? applySuggestionsClient(prev, [s]) : prev));
    setNextSuggestionId((n) => Math.max(n, (s.id || 0) + 1));
    setPreviewKey((k) => k + 1);
    setStaleScore(true);
    scheduleRecalc();
  }, [scheduleRecalc]);

  // ----- Chat copilot: append a reviewed project card to the resume (additive) -----
  const handleAppendProject = useCallback((project: GeneratedProject) => {
    // Remove from pending review list
    setChatGenProjects((prev) => prev.filter((p) => p.name !== project.name));
    // Append to tailored resume additively (after existing real projects)
    setTailoredResume((prev) => {
      if (!prev) return prev;
      const existingProjects = [...(prev.projects || [])];
      existingProjects.push({ name: project.name, tech: project.tech, bullets: project.bullets });
      return { ...prev, projects: existingProjects };
    });
    // Track in appendedProjects so it's included in score + download payloads (additive)
    setAppendedProjects((prev) => [...prev, project]);
    setPreviewKey((k) => k + 1);
    setStaleScore(true);
    scheduleRecalc();
  }, [scheduleRecalc]);

  // ----- Chat copilot: skip (dismiss) a reviewed project card -----
  const handleSkipProject = useCallback((projectName: string) => {
    setChatGenProjects((prev) => prev.filter((p) => p.name !== projectName));
  }, []);

  // ----- Copilot: per-response side effects (id bump + directives) -----
  const handleCopilotResult = useCallback((suggestions: Suggestion[], directives: { type: string }[]) => {
    if (suggestions.length > 0) {
      const maxId = suggestions.reduce((m, s) => Math.max(m, s.id || 0), 0);
      setNextSuggestionId((n) => Math.max(n, maxId + 1));
    }
    for (const d of directives || []) {
      if (d.type === "undo_last") {
        setApproved((prev) => {
          if (prev.length === 0) return prev;
          const last = prev[prev.length - 1];
          const next = prev.filter((x) => x.id !== last.id);
          setTailoredResume(originalResume ? applySuggestionsClient(originalResume, next) : originalResume);
          setPreviewKey((k) => k + 1);
          setStaleScore(true);
          scheduleRecalc();
          return next;
        });
      } else if (d.type === "generate_projects") {
        const gd = d as { count?: number; more?: boolean };
        void runGenerateProjects({ count: gd.count, more: gd.more });
      }
    }
  }, [originalResume, scheduleRecalc, runGenerateProjects]);

  // ----- Download -----
  const handleDownload = async (format: "pdf" | "docx", layoutDensity?: string) => {
    if (!resumeId) return;
    setIsDownloading(format);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
      const projPayload = buildMergedProjectPayload(keptProjects, appendedProjects, originalResume?.projects || []);
      const res = await fetch(`${apiUrl}/api/tailor/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: resumeId,
          suggestions: approved,
          format,
          template_id: templateId,
          layout_density: layoutDensity,
          ...(projPayload && projPayload.length > 0 ? { new_projects: projPayload } : {}),
          // Calibration signal — backend's implicit_labeler joins these to
          // compute acceptance ratio per (resume_id, jd_hash).
          jd_text: jdText,
          total_suggestions: initialSuggestionCount,
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
              {/* AI Copilot toggle button */}
              {!showChat && (
                <button
                  onClick={() => setShowChat(true)}
                  className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full bg-gradient-to-r from-blue-600 via-blue-700 to-indigo-700 hover:from-blue-500 hover:via-blue-600 hover:to-indigo-600 text-white text-[11px] font-semibold shadow-md shadow-blue-500/15 hover:shadow-lg hover:shadow-blue-500/25 hover:-translate-y-0.5 active:translate-y-0 active:scale-95 transition-all duration-200 cursor-pointer border border-blue-400/20"
                  title="Open AI Tailoring Copilot Chat"
                >
                  <Sparkles className="w-3 h-3.5 text-blue-100 animate-pulse" />
                  <span>AI Copilot</span>
                </button>
              )}
              {/* Match score pill */}
              {(matchScore || isInitialLoading || isScoreLoading) && (
                <button
                  onClick={recalcMatch}
                  disabled={isInitialLoading || isScoreLoading}
                  className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full border border-border text-[11px] font-medium hover:border-foreground/30 transition-colors disabled:opacity-50`}
                  title="Click to recalculate"
                >
                  Match:{" "}
                  {matchScore ? (
                    <span className={`${scoreColor} ${staleScore ? "opacity-60" : ""}`}>{matchScore.tailored}%</span>
                  ) : (
                    <span className="text-muted animate-pulse">--%</span>
                  )}
                  {isScoreLoading || isInitialLoading ? (
                    <Loader2 className="w-3 h-3 animate-spin" />
                  ) : (
                    <RefreshCw className="w-3 h-3 text-muted" />
                  )}
                </button>
              )}
            </div>
          </div>
 
          {/* The editor or skeleton */}
          {isInitialLoading ? (
            <div className="space-y-4 animate-pulse">
              {[1, 2, 3].map((i) => (
                <div key={i} className="card p-4 space-y-3">
                  <div className="h-4 bg-border rounded w-1/4" />
                  <div className="space-y-2">
                    <div className="h-2.5 bg-border/60 rounded w-full" />
                    <div className="h-2.5 bg-border/60 rounded w-5/6" />
                  </div>
                </div>
              ))}
            </div>
          ) : tailoredResume ? (
            <ResumeEditor
              resume={tailoredResume}
              templateId={templateId}
              pendingSuggestions={[] as EditorSuggestion[]}
              accepted={approved as EditorSuggestion[]}
              onEmit={(s) => handleEmit(s as Omit<Suggestion, "id">)}
              onRevert={handleRevert}
              onAcceptPending={handleAcceptPending}
              onRejectPending={handleRejectPending}
              onReorderSections={handleReorderSections}
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
              onCopilotFocus={(payload) => {
                setCopilotFocus(payload);
                setShowChat(true);
              }}
            />
          ) : (
            <div className="card p-6 text-center">
              <p className="text-sm text-muted">Resume not loaded.</p>
            </div>
          )}
        </div>

        {/* Divider 1 */}
        <div
          onMouseDown={onDivider1MouseDown}
          className="w-1.5 flex-shrink-0 cursor-col-resize group relative"
          title="Drag to resize"
        >
          <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-0.5 bg-border transition-colors group-hover:bg-foreground/30 group-active:bg-primary" />
        </div>

        {/* Middle — Copilot Chat (fixed 380px) */}
        {showChat && (
          <>
            <div
              className="relative overflow-hidden flex-shrink-0 h-full flex flex-col px-3"
              style={{ width: "380px" }}
            >
              <CopilotChat
                resumeId={resumeId}
                jdText={jdText}
                apiUrl={process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004"}
                approved={approved}
                keptProjects={keptProjects}
                nextSuggestionId={nextSuggestionId}
                focus={copilotFocus}
                onClearFocus={() => setCopilotFocus(null)}
                onAcceptSuggestion={handleAcceptCopilot}
                onResult={handleCopilotResult}
                onClose={() => setShowChat(false)}
                pendingProjects={chatGenProjects}
                onKeepProject={handleAppendProject}
                onSkipProject={handleSkipProject}
              />
            </div>

            {/* Divider 2 — static, no resize */}
            <div className="w-1.5 flex-shrink-0 relative">
              <div className="absolute inset-y-0 left-1/2 -translate-x-1/2 w-0.5 bg-border" />
            </div>
          </>
        )}

        {/* Right — preview or skeleton */}
        <div className="min-w-0 flex-1 flex flex-col overflow-hidden pl-3">
          <div className="flex-1 min-h-0 flex flex-col">
            {isInitialLoading ? (
              <div className="aspect-[8.5/11] bg-subtle animate-pulse p-8 space-y-5">
                <div className="space-y-2">
                  <div className="h-5 bg-border rounded w-2/5" />
                  <div className="h-3 bg-border/60 rounded w-1/2" />
                  <div className="h-3 bg-border/60 rounded w-1/3" />
                </div>
                <div className="h-px bg-border" />
                <div className="space-y-2">
                  <div className="h-3 bg-border rounded w-1/4" />
                  <div className="h-2.5 bg-border/60 rounded w-full" />
                  <div className="h-2.5 bg-border/60 rounded w-5/6" />
                </div>
                <div className="space-y-2">
                  <div className="h-3 bg-border rounded w-1/4" />
                  <div className="h-2.5 bg-border/60 rounded w-full" />
                  <div className="h-2.5 bg-border/60 rounded w-11/12" />
                </div>
                <div className="h-px bg-border" />
                <div className="space-y-2">
                  <div className="h-3 bg-border rounded w-1/5" />
                  <div className="h-2.5 bg-border/60 rounded w-3/4" />
                </div>
              </div>
            ) : (
              <ResumePreview
                resumeId={resumeId}
                templateId={templateId}
                approvedSuggestions={approved}
                newProjects={keptProjects.length > 0 ? keptProjects : undefined}
                resume={tailoredResume}
                onDownload={handleDownload}
                isDownloading={isDownloading}
                previewKey={previewKey}
              />
            )}
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
