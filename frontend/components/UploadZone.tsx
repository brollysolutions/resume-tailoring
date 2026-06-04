"use client";

import { useState, useEffect, useRef } from "react";
import FileUpload from "@/components/ui/file-upload";
import { getApiUrl, getBasePath } from "@/lib/api";

const ACCEPTED = [
  "application/pdf",
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
];

const MAX_BYTES = 10 * 1024 * 1024;

interface UploadZoneProps {
  templateId: string;
  onUploaded?: (data: { resume_id: string; keywords: string[]; stack: string[] }) => void;
}


const ANALYZE_STEPS = [
  "Reading your document…",
  "Extracting sections…",
  "Identifying skills…",
  "Analyzing your experience…",
  "Almost done…",
];

export function UploadZone({ templateId, onUploaded }: UploadZoneProps) {
  const [file, setFile] = useState<File | null>(null);
  const [isUploading, setIsUploading] = useState(false);
  const [uploaded, setUploaded] = useState(false);
  const [analyzeStep, setAnalyzeStep] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!isUploading) return;
    const id = setInterval(() => setAnalyzeStep(s => Math.min(s + 1, ANALYZE_STEPS.length - 1)), 1800);
    return () => clearInterval(id);
  }, [isUploading]);

  const handleFileSelect = (f: File) => {
    if (!ACCEPTED.includes(f.type)) {
      setError("Only PDF and DOCX files are supported.");
      return;
    }
    if (f.size > MAX_BYTES) {
      setError(`File is ${(f.size / 1024 / 1024).toFixed(1)} MB. Max is 10 MB.`);
      return;
    }
    setError(null);
    setFile(f);
  };

  const handleRemove = () => {
    if (isUploading) {
      abortRef.current?.abort();
      setIsUploading(false);
    }
    setFile(null);
    setUploaded(false);
    setError(null);
  };

  const onUpload = async () => {
    if (!file) return;
    setAnalyzeStep(0);
    setIsUploading(true);
    setError(null);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const formData = new FormData();
      formData.append("file", file);
      const apiUrl = getApiUrl();
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
        onUploaded({
          resume_id: data.resume_id,
          keywords: data.keywords || [],
          stack: data.stack || [],
        });
        setIsUploading(false);
        setUploaded(true);
        return;
      }

      const keywordsQuery = (data.keywords || []).join("|");
      const stackQuery = (data.stack || []).join("|");
      const basePath = getBasePath();
      window.location.href = `${basePath}/job-search?keywords=${encodeURIComponent(
        keywordsQuery
      )}&stack=${encodeURIComponent(stackQuery)}&resume_id=${data.resume_id}`;

    } catch (err: unknown) {
      if (err instanceof DOMException && err.name === "AbortError") return;
      setError(err instanceof Error ? err.message : "Something went wrong.");
      setIsUploading(false);
    }
  };

  // Map 5 steps to 20-95% progress
  const currentProgress = uploaded ? 100 : isUploading ? (20 + (analyzeStep * 15)) : 0;

  return (
    <div className="space-y-4">
      <FileUpload
        file={file}
        onFileSelect={handleFileSelect}
        onRemove={handleRemove}
        isUploading={isUploading}
        progress={currentProgress}
        error={error}
        analyzeStepLabel={ANALYZE_STEPS[analyzeStep]}
      />

      {file && !isUploading && !uploaded && (
        <button
          onClick={onUpload}
          className="w-full btn-primary py-3"
          aria-label="Continue with this file"
        >
          Continue
        </button>
      )}

      {uploaded && (
        <div className="text-center text-sm font-medium text-success animate-in fade-in slide-in-from-bottom-2">
          Uploaded successfully! Redirecting...
        </div>
      )}
    </div>
  );
}

