"use client";

import { useRef, useState } from "react";
import { Pencil, Trash2, Plus, Wand2 } from "lucide-react";

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
  /** Commit an edit — `newText` may equal `text` (no-op). */
  onEdit: (newText: string) => void;
  /** Remove this line. */
  onDelete: () => void;
  /** Insert a new empty line after this one. Receives the new line's text after the user types it. */
  onAddBelow?: (newText: string) => void;
  /** Open the Copilot chat focused on this line ("what do you want to change?"). */
  onCopilot?: () => void;
}

export function LineEditor({
  section,
  marker = "• ",
  text,
  hideAdd,
  hideDelete,
  wasEdited,
  badge,
  onEdit,
  onDelete,
  onAddBelow,
  onCopilot,
}: LineEditorProps) {
  const [mode, setMode] = useState<"view" | "edit" | "add-new">("view");
  const [draft, setDraft] = useState(text);
  const [lastSyncedText, setLastSyncedText] = useState(text);
  const [newDraft, setNewDraft] = useState("");
  const editRef = useRef<HTMLTextAreaElement>(null);
  const addRef = useRef<HTMLTextAreaElement>(null);

  // Keep local draft in sync if parent text changes (e.g. AI suggestion accepted elsewhere).
  // Uses the "adjust state while rendering" pattern to avoid setState-in-effect.
  if (text !== lastSyncedText) {
    setLastSyncedText(text);
    if (mode === "view") setDraft(text);
  }

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

  const enterAdd = () => {
    setNewDraft("");
    setMode("add-new");
    setTimeout(() => addRef.current?.focus(), 0);
  };

  const commitAdd = () => {
    if (newDraft.trim() && onAddBelow) {
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
              {onCopilot && (
                <button
                  onClick={onCopilot}
                  title="Ask Copilot to change this line"
                  className="p-1 rounded hover:bg-primary/10 text-primary"
                >
                  <Wand2 className="w-3 h-3" />
                </button>
              )}
              <button
                onClick={enterEdit}
                title="Edit"
                className="p-1 rounded hover:bg-subtle text-muted hover:text-foreground"
              >
                <Pencil className="w-3 h-3" />
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
            placeholder={section.toLowerCase() === "summary" ? "New summary sentence — Enter to save, Esc to cancel" : `New ${section.toLowerCase()} bullet — Enter to save, Esc to cancel`}
            className="flex-1 bg-subtle/60 border border-border rounded px-2 py-1 text-sm leading-relaxed resize-none focus:border-primary"
          />
        </div>
      )}
    </div>
  );
}
