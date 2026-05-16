"use client";

import { useEffect, useRef, useState } from "react";
import { Pencil, Trash2, Plus, Sparkles, Loader2, Check, X } from "lucide-react";

export interface LineEditorProps {
  /** Section name used by the suggestion pipeline (Experience, Projects, Education, Certifications, Summary). */
  section: string;
  /** Owner identifier for `add_line` payloads — e.g. "Experience::0". May be empty for Summary / Certifications. */
  ownerId?: string;
  /** Visual leading marker — typically "• " for bullets, "" for summary, etc. */
  marker?: string;
  /** The line's current text. */
  text: string;
  /** Set true to hide the Add-below button (e.g. Summary). */
  hideAdd?: boolean;
  /** Set true to hide the Delete button (e.g. Summary single-field). */
  hideDelete?: boolean;
  /** Set true to render an "edited" accent — this line is the result of an accepted suggestion. */
  wasEdited?: boolean;
  badge?: React.ReactNode;
  /** Async fetcher for the chat-line endpoint. Returns rewritten text. */
  onAiChat: (instruction: string) => Promise<string>;
  /** Commit an edit — `newText` may equal `text` (no-op). */
  onEdit: (newText: string) => void;
  /** Remove this line. */
  onDelete: () => void;
  /** Insert a new empty line after this one. Receives the new line's text after the user types it. */
  onAddBelow: (newText: string) => void;
}

