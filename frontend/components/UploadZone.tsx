"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { UploadCloud, FileText, X, ArrowRight, CheckCircle2 } from "lucide-react";

const ACCEPTED = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];

interface UploadZoneProps {
  templateId: string;
  onUploaded?: (data: { resume_id: string; keywords: string[] }) => void;
}

const ANALYZE_STEPS = [
  "Reading your document…",
  "Extracting sections…",
  "Identifying skills…",
  "Analyzing your experience…",
  "Almost done…",
];

export function UploadZone({ templateId, onUploaded }: UploadZoneProps) {
  const [isDragging, setIsDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploaded, setUploaded] = useState(false);
  const [analyzeStep, setAnalyzeStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!isUploading) { setAnalyzeStep(0); return; }
    const id = setInterval(() => setAnalyzeStep(s => Math.min(s + 1, ANALYZE_STEPS.length - 1)), 1800);
    return () => clearInterval(id);
  }, [isUploading]);

  const onDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(true);
  }, []);

  const onDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
  }, []);

  const accept = (f: File) => {
    if (!ACCEPTED.includes(f.type)) {
      setError("Only PDF and DOCX files are supported.");
      return;
    }
    setError(null);
    setFile(f);
  };

  const onDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragging(false);
    const dropped = e.dataTransfer.files?.[0];
    if (dropped) accept(dropped);
  }, []);

  const onSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const selected = e.target.files?.[0];
    if (selected) accept(selected);
  };

  const onUpload = async () => {
    if (!file) return;
    setIsUploading(true);
    setError(null);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const formData = new FormData();
      formData.append("file", file);
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
      const res = await fetch(`${apiUrl}/api/resume/upload`, {
        method: "POST",
        body: formData,
        signal: controller.signal,
      });
      if (!res.ok) throw new Error("Upload failed.");
      const data = await res.json();

      localStorage.removeItem("tailor_jd_text");
      localStorage.removeItem("match_state");
      localStorage.setItem("template_id", templateId);
      localStorage.setItem("current_resume_id", data.resume_id);

      if (onUploaded) {
        onUploaded({ resume_id: data.resume_id, keywords: data.keywords || [] });
        setIsUploading(false);
        setUploaded(true);
        return;
      }

      const keywordsQuery = (data.keywords || []).join("|");
      window.location.href = `/job-search?keywords=${encodeURIComponent(
        keywordsQuery
      )}&resume_id=${data.resume_id}`;
    } catch (err: any) {
      if (err.name === "AbortError") return;
      setError(err.message || "Something went wrong.");
      setIsUploading(false);
    }
  };

  if (!file) {
    return (
      <div className="space-y-3">
        <label
          htmlFor="file-input"
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onDrop={onDrop}
          className={`block w-full border border-dashed rounded-lg px-8 py-20 text-center cursor-pointer transition-colors ${
            isDragging
              ? "border-foreground bg-subtle"
              : "border-border hover:border-foreground/40 hover:bg-subtle/50"
          }`}
        >
          <input
            id="file-input"
            type="file"
            accept=".pdf,.docx"
            className="hidden"
            onChange={onSelect}
          />
          <UploadCloud className="w-6 h-6 mx-auto mb-3 text-muted" />
          <p className="text-sm font-medium mb-1">
            Click or drag your resume to upload
          </p>
          <p className="text-xs text-muted">PDF or DOCX · up to 10MB</p>
        </label>
        {error && <p className="text-xs text-danger">{error}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="card p-4 flex items-center justify-between relative overflow-hidden">
        {isUploading && (
          <div className="absolute inset-0 pointer-events-none overflow-hidden rounded-[inherit]">
            <div
              className="absolute top-0 bottom-0 w-1/2"
              style={{
                background: "linear-gradient(90deg, transparent, rgba(255,255,255,0.18), transparent)",
                animation: "shimmer 1.6s ease-in-out infinite",
              }}
            />
          </div>
        )}
        <div className="flex items-center gap-3 min-w-0">
          <div className={`w-9 h-9 rounded bg-subtle text-foreground flex items-center justify-center shrink-0 transition-colors ${isUploading ? "text-muted" : ""}`}>
            <FileText className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium truncate">{file.name}</p>
            <p className={`text-xs transition-colors ${isUploading ? "text-foreground/70" : uploaded ? "text-success" : "text-muted"}`}>
              {isUploading ? ANALYZE_STEPS[analyzeStep] : `${(file.size / 1024 / 1024).toFixed(2)} MB`}
            </p>
          </div>
        </div>
        <button
          onClick={() => {
            if (isUploading) {
              abortRef.current?.abort();
              setIsUploading(false);
            }
            setFile(null);
            setUploaded(false);
          }}
          className="btn-ghost p-2"
          aria-label={isUploading ? "Cancel upload" : "Remove file"}
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      {uploaded ? (
        <div className="w-full flex items-center justify-center gap-2 py-2.5 text-sm font-medium text-success">
          <CheckCircle2 className="w-4 h-4" />
          Uploaded successfully
        </div>
      ) : (
        <button
          onClick={onUpload}
          disabled={isUploading}
          className="w-full rounded-lg px-4 py-2.5 text-sm font-medium flex items-center justify-center gap-2 transition-all text-white"
          style={isUploading ? {
            background: "linear-gradient(90deg, #1d4ed8, #3b82f6, #60a5fa, #3b82f6, #1d4ed8)",
            backgroundSize: "300% 100%",
            animation: "gradientShift 2s ease infinite",
            cursor: "default",
          } : { background: "var(--color-accent)" }}
        >
          {isUploading ? (
            <span className="text-white">Analyzing…</span>
          ) : (
            <>
              Continue
              <ArrowRight className="w-4 h-4" />
            </>
          )}
        </button>
      )}

      {error && <p className="text-xs text-danger">{error}</p>}
    </div>
  );
}
