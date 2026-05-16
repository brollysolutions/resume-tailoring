"use client";

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
}: {
  value: T;
  onChange: (v: T) => void;
  options: readonly TabOption<T>[];
  className?: string;
}) {
  return (
    <div
      role="tablist"
      className={`inline-flex rounded-lg border border-border bg-subtle/40 p-0.5 gap-0.5 ${className}`}
    >
      {options.map((opt) => {
        const active = value === opt.value;
        return (
          <button
            key={opt.value}
            role="tab"
            aria-selected={active}
            onClick={() => onChange(opt.value)}
            className={`px-3 py-1.5 text-xs font-medium rounded-md transition-colors ${
              active
                ? "bg-background text-foreground shadow-sm"
                : "text-muted hover:text-foreground"
            }`}
          >
            {opt.label}
            {opt.count !== undefined && opt.count > 0 && (
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
