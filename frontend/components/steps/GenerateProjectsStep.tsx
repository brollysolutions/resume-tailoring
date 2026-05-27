"use client";

import { useState } from "react";
import { ArrowRight, ChevronDown, ChevronUp, Check, Sparkles, Loader2, RefreshCw } from "lucide-react";
import type { GeneratedProject } from "@/types/resume";

const DOMAIN_COLORS: Record<string, string> = {
  data: "bg-blue-50 text-blue-700 border-blue-200",
  product: "bg-purple-50 text-purple-700 border-purple-200",
  infra: "bg-orange-50 text-orange-700 border-orange-200",
  ml: "bg-green-50 text-green-700 border-green-200",
  tools: "bg-slate-100 text-slate-700 border-slate-200",
};

function ProjectCard({
  project, kept, replacesName, addDisabled, onToggleKeep,
}: {
  project: GeneratedProject;
  kept: boolean;
  replacesName: string | null;
  addDisabled: boolean;
  onToggleKeep: () => void;
}) {
  const [briefOpen, setBriefOpen] = useState(false);
  const domainClass = DOMAIN_COLORS[project.domain_tag] ?? DOMAIN_COLORS.tools;

  return (
    <div className={`card p-4 transition-all ${kept ? "ring-2 ring-foreground/30 bg-subtle/30" : ""}`}>
      <div className="flex items-start justify-between gap-3 mb-2">
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <p className="text-sm font-semibold">{project.name}</p>
            <span className={`inline-block px-1.5 py-0.5 rounded text-[10px] font-medium border ${domainClass}`}>
              {project.domain_tag}
            </span>
          </div>
          <p className="text-xs text-muted mt-0.5 font-mono">{project.tech}</p>
          {kept && replacesName && (
            <p className="text-[11px] text-muted mt-1">
              Replaces: <span className="text-foreground font-medium">{replacesName}</span>
            </p>
          )}
        </div>
        <button
          onClick={onToggleKeep}
          disabled={!kept && addDisabled}
          className={`shrink-0 flex items-center gap-1 px-2.5 py-1 rounded text-xs font-medium border transition-colors ${
            kept
              ? "bg-foreground text-white border-foreground"
              : addDisabled
              ? "bg-transparent text-muted/40 border-border/60 cursor-not-allowed"
              : "bg-transparent text-muted border-border hover:border-foreground/40"
          }`}
          title={!kept && addDisabled ? "Limit reached — unkeep another project first" : undefined}
        >
          {kept && <Check className="w-3 h-3" />}
          {kept ? "Added" : "Add to resume"}
        </button>
      </div>

      <ul className="space-y-1 mb-3">
        {project.bullets.map((b, i) => (
          <li key={i} className="text-xs text-foreground flex gap-2">
            <span className="text-muted mt-0.5 shrink-0">•</span>
            <span>{b}</span>
          </li>
        ))}
      </ul>

      {project.interview_brief && (
        <div>
          <button
            onClick={() => setBriefOpen(!briefOpen)}
            className="flex items-center gap-1 text-[11px] text-muted hover:text-foreground transition-colors"
          >
            {briefOpen ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            Interview brief
          </button>
          {briefOpen && (
            <p className="mt-2 text-xs text-muted leading-relaxed border-l-2 border-border pl-3">
              {project.interview_brief}
            </p>
          )}
        </div>
      )}
    </div>
  );
}

interface GenerateProjectsStepProps {
  resumeId: string | null;
  jdText: string;
  apiUrl: string;
  keptProjects: GeneratedProject[];
  projectCount: number;
  projectNames: string[];
  onProjectsGenerated: (projects: GeneratedProject[]) => void;
  onKeptChange: (projects: GeneratedProject[]) => void;
  continueDisabled?: boolean;
  onContinue: () => void;
  onSkip: () => void;
  continueLabel: string;
}

export function GenerateProjectsStep({
  resumeId, jdText, apiUrl, projectCount, projectNames, onProjectsGenerated,
  onKeptChange, continueDisabled = false, onContinue, onSkip, continueLabel,
}: GenerateProjectsStepProps) {
  const [projects, setProjects] = useState<GeneratedProject[]>([]);
  const [keptSet, setKeptSet] = useState<Set<number>>(new Set());
  const [isGenerating, setIsGenerating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [excludeNames, setExcludeNames] = useState<string[]>([]);
  const [listOpen, setListOpen] = useState(true);

  const maxSlots = projectCount > 0 ? projectCount : 3;

  const generate = async (regen = false) => {
    if (!resumeId || !jdText.trim()) return;
    setIsGenerating(true);
    setError(null);
    try {
      const res = await fetch(`${apiUrl}/api/tailor/generate-projects`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: resumeId,
          jd_text: jdText,
          count: maxSlots,
          exclude_names: regen ? excludeNames : [],
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || "Generation failed.");
      }
      const data = await res.json();
      const newProjects: GeneratedProject[] = data.projects || [];
      setProjects(newProjects);
      setKeptSet(new Set());
      onProjectsGenerated(newProjects);
      onKeptChange([]);
      if (regen) {
        setExcludeNames((prev) => [...prev, ...newProjects.map((p) => p.name)]);
      } else {
        setExcludeNames(newProjects.map((p) => p.name));
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setIsGenerating(false);
    }
  };

  const toggleKeep = (i: number) => {
    const next = new Set(keptSet);
    if (next.has(i)) {
      next.delete(i);
    } else {
      if (next.size >= maxSlots) return;
      next.add(i);
    }
    setKeptSet(next);
    onKeptChange(projects.filter((_, idx) => next.has(idx)));
  };

  const keptCount = keptSet.size;
  const addDisabled = keptCount >= maxSlots;

  const replacesByIndex: Record<number, string | null> = {};
  let slot = 0;
  projects.forEach((_, idx) => {
    if (keptSet.has(idx)) {
      replacesByIndex[idx] = projectNames[slot] ?? null;
      slot += 1;
    }
  });

  if (projects.length === 0 && !isGenerating) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Projects</h3>
        </div>
        <div className="card p-8 text-center space-y-4">
          <Sparkles className="w-7 h-7 mx-auto text-muted" />
          <div>
            <p className="text-sm font-medium mb-1">Generate Job Description-tailored projects</p>
            <p className="text-xs text-muted max-w-xs mx-auto">
              {projectCount > 0 ? null : (
                <>Creates {maxSlots} industry-level projects built around this Job Description and your skills.</>
              )}
            </p>
          </div>
          {error && <p className="text-xs text-danger">{error}</p>}
          <button onClick={() => generate(false)} className="btn-primary mx-auto">
            <Sparkles className="w-4 h-4" />
            Generate projects
          </button>
        </div>
        <div className="flex items-center justify-between pt-1">
          <button onClick={onSkip} className="text-xs text-muted hover:text-foreground transition-colors">
            Keep existing projects
          </button>
          <button onClick={onContinue} className="btn-secondary text-xs">
            Skip <ArrowRight className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>
    );
  }

  if (isGenerating) {
    return (
      <div className="space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Projects</h3>
        </div>
        <div className="space-y-3 animate-pulse select-none">
          {[1, 2].map((i) => (
            <div key={i} className="card p-4 space-y-4">
              <div className="flex items-start justify-between gap-3">
                <div className="space-y-2 w-1/2">
                  <div className="h-4 bg-muted/60 rounded w-2/3" />
                  <div className="h-3 bg-muted/40 rounded w-1/3" />
                </div>
                <div className="h-7 bg-muted/50 rounded w-24" />
              </div>
              <div className="space-y-2">
                <div className="h-2.5 bg-muted/30 rounded w-11/12" />
                <div className="h-2.5 bg-muted/30 rounded w-full" />
                <div className="h-2.5 bg-muted/30 rounded w-5/6" />
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 flex-wrap">
          <button
            onClick={() => setListOpen((v) => !v)}
            className="inline-flex items-center gap-1 text-muted hover:text-foreground transition-colors"
            title={listOpen ? "Hide generated projects" : "Show generated projects"}
          >
            {listOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            <h3 className="text-xs font-semibold uppercase tracking-wider">Projects</h3>
          </button>
          <span className="text-xs text-muted">
            · {keptCount} of {maxSlots} slot{maxSlots !== 1 ? "s" : ""} used
          </span>
          {!listOpen && <span className="text-xs text-muted">· {projects.length} generated</span>}
        </div>
        <button
          onClick={() => generate(true)}
          className="flex items-center gap-1.5 text-xs text-muted hover:text-foreground transition-colors"
        >
          <RefreshCw className="w-3 h-3" /> Regenerate
        </button>
      </div>

      {listOpen && projectCount > 0 && (
        <p className="text-[11px] text-muted px-1">
          The kth project you add replaces the kth existing project on your resume. Limit: {maxSlots}.
        </p>
      )}

      {error && <p className="text-xs text-danger">{error}</p>}

      {listOpen && projects.map((proj, i) => (
        <ProjectCard
          key={proj.fingerprint || i}
          project={proj}
          kept={keptSet.has(i)}
          replacesName={replacesByIndex[i] ?? null}
          addDisabled={addDisabled}
          onToggleKeep={() => toggleKeep(i)}
        />
      ))}

      <div className="flex items-center justify-between pt-2">
        {projects.length === 0 && (
          <button
            onClick={onSkip}
            disabled={continueDisabled}
            className="text-xs text-muted hover:text-foreground transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          >
            Keep existing projects
          </button>
        )}
        <button
          onClick={onContinue}
          disabled={continueDisabled}
          className="btn-primary disabled:opacity-60 disabled:cursor-not-allowed"
        >
          {continueDisabled ? (
            <><Loader2 className="w-4 h-4 animate-spin" />Calculating match…</>
          ) : (
            <>{continueLabel}<ArrowRight className="w-4 h-4" /></>
          )}
        </button>
      </div>
    </div>
  );
}
