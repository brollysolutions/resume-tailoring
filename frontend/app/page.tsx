"use client";

import { useEffect, useState } from "react";
import { ArrowRight } from "lucide-react";
import { ChoiceModal } from "@/components/ChoiceModal";
import {
  TemplatePickerModal,
  type Template,
} from "@/components/TemplatePickerModal";
import { ImportResumeModal } from "@/components/ImportResumeModal";

type Stage = "landing" | "choice" | "templates" | "import";

const STAGE_KEY = "home_stage";
const TEMPLATE_KEY = "home_selected_template";

function saveStage(s: Stage) {
  if (s === "landing") localStorage.removeItem(STAGE_KEY);
  else localStorage.setItem(STAGE_KEY, s);
}

export default function Home() {
  const [stage, setStage] = useState<Stage>("landing");
  const [mounted, setMounted] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [templatesLoading, setTemplatesLoading] = useState(true);
  const [templatesError, setTemplatesError] = useState<string | null>(null);
  const [selectedTemplate, setSelectedTemplate] = useState<string | null>(null);

  // Restore stage + template on mount. setState calls here synchronize React with
  // localStorage (an external system) on one-shot mount — the lint rule over-flags
  // this legitimate pattern.
  useEffect(() => {
    const savedStage = localStorage.getItem(STAGE_KEY) as Stage | null;
    const savedTemplate = localStorage.getItem(TEMPLATE_KEY);
    /* eslint-disable react-hooks/set-state-in-effect */
    if (savedTemplate) setSelectedTemplate(savedTemplate);
    if (savedStage === "import" && savedTemplate) setStage("import");
    else if (savedStage === "templates") setStage("templates");
    else if (savedStage === "choice") setStage("choice");
    setMounted(true);
    /* eslint-enable react-hooks/set-state-in-effect */
  }, []);

  const goToStage = (s: Stage) => { setStage(s); saveStage(s); };

  useEffect(() => {
    const apiUrl = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8055";
    fetch(`${apiUrl}/api/tailor/templates`)
      .then((r) => r.json())
      .then((data) => {
        setTemplates(data.templates || []);
        setTemplatesLoading(false);
      })
      .catch(() => {
        setTemplatesError("Could not load templates.");
        setTemplatesLoading(false);
      });
  }, []);

  if (!mounted) return null;

  return (
    <div className="min-h-screen flex items-center justify-center px-6">
      <div className="text-center max-w-xl">
        <h1 className="text-4xl sm:text-5xl font-semibold tracking-tight mb-5">
          Tailor your resume to any job.
        </h1>
        <p className="text-muted text-[15px] sm:text-base leading-relaxed mb-8">
          Match resumes against job descriptions and generate targeted edits in
          seconds.
        </p>
        <button
          onClick={() => goToStage("choice")}
          className="btn-primary px-6"
        >
          Get Started
          <ArrowRight className="w-4 h-4" />
        </button>
      </div>

      {stage === "choice" && (
        <ChoiceModal
          onClose={() => goToStage("landing")}
          onImport={() => goToStage("templates")}
        />
      )}

      {stage === "templates" && (
        <TemplatePickerModal
          templates={templates}
          loading={templatesLoading}
          error={templatesError}
          onClose={() => goToStage("landing")}
          onApply={(id) => {
            setSelectedTemplate(id);
            localStorage.setItem(TEMPLATE_KEY, id);
            goToStage("import");
          }}
        />
      )}

      {stage === "import" && selectedTemplate && (
        <ImportResumeModal
          templateId={selectedTemplate}
          onClose={() => goToStage("landing")}
          onBack={() => goToStage("templates")}
        />
      )}
    </div>
  );
}
