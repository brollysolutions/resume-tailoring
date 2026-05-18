"use client";

import { useState, useEffect, useCallback } from "react";
import { useRouter } from "next/navigation";
import { ArrowUp, ArrowDown, Save, ArrowLeft, Eye, EyeOff, Loader2 } from "lucide-react";

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

export default function SectionsPage() {
  const router = useRouter();
  const [resumeId, setResumeId] = useState<string | null>(null);
  const [order, setOrder] = useState<string[]>([]);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";

  const buildOrderFromResume = useCallback((r: ResumeShape): string[] => {
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
  }, []);

  useEffect(() => {
    const rid = sessionStorage.getItem("current_resume_id");
    if (!rid) {
      router.push("/");
      return;
    }
    setResumeId(rid);
    (async () => {
      try {
        const res = await fetch(`${apiUrl}/api/resume/${rid}/json`);
        if (!res.ok) throw new Error("Failed to load resume");
        const r: ResumeShape = await res.json();
        setOrder(buildOrderFromResume(r));
        setHidden(new Set(r.hidden_sections || []));
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to load");
      } finally {
        setLoading(false);
      }
    })();
  }, [apiUrl, router, buildOrderFromResume]);

  const moveSection = (idx: number, delta: number) => {
    const target = idx + delta;
    if (target < 0 || target >= order.length) return;
    const next = [...order];
    [next[idx], next[target]] = [next[target], next[idx]];
    setOrder(next);
  };

  const toggleHide = (key: string) => {
    const next = new Set(hidden);
    if (next.has(key)) next.delete(key);
    else next.add(key);
    setHidden(next);
  };

  const onSave = async () => {
    if (!resumeId) return;
    setSaving(true);
    setError(null);
    try {
      const res = await fetch(`${apiUrl}/api/resume/${resumeId}/sections`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          section_order: order,
          hidden_sections: Array.from(hidden),
        }),
      });
      if (!res.ok) throw new Error("Save failed");
      router.push("/job-search");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="w-full max-w-2xl mx-auto px-6 py-20 flex items-center justify-center">
        <Loader2 className="w-5 h-5 animate-spin text-muted" />
      </div>
    );
  }

  return (
    <div className="w-full max-w-2xl mx-auto px-6 py-12">
      <button
        onClick={() => router.back()}
        className="text-sm text-muted hover:text-foreground mb-6 flex items-center gap-1"
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        Back
      </button>

      <h1 className="text-2xl font-semibold tracking-tight mb-2">Manage sections</h1>
      <p className="text-muted text-sm mb-8">
        Reorder sections with arrows. Hide ones you don&apos;t want to appear in the rendered resume.
      </p>

      {error && (
        <div className="card p-3 mb-4 border-danger/30 bg-danger/5">
          <p className="text-xs text-danger">{error}</p>
        </div>
      )}

      <div className="card divide-y divide-border mb-6">
        {order.map((key, i) => {
          const isHidden = hidden.has(key);
          return (
            <div
              key={key}
              className={`flex items-center justify-between px-4 py-3 ${isHidden ? "opacity-50" : ""}`}
            >
              <div className="flex items-center gap-3 min-w-0">
                <div className="flex flex-col gap-0.5 shrink-0">
                  <button
                    onClick={() => moveSection(i, -1)}
                    disabled={i === 0}
                    className="text-muted hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed"
                    aria-label="Move up"
                  >
                    <ArrowUp className="w-3.5 h-3.5" />
                  </button>
                  <button
                    onClick={() => moveSection(i, 1)}
                    disabled={i === order.length - 1}
                    className="text-muted hover:text-foreground disabled:opacity-30 disabled:cursor-not-allowed"
                    aria-label="Move down"
                  >
                    <ArrowDown className="w-3.5 h-3.5" />
                  </button>
                </div>
                <span className="text-sm font-medium truncate">{sectionLabel(key)}</span>
              </div>
              <button
                onClick={() => toggleHide(key)}
                className="btn-ghost p-2"
                aria-label={isHidden ? "Show section" : "Hide section"}
                title={isHidden ? "Show section" : "Hide section"}
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

      <div className="flex items-center justify-end gap-3">
        <button onClick={() => router.back()} className="btn-secondary text-sm">
          Cancel
        </button>
        <button onClick={onSave} disabled={saving} className="btn-primary text-sm">
          {saving ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              Saving…
            </>
          ) : (
            <>
              <Save className="w-4 h-4" />
              Save changes
            </>
          )}
        </button>
      </div>
    </div>
  );
}
