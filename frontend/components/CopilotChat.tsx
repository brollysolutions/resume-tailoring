"use client";

import { useState, useRef, useEffect } from "react";
import { Send, Sparkles, Loader2, Bot, User, Cpu, Compass, X, Check, Wand2, FolderPlus, SkipForward, ChevronDown, ChevronUp } from "lucide-react";
import type { Suggestion, GeneratedProject } from "@/types/resume";

interface Message {
  id: string;
  sender: "user" | "copilot";
  text: string;
  suggestions?: Suggestion[];
  timestamp: Date;
}

export interface CopilotFocus {
  section: string;
  targetType: "line" | "entry" | "section";
  /** line target — the exact clicked line text */
  original?: string;
  /** entry target — index of the job/project entry */
  entryIndex?: number;
  /** display label for the chip (entry header / section name) */
  label?: string;
}

interface CopilotChatProps {
  resumeId: string | null;
  jdText: string;
  apiUrl: string;
  /** Already-accepted edits — sent so the copilot grounds on current tailored state. */
  approved: Suggestion[];
  keptProjects?: GeneratedProject[];
  /** Next id the parent will assign — seeds backend suggestion ids to avoid collisions. */
  nextSuggestionId: number;
  /** Line the user clicked in the editor to target ("what do you want to change?"). */
  focus: CopilotFocus | null;
  onClearFocus: () => void;
  /** Accept a single proposed suggestion (parent applies + queues for download). */
  onAcceptSuggestion: (s: Suggestion) => void;
  /** Per-response side effects: id bump + directives (undo_last, generate_projects). */
  onResult: (suggestions: Suggestion[], directives: { type: string }[]) => void;
  onClose?: () => void;
  /** Chat-generated projects awaiting review (not yet applied to resume). */
  pendingProjects?: GeneratedProject[];
  /** Called when user clicks Add on a pending project card. */
  onKeepProject?: (project: GeneratedProject) => void;
  /** Called when user clicks Skip on a pending project card. */
  onSkipProject?: (projectName: string) => void;
}

const PRESET_PILLS = [
  { text: "Tailor my experience to this JD", icon: Sparkles },
  { text: "Make my bullets metrics-driven", icon: Cpu },
  { text: "Align my skills to the JD", icon: Compass },
];

function describeSuggestion(s: Suggestion): { title: string; body?: React.ReactNode } {
  const section = s.section || "";
  const mode = s.mode || "replace";
  if (section.toLowerCase().startsWith("skill")) {
    switch (mode) {
      case "add_skill":
        return { title: `Add skill "${s.skill}"${s.target_category || s.category ? ` to ${s.target_category || s.category}` : ""}` };
      case "remove_skill":
        return { title: `Remove skill "${s.skill}" from ${s.category}` };
      case "rename_category":
        return { title: `Rename category "${s.category}" → "${s.target_category}"` };
      case "delete_category":
        return { title: `Delete category "${s.category}"` };
      case "move_skill":
        return { title: `Move "${s.skill}": ${s.category} → ${s.target_category}` };
      default:
        return { title: `Skills update` };
    }
  }
  if (mode === "reorder_sections") {
    let order: string[] = [];
    try { order = JSON.parse(s.suggested || "[]"); } catch { /* ignore */ }
    return { title: "Reorder sections", body: <span className="text-muted">{order.join(" · ")}</span> };
  }
  if (mode === "remove_line") {
    return { title: `Remove line from ${section}`, body: <span className="line-through text-muted">{s.original}</span> };
  }
  if (mode === "replace_bullets") {
    let bullets: string[] = [];
    try { bullets = JSON.parse(s.suggested || "[]"); } catch { /* ignore */ }
    return {
      title: `Rewrite ${bullets.length} bullet${bullets.length !== 1 ? "s" : ""} in ${section}`,
      body: (
        <ul className="list-disc pl-4 space-y-0.5">
          {bullets.map((b, i) => <li key={i}>{b}</li>)}
        </ul>
      ),
    };
  }
  // replace / add_line
  return {
    title: `${mode === "add_line" ? "Add line to" : "Edit"} ${section}`,
    body: (
      <div className="space-y-0.5">
        {s.original && mode !== "add_line" && <p className="line-through text-muted">{s.original}</p>}
        <p className="text-foreground">{s.suggested}</p>
      </div>
    ),
  };
}

