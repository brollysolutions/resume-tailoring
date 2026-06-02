"use client";

import { useState } from "react";
import { Check, X, Pencil, Plus, RefreshCw, Loader2 } from "lucide-react";

interface DiffProps {
  section: string;
  original: string;
  suggested: string;
  reasoning: string;
  mode?: "replace" | "add";
  jdText?: string;
  onApprove: (editedText: string) => void;
  onReject: () => void;
}

export function DiffViewer({
  section,
  original,
  suggested,
  reasoning,
  mode = "replace",
  jdText,
  onApprove,
  onReject,
}: DiffProps) {
  const [isEditing, setIsEditing] = useState(false);
  const [edited, setEdited] = useState(suggested);
  const [isRegenerating, setIsRegenerating] = useState(false);
  const [regenError, setRegenError] = useState<string | null>(null);

  const isAdd = mode === "add";

  const handleRegenerate = async () => {
    if (!jdText) {
      setRegenError("No Job Description context.");
      return;
    }
    setIsRegenerating(true);
    setRegenError(null);
    try {
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "https://brollysolutions.in/brollyresume";
      const res = await fetch(`${apiUrl}/api/tailor/regenerate`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jd_text: jdText,
          section,
          original,
          previous_suggested: edited,
          mode,
        }),
      });
      if (!res.ok) {
        const d = await res.json().catch(() => ({}));
        throw new Error(d.detail || "Regenerate failed.");
      }
      const data = await res.json();
      if (data.suggested) {
        setEdited(data.suggested);
      }
    } catch (err: unknown) {
      setRegenError(err instanceof Error ? err.message : "Regenerate failed.");
    } finally {
      setIsRegenerating(false);
    }
  };

  return (
    <div className="card overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border flex items-center justify-between bg-subtle/50">
        <div className="flex items-center gap-2">
          <span className="text-xs font-semibold tracking-wide">{section}</span>
          {isAdd && (
            <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-success/10 text-success border border-success/20">
              <Plus className="w-2.5 h-2.5" /> ADD
            </span>
          )}
        </div>
        <button
          onClick={() => setIsEditing(!isEditing)}
          className="text-xs text-muted hover:text-foreground transition-colors inline-flex items-center gap-1"
        >
          <Pencil className="w-3 h-3" />
          {isEditing ? "Preview" : "Edit"}
        </button>
      </div>

      <div className="p-4 space-y-3">
        {isAdd ? (
          <div>
            <p className="text-[10px] font-semibold uppercase tracking-wider text-muted mb-1">
              Add to category
            </p>
            <p className="text-sm leading-relaxed text-foreground">
              <span className="font-medium">{original}</span>
              <span className="text-muted"> ← </span>
              {isEditing ? (
                <input
                  value={edited}
                  onChange={(e) => setEdited(e.target.value)}
                  className="input inline-block w-auto min-w-[10rem] text-sm py-0.5 px-2"
                />
              ) : (
                <span className="font-medium text-success">{edited}</span>
              )}
            </p>
          </div>
        ) : (
          <>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted mb-1">
                Original
              </p>
              <p className="text-sm leading-relaxed text-muted line-through decoration-1">
                {original}
              </p>
            </div>

            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-muted mb-1">
                Suggested
              </p>
              {isEditing ? (
                <textarea
                  value={edited}
                  onChange={(e) => setEdited(e.target.value)}
                  className="input min-h-[80px] text-sm leading-relaxed"
                />
              ) : (
                <p className="text-sm leading-relaxed text-foreground">{edited}</p>
              )}
            </div>
          </>
        )}

        {reasoning && (
          <p className="text-xs text-muted pt-1 border-t border-border/60">
            <span className="font-medium text-foreground/80">Why:</span> {reasoning}
          </p>
        )}

        {regenError && (
          <p className="text-xs text-danger">{regenError}</p>
        )}
      </div>

      <div className="px-4 py-2.5 border-t border-border flex items-center justify-between gap-2">
        <button
          onClick={handleRegenerate}
          disabled={isRegenerating || !jdText}
          className="inline-flex items-center gap-1 text-xs text-muted hover:text-foreground transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
          title={!jdText ? "Job Description context unavailable" : "Generate a different suggestion"}
        >
          {isRegenerating ? (
            <Loader2 className="w-3 h-3 animate-spin" />
          ) : (
            <RefreshCw className="w-3 h-3" />
          )}
          {isRegenerating ? "Regenerating…" : "Regenerate"}
        </button>

        <div className="flex items-center gap-2">
          <button onClick={onReject} className="btn-secondary py-1.5 px-3">
            <X className="w-3.5 h-3.5" /> Reject
          </button>
          <button onClick={() => onApprove(edited)} className="btn-primary py-1.5 px-3">
            <Check className="w-3.5 h-3.5" /> {isAdd ? "Add" : "Approve"}
          </button>
        </div>
      </div>
    </div>
  );
}
