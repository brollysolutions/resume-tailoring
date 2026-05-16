"use client";

import { Check } from "lucide-react";

export type StepStatus = "pending" | "active" | "done" | "skipped";

export interface Step {
  key: string;
  label: string;
  status: StepStatus;
}

interface StepperProps {
  steps: Step[];
  onStepClick?: (key: string) => void;
}

export function Stepper({ steps, onStepClick }: StepperProps) {
  return (
    <div className="flex items-center gap-2 flex-wrap">
      {steps.map((step, i) => {
        const isLast = i === steps.length - 1;
        const isClickable = onStepClick && (step.status === "done" || step.status === "skipped");

        return (
          <div key={step.key} className="flex items-center gap-2">
            <button
              type="button"
              onClick={isClickable ? () => onStepClick!(step.key) : undefined}
              disabled={!isClickable}
              className={[
                "flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium transition-colors",
                step.status === "active" && "bg-foreground text-white",
                step.status === "done" && "bg-success/10 text-success hover:bg-success/20 cursor-pointer",
                step.status === "skipped" && "bg-subtle text-muted hover:bg-border cursor-pointer",
                step.status === "pending" && "bg-subtle text-muted cursor-default",
              ].filter(Boolean).join(" ")}
            >
              <span className={[
                "flex items-center justify-center w-4 h-4 rounded-full text-[10px] font-semibold",
                step.status === "active" && "bg-white text-foreground",
                step.status === "done" && "bg-success text-white",
                step.status === "skipped" && "bg-border text-muted",
                step.status === "pending" && "bg-border text-muted",
              ].filter(Boolean).join(" ")}>
                {step.status === "done" ? <Check className="w-2.5 h-2.5" /> : i + 1}
              </span>
              {step.label}
            </button>
            {!isLast && (
              <div className={[
                "w-6 h-px",
                step.status === "done" ? "bg-success/40" : "bg-border",
              ].join(" ")} />
            )}
          </div>
        );
      })}
    </div>
  );
}
