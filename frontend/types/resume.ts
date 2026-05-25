/** Shared types mirroring the backend Resume Pydantic schema + suggestion shapes. */

export type SuggestionMode =
  | "replace"
  | "remove_line"
  | "add_line"
  | "replace_field"
  | "delete_project"
  | "add_skill"
  | "remove_skill"
  | "rename_category"
  | "delete_category"
  | "move_skill"
  | "replace_section"
  | "replace_bullets"
  | "reorder_sections";

export interface Suggestion {
  id: number;
  section: string;
  reasoning?: string;
  project_index?: number;
  mode?: SuggestionMode;
  // Non-Skills modes (replace, remove_line, add_line, replace_field, delete_project)
  original?: string;
  suggested?: string;
  // Skills modes (add_skill, remove_skill, rename_category, delete_category, move_skill)
  category?: string;
  skill?: string;
  target_category?: string;
  is_new_category?: boolean;
  // replace_section (Skills wholesale regen)
  new_skills?: SkillCategory[];
}

export interface GeneratedProject {
  name: string;
  tech: string;
  bullets: string[];
  domain_tag: string;
  interview_brief: string;
  fingerprint: string;
}

export interface ContactInfo {
  email?: string;
  phone?: string;
  location?: string;
  linkedin?: string;
  github?: string;
  website?: string;
}

export interface ExperienceEntry {
  title?: string;
  company?: string;
  location?: string;
  start_date?: string;
  end_date?: string;
  bullets?: string[];
}

export interface EducationEntry {
  institution?: string;
  degree?: string;
  field?: string;
  location?: string;
  start_date?: string;
  end_date?: string;
  gpa?: string;
  details?: string[];
}

export interface ProjectEntry {
  name?: string;
  tech?: string;
  bullets?: string[];
}

export interface SkillCategory {
  category: string;
  skills: string[];
}

export interface SectionItem {
  header?: string;
  subheader?: string;
  bullets?: string[];
  text?: string;
}

export interface ExtraSection {
  title: string;
  content_type: "entries" | "text" | "list";
  items: SectionItem[];
}

export interface ResumeData {
  name?: string;
  contact?: ContactInfo;
  summary?: string;
  experience?: ExperienceEntry[];
  education?: EducationEntry[];
  projects?: ProjectEntry[];
  skills?: SkillCategory[];
  certifications?: string[];
  extra_sections?: ExtraSection[];
  section_order?: string[];
}
