"use client";

import { useState } from "react";
import { ArrowRight, ChevronDown, ChevronUp, Check } from "lucide-react";
import { DiffViewer } from "@/components/DiffViewer";
import type { Suggestion } from "@/types/resume";

interface FlatStepProps {
  title: string;
  pending: Suggestion[];
  accepted?: Suggestion[];
  jdText?: string;
  onApprove: (id: number, edited: string) => void;
  onReject: (id: number) => void;
  onRevert?: (id: number) => void;
  onContinue: () => void;
  onSkip: () => void;
  continueLabel: string;
}

export function FlatStep({
  title, pending, accepted = [], jdText, onApprove, onReject, onRevert, onContinue, onSkip, continueLabel,
}: FlatStepProps) {
  const [showAccepted, setShowAccepted] = useState(false);

  const handleSkip = () => {
    if (pending.length >= 4) {
      if (!confirm(`You have ${pending.length} pending changes in ${title}. Skip and discard them?`)) {
        return;
      }
    }
    onSkip();
  };

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wider text-muted">{title}</h3>
        <div className="flex items-center gap-2">
          {accepted.length > 0 && (
            <button
              onClick={() => setShowAccepted((v) => !v)}
              className="inline-flex items-center gap-1 text-xs text-muted hover:text-foreground transition-colors"
            >
              <Check className="w-3 h-3 text-success" />
              {accepted.length} accepted
              {showAccepted ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
            </button>
          )}
          <span className="text-xs text-muted tabular-nums">{pending.length} pending</span>
        </div>
      </div>

      {showAccepted && accepted.length > 0 && (
        <div className="card p-3 space-y-1.5 border-success/20 bg-success/5">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-muted mb-2">Accepted — click Undo to revert</p>
          {accepted.map((s) => (
            <div key={s.id} className="flex items-start justify-between gap-2 text-xs">
              <div className="min-w-0 flex-1">
                <p className="text-muted line-through truncate text-[11px]">{s.original}</p>
                <p className="truncate">{s.suggested}</p>
              </div>
              {onRevert && (
                <button
                  onClick={() => onRevert(s.id)}
                  className="text-[10px] text-muted hover:text-danger shrink-0 border border-border rounded px-1.5 py-0.5"
                >
                  Undo
                </button>
              )}
            </div>
          ))}
        </div>
      )}

      {pending.length > 0 ? (
        pending.map((s) => (
          <DiffViewer
            key={s.id}
            section={s.section}
            original={s.original ?? ""}
            suggested={s.suggested ?? ""}
            reasoning={s.reasoning ?? ""}
            mode={s.mode === "add_skill" ? "add" : "replace"}
            jdText={jdText}
            onApprove={(edited) => onApprove(s.id, edited)}
            onReject={() => onReject(s.id)}
          />
        ))
      ) : (
        <div className="card p-6 text-center">
          <p className="text-sm text-muted">All decisions made for this section.</p>
        </div>
      )}

      <div className="flex items-center justify-between pt-2">
        <button onClick={handleSkip} className="text-xs text-muted hover:text-foreground transition-colors">
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
