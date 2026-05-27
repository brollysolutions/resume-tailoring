"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { ExternalLink, ArrowRight, Loader2, Target, Maximize2, X, SlidersHorizontal, Wand2, GripVertical, Save, Eye, EyeOff, Download, AlertTriangle, CheckCircle2, Sparkles, HelpCircle, Info } from "lucide-react";
import { Tabs } from "@/components/Tabs";
import { TemplatePreview } from "@/components/TemplatePreview";

type LowSection = { section: string; score: number; reason: string; explanation: string };

interface GapAnalysis {
  missing_keywords: string[];
  low_sections: LowSection[];
}

type ResultsTab = "overview" | "sections" | "suggestions";

const SECTION_ORDER = ["Experience", "Projects", "Skills", "Summary"] as const;

const SECTION_LABELS: Record<string, string> = {
  summary: "Summary",
  experience: "Experience",
  projects: "Projects",
  education: "Education",
  skills: "Skills",
  certifications: "Certifications",
  publications: "Publications",
  awards: "Awards",
  languages: "Languages",
  volunteer: "Volunteer Experience",
  patents: "Patents",
  talks: "Talks & Presentations",
};

function sectionLabel(key: string): string {
  if (key.startsWith("extra:")) return key.slice(6);
  return SECTION_LABELS[key] || key;
}

type ResumeShape = {
  section_order?: string[];
  hidden_sections?: string[];
  summary?: string | null;
  experience?: unknown[];
  projects?: unknown[];
  education?: unknown[];
  skills?: unknown[];
  certifications?: unknown[];
  publications?: unknown[];
  awards?: unknown[];
  languages?: unknown[];
  volunteer?: unknown[];
  patents?: unknown[];
  talks?: unknown[];
  extra_sections?: { title: string }[];
};

function buildOrderFromResume(r: ResumeShape): string[] {
  const present = new Set<string>();
  if (r.summary) present.add("summary");
  if ((r.experience?.length ?? 0) > 0) present.add("experience");
  if ((r.projects?.length ?? 0) > 0) present.add("projects");
  if ((r.education?.length ?? 0) > 0) present.add("education");
  if ((r.skills?.length ?? 0) > 0) present.add("skills");
  if ((r.certifications?.length ?? 0) > 0) present.add("certifications");
  if ((r.publications?.length ?? 0) > 0) present.add("publications");
  if ((r.awards?.length ?? 0) > 0) present.add("awards");
  if ((r.languages?.length ?? 0) > 0) present.add("languages");
  if ((r.volunteer?.length ?? 0) > 0) present.add("volunteer");
  if ((r.patents?.length ?? 0) > 0) present.add("patents");
  if ((r.talks?.length ?? 0) > 0) present.add("talks");
  const extras = (r.extra_sections || []).map((e) => `extra:${e.title}`);
  const stored = r.section_order || [];
  const merged: string[] = [];
  for (const s of stored) {
    if (present.has(s) || s.startsWith("extra:")) merged.push(s);
  }
  for (const s of present) {
    if (!merged.includes(s)) merged.push(s);
  }
  for (const s of extras) {
    if (!merged.includes(s)) merged.push(s);
  }
  return merged;
}

type SectionFeatures = { keyword?: number; skill?: number; ngram?: number; edu?: number; seniority?: number; cosine?: number };

type DatePosted = "any" | "24h" | "week" | "month";

interface LinkedInFilters {
  location: string;
  distance: "" | "5" | "10" | "25" | "50" | "100";
  datePosted: DatePosted;
  experience: string[];
  workType: string[];
  jobType: string[];
  easyApply: boolean;
}

const DEFAULT_FILTERS: LinkedInFilters = {
  location: "",
  distance: "",
  datePosted: "24h",
  experience: [],
  workType: [],
  jobType: [],
  easyApply: false,
};

const EXPERIENCE_OPTIONS: { value: string; label: string }[] = [
  { value: "1", label: "Internship (0 yrs)" },
  { value: "2", label: "Entry (0–2 yrs)" },
  { value: "3", label: "Associate (2–5 yrs)" },
  { value: "4", label: "Mid–Senior (5–10 yrs)" },
  { value: "5", label: "Director (10–15 yrs)" },
  { value: "6", label: "Executive (15+ yrs)" },
];

const WORK_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "2", label: "Remote" },
  { value: "1", label: "Onsite" },
  { value: "3", label: "Hybrid" },
];

const JOB_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: "F", label: "Full-time" },
  { value: "P", label: "Part-time" },
  { value: "C", label: "Contract" },
  { value: "I", label: "Internship" },
  { value: "T", label: "Temporary" },
];

const DATE_POSTED_OPTIONS: { value: DatePosted; label: string }[] = [
  { value: "any", label: "Any time" },
  { value: "24h", label: "Past 24 hours" },
  { value: "week", label: "Past week" },
  { value: "month", label: "Past month" },
];

const DISTANCE_OPTIONS: { value: LinkedInFilters["distance"]; label: string }[] = [
  { value: "", label: "Any" },
  { value: "5", label: "5 mi" },
  { value: "10", label: "10 mi" },
  { value: "25", label: "25 mi" },
  { value: "50", label: "50 mi" },
  { value: "100", label: "100 mi" },
];

const DATE_POSTED_PARAM: Record<DatePosted, string> = {
  any: "",
  "24h": "r86400",
  week: "r604800",
  month: "r2592000",
};

const TAILOR_MESSAGES = [
  "Preparing your resume for tailoring...",
  "Matching keywords to the job description...",
  "Identifying gaps in your resume...",
  "Building personalized suggestions...",
  "Almost ready...",
];

function buildLinkedInUrl(kw: string, f: LinkedInFilters): string {
  const p = new URLSearchParams();
  p.set("keywords", kw);
  if (f.location.trim()) {
    p.set("location", f.location.trim());
    if (f.distance) p.set("distance", f.distance);
  }
  const tpr = DATE_POSTED_PARAM[f.datePosted];
  if (tpr) p.set("f_TPR", tpr);
  if (f.experience.length) p.set("f_E", [...f.experience].sort().join(","));
  if (f.workType.length) p.set("f_WT", [...f.workType].sort().join(","));
  if (f.jobType.length) p.set("f_JT", f.jobType.join(","));
  if (f.easyApply) p.set("f_AL", "true");
  return `https://www.linkedin.com/jobs/search/?${p.toString()}`;
}

