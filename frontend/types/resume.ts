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
  | "reorder_sections"
  | "add_entry"
  | "delete_entry"
  | "toggle_hidden"
  | "set_summary";

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

export interface CustomLink {
  label: string;
  url: string;
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
  company_url?: string;
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
  date?: string;
  url?: string;
  demo_url?: string;
  bullets?: string[];
}

export interface SkillCategory {
  category: string;
  skills: string[];
}

export interface Certification {
  name?: string;
  issuer?: string;
  date?: string;
  credential_url?: string;
}

export interface Publication {
  title?: string;
  authors?: string;
  venue?: string;
  year?: string;
  doi?: string;
  url?: string;
}

export interface Award {
  title?: string;
  issuer?: string;
  date?: string;
  description?: string;
}

export interface Language {
  name?: string;
  proficiency?: string;
}

export interface VolunteerEntry {
  role?: string;
  organization?: string;
  location?: string;
  start_date?: string;
  end_date?: string;
  bullets?: string[];
}

export interface Patent {
  title?: string;
  number?: string;
  date?: string;
  status?: string;
  authors?: string;
}

export interface Talk {
  title?: string;
  venue?: string;
  date?: string;
  type?: string;
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
  custom_links?: CustomLink[];
  summary?: string;
  experience?: ExperienceEntry[];
  education?: EducationEntry[];
  projects?: ProjectEntry[];
  skills?: SkillCategory[];
  certifications?: Certification[];
  publications?: Publication[];
  awards?: Award[];
  languages?: Language[];
  volunteer?: VolunteerEntry[];
  patents?: Patent[];
  talks?: Talk[];
  extra_sections?: ExtraSection[];
  section_order?: string[];
  hidden_sections?: string[];
}

export interface ATSSuggestion {
  action: "tailor_section" | "add_field" | "restructure";
  target: string;
  reason: string;
}

export interface ATSReportPayload {
  parse_score: number;
  keyword_score: number;
  section_recognition: Record<string, boolean>;
  format_warnings: string[];
  missing_fields: string[];
  found_keywords: string[];
  missing_keywords: string[];
  suggestions: ATSSuggestion[];
}

export interface ImprovementAction {
  kind: "add_keywords";
  section: string;
  keywords: string[];
  est_gain: number;
  label: string;
}

export interface ImprovementBlocker {
  reason: string;
  kind: "experience" | "education" | "seniority" | "other";
}

export interface ImprovementPlan {
  current_score: number;
  achievable_ceiling: number;
  actions: ImprovementAction[];
  blockers: ImprovementBlocker[];
}

export interface MatchGuidanceBlocker {
  kind: string;
  headline: string;
  detail: string;
}

export interface MatchGuidance {
  sections: Record<string, string>;
  blockers: MatchGuidanceBlocker[];
}

export interface Directive {
  type: "undo_last" | "generate_projects" | "ats_report";
  payload?: ATSReportPayload;
  count?: number;
  more?: boolean;
}
