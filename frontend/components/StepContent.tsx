/**
 * Barrel re-export for step components.
 * Each step lives in its own file under components/steps/.
 */

export type { GeneratedProject, Suggestion } from "@/types/resume";

export { FlatStep } from "@/components/steps/FlatStep";
export { ProjectsStep } from "@/components/steps/ProjectsStep";
export { GenerateProjectsStep } from "@/components/steps/GenerateProjectsStep";
export { InjectKeywordsStep } from "@/components/steps/InjectKeywordsStep";
export { SkillsCategoryDeleteBar } from "@/components/steps/SkillsCategoryDeleteBar";
