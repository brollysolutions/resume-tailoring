"use client";

import { UploadZone } from "@/components/UploadZone";

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
    </div>
  );
}
