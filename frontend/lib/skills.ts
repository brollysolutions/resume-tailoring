// Frontend mirror of backend/app/core/suggestion_applier.py — Skills only.
// Used by SkillsStep to show the user the live category/skill state that the
// iframe preview is about to render, so direct edits feel instant.

export type SkillCategory = { category: string; skills: string[] };

export type SkillSuggestionMode =
  | "add_skill"
  | "remove_skill"
  | "rename_category"
  | "delete_category"
  | "move_skill";

export type SkillSuggestion = {
  id: number;
  section: string; // expected "Skills"
  mode?: SkillSuggestionMode;
  reasoning?: string;
  category?: string;
  skill?: string;
  target_category?: string;
  is_new_category?: boolean;
};

function findCategory(skills: SkillCategory[], name: string): number {
  const target = name.trim().toLowerCase();
  return skills.findIndex((c) => (c.category || "").trim().toLowerCase() === target);
}

/**
 * Apply approved Skills suggestions in order. Returns a new array; doesn't
 * mutate `original`. Categories that end up empty are dropped (mirrors backend).
 */
export function projectApprovedSkills(
  original: SkillCategory[],
  approved: SkillSuggestion[],
): SkillCategory[] {
  const data: SkillCategory[] = original.map((c) => ({
    category: c.category,
    skills: [...(c.skills || [])],
  }));

  for (const s of approved) {
    if ((s.section || "").toLowerCase() !== "skills") continue;
    const mode = s.mode;
    const category = (s.category || "").trim();
    const skill = (s.skill || "").trim();
    const targetCategory = (s.target_category || "").trim();
    const isNewCategory = !!s.is_new_category;

    if (mode === "delete_category") {
      if (!category) continue;
      const idx = findCategory(data, category);
      if (idx >= 0) data.splice(idx, 1);
      continue;
    }

    if (mode === "rename_category") {
      if (!category || !targetCategory) continue;
      const idx = findCategory(data, category);
      if (idx >= 0) data[idx].category = targetCategory;
      continue;
    }

    if (mode === "remove_skill") {
      if (!category || !skill) continue;
      const idx = findCategory(data, category);
      if (idx >= 0) {
        const targ = skill.toLowerCase();
        data[idx].skills = data[idx].skills.filter((x) => (x || "").trim().toLowerCase() !== targ);
      }
      continue;
    }

    if (mode === "move_skill") {
      if (!category || !skill || !targetCategory) continue;
      const srcIdx = findCategory(data, category);
      if (srcIdx < 0) continue;
      const srcLower = data[srcIdx].skills.map((x) => x.trim().toLowerCase());
      if (!srcLower.includes(skill.toLowerCase())) continue;
      data[srcIdx].skills = data[srcIdx].skills.filter(
        (x) => x.trim().toLowerCase() !== skill.toLowerCase(),
      );
      const tIdx = findCategory(data, targetCategory);
      if (tIdx >= 0) {
        const tLower = data[tIdx].skills.map((x) => x.trim().toLowerCase());
        if (!tLower.includes(skill.toLowerCase())) data[tIdx].skills.push(skill);
      } else {
        data.push({ category: targetCategory, skills: [skill] });
      }
      continue;
    }

    if (mode === "add_skill") {
      if (!skill) continue;
      let destName: string;
      if (isNewCategory && targetCategory) destName = targetCategory;
      else if (category) destName = category;
      else if (targetCategory) destName = targetCategory;
      else destName = "Additional Skills";
      const idx = findCategory(data, destName);
      if (idx >= 0) {
        const lower = data[idx].skills.map((x) => (x || "").trim().toLowerCase());
        if (!lower.includes(skill.toLowerCase())) data[idx].skills.push(skill);
      } else {
        data.push({ category: destName, skills: [skill] });
      }
      continue;
    }
  }

  return data.filter((c) => (c.skills || []).length > 0);
}
