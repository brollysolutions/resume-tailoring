"use client";

import { useEffect } from "react";
import { X, FilePlus, Upload, Lock } from "lucide-react";
import { useFocusTrap } from "@/lib/useFocusTrap";

interface ChoiceModalProps {
  onClose: () => void;
  onImport: () => void;
}

export function ChoiceModal({ onClose, onImport }: ChoiceModalProps) {
  const trapRef = useFocusTrap<HTMLDivElement>(true);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-labelledby="choice-modal-title">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div ref={trapRef} className="relative z-50 w-full max-w-2xl card shadow-2xl p-8">
        <button
          onClick={onClose}
          aria-label="Close"
          className="absolute top-4 right-4 btn-ghost p-2"
        >
          <X className="w-4 h-4" />
        </button>

        <div className="mb-8">
          <h2 id="choice-modal-title" className="text-2xl font-semibold tracking-tight mb-2">
            How do you want to start?
          </h2>
          <p className="text-sm text-muted leading-relaxed">
            Pick a path. You can switch later.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <button
            type="button"
            disabled
            title="Coming soon — build a resume from scratch with AI"
            className="text-left card p-6 flex flex-col items-start gap-4 opacity-60 cursor-not-allowed"
          >
            <div className="w-11 h-11 rounded bg-subtle flex items-center justify-center">
              <FilePlus className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2 mb-2">
                <p className="text-base font-semibold">Build Resume</p>
                <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted bg-subtle border border-border rounded px-1.5 py-0.5">
                  <Lock className="w-2.5 h-2.5" aria-hidden="true" />
                  <span>Coming soon</span>
                </span>
              </div>
              <p className="text-sm text-muted leading-relaxed">
                Create a new resume from scratch with AI assistance.
              </p>
            </div>
          </button>

          <button
            onClick={onImport}
            className="text-left card p-6 flex flex-col items-start gap-4 hover:border-foreground/40 transition-colors group"
          >
            <div className="w-11 h-11 rounded bg-subtle flex items-center justify-center">
              <Upload className="w-5 h-5" />
            </div>
            <div className="flex-1">
              <p className="text-base font-semibold mb-2">Import Resume</p>
              <p className="text-sm text-muted leading-relaxed">
                Upload your existing resume to get started.
              </p>
            </div>
          </button>
        </div>
      </div>
    </div>
  );
}
