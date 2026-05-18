"use client";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { ExternalLink, ArrowRight, Loader2, Check, Maximize2, X, Wand2, Target } from "lucide-react";
import { TemplatePreview } from "@/components/TemplatePreview";
import { Tabs } from "@/components/Tabs";

interface TemplateMeta {
  id: string;
  name: string;
  description: string;
}

type LowSection = { section: string; score: number; reason: string; explanation: string };

interface GapAnalysis {
  missing_keywords: string[];
  low_sections: LowSection[];
}

type ResultsTab = "overview" | "sections" | "suggestions";

const SECTION_ORDER = ["Experience", "Projects", "Skills", "Summary"] as const;

function scoreBarColor(val: number) {
  return val >= 70 ? "bg-success" : val >= 40 ? "bg-amber-400" : "bg-danger";
}

function scoreTextColor(val: number) {
  return val >= 70 ? "text-success" : val >= 40 ? "text-amber-600" : "text-danger";
}

function OverviewPanel({
  matchScore,
  matchBreakdown,
  matchWeights,
  matchCeiling,
  scoreColor,
}: {
  matchScore: number;
  matchBreakdown: { kw: number; sk: number; cos: number } | null;
  matchWeights: { kw: number; sk: number; cos: number };
  matchCeiling: { score: number; reasons: string[]; exp_required?: number | null; exp_actual?: number | null } | null;
  scoreColor: string;
}) {
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

        {matchBreakdown && (
          <div className="mt-4 space-y-2">
            {[
              { label: "Keywords", value: matchBreakdown.kw, weight: matchWeights.kw, tooltip: "JD keywords found anywhere in your resume" },
              { label: "Skills→JD coverage", value: matchBreakdown.sk, weight: matchWeights.sk, tooltip: "How many of your listed skills appear in the JD (different from per-section Skills score)" },
              { label: "Semantic", value: matchBreakdown.cos, weight: matchWeights.cos, tooltip: "Overall content similarity (embedding cosine)" },
            ].map((b) => (
              <div key={b.label} className="flex items-center gap-3">
                <span className="text-[11px] text-muted w-32 shrink-0 cursor-help" title={b.tooltip}>{b.label}</span>
                <div className="flex-1 h-1 rounded-full bg-subtle overflow-hidden">
                  <div className="h-full bg-foreground/70 rounded-full transition-all duration-500" style={{ width: `${b.value}%` }} />
                </div>
                <span className="text-[11px] tabular-nums text-muted w-10 text-right">{b.value}%</span>
                <span className="text-[10px] tabular-nums text-muted/60 w-8 text-right">×{b.weight}%</span>
              </div>
            ))}
          </div>
        )}
      </div>

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
}: {
  sectionScores: Record<string, number | null> | null;
  matchGaps: GapAnalysis | null;
}) {
  const hasScores = sectionScores && Object.keys(sectionScores).length > 0;
  const lowMap = new Map<string, LowSection>(
    (matchGaps?.low_sections ?? []).map((s) => [s.section, s])
  );

  return (
    <div className="space-y-3">
      {hasScores && (
        <div className="card p-4">
          <p className="text-xs font-semibold uppercase tracking-wider text-muted mb-1">Match by section</p>
          <p className="text-[10px] text-muted mb-3 leading-relaxed">Each section is scored independently against the full JD — these don&apos;t sum to the overall match score.</p>
          <div className="space-y-2">
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
  keywords,
  matchGaps,
  onTailor,
  linkedInUrl,
  isTailorDisabled,
}: {
  keywords: string[];
  matchGaps: GapAnalysis | null;
  onTailor: () => void;
  linkedInUrl: (kw: string) => string;
  isTailorDisabled: boolean;
}) {
  const worst = (matchGaps?.low_sections ?? [])
    .slice()
    .sort((a, b) => a.score - b.score)[0];

  return (
    <div className="space-y-3">
      <div className="card p-5">
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-md bg-foreground/5 flex items-center justify-center shrink-0">
            <Wand2 className="w-4 h-4 text-foreground" />
          </div>
          <div className="flex-1">
            <p className="text-sm font-semibold mb-0.5">Tailor your resume to this JD</p>
            <p className="text-xs text-muted leading-relaxed mb-3">
              Review per-section edit suggestions, accept the ones that fit, and download a tailored copy.
            </p>
            <button
              onClick={onTailor}
              disabled={isTailorDisabled}
              className="btn-primary py-2 px-3 text-xs"
            >
              Open tailor flow
              <ArrowRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      </div>

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

      {keywords.length > 0 && (
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wider text-muted px-1 mb-2">Suggested roles to search</p>
          <div className="card divide-y divide-border">
            {keywords.map((kw, i) => (
              <a
                key={i}
                href={linkedInUrl(kw)}
                target="_blank"
                rel="noopener noreferrer"
                className="flex items-center justify-between px-4 py-3 hover:bg-subtle transition-colors text-sm"
              >
                <span className="font-medium">{kw}</span>
                <ExternalLink className="w-3.5 h-3.5 text-muted" />
              </a>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function JobSearchContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  
  const [keywords, setKeywords] = useState<string[]>([]);
  const [jdText, setJdText] = useState("");
  const [isMatching, setIsMatching] = useState(false);
  const [matchScore, setMatchScore] = useState<number | null>(null);
  const [matchBreakdown, setMatchBreakdown] = useState<{ kw: number; sk: number; cos: number } | null>(null);
  const [matchWeights, setMatchWeights] = useState<{ kw: number; sk: number; cos: number }>({ kw: 55, sk: 25, cos: 20 });
  const [matchCeiling, setMatchCeiling] = useState<{ score: number; reasons: string[]; exp_required?: number | null; exp_actual?: number | null } | null>(null);
  const [sectionScores, setSectionScores] = useState<Record<string, number | null> | null>(null);
  const [matchGaps, setMatchGaps] = useState<GapAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [templates, setTemplates] = useState<TemplateMeta[]>([]);
  const [isTemplatesLoading, setIsTemplatesLoading] = useState(true);
  const [templatesError, setTemplatesError] = useState(false);
  const [previews, setPreviews] = useState<Record<string, string>>({});
  const [selectedTemplate, setSelectedTemplate] = useState<string>("modern");
  const [modalTemplate, setModalTemplate] = useState<TemplateMeta | null>(null);
  const [resultsTab, setResultsTab] = useState<ResultsTab>("overview");
  const [layoutDensity, setLayoutDensity] = useState<"auto" | "compact" | "standard" | "expanded">("auto");

  const loadTemplates = useCallback(async (resumeId: string | null, apiUrl: string, density: string) => {
    setIsTemplatesLoading(true);
    setTemplatesError(false);
    try {
      const tRes = await fetch(`${apiUrl}/api/tailor/templates`);
      if (!tRes.ok) throw new Error("Templates fetch failed");
      const tData = await tRes.json();
      const list: TemplateMeta[] = tData.templates || [];
      setTemplates(list);

      if (!resumeId) return;
      await Promise.all(
        list.map(async (t) => {
          try {
            const res = await fetch(`${apiUrl}/api/tailor/preview`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                resume_id: resumeId,
                template_id: t.id,
                suggestions: [],
                layout_density: density === "auto" ? null : density,
              }),
            });
            if (!res.ok) return;
            const data = await res.json();
            setPreviews((prev) => ({ ...prev, [t.id]: data.html || "" }));
          } catch (err: unknown) {}
        })
      );
    } catch (err: unknown) {
      setTemplatesError(true);
    } finally {
      setIsTemplatesLoading(false);
    }
  }, []);

  useEffect(() => {
    const kw = searchParams.get("keywords");
    if (kw) {
      setKeywords(kw.split("|").map((k) => k.trim()).filter(Boolean));
      const rid = searchParams.get("resume_id");
      if (rid) sessionStorage.setItem("current_resume_id", rid);
    } else if (!sessionStorage.getItem("current_resume_id")) {
      router.push("/");
      return;
    }

    const stored = sessionStorage.getItem("template_id");
    if (stored) setSelectedTemplate(stored);

    const storedDensity = sessionStorage.getItem("layout_density");
    const initialDensity = (storedDensity as "auto" | "compact" | "standard" | "expanded") || "auto";
    if (storedDensity) setLayoutDensity(initialDensity);

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
    const resumeId = sessionStorage.getItem("current_resume_id");
    loadTemplates(resumeId, apiUrl, initialDensity);
  }, [searchParams, router, loadTemplates]);

  const handleDensityChange = useCallback((d: "auto" | "compact" | "standard" | "expanded") => {
    setLayoutDensity(d);
    sessionStorage.setItem("layout_density", d);
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
    const resumeId = sessionStorage.getItem("current_resume_id");
    loadTemplates(resumeId, apiUrl, d);
  }, [loadTemplates]);

  const handleSelectTemplate = useCallback((id: string) => {
    setSelectedTemplate(id);
    sessionStorage.setItem("template_id", id);
  }, []);

  const resetMatch = () => {
    setMatchScore(null);
    setMatchBreakdown(null);
    setMatchCeiling(null);
    setSectionScores(null);
    setMatchGaps(null);
  };

  const handleJdChange = (val: string) => {
    setJdText(val);
    resetMatch();
  };

  const linkedInUrl = (kw: string) =>
    `https://www.linkedin.com/jobs/search/?f_TPR=r1800&keywords=${encodeURIComponent(kw)}`;

  const onMatch = async () => {
    if (!jdText.trim()) return;
    setIsMatching(true);
    setError(null);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
      const res = await fetch(`${apiUrl}/api/match/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: sessionStorage.getItem("current_resume_id") || "",
          jd_text: jdText,
        }),
      });
      if (!res.ok) throw new Error("Match failed.");
      const data = await res.json();
      setMatchScore(data.score ?? data.match_score ?? null);
      // Map backend breakdown keys to frontend shape
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
      setSectionScores(data.section_scores ?? null);
      setMatchGaps(data.gap_analysis ?? null);
      setResultsTab("overview");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setIsMatching(false);
    }
  };

  const onTailor = () => {
    sessionStorage.setItem("tailor_jd_text", jdText);
    sessionStorage.setItem("template_id", selectedTemplate);
    sessionStorage.setItem("layout_density", layoutDensity);
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
    <div className="w-full max-w-5xl mx-auto px-6 py-12">
      <div className="mb-10">
        <h1 className="text-2xl font-semibold tracking-tight mb-2">
          Pick a template, match a job
        </h1>
        <p className="text-muted text-sm">
          Choose a template — your resume rendered in each is shown below — then
          paste a job description to see how well it matches.
        </p>
      </div>

      {/* Template picker */}
      <section className="mb-12">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
            Template
          </h2>
          <div className="flex items-center gap-2">
            <span className="text-[10px] uppercase tracking-wider text-muted">Density</span>
            <div className="inline-flex rounded-md border border-border overflow-hidden">
              {(["auto", "compact", "standard", "expanded"] as const).map((d) => (
                <button
                  key={d}
                  type="button"
                  onClick={() => handleDensityChange(d)}
                  className={`px-2.5 py-1 text-[11px] capitalize transition-colors ${
                    layoutDensity === d
                      ? "bg-foreground text-background"
                      : "bg-transparent text-muted hover:bg-subtle"
                  }`}
                >
                  {d}
                </button>
              ))}
            </div>
          </div>
        </div>
        {isTemplatesLoading ? (
          <div className="h-40 card flex items-center justify-center gap-2 text-sm text-muted">
            <Loader2 className="w-4 h-4 animate-spin" />
            Loading templates…
          </div>
        ) : templatesError ? (
          <div className="h-40 card flex flex-col items-center justify-center gap-3 text-sm text-muted">
            <p>Could not load templates.</p>
            <button
              className="btn-secondary text-xs"
              onClick={() => loadTemplates(sessionStorage.getItem("current_resume_id"), process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004", layoutDensity)}
            >
              Retry
            </button>
          </div>
        ) : templates.length === 0 ? (
          <div className="h-40 card flex items-center justify-center text-sm text-muted">
            No templates available.
          </div>
        ) : (
          <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
            {templates.map((t) => {
              const isSelected = selectedTemplate === t.id;
              const html = previews[t.id] ?? null;
              return (
                <div
                  key={t.id}
                  className={`card overflow-hidden transition-all cursor-pointer ${
                    isSelected
                      ? "ring-2 ring-foreground border-foreground"
                      : "hover:border-foreground/40"
                  }`}
                  onClick={() => handleSelectTemplate(t.id)}
                >
                  <div className="relative">
                    {/* Always-visible maximize icon — opens full preview */}
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setModalTemplate(t);
                      }}
                      className="absolute top-2 right-2 z-10 w-6 h-6 rounded bg-white/90 shadow-sm flex items-center justify-center hover:bg-white transition-colors"
                      aria-label="View full preview"
                    >
                      <Maximize2 className="w-3 h-3 text-foreground" />
                    </button>

                    {isSelected && (
                      <div className="absolute top-2 left-2 z-10 w-5 h-5 rounded-full bg-foreground text-white flex items-center justify-center shadow-sm">
                        <Check className="w-3 h-3" />
                      </div>
                    )}

                    <TemplatePreview html={html} />
                  </div>
                  <div className="p-3 border-t border-border">
                    <p className="text-sm font-semibold">{t.name}</p>
                    <p className="text-xs text-muted mt-0.5 line-clamp-1">{t.description}</p>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Match section — single column; results render as tabs once a match is computed */}
      <section className="space-y-3">
        {/* Pre-match: suggested roles inline. Post-match they move into the Suggestions tab. */}
        {keywords.length > 0 && matchScore === null && (
          <div>
            <h2 className="text-xs font-semibold uppercase tracking-wider text-muted mb-2">
              Suggested roles
            </h2>
            <div className="card divide-y divide-border">
              {keywords.map((kw, i) => (
                <a
                  key={i}
                  href={linkedInUrl(kw)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="flex items-center justify-between px-4 py-3 hover:bg-subtle transition-colors text-sm"
                >
                  <span className="font-medium">{kw}</span>
                  <ExternalLink className="w-3.5 h-3.5 text-muted" />
                </a>
              ))}
            </div>
          </div>
        )}

          <h2 className="text-xs font-semibold uppercase tracking-wider text-muted">
            Job description
          </h2>
          <textarea
            value={jdText}
            onChange={(e) => handleJdChange(e.target.value)}
            placeholder="Paste the job description…"
            className="input min-h-[260px] resize-y leading-relaxed"
          />

          <div className="flex items-center justify-end gap-3 flex-wrap">
            {matchScore === null ? (
              <button
                onClick={onMatch}
                disabled={isMatching || !jdText.trim()}
                className="btn-primary"
              >
                {isMatching ? (
                  <>
                    <Loader2 className="w-4 h-4 animate-spin" />
                    Analyzing…
                  </>
                ) : (
                  "Calculate match"
                )}
              </button>
            ) : (
              <button
                onClick={onTailor}
                disabled={!jdText.trim()}
                className="btn-primary"
              >
                Tailor resume
                <ArrowRight className="w-4 h-4" />
              </button>
            )}
          </div>

        {error && <p className="text-xs text-danger">{error}</p>}

        {/* Results — three-tab panel (Overview / Sections / Suggestions). Only renders post-match. */}
        {matchScore !== null && (
          <div className="mt-4 space-y-4">
            <Tabs<ResultsTab>
              value={resultsTab}
              onChange={setResultsTab}
              options={[
                { value: "overview", label: "Overview" },
                { value: "sections", label: "Sections", count: matchGaps?.low_sections?.length ?? 0 },
                { value: "suggestions", label: "Suggestions" },
              ]}
            />

            {resultsTab === "overview" && (
              <OverviewPanel
                matchScore={matchScore}
                matchBreakdown={matchBreakdown}
                matchWeights={matchWeights}
                matchCeiling={matchCeiling}
                scoreColor={scoreColor}
              />
            )}

            {resultsTab === "sections" && (
              <SectionsPanel sectionScores={sectionScores} matchGaps={matchGaps} />
            )}

            {resultsTab === "suggestions" && (
              <SuggestionsPanel
                keywords={keywords}
                matchGaps={matchGaps}
                onTailor={onTailor}
                linkedInUrl={linkedInUrl}
                isTailorDisabled={!jdText.trim()}
              />
            )}
          </div>
        )}
      </section>

      {/* Full preview modal */}
      {modalTemplate && (
        <div
          className="fixed inset-0 z-50 bg-black/60 backdrop-blur-sm flex items-center justify-center p-6"
          onClick={() => setModalTemplate(null)}
        >
          <div
            className="bg-white rounded-lg shadow-2xl w-full max-w-3xl max-h-[90vh] flex flex-col overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-3 border-b border-border">
              <div>
                <p className="text-sm font-semibold">{modalTemplate.name}</p>
                <p className="text-xs text-muted">{modalTemplate.description}</p>
              </div>
              <div className="flex items-center gap-2">
                <button
                  className="btn-primary py-1.5 px-3 text-xs"
                  onClick={() => {
                    handleSelectTemplate(modalTemplate.id);
                    setModalTemplate(null);
                  }}
                >
                  <Check className="w-3.5 h-3.5" />
                  Use this template
                </button>
                <button
                  onClick={() => setModalTemplate(null)}
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
                  srcDoc={previews[modalTemplate.id] || ""}
                  style={{
                    width: "100%",
                    height: "1056px",
                    border: 0,
                    background: "white",
                  }}
                />
              </div>
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
      <div className="flex items-center justify-center min-h-[50vh]">
        <Loader2 className="w-8 h-8 animate-spin text-muted" />
      </div>
    }>
      <JobSearchContent />
    </Suspense>
  );
}
