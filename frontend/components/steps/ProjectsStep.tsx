"use client";

import { useState } from "react";
import { ArrowRight, ChevronRight } from "lucide-react";
import { DiffViewer } from "@/components/DiffViewer";
import type { Suggestion } from "@/types/resume";

interface ProjectsStepProps {
  pending: Suggestion[];
  projectNames: string[];
  onApprove: (id: number, edited: string) => void;
  onReject: (id: number) => void;
  onContinue: () => void;
  onSkip: () => void;
  continueLabel: string;
}

export function ProjectsStep({
  pending, projectNames, onApprove, onReject, onContinue, onSkip, continueLabel,
}: ProjectsStepProps) {
  const [frozenIndices, setFrozenIndices] = useState<number[] | null>(null);
  const [carouselIdx, setCarouselIdx] = useState(0);

  // Freeze the project index set on first non-empty `pending` payload; later updates
  // change suggestion bodies, not which projects we walk through. Uses "adjust state
  // while rendering" to avoid setState-in-effect cascades.
  if (frozenIndices === null) {
    const set = new Set<number>();
    pending.forEach((s) => {
      if (typeof s.project_index === "number") set.add(s.project_index);
    });
    if (set.size > 0) {
      setFrozenIndices(Array.from(set).sort((a, b) => a - b));
    }
  }
  const projectIndices: number[] = frozenIndices ?? [];

  if (!projectIndices || projectIndices.length === 0) {
    return (
      <div className="space-y-3">
        <div className="card p-6 text-center">
          <p className="text-sm text-muted">No project changes proposed.</p>
        </div>
        <div className="flex justify-end pt-2">
          <button onClick={onContinue} className="btn-primary">
            {continueLabel}
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  }

  const currentProjectIndex = projectIndices[carouselIdx];
  const currentSuggestions = pending.filter((s) => s.project_index === currentProjectIndex);
  const currentName = projectNames[currentProjectIndex] ?? `Project ${currentProjectIndex + 1}`;
  const isLastProject = carouselIdx === projectIndices.length - 1;

  const handleAdvance = () => {
    if (isLastProject) {
      onContinue();
    } else {
      setCarouselIdx(carouselIdx + 1);
    }
  };

  const handleSkip = () => {
    if (pending.length >= 4) {
      if (!confirm(`You have ${pending.length} pending project changes. Skip and discard them?`)) {
        return;
      }
    }
    onSkip();
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">Projects</h3>
          <span className="text-xs text-muted">·</span>
          <span className="text-xs font-medium">{currentName}</span>
        </div>
        <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wider px-2 py-0.5 rounded-full bg-subtle border border-border text-muted tabular-nums">
          {carouselIdx + 1} / {projectIndices.length}
        </span>
      </div>

      {currentSuggestions.length > 0 ? (
        currentSuggestions.map((s) => (
          <DiffViewer
            key={s.id}
            section={s.section}
            original={s.original ?? ""}
            suggested={s.suggested ?? ""}
            reasoning={s.reasoning ?? ""}
            mode={s.mode === "add_skill" ? "add" : "replace"}
            onApprove={(edited) => onApprove(s.id, edited)}
            onReject={() => onReject(s.id)}
          />
        ))
      ) : (
        <div className="card p-6 text-center">
          <p className="text-sm text-muted">All decisions made for this project.</p>
        </div>
      )}

      <div className="flex items-center justify-between pt-2">
        <button onClick={handleSkip} className="text-xs text-muted hover:text-foreground transition-colors">
          Skip section
        </button>
        <button onClick={handleAdvance} className="btn-primary">
          {isLastProject ? continueLabel : `Continue to next project`}
          {isLastProject ? <ArrowRight className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        </button>
      </div>
    </div>
  );
}
