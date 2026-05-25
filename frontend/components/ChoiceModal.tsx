"use client";

import { useEffect } from "react";
import { X, FilePlus, Upload, Lock, ArrowRight } from "lucide-react";

interface ChoiceModalProps {
  onClose: () => void;
  onImport: () => void;
}

export function ChoiceModal({ onClose, onImport }: ChoiceModalProps) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4">
      <div className="absolute inset-0 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="relative z-50 w-full max-w-2xl card shadow-2xl p-8">
        <button
          onClick={onClose}
          aria-label="Close"
          className="absolute top-4 right-4 btn-ghost p-2"
        >
          <X className="w-4 h-4" />
        </button>

        <div className="mb-8">
          <h2 className="text-2xl font-semibold tracking-tight mb-2">
            How do you want to start?
          </h2>
          <p className="text-sm text-muted leading-relaxed">
            Pick a path. You can switch later.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div
            aria-disabled="true"
            className="card p-6 flex flex-col items-start gap-4 opacity-60 cursor-not-allowed"
          >
            <div className="w-11 h-11 rounded bg-subtle flex items-center justify-center">
              <FilePlus className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center gap-2 mb-2">
                <p className="text-base font-semibold">Build Resume</p>
                <span className="inline-flex items-center gap-1 text-[10px] uppercase tracking-wider text-muted bg-subtle border border-border rounded px-1.5 py-0.5">
                  <Lock className="w-2.5 h-2.5" />
                  Coming soon
                </span>
              </div>
              <p className="text-sm text-muted leading-relaxed">
                Create a new resume from scratch with AI assistance.
              </p>
            </div>
          </div>

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
