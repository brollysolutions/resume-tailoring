"use client";

import { useRef } from "react";

type TabOption<T extends string> = {
  value: T;
  label: string;
  count?: number;
};

export function Tabs<T extends string>({
  value,
  onChange,
  options,
  className = "",
  panelIdPrefix,
}: {
  value: T;
  onChange: (v: T) => void;
  options: readonly TabOption<T>[];
  className?: string;
  /** Optional prefix to wire aria-controls to a sibling tabpanel (`${prefix}-${value}`). */
  panelIdPrefix?: string;
}) {
  const refs = useRef<Record<string, HTMLButtonElement | null>>({});

  const focusByIndex = (idx: number) => {
    const wrapped = (idx + options.length) % options.length;
    const opt = options[wrapped];
    if (!opt) return;
    onChange(opt.value);
    refs.current[opt.value]?.focus();
  };

  const onKeyDown = (e: React.KeyboardEvent, currentIdx: number) => {
    if (e.key === "ArrowRight") { e.preventDefault(); focusByIndex(currentIdx + 1); }
    else if (e.key === "ArrowLeft") { e.preventDefault(); focusByIndex(currentIdx - 1); }
    else if (e.key === "Home") { e.preventDefault(); focusByIndex(0); }
    else if (e.key === "End") { e.preventDefault(); focusByIndex(options.length - 1); }
  };

  return (
    <div
      role="tablist"
      className={`inline-flex rounded-lg border border-border bg-subtle/40 p-0.5 gap-0.5 ${className}`}
    >
      {options.map((opt, idx) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            ref={(el) => { refs.current[opt.value] = el; }}
            role="tab"
            id={panelIdPrefix ? `${panelIdPrefix}-tab-${opt.value}` : undefined}
            aria-selected={active}
            aria-controls={panelIdPrefix ? `${panelIdPrefix}-${opt.value}` : undefined}
            tabIndex={active ? 0 : -1}
            onClick={() => onChange(opt.value)}
            onKeyDown={(e) => onKeyDown(e, idx)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              active
                ? "bg-background text-foreground shadow-sm"
                : "text-muted hover:text-foreground"
            }`}
          >
            {opt.label}
            {opt.count !== undefined && (
              <span
                className={`ml-1.5 inline-flex items-center justify-center min-w-[16px] h-[16px] px-1 rounded text-[9px] tabular-nums ${
                  active ? "bg-foreground/10 text-foreground" : "bg-muted/20 text-muted"
                }`}
              >
                {opt.count}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