function countActiveFilters(f: LinkedInFilters): number {
  let n = 0;
  if (f.location.trim()) n++;
  if (f.distance) n++;
  if (f.datePosted !== "any") n++;
  if (f.experience.length) n++;
  if (f.workType.length) n++;
  if (f.jobType.length) n++;
  if (f.easyApply) n++;
  return n;
}

function toggleValue<T>(arr: T[], v: T): T[] {
  return arr.includes(v) ? arr.filter((x) => x !== v) : [...arr, v];
}

function scoreBarColor(val: number) {
  return val >= 70 ? "bg-success" : val >= 40 ? "bg-amber-400" : "bg-danger";
}

function scoreTextColor(val: number) {
  return val >= 70 ? "text-success" : val >= 40 ? "text-amber-600" : "text-danger";
}

function OverviewPanel({
  matchScore,
  matchCeiling,
  scoreColor,
  isLoading,
  diagnosis,
}: {
  matchScore: number | null;
  matchCeiling: { score: number; reasons: string[]; exp_required?: number | null; exp_actual?: number | null } | null;
  scoreColor: string;
  isLoading?: boolean;
  diagnosis: { code: string; headline: string; detail: string } | null;
}) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        <div className="card p-5">
          <div className="flex items-baseline justify-between mb-3">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted">Match score</span>
            <div className="w-16 h-8 bg-subtle rounded-md animate-pulse" />
          </div>
          <div className="h-1.5 rounded-full bg-subtle overflow-hidden">
            <div
              className="h-full w-1/2 bg-border rounded-full"
              style={{ animation: "shimmer 1.5s ease-in-out infinite" }}
            />
          </div>
          <p className="text-[10px] text-muted mt-3 animate-pulse">
            Analyzing your resume against the job description…
          </p>
        </div>
      </div>
    );
  }
  if (matchScore === null) return null;
  return (
    <div className="space-y-3">
      <div className="card p-5">
        <div className="flex items-baseline justify-between mb-3">
          <span className="text-xs font-semibold uppercase tracking-wider text-muted">Match score</span>
          <span className={`text-3xl font-semibold tabular-nums ${scoreColor}`}>
            {matchScore}
            <span className="text-base text-muted">%</span>
          </span>
        </div>
        <div className="h-1.5 rounded-full bg-subtle overflow-hidden">
          <div
            className={`h-full rounded-full transition-all duration-500 ${scoreBarColor(matchScore)}`}
            style={{ width: `${matchScore}%` }}
          />
        </div>
      </div>

      {/* Premium, highly specific Diagnosis Box */}
      {diagnosis && diagnosis.headline && (
        (() => {
          let themeClass = "border-muted/30 bg-muted/5 text-muted";
          let icon = <Info className="w-4 h-4 text-muted" />;
          
          if (diagnosis.code === "excellent") {
            themeClass = "border-success/30 bg-success/5 text-success";
            icon = <CheckCircle2 className="w-4 h-4 text-success" />;
          } else if (diagnosis.code === "good") {
            themeClass = "border-indigo-500/30 bg-indigo-500/5 text-indigo-500";
            icon = <Sparkles className="w-4 h-4 text-indigo-500" />;
          } else if (["experience_gap", "seniority_title_gap", "degree_gap"].includes(diagnosis.code)) {
            themeClass = "border-amber-500/30 bg-amber-500/5 text-amber-600";
            icon = <AlertTriangle className="w-4 h-4 text-amber-500" />;
          } else if (["low_keywords", "low_skills", "low_semantic"].includes(diagnosis.code)) {
            themeClass = "border-purple-500/30 bg-purple-500/5 text-purple-600";
            icon = <HelpCircle className="w-4 h-4 text-purple-500" />;
          }

          return (
            <div className={`card p-4 border-l-4 ${themeClass} shadow-sm backdrop-blur-sm transition-all duration-300`}>
              <div className="flex items-center gap-2 mb-2">
                {icon}
                <span className="text-[11px] font-semibold uppercase tracking-wider text-foreground">
                  Match Analysis
                </span>
              </div>
              <p className="text-sm font-semibold text-foreground mb-1 leading-snug">
                {diagnosis.headline}
              </p>
              <p className="text-xs text-muted leading-relaxed">
                {diagnosis.detail}
              </p>
            </div>
          );
        })()
      )}

      {matchCeiling &&
        typeof matchCeiling.exp_required === "number" &&
        matchCeiling.exp_required > 0 &&
        matchCeiling.exp_actual !== null &&
        matchCeiling.exp_actual !== undefined &&
        matchCeiling.exp_actual < matchCeiling.exp_required && (
          <div className="card p-4">
            <p className="text-xs font-semibold uppercase tracking-wider text-muted mb-2">Experience gap</p>
            <div className="flex items-center gap-6 text-sm mb-1">
              <span className="text-muted">Job Description requires <span className="font-semibold text-foreground">{matchCeiling.exp_required}+ yrs</span></span>
              <span className="text-muted">Your resume <span className="font-semibold text-foreground">~{matchCeiling.exp_actual} yrs</span></span>
            </div>
            <p className="text-xs text-muted">Tailoring can still help, but expect a lower match ceiling.</p>
          </div>
        )}
    </div>
  );
}