const DOMAIN_COLORS: Record<string, string> = {
  data: "bg-blue-50 text-blue-700 border-blue-200",
  product: "bg-purple-50 text-purple-700 border-purple-200",
  infra: "bg-orange-50 text-orange-700 border-orange-200",
  ml: "bg-green-50 text-green-700 border-green-200",
  tools: "bg-slate-100 text-slate-700 border-slate-200",
};

function ChatProjectCard({
  project,
  onKeep,
  onSkip,
}: {
  project: GeneratedProject;
  onKeep: () => void;
  onSkip: () => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const domainClass = DOMAIN_COLORS[project.domain_tag] ?? DOMAIN_COLORS.tools;
  return (
    <div className="rounded-lg border border-emerald-100 bg-emerald-50/40 p-2.5 space-y-1.5">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5 flex-wrap">
            <p className="text-[12px] font-semibold text-slate-800 leading-snug">{project.name}</p>
            <span className={`inline-block px-1.5 py-0.5 rounded text-[9px] font-medium border ${domainClass}`}>
              {project.domain_tag}
            </span>
          </div>
          <p className="text-[10px] text-slate-500 font-mono mt-0.5 truncate">{project.tech}</p>
        </div>
        <div className="flex items-center gap-1 shrink-0">
          <button
            onClick={onSkip}
            className="p-1 rounded hover:bg-slate-100 text-slate-400 hover:text-slate-600 transition-colors"
            title="Skip this project"
          >
            <X className="w-3.5 h-3.5" />
          </button>
          <button
            onClick={onKeep}
            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold text-white bg-emerald-600 hover:bg-emerald-500 transition-colors"
          >
            <FolderPlus className="w-3 h-3" /> Add
          </button>
        </div>
      </div>
      <button
        onClick={() => setExpanded((v) => !v)}
        className="flex items-center gap-1 text-[10px] text-slate-400 hover:text-slate-600 transition-colors"
      >
        {expanded ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
        {expanded ? "Hide bullets" : `${project.bullets.length} bullet${project.bullets.length !== 1 ? "s" : ""}`}
      </button>
      {expanded && (
        <ul className="space-y-0.5 pl-1">
          {project.bullets.map((b, i) => (
            <li key={i} className="text-[10px] text-slate-600 flex gap-1.5">
              <span className="text-slate-400 shrink-0">•</span>
              <span>{b}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function CopilotChat({
  resumeId,
  jdText,
  apiUrl,
  approved,
  keptProjects,
  nextSuggestionId,
  focus,
  onClearFocus,
  onAcceptSuggestion,
  onResult,
  onClose,
  pendingProjects = [],
  onKeepProject,
  onSkipProject,
}: CopilotChatProps) {
  const CHAT_STORAGE_KEY = resumeId ? `copilot_chat_${resumeId}` : null;
  const DECIDED_STORAGE_KEY = resumeId ? `copilot_decided_${resumeId}` : null;

  const [messages, setMessages] = useState<Message[]>(() => {
    if (typeof window !== "undefined" && resumeId) {
      const key = `copilot_chat_${resumeId}`;
      const saved = sessionStorage.getItem(key);
      if (saved) {
        try {
          const parsed = JSON.parse(saved) as Message[];
          // Re-hydrate timestamp strings back to Date objects
          return parsed.map((m) => ({ ...m, timestamp: new Date(m.timestamp) }));
        } catch { /* ignore */ }
      }
    }
    return [
      {
        id: "initial",
        sender: "copilot",
        text: "Hi! I'm your tailoring copilot. Tell me what to change — e.g. \"tailor my experience to this JD\" — or click the ✦ wand on any line to edit it here. I'll propose changes for you to review and accept.",
        timestamp: new Date(),
      },
    ];
  });
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [decided, setDecided] = useState<Record<number, "accepted" | "rejected">>(() => {
    if (typeof window !== "undefined" && resumeId) {
      const saved = sessionStorage.getItem(`copilot_decided_${resumeId}`);
      if (saved) {
        try { return JSON.parse(saved); } catch { /* ignore */ }
      }
    }
    return {};
  });
  const messagesEndRef = useRef<HTMLDivElement>(null);

  // Persist messages + decided state to sessionStorage whenever they change
  useEffect(() => {
    if (!CHAT_STORAGE_KEY) return;
    sessionStorage.setItem(CHAT_STORAGE_KEY, JSON.stringify(messages));
  }, [messages, CHAT_STORAGE_KEY]);

  useEffect(() => {
    if (!DECIDED_STORAGE_KEY) return;
    sessionStorage.setItem(DECIDED_STORAGE_KEY, JSON.stringify(decided));
  }, [decided, DECIDED_STORAGE_KEY]);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isLoading]);

  const mapAccepted = (list: Suggestion[]) =>
    list.map((s) => ({
      id: s.id, section: s.section, mode: s.mode,
      original: s.original, suggested: s.suggested,
      category: s.category, skill: s.skill,
      target_category: s.target_category, is_new_category: s.is_new_category,
      new_skills: s.new_skills,
    }));

  const handleSendMessage = async (textToSend: string) => {
    if (!textToSend.trim() || !resumeId || isLoading) return;
    const activeFocus = focus;

    const focusEcho = activeFocus
      ? activeFocus.targetType === "line"
        ? `(on "${(activeFocus.original || "").slice(0, 48)}…") `
        : activeFocus.targetType === "entry"
        ? `(on ${activeFocus.label || "entry"}) `
        : `(on ${activeFocus.section} section) `
      : "";
    const userMessage: Message = {
      id: Math.random().toString(),
      sender: "user",
      text: `${focusEcho}${textToSend}`,
      timestamp: new Date(),
    };
    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);

    let intensity = "balanced";
    let sectionIntensities: Record<string, string> | null = null;
    if (typeof window !== "undefined") {
      intensity = localStorage.getItem("tailor_intensity") || "balanced";
      const saved = localStorage.getItem("tailor_section_intensities");
      if (saved) {
        try {
          sectionIntensities = JSON.parse(saved);
        } catch {
          /* ignore malformed storage */
        }
      }
    }

    try {
      const response = await fetch(`${apiUrl}/api/tailor/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          resume_id: resumeId,
          jd_text: jdText,
          user_prompt: textToSend,
          focus: activeFocus
            ? {
                section: activeFocus.section,
                target_type: activeFocus.targetType,
                ...(activeFocus.original ? { original: activeFocus.original } : {}),
                ...(activeFocus.entryIndex != null ? { entry_index: activeFocus.entryIndex } : {}),
              }
            : null,
          accepted_suggestions: mapAccepted(approved),
          new_projects: keptProjects && keptProjects.length > 0 ? keptProjects : undefined,
          next_id: nextSuggestionId,
          intensity,
          section_intensities: sectionIntensities,
        }),
      });
      if (!response.ok) {
        const errorData = await response.json().catch(() => ({}));
        throw new Error(errorData.detail || "Failed to communicate with Copilot.");
      }
      const data = await response.json();
      const suggestions: Suggestion[] = data.suggestions || [];
      const directives: { type: string }[] = data.directives || [];

      onResult(suggestions, directives);

      setMessages((prev) => [
        ...prev,
        {
          id: Math.random().toString(),
          sender: "copilot",
          text: data.response || "Done.",
          suggestions: suggestions.length > 0 ? suggestions : undefined,
          timestamp: new Date(),
        },
      ]);
    } catch (error) {
      setMessages((prev) => [
        ...prev,
        {
          id: Math.random().toString(),
          sender: "copilot",
          text: error instanceof Error ? error.message : "Sorry, I hit an error. Try again.",
          timestamp: new Date(),
        },
      ]);
    } finally {
      if (activeFocus) onClearFocus();
      setIsLoading(false);
    }
  };

  const accept = (s: Suggestion) => {
    onAcceptSuggestion(s);
    setDecided((prev) => ({ ...prev, [s.id]: "accepted" }));
  };
  const reject = (id: number) => setDecided((prev) => ({ ...prev, [id]: "rejected" }));
  const acceptAll = (suggestions: Suggestion[]) => {
    for (const s of suggestions) {
      if (!decided[s.id]) accept(s);
    }
  };

  return (
    <div className="flex flex-col h-full bg-white border border-slate-200 rounded-xl overflow-hidden shadow-lg shadow-blue-500/5">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 bg-gradient-to-r from-blue-600 to-indigo-600 text-white">
        <div className="flex items-center gap-2.5">
          <div className="relative flex items-center justify-center w-8 h-8 rounded-full bg-white/10 text-white border border-white/20 shadow-md">
            <Bot className="w-4 h-4" />
            <span className="absolute bottom-0 right-0 w-2 h-2 bg-emerald-500 rounded-full border border-white" />
          </div>
          <h2 className="text-sm font-bold tracking-tight text-white">AI Tailoring Copilot</h2>
        </div>
        {onClose && (
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-white/10 text-white/80 hover:text-white transition-colors cursor-pointer"
            title="Close Chat"
          >
            <X className="w-4 h-4" />
          </button>
        )}
      </div>

      {/* Message Area */}
      <div className="flex-1 overflow-y-auto p-4 space-y-4 scrollbar-thin bg-white">
        {messages.map((msg) => (
          <div key={msg.id} className="space-y-2">
            <div
              className={`flex gap-3 max-w-[85%] ${
                msg.sender === "user" ? "ml-auto flex-row-reverse" : "mr-auto"
              }`}
            >
              <div
                className={`flex items-center justify-center w-7 h-7 rounded-full flex-shrink-0 shadow-sm ${
                  msg.sender === "user"
                    ? "bg-slate-100 text-slate-600"
                    : "bg-gradient-to-tr from-blue-500 to-indigo-600 text-white"
                }`}
              >
                {msg.sender === "user" ? <User className="w-3.5 h-3.5" /> : <Bot className="w-3.5 h-3.5" />}
              </div>
              <div
                className={`px-3.5 py-2 rounded-2xl text-xs leading-relaxed ${
                  msg.sender === "user"
                    ? "bg-gradient-to-r from-blue-600 to-indigo-600 text-white rounded-tr-none shadow-md shadow-blue-500/10 font-medium"
                    : "bg-slate-50 border border-slate-100 text-slate-800 rounded-tl-none shadow-sm"
                }`}
              >
                {msg.text}
              </div>
            </div>

            {/* In-chat review of proposed changes */}
            {msg.suggestions && msg.suggestions.length > 0 && (
              <div className="ml-10 space-y-1.5">
                {msg.suggestions.map((s) => {
                  const state = decided[s.id];
                  const { title, body } = describeSuggestion(s);
                  return (
                    <div
                      key={s.id}
                      className={`rounded-lg border px-2.5 py-2 text-[11px] transition-colors ${
                        state === "accepted"
                          ? "border-success/40 bg-success/5"
                          : state === "rejected"
                          ? "border-border bg-slate-50 opacity-50"
                          : "border-blue-100 bg-blue-50/40"
                      }`}
                    >
                      <p className="font-semibold text-slate-700 mb-1">{title}</p>
                      {body && <div className="text-slate-600 leading-relaxed mb-1.5">{body}</div>}
                      {!state && (
                        <div className="flex items-center justify-end gap-1.5">
                          <button
                            onClick={() => reject(s.id)}
                            className="px-2 py-0.5 rounded text-[10px] text-muted hover:text-foreground hover:bg-slate-100 transition-colors"
                          >
                            Reject
                          </button>
                          <button
                            onClick={() => accept(s)}
                            className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[10px] font-semibold text-white bg-blue-600 hover:bg-blue-500 transition-colors"
                          >
                            <Check className="w-3 h-3" /> Accept
                          </button>
                        </div>
                      )}
                      {state === "accepted" && (
                        <p className="text-[10px] text-success font-medium flex items-center gap-1 justify-end">
                          <Check className="w-3 h-3" /> Applied
                        </p>
                      )}
                    </div>
                  );
                })}
                {msg.suggestions.some((s) => !decided[s.id]) && (
                  <button
                    onClick={() => acceptAll(msg.suggestions!)}
                    className="text-[10px] font-semibold text-blue-700 hover:text-blue-900 transition-colors"
                  >
                    Accept all
                  </button>
                )}
              </div>
            )}
          </div>
        ))}
        {isLoading && (
          <div className="flex gap-3 max-w-[80%] mr-auto items-center">
            <div className="flex items-center justify-center w-7 h-7 rounded-full bg-gradient-to-tr from-blue-500 to-indigo-600 text-white flex-shrink-0 shadow-sm animate-pulse">
              <Bot className="w-3.5 h-3.5" />
            </div>
            <div className="flex items-center gap-2 px-3.5 py-2 rounded-2xl bg-slate-50 border border-slate-100 text-xs text-slate-500 rounded-tl-none shadow-sm animate-pulse">
              <Loader2 className="w-3 h-3 animate-spin text-blue-500" />
              <span>Working on it…</span>
            </div>
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>

      {/* Preset Pills */}
      {messages.length === 1 && !isLoading && !focus && (
        <div className="px-4 py-2.5 flex flex-wrap gap-2 border-t border-slate-100 bg-white">
          {PRESET_PILLS.map((pill, idx) => {
            const Icon = pill.icon;
            return (
              <button
                key={idx}
                onClick={() => handleSendMessage(pill.text)}
                className="inline-flex items-center gap-1.5 px-3 py-1 rounded-full border border-blue-100 bg-blue-50/50 hover:bg-blue-100/60 text-[10px] font-semibold text-blue-700 transition-all cursor-pointer hover:-translate-y-0.5 active:translate-y-0 shadow-sm"
              >
                <Icon className="w-3 h-3 text-blue-500" />
                {pill.text}
              </button>
            );
          })}
        </div>
      )}

      {/* Focus chip */}
      {focus && (
        <div className="px-3 pt-2 bg-white">
          <div className="flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50/60 px-2.5 py-1.5">
            <Wand2 className="w-3.5 h-3.5 text-blue-600 mt-0.5 shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="text-[10px] font-semibold uppercase tracking-wider text-blue-700">
                {focus.targetType === "section"
                  ? `Tailoring the ${focus.section} section`
                  : focus.targetType === "entry"
                  ? `Editing entry`
                  : `Editing this ${focus.section} line`}
              </p>
              {(focus.targetType === "line" ? focus.original : focus.label) && (
                <p className="text-[11px] text-slate-600 truncate" title={focus.targetType === "line" ? focus.original : focus.label}>
                  {focus.targetType === "line" ? focus.original : focus.label}
                </p>
              )}
            </div>
            <button
              onClick={onClearFocus}
              className="p-0.5 rounded hover:bg-blue-100 text-blue-500 shrink-0"
              title="Clear focus"
            >
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Pending project review cards */}
      {pendingProjects.length > 0 && (
        <div className="px-3 pb-2 space-y-2 bg-white border-t border-slate-100 pt-2">
          <p className="text-[10px] font-semibold uppercase tracking-wider text-emerald-700 flex items-center gap-1">
            <FolderPlus className="w-3 h-3" />
            {pendingProjects.length} project{pendingProjects.length !== 1 ? "s" : ""} to review
          </p>
          {pendingProjects.map((proj) => (
            <ChatProjectCard
              key={proj.name}
              project={proj}
              onKeep={() => onKeepProject?.(proj)}
              onSkip={() => onSkipProject?.(proj.name)}
            />
          ))}
        </div>
      )}

      {/* Input Form */}
      <div className="p-3 border-t border-slate-100 bg-white">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            handleSendMessage(input);
          }}
          className="flex items-center gap-2"
        >
          <input
            type="text"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            disabled={isLoading}
            placeholder={
              !resumeId
                ? "Awaiting resume load…"
                : focus
                ? "What should I change about this line?"
                : "Instruct the copilot to tailor your resume…"
            }
            className="flex-1 min-w-0 bg-white border border-slate-200 focus:border-blue-500 focus:ring-4 focus:ring-blue-500/10 rounded-lg px-3 py-2 text-xs transition-all disabled:opacity-50 text-slate-800 outline-none"
          />
          <button
            type="submit"
            disabled={isLoading || !input.trim() || !resumeId}
            className="flex-shrink-0 flex items-center justify-center w-8 h-8 rounded-lg bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-medium disabled:opacity-50 transition-all shadow-md shadow-blue-500/10 hover:shadow-lg hover:shadow-blue-500/20 active:scale-95 cursor-pointer"
            aria-label="Send"
          >
            <Send className="w-3.5 h-3.5" />
          </button>
        </form>
      </div>
    </div>
  );
}
