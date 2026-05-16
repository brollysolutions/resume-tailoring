"use client";

import { useState, useCallback } from "react";
import { UploadCloud, FileText, Loader2, X, ArrowRight } from "lucide-react";

const ACCEPTED = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];

export function UploadZone() {
  const [isDragging, setIsDragging] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
    try {
      const formData = new FormData();
      formData.append("file", file);
      const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8004";
      const res = await fetch(`${apiUrl}/api/resume/upload`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) throw new Error("Upload failed.");
      const data = await res.json();
      // Clear any JD/template state from a previous session so stale data
      // doesn't carry forward to the new resume's tailor flow.
      sessionStorage.removeItem("tailor_jd_text");
      sessionStorage.removeItem("template_id");
      // Use "|" as delimiter — commas appear inside job titles like "Director, Product"
      const keywordsQuery = (data.keywords || []).join("|");
      window.location.href = `/job-search?keywords=${encodeURIComponent(
        keywordsQuery
      )}&resume_id=${data.resume_id}`;
    } catch (err: any) {
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
          className={`block w-full border border-dashed rounded-lg px-8 py-12 text-center cursor-pointer transition-colors ${
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
            Drop your resume here, or <span className="underline underline-offset-2">browse</span>
          </p>
          <p className="text-xs text-muted">PDF or DOCX · up to 10MB</p>
        </label>
        {error && <p className="text-xs text-danger">{error}</p>}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="card p-4 flex items-center justify-between">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-9 h-9 rounded bg-subtle text-foreground flex items-center justify-center shrink-0">
            <FileText className="w-4 h-4" />
          </div>
          <div className="min-w-0">
            <p className="text-sm font-medium truncate">{file.name}</p>
            <p className="text-xs text-muted">
              {(file.size / 1024 / 1024).toFixed(2)} MB
            </p>
          </div>
        </div>
        <button
          onClick={() => setFile(null)}
          disabled={isUploading}
          className="btn-ghost p-2"
          aria-label="Remove file"
        >
          <X className="w-4 h-4" />
        </button>
      </div>

      <button onClick={onUpload} disabled={isUploading} className="btn-primary w-full">
        {isUploading ? (
          <>
            <Loader2 className="w-4 h-4 animate-spin" />
            Analyzing Your Document…
          </>
        ) : (
          <>
            Continue
            <ArrowRight className="w-4 h-4" />
          </>
        )}
      </button>

      {error && <p className="text-xs text-danger">{error}</p>}
    </div>
  );
}