export function LineEditor({
  section,
  ownerId,
  marker = "• ",
  text,
  hideAdd,
  hideDelete,
  wasEdited,
  badge,
  onAiChat,
  onEdit,
  onDelete,
  onAddBelow,
}: LineEditorProps) {
  const [mode, setMode] = useState<"view" | "edit" | "ai" | "ai-pending" | "ai-result" | "add-new">("view");
  const [draft, setDraft] = useState(text);
  const [instruction, setInstruction] = useState("");
  const [aiResult, setAiResult] = useState("");
  const [aiError, setAiError] = useState<string | null>(null);
  const [newDraft, setNewDraft] = useState("");
  const editRef = useRef<HTMLTextAreaElement>(null);
  const instructionRef = useRef<HTMLTextAreaElement>(null);
  const addRef = useRef<HTMLTextAreaElement>(null);
  const lastInstructionRef = useRef("");

  // Keep local draft in sync if parent text changes (e.g. AI suggestion accepted elsewhere).
  useEffect(() => {
    if (mode === "view") setDraft(text);
  }, [text, mode]);

  const enterEdit = () => {
    setDraft(text);
    setMode("edit");
    setTimeout(() => editRef.current?.focus(), 0);
  };

  const commitEdit = () => {
    if (draft.trim() !== text.trim()) {
      onEdit(draft.trim());
    }
    setMode("view");
  };

  const cancelEdit = () => {
    setDraft(text);
    setMode("view");
  };

  const enterAi = () => {
    setInstruction("");
    setAiResult("");
    setAiError(null);
    setMode("ai");
    setTimeout(() => instructionRef.current?.focus(), 0);
  };

  const submitAi = async (retry = false) => {
    const prompt = retry ? lastInstructionRef.current : instruction.trim();
    if (!prompt) return;
    lastInstructionRef.current = prompt;
    setMode("ai-pending");
    setAiError(null);
    try {
      const rewritten = await onAiChat(prompt);
      setAiResult(rewritten);
      setMode("ai-result");
    } catch (e: unknown) {
      setAiError(e instanceof Error ? e.message : "AI request failed.");
      setMode("ai");
    }
  };

  const applyAi = () => {
    if (aiResult && aiResult.trim() !== text.trim()) {
      onEdit(aiResult.trim());
    }
    setMode("view");
  };

  const discardAi = () => {
    setAiResult("");
    setInstruction("");
    setMode("view");
  };

  const enterAdd = () => {
    setNewDraft("");
    setMode("add-new");
    setTimeout(() => addRef.current?.focus(), 0);
  };

  const commitAdd = () => {
    if (newDraft.trim()) {
      onAddBelow(newDraft.trim());
    }
    setNewDraft("");
    setMode("view");
  };

  return (
    <div
      className={`group/line relative py-1 ${
        wasEdited && mode === "view" ? "border-l-2 border-success/60 pl-2 -ml-2" : ""
      }`}
    >
      <div className="flex items-start gap-2 text-sm">
        {/* Marker + text or edit textarea */}
        <span className="text-muted shrink-0 leading-relaxed select-none">{marker}</span>
        <div className="flex-1 min-w-0">
          {mode === "edit" ? (
            <textarea
              ref={editRef}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onBlur={commitEdit}
              onKeyDown={(e) => {
                if (e.key === "Escape") { e.preventDefault(); cancelEdit(); }
                if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commitEdit(); }
              }}
              rows={Math.max(1, Math.min(8, draft.split("\n").length))}
              className="w-full bg-subtle/60 border border-border rounded px-2 py-1 text-sm leading-relaxed resize-none focus:outline-none focus:border-primary"
            />
          ) : (
            <p className="leading-relaxed whitespace-pre-wrap break-words">{text}</p>
          )}
        </div>

        {/* "Edited" pill — always visible when this line came from an accepted suggestion */}
        {wasEdited && mode === "view" && (
          <span
            title="This line was tailored — accepted from a suggestion"
            className="shrink-0 inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-medium bg-success/10 text-success border border-success/30"
          >
            Edited
          </span>
        )}

        {/* Per-line toolbar — visible on hover, always visible while interactive */}
        <div
          className={`flex items-center gap-0.5 shrink-0 transition-opacity ${
            mode === "view" && !badge ? "opacity-0 group-hover/line:opacity-100" : "opacity-100"
          }`}
        >
          {badge}
          {mode === "view" && (
            <>
              <button
                onClick={enterEdit}
                title="Edit"
                className="p-1 rounded hover:bg-subtle text-muted hover:text-foreground"
              >
                <Pencil className="w-3 h-3" />
              </button>
              <button
                onClick={enterAi}
                title="AI chat — improve this line"
                className="p-1 rounded hover:bg-primary/10 text-primary"
              >
                <Sparkles className="w-3 h-3" />
              </button>
              {!hideDelete && (
                <button
                  onClick={onDelete}
                  title="Delete"
                  className="p-1 rounded hover:bg-danger/10 text-muted hover:text-danger"
                >
                  <Trash2 className="w-3 h-3" />
                </button>
              )}
              {!hideAdd && (
                <button
                  onClick={enterAdd}
                  title="Add a new line below"
                  className="p-1 rounded hover:bg-subtle text-muted hover:text-foreground"
                >
                  <Plus className="w-3 h-3" />
                </button>
              )}
            </>
          )}
        </div>
      </div>

      {/* AI chat panel */}
      {(mode === "ai" || mode === "ai-pending" || mode === "ai-result") && (
        <div className="mt-1.5 ml-5 mr-1 border border-primary/30 bg-primary/5 rounded p-2 space-y-1.5">
          {mode === "ai" && (
            <>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-primary">
                AI chat — improve this {section.toLowerCase()} line
              </p>
              <textarea
                ref={instructionRef}
                value={instruction}
                onChange={(e) => setInstruction(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Escape") { e.preventDefault(); discardAi(); }
                  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submitAi(false); }
                }}
                rows={2}
                placeholder="e.g. 'add a throughput metric and mention the auth flow'"
                className="w-full bg-white border border-border rounded px-2 py-1 text-xs resize-none focus:outline-none focus:border-primary"
              />
              {aiError && <p className="text-[11px] text-danger">{aiError}</p>}
              <div className="flex items-center justify-end gap-2">
                <button onClick={discardAi} className="text-[11px] text-muted hover:text-foreground">
                  Cancel
                </button>
                <button
                  onClick={() => submitAi(false)}
                  disabled={!instruction.trim()}
                  className="btn-primary py-1 px-2.5 text-[11px] disabled:opacity-40"
                >
                  Ask
                </button>
              </div>
            </>
          )}
          {mode === "ai-pending" && (
            <div className="flex items-center gap-2 text-[11px] text-muted py-1">
              <Loader2 className="w-3 h-3 animate-spin" />
              Rewriting line with the resume + JD as context…
            </div>
          )}
          {mode === "ai-result" && (
            <>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-primary">
                AI rewrite
              </p>
              <p className="text-xs leading-relaxed bg-white border border-border rounded px-2 py-1.5">
                {aiResult}
              </p>
              <div className="flex items-center justify-between gap-2">
                <button
                  onClick={() => submitAi(true)}
                  className="text-[11px] text-muted hover:text-foreground inline-flex items-center gap-1"
                >
                  <Loader2 className="w-3 h-3" /> Try again
                </button>
                <div className="flex items-center gap-2">
                  <button onClick={discardAi} className="btn-ghost py-1 px-2.5 text-[11px]">
                    <X className="w-3 h-3" /> Discard
                  </button>
                  <button onClick={applyAi} className="btn-primary py-1 px-2.5 text-[11px]">
                    <Check className="w-3 h-3" /> Apply
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      )}

      {/* Add-new line input */}
      {mode === "add-new" && (
        <div className="mt-1.5 ml-5 flex items-start gap-2">
          <span className="text-muted shrink-0 leading-relaxed select-none">{marker}</span>
          <textarea
            ref={addRef}
            value={newDraft}
            onChange={(e) => setNewDraft(e.target.value)}
            onBlur={commitAdd}
            onKeyDown={(e) => {
              if (e.key === "Escape") { e.preventDefault(); setMode("view"); setNewDraft(""); }
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); commitAdd(); }
            }}
            rows={Math.max(1, Math.min(6, newDraft.split("\n").length))}
            placeholder={`New ${section.toLowerCase()} line — Enter to save, Esc to cancel`}
            className="flex-1 bg-subtle/60 border border-border rounded px-2 py-1 text-sm leading-relaxed resize-none focus:outline-none focus:border-primary"
          />
        </div>
      )}

      {/* Owner id annotation (debug-only, hidden) */}
      {ownerId && false && <span className="hidden">{ownerId}</span>}
    </div>
  );
}