function SectionsPanel({
  sectionScores,
  matchGaps,
  isLoading,
}: {
  sectionScores: Record<string, number | null> | null;
  matchGaps: GapAnalysis | null;
  isLoading?: boolean;
}) {
  if (isLoading) {
    return (
      <div className="space-y-3 animate-pulse">
        <div className="card p-4">
          <div className="h-3 bg-muted/60 rounded w-32 mb-4" />
          <div className="space-y-3">
            {[1, 2, 3, 4, 5].map((i) => (
              <div key={i} className="flex items-center gap-3">
                <div className="h-2.5 bg-muted/60 rounded w-16 shrink-0" />
                <div className="flex-1 h-1.5 rounded-full bg-subtle" />
                <div className="h-2.5 bg-muted/60 rounded w-6" />
              </div>
            ))}
          </div>
        </div>
      </div>
    );
  }
  const hasScores = sectionScores && Object.keys(sectionScores).length > 0;
  const lowMap = new Map<string, LowSection>(
    (matchGaps?.low_sections ?? []).map((s) => [s.section, s])
  );

  return (
    <div className="space-y-3">
      {hasScores && (
        <div className="card p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted mb-1">Match by section</p>
          <p className="text-[10px] text-muted mb-3 leading-relaxed">Each section uses its own weight blend (calibrated or hand-tuned per section). Independent of the overall score.</p>
          <div className="space-y-3">
            {SECTION_ORDER.map((sec) => {
              const val = sectionScores![sec];
              if (val === null || val === undefined) return null;
              return (
                <div key={sec} className="flex items-center gap-3">
                  <span className="text-[11px] text-muted w-20 shrink-0">{sec}</span>
                  <div className="flex-1 h-1.5 rounded-full bg-subtle overflow-hidden">
                    <div className={`h-full rounded-full transition-all duration-500 ${scoreBarColor(val)}`} style={{ width: `${val}%` }} />
                  </div>
                  <span className={`text-[11px] tabular-nums font-medium w-8 text-right ${scoreTextColor(val)}`}>{val}%</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {lowMap.size > 0 ? (
        <div className="space-y-2">
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted px-1">Why these sections scored low</p>
          {Array.from(lowMap.values())
            .sort((a, b) => a.score - b.score)
            .map((sec) => (
              <div key={sec.section} className="card p-4">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-sm font-semibold text-foreground">{sec.section}</span>
                  <span className={`text-xs font-semibold tabular-nums ${scoreTextColor(sec.score)}`}>{sec.score}%</span>
                </div>
                <div className="flex items-center gap-1.5 mb-1">
                  <span className="text-[9px] uppercase tracking-wider font-semibold text-muted">
                    {sec.explanation && sec.explanation.trim().length > 0 ? "AI explanation" : "Heuristic reason"}
                  </span>
                </div>
                <p className="text-xs text-muted leading-relaxed">
                  {sec.explanation && sec.explanation.trim().length > 0 ? sec.explanation : sec.reason}
                </p>
              </div>
            ))}
        </div>
      ) : (
        hasScores && (
          <div className="card p-4 border-success/30 bg-success/5">
            <p className="text-xs text-success font-medium">All sections meet the threshold — strong match.</p>
          </div>
        )
      )}
    </div>
  );
}

function SuggestionsPanel({
  matchGaps,
  isLoading,
}: {
  matchGaps: GapAnalysis | null;
  isLoading?: boolean;
}) {
  if (isLoading) {
    return (
      <div className="space-y-3">
        <div className="card p-4 animate-pulse">
          <div className="flex items-start gap-2 mb-2">
            <div className="w-3.5 h-3.5 bg-muted/60 rounded mt-0.5 shrink-0" />
            <div className="space-y-1.5 w-full">
              <div className="h-3 bg-muted/60 rounded w-24" />
              <div className="h-3 bg-muted/60 rounded w-48 mt-1" />
            </div>
          </div>
          <div className="space-y-2 mt-3 pl-5">
            <div className="h-2.5 bg-muted/60 rounded w-full" />
            <div className="h-2.5 bg-muted/60 rounded w-5/6" />
            <div className="h-2.5 bg-muted/60 rounded w-4/6" />
          </div>
        </div>
      </div>
    );
  }

  const worst = (matchGaps?.low_sections ?? [])
    .slice()
    .sort((a, b) => a.score - b.score)[0];

  return (
    <div className="space-y-3">
      {worst && (worst.explanation || worst.reason) && (
        <div className="card p-4">
          <div className="flex items-start gap-2 mb-2">
            <Target className="w-3.5 h-3.5 text-amber-600 mt-0.5 shrink-0" />
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-muted">Fix this first</p>
              <p className="text-xs text-foreground/80 mt-0.5">Lowest-scoring section: <span className="font-semibold">{worst.section}</span> ({worst.score}%)</p>
            </div>
          </div>
          <p className="text-xs text-muted leading-relaxed">
            {worst.explanation && worst.explanation.trim().length > 0 ? worst.explanation : worst.reason}
          </p>
        </div>
      )}
    </div>
  );
}

function JobSearchContent() {
  const searchParams = useSearchParams();
  const router = useRouter();

  const [isTailoring, setIsTailoring] = useState(false);
  const [tailorStep, setTailorStep] = useState(0);

  const [keywords, setKeywords] = useState<string[]>([]);
  const [jdText, setJdText] = useState("");
  const [isMatching, setIsMatching] = useState(false);
  const [matchScore, setMatchScore] = useState<number | null>(null);
  // matchBreakdown is hydrated from localStorage and used by the conditional weights blend below; the destructured read is unused but the setter side-channel matters.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [matchBreakdown, setMatchBreakdown] = useState<{ kw: number; sk: number; cos: number } | null>(null);
  const [matchWeights, setMatchWeights] = useState<{ kw: number; sk: number; cos: number }>({ kw: 55, sk: 25, cos: 20 });
  const [matchCeiling, setMatchCeiling] = useState<{ score: number; reasons: string[]; exp_required?: number | null; exp_actual?: number | null } | null>(null);
  const [sectionScores, setSectionScores] = useState<Record<string, number | null> | null>(null);
  // sectionFeatures hydrated from localStorage for future debug overlay; setter side-channel keeps it warm.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  const [sectionFeatures, setSectionFeatures] = useState<Record<string, SectionFeatures | null> | null>(null);
  const [matchGaps, setMatchGaps] = useState<GapAnalysis | null>(null);
  const [matchDiagnosis, setMatchDiagnosis] = useState<{ code: string; headline: string; detail: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isEditingJd, setIsEditingJd] = useState(false);
  const [lastMatchedJd, setLastMatchedJd] = useState<string>("");

  const [selectedTemplate, setSelectedTemplate] = useState<string>("standard");
  const [resultsTab, setResultsTab] = useState<ResultsTab>("overview");

  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [previewError, setPreviewError] = useState(false);
  const [previewModalOpen, setPreviewModalOpen] = useState(false);
  const [isDownloading, setIsDownloading] = useState(false);

  const [filters, setFilters] = useState<LinkedInFilters>(DEFAULT_FILTERS);
  const [pendingFilters, setPendingFilters] = useState<LinkedInFilters>(DEFAULT_FILTERS);
  const [filtersOpen, setFiltersOpen] = useState(false);

  const [sectionsOpen, setSectionsOpen] = useState(false);
  const [sectionsOrder, setSectionsOrder] = useState<string[]>([]);
  const [sectionsHidden, setSectionsHidden] = useState<Set<string>>(new Set());
  const [sectionsLoading, setSectionsLoading] = useState(false);
  const [sectionsSaving, setSectionsSaving] = useState(false);
  const [sectionsError, setSectionsError] = useState<string | null>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [dragOverIndex, setDragOverIndex] = useState<number | null>(null);

  const handleDownload = async () => {
    const rid = localStorage.getItem("current_resume_id");
    if (!rid) return;
    setIsDownloading(true);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
      const res = await fetch(`${apiUrl}/api/tailor/apply`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: rid,
          suggestions: [],
          format: "pdf",
          template_id: selectedTemplate,
          jd_text: jdText,
          total_suggestions: 0,
        }),
      });
      if (!res.ok) throw new Error("Failed to generate PDF.");
      const disposition = res.headers.get("content-disposition") || "";
      const match = disposition.match(/filename\*?=(?:UTF-8'')?\"?([^\";]+)\"?/i);
      const filename = match ? decodeURIComponent(match[1]) : `Resume_Debug.pdf`;
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
      alert(err instanceof Error ? err.message : "Failed to download PDF.");
    } finally {
      setIsDownloading(false);
    }
  };

  const loadPreview = useCallback(async (resumeId: string | null, tid: string) => {
    if (!resumeId) return;
    setPreviewError(false);
    setPreviewHtml(null);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
      const res = await fetch(`${apiUrl}/api/tailor/preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: resumeId,
          template_id: tid,
          suggestions: [],
          layout_density: null,
          target_pages: null,
        }),
      });
      if (!res.ok) throw new Error("Preview fetch failed");
      const data = await res.json();
      setPreviewHtml(data.html || "");
    } catch {
      setPreviewError(true);
    }
  }, []);

  const openSections = useCallback(async () => {
    setSectionsOpen(true);
    setSectionsError(null);
    setSectionsLoading(true);
    const rid = localStorage.getItem("current_resume_id");
    if (!rid) { setSectionsLoading(false); return; }
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
      const res = await fetch(`${apiUrl}/api/resume/${rid}/json`);
      if (!res.ok) throw new Error("Failed to load resume");
      const r: ResumeShape = await res.json();
      setSectionsOrder(buildOrderFromResume(r));
      setSectionsHidden(new Set(r.hidden_sections || []));
    } catch (e) {
      setSectionsError(e instanceof Error ? e.message : "Failed to load");
    } finally {
      setSectionsLoading(false);
    }
  }, []);

  const saveSections = useCallback(async () => {
    const rid = localStorage.getItem("current_resume_id");
    if (!rid) return;
    setSectionsSaving(true);
    setSectionsError(null);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
      const res = await fetch(`${apiUrl}/api/resume/${rid}/sections`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          section_order: sectionsOrder,
          hidden_sections: Array.from(sectionsHidden),
        }),
      });
      if (!res.ok) throw new Error("Save failed");
      setSectionsOpen(false);
      const stored = localStorage.getItem("template_id");
      const tid = stored && stored !== "mimic" ? stored : "standard";
      loadPreview(rid, tid);
    } catch (e) {
      setSectionsError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSectionsSaving(false);
    }
  }, [sectionsOrder, sectionsHidden, loadPreview]);

  const onDragStart = (e: React.DragEvent, idx: number) => {
    setDragIndex(idx);
    e.dataTransfer.effectAllowed = "move";
  };
  const onDragOver = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    setDragOverIndex(idx);
  };
  const onDrop = (e: React.DragEvent, idx: number) => {
    e.preventDefault();
    if (dragIndex === null || dragIndex === idx) { setDragIndex(null); setDragOverIndex(null); return; }
    const next = [...sectionsOrder];
    const [moved] = next.splice(dragIndex, 1);
    next.splice(idx, 0, moved);
    setSectionsOrder(next);
    setDragIndex(null);
    setDragOverIndex(null);
  };
  const onDragEnd = () => { setDragIndex(null); setDragOverIndex(null); };

  const moveSection = (from: number, to: number) => {
    if (to < 0 || to >= sectionsOrder.length || to === from) return;
    const next = [...sectionsOrder];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setSectionsOrder(next);
  };

  const onRowKeyDown = (e: React.KeyboardEvent, idx: number) => {
    const meta = e.ctrlKey || e.metaKey;
    if (!meta) return;
    if (e.key === "ArrowUp") { e.preventDefault(); moveSection(idx, idx - 1); }
    else if (e.key === "ArrowDown") { e.preventDefault(); moveSection(idx, idx + 1); }
  };

  const toggleHide = (key: string) => {
    const next = new Set(sectionsHidden);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setSectionsHidden(next);
  };

  // One-shot mount: hydrate React state from URL + localStorage + sessionStorage.
  // These are external-system synchronizations; the lint rule over-flags this
  // legitimate pattern.
  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect */
    // 1. Initial setup from URL
    const kw = searchParams.get("keywords");
    if (kw) {
      setKeywords(kw.split("|").map((k) => k.trim()).filter(Boolean));
      const rid = searchParams.get("resume_id");
      if (rid) localStorage.setItem("current_resume_id", rid);
    } else if (!localStorage.getItem("current_resume_id")) {
      router.push("/");
      return;
    }

    // 2. Restore saved state (survives refresh)
    const savedJd = localStorage.getItem("tailor_jd_text") || "";
    if (savedJd) setJdText(savedJd);
    
    const savedMatch = localStorage.getItem("match_state");
    if (savedMatch) {
      try {
        const s = JSON.parse(savedMatch);
        if (s.score !== null && s.score !== undefined) setMatchScore(s.score);
        if (s.breakdown) setMatchBreakdown(s.breakdown);
        if (s.weights) setMatchWeights(s.weights);
        if (s.ceiling !== undefined) setMatchCeiling(s.ceiling);
        if (s.sectionScores) setSectionScores(s.sectionScores);
        if (s.sectionFeatures) setSectionFeatures(s.sectionFeatures);
        if (s.gaps) setMatchGaps(s.gaps);
        if (s.diagnosis) setMatchDiagnosis(s.diagnosis);
        if (s.lastJd) setLastMatchedJd(s.lastJd);
        if (s.keywords?.length) setKeywords(s.keywords);
      } catch { /* ignore corrupt data */ }
    }

    // 3. UI State (Template & Filters)
    const stored = localStorage.getItem("template_id");
    const tid = stored && stored !== "mimic" ? stored : "standard";
    setSelectedTemplate(tid);

    const storedFilters = sessionStorage.getItem("linkedin_filters");
    if (storedFilters) {
      try {
        setFilters({ ...DEFAULT_FILTERS, ...JSON.parse(storedFilters) });
      } catch {
        /* keep defaults */
      }
    }

    const resumeId = localStorage.getItem("current_resume_id");
    loadPreview(resumeId, tid);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [searchParams, router, loadPreview]);

  // Persist JD text as user types so it survives refresh even without matching
  useEffect(() => {
    localStorage.setItem("tailor_jd_text", jdText);
  }, [jdText]);

  useEffect(() => {
    sessionStorage.setItem("linkedin_filters", JSON.stringify(filters));
  }, [filters]);

  useEffect(() => {
    if (!isTailoring) return;
    const id = setInterval(() => setTailorStep(s => (s + 1) % TAILOR_MESSAGES.length), 600);
    return () => clearInterval(id);
  }, [isTailoring]);

  const handleJdChange = (val: string) => {
    setJdText(val);
  };

  const onMatch = async () => {
    if (!jdText.trim()) return;
    setIsMatching(true);
    setIsEditingJd(false);
    setMatchScore(null);
    setSectionScores(null);
    setMatchGaps(null);
    setMatchCeiling(null);
    setMatchDiagnosis(null);
    setResultsTab("overview");
    setError(null);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
      const res = await fetch(`${apiUrl}/api/match/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: localStorage.getItem("current_resume_id") || "",
          jd_text: jdText,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.detail || "Match failed.");
      }
      const data = await res.json();
      setMatchScore(data.score ?? data.match_score ?? null);
      if (data.breakdown) {
        const b = data.breakdown;
        setMatchBreakdown({
          kw: b.bm25 ?? b.kw ?? 0,
          sk: b.skill_coverage ?? b.sk ?? 0,
          cos: b.semantic ?? b.cos ?? 0,
        });
      } else {
        setMatchBreakdown(null);
      }
      if (data.active_weights) {
        setMatchWeights({
          kw: data.active_weights.w_kw ?? 55,
          sk: data.active_weights.w_skill ?? 25,
          cos: data.active_weights.w_cos ?? 20,
        });
      }
      setMatchCeiling(data.ceiling ?? null);
      setMatchDiagnosis(data.diagnosis ?? null);
      setSectionScores(data.section_scores ?? null);
      setSectionFeatures(data.section_features ?? null);
      setMatchGaps(data.gap_analysis ?? null);
      setLastMatchedJd(jdText);
      // Persist so back-navigation from sections/tailor restores full state
      const bd = data.breakdown ? {
        kw: data.breakdown.bm25 ?? data.breakdown.kw ?? 0,
        sk: data.breakdown.skill_coverage ?? data.breakdown.sk ?? 0,
        cos: data.breakdown.semantic ?? data.breakdown.cos ?? 0,
      } : null;
      const wt = data.active_weights ? {
        kw: data.active_weights.w_kw ?? 55,
        sk: data.active_weights.w_skill ?? 25,
        cos: data.active_weights.w_cos ?? 20,
      } : matchWeights;
      localStorage.setItem("match_state", JSON.stringify({
        score: data.score ?? data.match_score ?? null,
        breakdown: bd,
        weights: wt,
        ceiling: data.ceiling ?? null,
        sectionScores: data.section_scores ?? null,
        sectionFeatures: data.section_features ?? null,
        gaps: data.gap_analysis ?? null,
        diagnosis: data.diagnosis ?? null,
        lastJd: jdText,
        keywords,
      }));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setIsMatching(false);
    }
  };

  const onTailor = async () => {
    localStorage.setItem("tailor_jd_text", jdText);
    localStorage.setItem("template_id", selectedTemplate);
    setIsTailoring(true);
    setTailorStep(0);
 
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
    const rid = localStorage.getItem("current_resume_id") || "";
    try {
      const resumeRes = await fetch(`${apiUrl}/api/resume/${rid}/json`);
      const prefetch: Record<string, unknown> = {};
      if (resumeRes.ok) {
        prefetch.resume = await resumeRes.json();
      }
      sessionStorage.setItem("tailor_prefetch", JSON.stringify(prefetch));
    } catch {
      // prefetch failed
    }
    router.push("/tailor");
  };

  const scoreColor =
    matchScore === null
      ? ""
      : matchScore >= 70
      ? "text-success"
      : matchScore >= 40
      ? "text-amber-600"
      : "text-danger";

  return (
    <div className="w-full max-w-6xl mx-auto px-6 py-12">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold tracking-tight mb-2">
          Match a job
        </h1>
        <p className="text-muted text-sm">
          Paste a job description to see how well your resume matches.
        </p>
      </div>

      {/* Suggested roles — always visible at top */}
      {keywords.length > 0 && (
        <section className="mb-8">
          <div className="flex items-center justify-between mb-2">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
              Suggested roles
            </h2>
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => { if (!filtersOpen) setPendingFilters(filters); setFiltersOpen((v) => !v); }}
                className="text-[11px] text-muted hover:text-foreground inline-flex items-center gap-1.5"
              >
                <SlidersHorizontal className="w-3 h-3" />
                Filters
                {countActiveFilters(filters) > 0 && (
                  <span className="ml-1 px-1.5 py-0.5 rounded-full bg-foreground text-background text-[10px] tabular-nums">
                    {countActiveFilters(filters)}
                  </span>
                )}
              </button>
              {countActiveFilters(filters) > 0 && (
                <button
                  type="button"
                  onClick={() => { setFilters(DEFAULT_FILTERS); setPendingFilters(DEFAULT_FILTERS); }}
                  className="text-[11px] text-muted hover:text-danger underline underline-offset-2"
                >
                  Clear filters
                </button>
              )}
            </div>
          </div>

          {filtersOpen && (
            <div className="card p-4 mb-3 space-y-4">
              {/* Row 1: Location + Distance + Date posted */}
              <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                <div className="sm:col-span-2">
                  <label className="block text-[10px] uppercase tracking-wider text-muted mb-1">Location</label>
                  <input
                    type="text"
                    value={pendingFilters.location}
                    onChange={(e) => setPendingFilters((f) => ({ ...f, location: e.target.value }))}
                    placeholder="City, state, or country"
                    className="input text-sm w-full"
                  />
                </div>
                <div>
                  <label className="block text-[10px] uppercase tracking-wider text-muted mb-1">Distance</label>
                  <select
                    value={pendingFilters.distance}
                    onChange={(e) =>
                      setPendingFilters((f) => ({ ...f, distance: e.target.value as LinkedInFilters["distance"] }))
                    }
                    disabled={!pendingFilters.location.trim()}
                    className="input text-sm w-full disabled:opacity-50"
                  >
                    {DISTANCE_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div>
                <label className="block text-[10px] uppercase tracking-wider text-muted mb-1">Date posted</label>
                <div className="flex flex-wrap gap-1.5">
                  {DATE_POSTED_OPTIONS.map((o) => {
                    const active = pendingFilters.datePosted === o.value;
                    return (
                      <button
                        key={o.value}
                        type="button"
                        onClick={() => setPendingFilters((f) => ({ ...f, datePosted: o.value }))}
                        className={`px-2.5 py-1 text-[11px] rounded-md border transition-colors ${
                          active
                            ? "bg-foreground text-background border-foreground"
                            : "bg-transparent text-muted hover:bg-subtle border-border"
                        }`}
                      >
                        {o.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div>
                <label className="block text-[10px] uppercase tracking-wider text-muted mb-1">Experience level</label>
                <p className="text-[10px] text-muted/70 mb-1.5">LinkedIn buckets roles by seniority, not exact years. Pick the band that fits you.</p>
                <div className="flex flex-wrap gap-1.5">
                  {EXPERIENCE_OPTIONS.map((o) => {
                    const active = pendingFilters.experience.includes(o.value);
                    return (
                      <button
                        key={o.value}
                        type="button"
                        onClick={() =>
                          setPendingFilters((f) => ({ ...f, experience: toggleValue(f.experience, o.value) }))
                        }
                        className={`px-2.5 py-1 text-[11px] rounded-md border transition-colors ${
                          active
                            ? "bg-foreground text-background border-foreground"
                            : "bg-transparent text-muted hover:bg-subtle border-border"
                        }`}
                      >
                        {o.label}
                      </button>
                    );
                  })}
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-[10px] uppercase tracking-wider text-muted mb-1">Work type</label>
                  <div className="flex flex-wrap gap-1.5">
                    {WORK_TYPE_OPTIONS.map((o) => {
                      const active = pendingFilters.workType.includes(o.value);
                      return (
                        <button
                          key={o.value}
                          type="button"
                          onClick={() =>
                            setPendingFilters((f) => ({ ...f, workType: toggleValue(f.workType, o.value) }))
                          }
                          className={`px-2.5 py-1 text-[11px] rounded-md border transition-colors ${
                            active
                              ? "bg-foreground text-background border-foreground"
                              : "bg-transparent text-muted hover:bg-subtle border-border"
                          }`}
                        >
                          {o.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <div>
                  <label className="block text-[10px] uppercase tracking-wider text-muted mb-1">Job type</label>
                  <div className="flex flex-wrap gap-1.5">
                    {JOB_TYPE_OPTIONS.map((o) => {
                      const active = pendingFilters.jobType.includes(o.value);
                      return (
                        <button
                          key={o.value}
                          type="button"
                          onClick={() =>
                            setPendingFilters((f) => ({ ...f, jobType: toggleValue(f.jobType, o.value) }))
                          }
                          className={`px-2.5 py-1 text-[11px] rounded-md border transition-colors ${
                            active
                              ? "bg-foreground text-background border-foreground"
                              : "bg-transparent text-muted hover:bg-subtle border-border"
                          }`}
                        >
                          {o.label}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </div>

              <label className="inline-flex items-center gap-2 text-xs text-muted cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={pendingFilters.easyApply}
                  onChange={(e) => setPendingFilters((f) => ({ ...f, easyApply: e.target.checked }))}
                  className="rounded border-border"
                />
                Easy Apply only
              </label>

              <div className="flex justify-end pt-1">
                <button
                  type="button"
                  onClick={() => { setFilters(pendingFilters); setFiltersOpen(false); }}
                  className="btn-primary text-sm"
                >
                  Apply filters
                </button>
              </div>
            </div>
          )}

          <div className="card divide-y divide-border">
            {keywords.map((kw, i) => (
              <a
                key={i}
                href={buildLinkedInUrl(kw, filters)}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-between px-4 py-3 hover:bg-subtle transition-colors text-sm group"
                title={`Search LinkedIn for "${kw}" jobs`}
              >
                <span className="font-medium group-hover:text-accent group-hover:underline underline-offset-4">{kw}</span>
                <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted group-hover:text-accent">
                  Open
                  <ExternalLink className="w-3.5 h-3.5" />
                </span>
              </a>
            ))}
          </div>
        </section>
      )}

      {/* Main 2-column grid: preview left, JD/results right (stack with JD first on mobile) */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* LEFT — Template preview or Manage sections (rendered second on mobile so CTA stays above fold) */}
        <section className="order-2 lg:order-1">
          <div className="flex items-center justify-between mb-3 gap-3 flex-wrap">
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
              {sectionsOpen ? "Manage sections" : "Preview"}
            </h2>
            {sectionsOpen ? (
              <button
                type="button"
                onClick={() => setSectionsOpen(false)}
                className="text-[11px] text-muted hover:text-foreground underline underline-offset-2"
              >
                Cancel
              </button>
            ) : (
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  onClick={openSections}
                  className="text-[11px] text-muted hover:text-foreground underline underline-offset-2"
                >
                  Manage sections
                </button>
                {previewHtml && (
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={handleDownload}
                      disabled={isDownloading}
                      className="text-[11px] text-muted hover:text-foreground inline-flex items-center gap-1 transition-colors disabled:opacity-50"
                    >
                      {isDownloading ? (
                        <Loader2 className="w-3 h-3 animate-spin" />
                      ) : (
                        <Download className="w-3 h-3" />
                      )}
                      {isDownloading ? "Downloading..." : "Download PDF"}
                    </button>
                    <button
                      type="button"
                      onClick={() => setPreviewModalOpen(true)}
                      className="text-[11px] text-muted hover:text-foreground inline-flex items-center gap-1"
                    >
                      <Maximize2 className="w-3 h-3" />
                      Full preview
                    </button>
                  </div>
                )}
              </div>
            )}
          </div>

          {sectionsOpen ? (
            <div>
              <p className="text-[10px] text-muted mb-4 leading-relaxed">
                Drag to reorder. Toggle the eye icon to show or hide sections.
              </p>
              {sectionsError && (
                <div className="card p-3 mb-4 border-danger/30 bg-danger/5">
                  <p className="text-xs text-danger">{sectionsError}</p>
                </div>
              )}
              {sectionsLoading ? (
                <div className="card divide-y divide-border mb-4 animate-pulse">
                  {[1, 2, 3, 4].map((idx) => (
                    <div key={idx} className="flex items-center justify-between px-4 py-[14px]">
                      <div className="flex items-center gap-3 w-1/2">
                        <div className="w-4 h-4 bg-muted/60 rounded shrink-0" />
                        <div className="h-4 bg-muted/60 rounded w-2/3" />
                      </div>
                      <div className="w-8 h-8 bg-muted/60 rounded shrink-0" />
                    </div>
                  ))}
                </div>
              ) : (
                <div className="card divide-y divide-border mb-4">
                  {sectionsOrder.map((key, i) => {
                    const isHidden = sectionsHidden.has(key);
                    const isDraggingThis = dragIndex === i;
                    const isOver = dragOverIndex === i && dragIndex !== i;
                    return (
                      <div
                        key={key}
                        draggable
                        tabIndex={0}
                        role="button"
                        aria-label={`Reorder ${sectionLabel(key)}. Use Ctrl Arrow Up or Down.`}
                        onDragStart={(e) => onDragStart(e, i)}
                        onDragOver={(e) => onDragOver(e, i)}
                        onDrop={(e) => onDrop(e, i)}
                        onDragEnd={onDragEnd}
                        onKeyDown={(e) => onRowKeyDown(e, i)}
                        title="Drag to reorder · Ctrl+↑/↓ keyboard"
                        className={`flex items-center justify-between px-4 py-3 transition-colors select-none ${isHidden ? "opacity-50" : ""} ${isDraggingThis ? "opacity-40 bg-subtle" : ""} ${isOver ? "border-t-2 border-accent" : ""}`}
                      >
                        <div className="flex items-center gap-3 min-w-0">
                          <GripVertical className="w-4 h-4 text-muted cursor-grab shrink-0" />
                          <span className="text-sm font-medium truncate">{sectionLabel(key)}</span>
                        </div>
                        <button
                          onClick={() => toggleHide(key)}
                          className="btn-ghost p-2"
                          aria-label={isHidden ? "Show section" : "Hide section"}
                        >
                          {isHidden ? (
                            <EyeOff className="w-4 h-4 text-muted" />
                          ) : (
                            <Eye className="w-4 h-4 text-foreground" />
                          )}
                        </button>
                      </div>
                    );
                  })}
                </div>
              )}
              <div className="flex items-center justify-end gap-3">
                <button onClick={() => setSectionsOpen(false)} className="btn-secondary text-sm">
                  Cancel
                </button>
                <button onClick={saveSections} disabled={sectionsSaving || sectionsLoading} className="btn-primary text-sm">
                  {sectionsSaving ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Saving…
                    </>
                  ) : (
                    <>
                      <Save className="w-4 h-4" />
                      Save
                    </>
                  )}
                </button>
              </div>
            </div>
          ) : (
            <div className="card overflow-hidden">
              {previewError ? (
                <div className="aspect-[8.5/11] flex flex-col items-center justify-center gap-2 text-sm text-muted p-4">
                  <p>Could not load preview.</p>
                  <button
                    className="btn-secondary text-xs"
                    onClick={() => loadPreview(localStorage.getItem("current_resume_id"), selectedTemplate)}
                  >
                    Retry
                  </button>
                </div>
              ) : previewHtml === null ? (
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
                    <div className="h-2.5 bg-border/60 rounded w-4/5" />
                  </div>
                  <div className="space-y-2">
                    <div className="h-3 bg-border rounded w-1/4" />
                    <div className="h-2.5 bg-border/60 rounded w-full" />
                    <div className="h-2.5 bg-border/60 rounded w-11/12" />
                    <div className="h-2.5 bg-border/60 rounded w-4/6" />
                  </div>
                  <div className="space-y-2">
                    <div className="h-3 bg-border rounded w-1/5" />
                    <div className="h-2.5 bg-border/60 rounded w-3/4" />
                    <div className="h-2.5 bg-border/60 rounded w-2/3" />
                  </div>
                  <div className="h-px bg-border" />
                  <div className="space-y-2">
                    <div className="h-3 bg-border rounded w-1/4" />
                    <div className="h-2.5 bg-border/60 rounded w-full" />
                    <div className="h-2.5 bg-border/60 rounded w-5/6" />
                  </div>
                </div>
              ) : (
                <TemplatePreview html={previewHtml} showControls />
              )}
            </div>
          )}
        </section>

        {/* RIGHT — JD textarea pre-match or while editing, results otherwise (first on mobile) */}
        <section className="order-1 lg:order-2 space-y-3">
          {(matchScore === null && !isMatching) || isEditingJd ? (
            <>
              <div className="flex items-center justify-between">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
                  Job description
                </h2>
                {isEditingJd && (
                  <button
                    type="button"
                    onClick={() => {
                      setJdText(lastMatchedJd);
                      setIsEditingJd(false);
                    }}
                    className="text-[11px] text-muted hover:text-foreground underline underline-offset-2"
                  >
                    Cancel
                  </button>
                )}
              </div>
              <textarea
                value={jdText}
                onChange={(e) => handleJdChange(e.target.value)}
                placeholder="Paste the job description…"
                className="input min-h-[160px] md:min-h-[260px] resize-y leading-relaxed"
              />
              {(() => {
                const len = jdText.trim().length;
                if (len === 0) return null;
                if (len < 200) {
                  return (
                    <p className="text-[11px] text-amber-600">
                      Paste at least 200 characters of the JD for a reliable score ({len}/200).
                    </p>
                  );
                }
                return (
                  <p className="text-[11px] text-muted">
                    {len.toLocaleString()} characters
                  </p>
                );
              })()}
              <div className="flex items-center justify-end gap-3 flex-wrap">
                <button
                  onClick={onMatch}
                  disabled={isMatching || jdText.trim().length < 200}
                  title={jdText.trim().length < 200 ? "Paste at least 200 characters of the JD first" : undefined}
                  className="btn-primary"
                >
                  {isMatching ? (
                    <>
                      <Loader2 className="w-4 h-4 animate-spin" />
                      Analyzing…
                    </>
                  ) : isEditingJd ? (
                    "Recalculate match"
                  ) : (
                    "Calculate match"
                  )}
                </button>
              </div>
              {error && <p className="text-xs text-danger">{error}</p>}
            </>
          ) : (
            <>
              <div className="flex items-center justify-between mb-1">
                <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
                  Match results
                </h2>
                <button
                  type="button"
                  onClick={() => setIsEditingJd(true)}
                  className="text-[11px] text-muted hover:text-foreground underline underline-offset-2"
                >
                  Edit JD
                </button>
              </div>

              <Tabs<ResultsTab>
                value={resultsTab}
                onChange={setResultsTab}
                options={[
                  { value: "overview", label: "Overview" },
                  { value: "sections", label: "Sections", count: matchGaps?.low_sections?.length ?? 0 },
                  { value: "suggestions", label: "Suggestions" },
                ]}
              />

              {resultsTab === "overview" && (() => {
                const sectionVals = sectionScores
                  ? (Object.values(sectionScores).filter((v): v is number => v !== null))
                  : [];
                const avgSection = sectionVals.length
                  ? sectionVals.reduce((a, b) => a + b, 0) / sectionVals.length
                  : null;
                const showGapNote = matchScore !== null && avgSection !== null && matchScore - avgSection >= 20;
                return (
                  <>
                    <OverviewPanel
                      matchScore={matchScore}
                      matchCeiling={matchCeiling}
                      scoreColor={scoreColor}
                      isLoading={isMatching}
                      diagnosis={matchDiagnosis}
                    />
                    {showGapNote && (
                      <div className="card p-4">
                        <p className="text-[11px] font-semibold uppercase tracking-wider text-muted mb-1">Why is overall higher than sections?</p>
                        <p className="text-xs text-muted leading-relaxed">
                          The overall score uses your full resume and includes signals like education fit and seniority that section scores don&apos;t. Section scores isolate each section&apos;s text — they&apos;re more granular and show exactly where to improve.
                        </p>
                      </div>
                    )}
                  </>
                );
              })()}

              {resultsTab === "sections" && (
                <SectionsPanel sectionScores={sectionScores} matchGaps={matchGaps} isLoading={isMatching} />
              )}

              {resultsTab === "suggestions" && (
                <SuggestionsPanel matchGaps={matchGaps} isLoading={isMatching} />
              )}

              <div className="flex items-center justify-end pt-2">
                <button
                  onClick={onTailor}
                  disabled={!jdText.trim() || isMatching || matchScore === null}
                  title={
                    !jdText.trim()
                      ? "Paste a JD first"
                      : isMatching
                      ? "Calculating match…"
                      : matchScore === null
                      ? "Run Calculate match first"
                      : undefined
                  }
                  className="btn-primary"
                >
                  Tailor resume
                  <ArrowRight className="w-4 h-4" />
                </button>
              </div>
            </>
          )}
        </section>
      </div>

      {/* Full preview modal */}
      {previewModalOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-6"
          onClick={() => setPreviewModalOpen(false)}
        >
          <div
            className="bg-card rounded-lg shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-3 border-b border-border">
              <div>
                <p className="text-sm font-semibold">Preview</p>
                <p className="text-xs text-muted">Your resume rendered with the selected template.</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleDownload}
                  disabled={isDownloading}
                  className="btn-ghost p-1.5 inline-flex items-center gap-1.5 text-xs transition-colors disabled:opacity-50"
                  title="Download as PDF"
                >
                  {isDownloading ? (
                    <Loader2 className="w-4 h-4 animate-spin text-muted" />
                  ) : (
                    <Download className="w-4 h-4" />
                  )}
                  <span>{isDownloading ? "Downloading..." : "Download PDF"}</span>
                </button>
                <button
                  onClick={() => setPreviewModalOpen(false)}
                  className="btn-ghost p-1.5"
                  aria-label="Close"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-auto bg-slate-100 p-6">
              <div
                className="mx-auto bg-white shadow-md"
                style={{ width: "816px", maxWidth: "100%" }}
              >
                <iframe
                  title="Full preview"
                  srcDoc={previewHtml || ""}
                  scrolling="no"
                  onLoad={(e) => {
                    const f = e.currentTarget;
                    const doc = f.contentDocument;
                    if (doc) {
                      const h = Math.max(
                        doc.documentElement.scrollHeight,
                        doc.body?.scrollHeight || 0
                      );
                      f.style.height = `${h}px`;
                    }
                  }}
                  style={{
                    width: "100%",
                    height: "1056px",
                    border: 0,
                    background: "white",
                    display: "block",
                  }}
                />
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Tailoring overlay — blurs page, shows animation before navigating */}
      {isTailoring && (
        <div className="fixed inset-0 z-50 backdrop-blur-md bg-black/60 flex items-center justify-center overflow-hidden">
          <style jsx global>{`
            body { overflow: hidden !important; }
          `}</style>
          <div className="flex flex-col items-center gap-6 text-center px-8">
            <div className="w-16 h-16 rounded-full bg-white/10 border border-white/20 flex items-center justify-center">
              <Wand2 className="w-7 h-7 text-white animate-pulse" />
            </div>
            <div className="space-y-1.5">
              <p className="text-base font-semibold tracking-tight text-white">Tailoring your resume</p>
              <p className="text-sm text-white/60 transition-all duration-300">{TAILOR_MESSAGES[tailorStep]}</p>
            </div>
            <div className="w-64 h-1.5 rounded-full bg-white/20 overflow-hidden">
              <div
                className="h-full w-1/2 bg-white/70 rounded-full"
                style={{ animation: "shimmer 1.5s ease-in-out infinite" }}
              />
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export default function JobSearchPage() {
  return (
    <Suspense fallback={
      <div className="max-w-6xl mx-auto px-4 py-8 animate-pulse space-y-8 select-none">
        {/* Header Skeleton */}
        <div className="flex items-center justify-between">
          <div className="space-y-2">
            <div className="h-6 bg-muted/60 rounded w-48" />
            <div className="h-4 bg-muted/60 rounded w-64" />
          </div>
          <div className="h-10 bg-muted/60 rounded w-28" />
        </div>

        {/* Suggested Roles Skeleton */}
        <section>
          <div className="flex items-center justify-between mb-2">
            <div className="h-4 bg-muted/60 rounded w-24" />
            <div className="h-4 bg-muted/60 rounded w-16" />
          </div>
          <div className="card divide-y divide-border">
            {[1, 2, 3].map((i) => (
              <div key={i} className="flex items-center justify-between px-4 py-3">
                <div className="h-4 bg-muted/60 rounded w-1/3" />
                <div className="w-3.5 h-3.5 bg-muted/60 rounded" />
              </div>
            ))}
          </div>
        </section>

        {/* Grid Layout Skeleton */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
          {/* Left Column (Resume Preview) */}
          <div className="lg:col-span-5 space-y-6">
            <div className="card p-6 space-y-4">
              <div className="h-4.5 bg-muted/60 rounded w-1/3" />
              <div className="aspect-[8.5/11] bg-muted/20 rounded w-full" />
            </div>
          </div>

          {/* Right Column (JD / Match Panel) */}
          <div className="lg:col-span-7 space-y-6">
            <div className="card p-6 space-y-6">
              <div className="space-y-3">
                <div className="h-4 bg-muted/60 rounded w-1/4" />
                <div className="h-32 bg-muted/20 rounded w-full" />
              </div>
              <div className="flex justify-end">
                <div className="h-10 bg-muted/60 rounded w-32" />
              </div>
            </div>
          </div>
        </div>
      </div>
    }>
      <JobSearchContent />
    </Suspense>
  );
}
