"use client";

import { useState } from "react";
import { Info } from "lucide-react";
import { motion, AnimatePresence } from "framer-motion";

type Intensity = "light" | "balanced" | "aggressive";

const LEVELS: { key: Intensity; label: string; title: string; description: string }[] = [
  {
    key: "light",
    label: "L",
    title: "Light — minimal changes",
    description: "Fixes grammar, tense, and clarity only. Preserves your original structure and avoids adding new claims."
  },
  {
    key: "balanced",
    label: "B",
    title: "Balanced — moderate tailoring",
    description: "Rephrases bullets to surface relevant work and weaves in missing keywords where honestly supported."
  },
  {
    key: "aggressive",
    label: "A",
    title: "Aggressive — heavy rewrite",
    description: "Deeply rewrites bullets to lead with the JD angle and injects every claimable keyword for maximum match."
  },
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
  const [value, setValue] = useState<Intensity>(() => readSectionIntensity(sectionKey));
  const [showHelp, setShowHelp] = useState(false);

  const pick = (v: Intensity) => {
    setValue(v);
    writeSectionIntensity(sectionKey, v);
  };

  return (
    <div className="flex items-center gap-1.5">
      <div
        className="inline-flex items-center rounded-md border border-border bg-subtle/60 p-0.5"
        title="Set tailoring intensity for this section"
      >
        {LEVELS.map((lvl) => (
          <button
            key={lvl.key}
            type="button"
            title={lvl.title}
            onClick={(e) => {
              e.stopPropagation();
              pick(lvl.key);
            }}
            className={`w-5 py-0.5 rounded text-[10px] font-bold transition-colors ${
              value === lvl.key
                ? "bg-accent text-white shadow-sm"
                : "text-muted hover:text-foreground"
            }`}
          >
            {lvl.label}
          </button>
        ))}
      </div>
      
      <div className="relative">
        <button
          type="button"
          onMouseEnter={() => setShowHelp(true)}
          onMouseLeave={() => setShowHelp(false)}
          onClick={(e) => {
            e.stopPropagation();
            setShowHelp(!showHelp);
          }}
          className="p-1 rounded-full text-muted hover:text-foreground hover:bg-subtle transition-colors"
          aria-label="Tailoring intensity info"
        >
          <Info className="w-3 h-3" />
        </button>

        <AnimatePresence>
          {showHelp && (
            <motion.div 
              initial={{ opacity: 0, y: 4, scale: 0.95 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: 4, scale: 0.95 }}
              transition={{ duration: 0.15, ease: "easeOut" }}
              className="absolute right-0 bottom-full mb-2 w-64 p-3 bg-card border border-border rounded-lg shadow-xl z-50 pointer-events-none"
            >
              <h4 className="text-[11px] font-bold mb-2 uppercase tracking-wider text-foreground border-b border-border pb-1.5">Tailoring Strength</h4>
              <div className="space-y-3 pt-1">
                {LEVELS.map((lvl) => (
                  <div key={lvl.key} className={value === lvl.key ? "opacity-100" : "opacity-75"}>
                    <p className="text-[10px] font-bold flex items-center gap-1.5 text-foreground">
                      <span
                        aria-hidden="true"
                        className={`inline-flex items-center justify-center w-4 h-4 rounded-full border text-[8px] font-bold uppercase tracking-tight ${
                          lvl.key === 'light'
                            ? 'bg-sky-100 text-sky-800 border-sky-300'
                            : lvl.key === 'balanced'
                            ? 'bg-amber-100 text-amber-800 border-amber-300'
                            : 'bg-rose-100 text-rose-800 border-rose-400'
                        }`}
                      >
                        {lvl.label}
                      </span>
                      <span>{lvl.title.split('—')[0].trim()}</span>
                    </p>
                    <p className="text-[10px] text-muted leading-relaxed mt-1 ml-5">
                      {lvl.description}
                    </p>
                  </div>
                ))}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
