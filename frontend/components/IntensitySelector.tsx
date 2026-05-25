"use client";

import { useState } from "react";

type Intensity = "light" | "balanced" | "aggressive";

const LEVELS: { key: Intensity; label: string; title: string }[] = [
  { key: "light", label: "Light", title: "Light — minimal changes, strict guardrails" },
  { key: "balanced", label: "Balanced", title: "Balanced — moderate tailoring" },
  { key: "aggressive", label: "Aggressive", title: "Aggressive — heavy rewrite, inject every honestly-claimable keyword" },
];

function isIntensity(v: unknown): v is Intensity {
  return v === "light" || v === "balanced" || v === "aggressive";
}

function readSectionIntensity(sectionKey: string): Intensity {
  if (typeof window === "undefined") return "balanced";
  try {
    const raw = localStorage.getItem("tailor_section_intensities");
    if (raw) {
      const dict = JSON.parse(raw);
      const v = dict?.[sectionKey];
      if (isIntensity(v)) return v;
    }
  } catch {
    /* ignore malformed storage */
  }
  const g = localStorage.getItem("tailor_intensity");
  return isIntensity(g) ? g : "balanced";
}

function writeSectionIntensity(sectionKey: string, value: Intensity) {
  if (typeof window === "undefined") return;
  let dict: Record<string, string> = {};
  try {
    const raw = localStorage.getItem("tailor_section_intensities");
    if (raw) dict = JSON.parse(raw) || {};
  } catch {
    dict = {};
  }
  dict[sectionKey] = value;
  localStorage.setItem("tailor_section_intensities", JSON.stringify(dict));
}

/** Per-section tailoring intensity. Persists to localStorage("tailor_section_intensities")
 *  keyed by lowercase section name; the Skills + Copilot tailoring paths read it at call time. */
export function IntensitySelector({ sectionKey }: { sectionKey: string }) {
  // Lazy init reads localStorage on first client render; returns "balanced" on the
  // server. Safe here because /tailor loads the resume client-side, so this control
  // is never server-rendered (no hydration mismatch).
  const [value, setValue] = useState<Intensity>(() => readSectionIntensity(sectionKey));

  const pick = (v: Intensity) => {
    setValue(v);
    writeSectionIntensity(sectionKey, v);
  };

  return (
    <div
      className="inline-flex items-center rounded-md border border-border bg-subtle/60 p-0.5"
      title="How hard the AI tailors this section"
    >
      {LEVELS.map((lvl) => (
        <button
          key={lvl.key}
          type="button"
          onClick={(e) => {
            e.stopPropagation();
            pick(lvl.key);
          }}
          title={lvl.title}
          className={`px-1.5 py-0.5 rounded text-[10px] font-medium transition-colors ${
            value === lvl.key
              ? "bg-accent text-white shadow-sm"
              : "text-muted hover:text-foreground"
          }`}
        >
          {lvl.label}
        </button>
      ))}
    </div>
  );
}
