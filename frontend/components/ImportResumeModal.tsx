"use client";

import { useEffect, useState } from "react";
import { Loader2, ArrowRight, FileText, ArrowLeft, X } from "lucide-react";
import { UploadZone } from "@/components/UploadZone";
import { TemplatePreview } from "@/components/TemplatePreview";

interface ImportResumeModalProps {
  templateId: string;
  onClose: () => void;
  onBack?: () => void;
}

export function ImportResumeModal({
  templateId,
  onClose,
  onBack,
}: ImportResumeModalProps) {
  const [resumeId, setResumeId] = useState<string | null>(() => {
    if (typeof window !== "undefined") {
      return sessionStorage.getItem("import_resume_id") || null;
    }
    return null;
  });
  const [keywords, setKeywords] = useState<string[]>(() => {
    if (typeof window !== "undefined") {
      const kws = sessionStorage.getItem("import_keywords");
      return kws ? JSON.parse(kws) : [];
    }
    return [];
  });
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [isLoadingPreview, setIsLoadingPreview] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !resumeId) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, resumeId]);

  useEffect(() => {
    if (!resumeId) {
      setPreviewHtml(null);
      return;
    }
    let cancelled = false;
    const fetchPreview = async () => {
      setIsLoadingPreview(true);
      setError(null);
      try {
        const apiUrl =
          process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
        const res = await fetch(`${apiUrl}/api/tailor/preview`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            resume_id: resumeId,
            template_id: templateId,
            suggestions: [],
          }),
        });
        if (!res.ok) throw new Error("Could not render preview.");
        const data = await res.json();
        if (!cancelled) setPreviewHtml(data.html || "");
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "Preview failed.");
        }
      } finally {
        if (!cancelled) setIsLoadingPreview(false);
      }
    };
    fetchPreview();
    return () => {
      cancelled = true;
    };
  }, [resumeId, templateId]);

  const onContinue = () => {
    if (!resumeId) return;
    localStorage.setItem("template_id", templateId);
    // Clear home-page stage so returning to / shows the landing, not the modal
    localStorage.removeItem("home_stage");
    localStorage.removeItem("home_selected_template");

    // Clear import session storage
    sessionStorage.removeItem("import_resume_id");
    sessionStorage.removeItem("import_keywords");

    const kw = keywords.join("|");
    window.location.href = `/job-search?keywords=${encodeURIComponent(
      kw
    )}&resume_id=${resumeId}`;
  };

  const previewPlaceholder = error ? (
    <p className="text-xs text-danger">{error}</p>
  ) : isLoadingPreview ? (
    <div className="w-[80%] max-w-[480px] aspect-[8.5/11] bg-white rounded shadow-md border border-border/60 p-8 space-y-6 animate-pulse select-none">
      {/* Name and title */}
      <div className="space-y-2 text-center">
        <div className="h-4.5 bg-muted/60 rounded w-1/3 mx-auto" />
        <div className="h-3 bg-muted/50 rounded w-1/2 mx-auto" />
      </div>
      
      {/* Contact info bar */}
      <div className="h-2.5 bg-muted/40 rounded w-3/4 mx-auto" />

      <hr className="border-border/60" />

      {/* Summary section */}
      <div className="space-y-2">
        <div className="h-3 bg-muted/60 rounded w-1/4" />
        <div className="space-y-1.5">
          <div className="h-2 bg-muted/30 rounded w-full" />
          <div className="h-2 bg-muted/30 rounded w-5/6" />
        </div>
      </div>

      {/* Experience section */}
      <div className="space-y-3">
        <div className="h-3 bg-muted/60 rounded w-1/4" />
        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="h-2.5 bg-muted/50 rounded w-1/3" />
            <div className="h-2 bg-muted/40 rounded w-1/6" />
          </div>
          <div className="space-y-1.5 pl-3">
            <div className="h-2 bg-muted/30 rounded w-11/12" />
            <div className="h-2 bg-muted/30 rounded w-full" />
          </div>
        </div>
      </div>

      {/* Skills section */}
      <div className="space-y-2.5">
        <div className="h-3 bg-muted/60 rounded w-1/4" />
        <div className="flex gap-2">
          <div className="h-5 bg-muted/40 rounded w-16" />
          <div className="h-5 bg-muted/40 rounded w-20" />
          <div className="h-5 bg-muted/40 rounded w-12" />
        </div>
      </div>
    </div>
  ) : (
    <div className="text-center max-w-xs">
      <div className="w-12 h-12 rounded-full bg-subtle border border-border flex items-center justify-center mx-auto mb-3">
        <FileText className="w-5 h-5 text-muted" />
      </div>
      <p className="text-sm text-muted leading-relaxed">
        Your resume preview will appear here after upload.
      </p>
    </div>
  );

  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center p-4">
      <div
        className="absolute inset-0 bg-black/40"
        onClick={() => {
          if (!resumeId) onClose();
        }}
      />
      <div className="relative z-50 w-[95vw] h-[90vh] max-w-7xl card shadow-xl flex overflow-hidden">

        {/* ── Left column: header + upload + footer ── */}
        <div className="flex-1 flex flex-col border-r border-border">
          <div className="px-8 pt-6 pb-4 border-b border-border flex items-center gap-3">
            {onBack && (
              <button
                onClick={onBack}
                aria-label="Back to templates"
                className="btn-ghost p-1.5 shrink-0"
              >
                <ArrowLeft className="w-4 h-4" />
              </button>
            )}
            <h2 className="text-xl font-semibold tracking-tight">
              Import your resume
            </h2>
          </div>

          <div className="flex-1 px-8 py-6 overflow-y-auto scrollbar-thin">
            {resumeId ? (
              <div className="card p-4 flex items-center justify-between border-success/30 bg-success/5">
                <div className="flex items-center gap-3">
                  <div className="w-9 h-9 rounded bg-success/10 text-success flex items-center justify-center shrink-0">
                    <FileText className="w-4 h-4" />
                  </div>
                  <div>
                    <p className="text-sm font-medium">Resume uploaded</p>
                    <p className="text-xs text-muted">Click continue or upload another to replace</p>
                  </div>
                </div>
                <button
                  onClick={() => {
                    setResumeId(null);
                    setKeywords([]);
                    sessionStorage.removeItem("import_resume_id");
                    sessionStorage.removeItem("import_keywords");
                  }}
                  className="btn-ghost p-2 text-muted hover:text-danger"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            ) : (
              <UploadZone
                templateId={templateId}
                onUploaded={(data) => {
                  setResumeId(data.resume_id);
                  setKeywords(data.keywords);
                  sessionStorage.setItem("import_resume_id", data.resume_id);
                  sessionStorage.setItem("import_keywords", JSON.stringify(data.keywords));
                }}
              />
            )}
          </div>

          <div className="px-8 py-4 border-t border-border flex items-center justify-end">
            <button
              onClick={onContinue}
              disabled={!resumeId}
              className="btn-primary"
            >
              Continue
              <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* ── Right column: pure preview, no chrome ── */}
        <div className="flex-1 relative overflow-hidden flex flex-col">
          <TemplatePreview
            html={previewHtml}
            showControls
            fillParent
            onClose={onClose}
            placeholder={previewPlaceholder}
          />
        </div>

      </div>
    </div>
  );
}
