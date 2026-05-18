"use client";

import { UploadZone } from "@/components/UploadZone";

const TEMPLATES = [
  { name: "Modern", description: "Sans-serif, left-aligned" },
  { name: "Classic", description: "Serif, centered header" },
  { name: "Academic", description: "LaTeX-style, publications" },
];

export default function Home() {
  return (
    <div className="w-full max-w-2xl mx-auto px-6 py-20">
      <div className="mb-10">
        <h1 className="text-3xl font-semibold tracking-tight mb-3">
          Tailor your resume to the job.
        </h1>
        <p className="text-muted text-[15px] leading-relaxed">
          Upload your resume, paste a job description, and download a tailored
          version.
        </p>
      </div>

      <UploadZone />

      <div className="mt-8">
        <p className="text-xs font-semibold uppercase tracking-wider text-muted mb-3">
          Available templates
        </p>
        <div className="flex gap-3 flex-wrap">
          {TEMPLATES.map((t) => (
            <div key={t.name} className="card px-3 py-2">
              <p className="text-sm font-medium">{t.name}</p>
              <p className="text-xs text-muted mt-0.5">{t.description}</p>
            </div>
          ))}
        </div>
        <p className="text-xs text-muted mt-3">
          Preview your resume in each template after uploading.
        </p>
      </div>
    </div>
  );
}
