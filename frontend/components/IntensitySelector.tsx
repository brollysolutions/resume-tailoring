"use client";

import { useState, useRef, useEffect } from "react";
import { X, Zap } from "lucide-react";

type Intensity = "light" | "balanced" | "aggressive";

const LEVELS: { key: Intensity; label: string; short: string }[] = [
  { key: "light", label: "Light", short: "L" },
  { key: "balanced", label: "Balanced", short: "B" },
  { key: "aggressive", label: "Aggressive", short: "A" },
];

function isIntensity(v: unknown): v is Intensity {
  return v === "light" || v === "balanced" || v === "aggressive";
}

function readGlobalIntensity(): Intensity {
  if (typeof window === "undefined") return "balanced";
  const g = localStorage.getItem("tailor_intensity");
  return isIntensity(g) ? g : "balanced";
}

function writeGlobalIntensity(v: Intensity) {
  if (typeof window === "undefined") return;
  localStorage.setItem("tailor_intensity", v);
  window.dispatchEvent(new CustomEvent("globalIntensityChange", { detail: v }));
}

function readSectionSpecific(sectionKey: string): Intensity | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem("tailor_section_intensities");
    if (raw) {
      const dict = JSON.parse(raw);
      const v = dict?.[sectionKey];
      if (isIntensity(v)) return v;
    }
  } catch { /* ignore */ }
  return null;
}

function writeSectionIntensity(sectionKey: string, value: Intensity) {
  if (typeof window === "undefined") return;
  let dict: Record<string, string> = {};
  try {
    const raw = localStorage.getItem("tailor_section_intensities");
    if (raw) dict = JSON.parse(raw) || {};
  } catch { dict = {}; }
  dict[sectionKey] = value;
  localStorage.setItem("tailor_section_intensities", JSON.stringify(dict));
}

function deleteSectionIntensity(sectionKey: string) {
  if (typeof window === "undefined") return;
  try {
    const raw = localStorage.getItem("tailor_section_intensities");
    if (!raw) return;
    const dict = JSON.parse(raw) || {};
    delete dict[sectionKey];
    localStorage.setItem("tailor_section_intensities", JSON.stringify(dict));
  } catch { /* ignore */ }
}

/** Global intensity control — place once in the tailor toolbar. */
export function GlobalIntensitySelector() {
  const [mounted, setMounted] = useState(false);
  const [value, setValue] = useState<Intensity>("balanced");

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect */
    setMounted(true);
    setValue(readGlobalIntensity());
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  const pick = (v: Intensity) => {
    setValue(v);
    writeGlobalIntensity(v);
  };

  if (!mounted) {
    return (
      <div className="flex items-center gap-1.5 opacity-0">
        <span className="text-[10px] text-muted uppercase tracking-wider font-medium select-none">Intensity</span>
        <div className="inline-flex items-center rounded-md border border-border bg-subtle/60 p-0.5">
          {LEVELS.map((lvl) => (
            <div key={lvl.key} className="px-2 py-0.5 rounded text-[10px] font-bold">
              {lvl.short}
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[10px] text-muted uppercase tracking-wider font-medium select-none">Intensity</span>
      <div className="inline-flex items-center rounded-md border border-border bg-subtle/60 p-0.5">
        {LEVELS.map((lvl) => (
          <button
            key={lvl.key}
            type="button"
            title={lvl.label}
            onClick={() => pick(lvl.key)}
            className={`px-2 py-0.5 rounded text-[10px] font-bold transition-colors ${
              value === lvl.key
                ? "bg-accent text-white shadow-sm"
                : "text-muted hover:text-foreground"
            }`}
          >
            {lvl.short}
          </button>
        ))}
      </div>
    </div>
  );
}

/** Per-section intensity override indicator.
 *  Hidden by default (reveals on group-hover of section header); always visible when overriding global. */
export function IntensitySelector({ sectionKey }: { sectionKey: string }) {
  const [mounted, setMounted] = useState(false);
  const [globalVal, setGlobalVal] = useState<Intensity>("balanced");
  const [sectionVal, setSectionVal] = useState<Intensity | null>(null);
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    /* eslint-disable react-hooks/set-state-in-effect */
    setMounted(true);
    setGlobalVal(readGlobalIntensity());
    setSectionVal(readSectionSpecific(sectionKey));
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [sectionKey]);

  const effectiveVal = sectionVal ?? globalVal;
  const isOverridden = sectionVal !== null;

  useEffect(() => {
    const handler = (e: Event) => {
      const v = (e as CustomEvent<Intensity>).detail;
      if (isIntensity(v)) setGlobalVal(v);
    };
    window.addEventListener("globalIntensityChange", handler);
    return () => window.removeEventListener("globalIntensityChange", handler);
  }, []);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const pickOverride = (v: Intensity) => {
    if (v === globalVal) {
      deleteSectionIntensity(sectionKey);
      setSectionVal(null);
    } else {
      writeSectionIntensity(sectionKey, v);
      setSectionVal(v);
    }
    setOpen(false);
  };

  const reset = (e: React.MouseEvent) => {
    e.stopPropagation();
    deleteSectionIntensity(sectionKey);
    setSectionVal(null);
    setOpen(false);
  };

  if (!mounted) return null;

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={(e) => { e.stopPropagation(); setOpen((v) => !v); }}
        className={`inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] border transition-all duration-150 ${
          isOverridden
            ? "opacity-100 border-border/80 bg-background text-foreground"
            : "opacity-100 border-border/60 bg-background text-muted hover:text-foreground hover:border-border"
        }`}
        title={`Section intensity: ${effectiveVal}${isOverridden ? " (overrides global)" : " (inherits global)"}`}
      >
        <Zap className={`w-2.5 h-2.5 shrink-0 ${isOverridden ? "text-accent" : ""}`} />
        <span className="capitalize">{effectiveVal}</span>
        {isOverridden && (
          <X
            className="w-2.5 h-2.5 ml-0.5 text-muted hover:text-foreground shrink-0"
            onClick={reset}
          />
        )}
      </button>

      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-card border border-border rounded-lg shadow-lg p-1.5 min-w-[120px]">
          {LEVELS.map((lvl) => (
            <button
              key={lvl.key}
              type="button"
              onClick={(e) => { e.stopPropagation(); pickOverride(lvl.key); }}
              className={`w-full text-left px-2 py-1 rounded text-[11px] transition-colors flex items-center justify-between gap-2 ${
                effectiveVal === lvl.key
                  ? "bg-accent/10 text-foreground font-semibold"
                  : "text-muted hover:bg-subtle hover:text-foreground"
              }`}
            >
              <span>{lvl.label}</span>
              {lvl.key === globalVal && (
                <span className="text-[9px] text-muted/60">global</span>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
