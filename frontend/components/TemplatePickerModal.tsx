"use client";

import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { TemplatePreview } from "./TemplatePreview";

export type Template = { id: string; name: string; description: string };

interface TemplatePickerModalProps {
  templates: Template[];
  loading: boolean;
  error: string | null;
  onClose: () => void;
  onApply: (templateId: string) => void;
}

export function TemplatePickerModal({
  templates,
  loading,
  error,
  onClose,
  onApply,
}: TemplatePickerModalProps) {
  const [manualSelection, setManualSelection] = useState<string | null>(null);
  const selected = manualSelection ?? templates[0]?.id ?? null;
  const [previews, setPreviews] = useState<Record<string, string | null>>({});
  const [previewsLoading, setPreviewsLoading] = useState(true);

  useEffect(() => {
    if (!templates.length) return;
    setPreviewsLoading(true);
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
    Promise.all(
      templates.map((t) =>
        fetch(`${apiUrl}/api/tailor/sample-preview?template_id=${t.id}`)
          .then((r) => r.json())
          .then((d) => [t.id, d.html as string] as const)
          .catch(() => [t.id, null] as const)
      )
    ).then((results) => {
      setPreviews(Object.fromEntries(results));
      setPreviewsLoading(false);
    });
  }, [templates]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />
      <div className="relative z-50 w-[95vw] h-[94vh] max-w-[90vw] card shadow-xl flex flex-col overflow-hidden">
        <button
          onClick={onClose}
          aria-label="Close"
          className="absolute top-4 right-4 btn-ghost p-2 z-10"
        >
          <X className="w-4 h-4" />
        </button>

        <div className="px-8 pt-8 pb-4 border-b border-border">
          <h2 className="text-2xl font-semibold tracking-tight mb-2">
            Choose a template
          </h2>
          <p className="text-sm text-muted leading-relaxed">
            Pick a layout for your resume. You can change it later.
          </p>
        </div>

        <div className="flex-1 overflow-y-auto px-8 py-6 scrollbar-thin">
          {error && <p className="text-xs text-danger mb-4">{error}</p>}
          {loading && (
            <div className="grid grid-cols-2 gap-6 animate-pulse">
              {[1, 2].map((i) => (
                <div key={i} className="rounded-lg border border-border p-4 space-y-4">
                  <div className="space-y-2">
                    <div className="h-4 bg-muted/60 rounded w-1/3" />
                    <div className="h-3 bg-muted/50 rounded w-2/3" />
                  </div>
                  <div className="aspect-[8.5/11] border border-border/40 rounded bg-muted/20" />
                </div>
              ))}
            </div>
          )}
          {!loading && templates.length > 0 && (
            <div className="grid grid-cols-2 gap-6">
              {templates.map((t) => {
                const active = selected === t.id;
                return (
                  <button
                    key={t.id}
                    onClick={() => setManualSelection(t.id)}
                    className={`text-left rounded-lg border p-4 transition-all ${
                      active
                        ? "bg-blue-50 border-blue-500 shadow-md"
                        : "bg-card border-border hover:border-foreground/40 hover:shadow-md"
                    }`}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <p className="text-sm font-semibold">{t.name}</p>
                      {t.id === "standard" && (
                        <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 border border-blue-200">
                          Default
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-muted leading-relaxed mb-4">
                      {t.description}
                    </p>
                    <div className="aspect-[8.5/11] max-h-[800px] border border-border rounded overflow-hidden bg-white">
                      {previewsLoading || previews[t.id] === undefined ? (
                        <div className="w-full h-full p-6 space-y-4 animate-pulse bg-white select-none">
                          <div className="space-y-1.5">
                            <div className="h-3 bg-muted/60 rounded w-1/3 mx-auto" />
                            <div className="h-2 bg-muted/50 rounded w-1/2 mx-auto" />
                          </div>
                          <div className="h-2 bg-muted/40 rounded w-3/4 mx-auto" />
                          <hr className="border-border/40" />
                          <div className="space-y-1.5">
                            <div className="h-2 bg-muted/60 rounded w-1/4" />
                            <div className="h-1.5 bg-muted/30 rounded w-full" />
                            <div className="h-1.5 bg-muted/30 rounded w-5/6" />
                          </div>
                          <div className="space-y-2 pt-2">
                            <div className="h-2 bg-muted/60 rounded w-1/4" />
                            <div className="h-1.5 bg-muted/30 rounded w-11/12" />
                            <div className="h-1.5 bg-muted/30 rounded w-full" />
                          </div>
                        </div>
                      ) : previews[t.id] ? (
                        <TemplatePreview html={previews[t.id]} />
                      ) : (
                        <div className="w-full h-full flex items-center justify-center bg-subtle">
                          <span className="text-[11px] text-muted uppercase tracking-wider">
                            {t.name}
                          </span>
                        </div>
                      )}
                    </div>
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div className="px-8 py-4 border-t border-border flex items-center justify-between gap-4">
          <p className="text-xs text-muted">
            {selected
              ? `Selected: ${templates.find((t) => t.id === selected)?.name}`
              : "Select a template to continue."}
          </p>
          <button
            disabled={!selected}
            onClick={() => selected && onApply(selected)}
            className="btn-primary"
          >
            Apply Template
          </button>
        </div>
      </div>
    </div>
  );
}
