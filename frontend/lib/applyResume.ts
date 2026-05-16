/**
 * Client-side mirror of `backend/app/core/suggestion_applier.py::apply_suggestions`.
 *
 * Keeps the editor view in sync with what the backend's preview endpoint
 * produces. The backend is the source of truth for the rendered PDF/DOCX;
 * any client-side miss just means the editor view shows the un-applied
 * original until the next preview re-render catches up.
 *
 * Supported modes (must mirror backend):
 *   - Non-Skills: replace, remove_line, add_line, replace_field, delete_project
 *   - Skills:     add_skill, remove_skill, rename_category, delete_category, move_skill
 *                 (explicit fields: category, skill, target_category, is_new_category)
 */

import type { ResumeData, SkillCategory, Suggestion } from "@/types/resume";

const sameText = (a: string, b: string) =>
  (a || "").trim().toLowerCase() === (b || "").trim().toLowerCase();

function clone<T>(x: T): T {
  return JSON.parse(JSON.stringify(x));
}

function replaceInList(list: string[] | undefined, oldText: string, newText: string): boolean {
  if (!list) return false;
  for (let i = 0; i < list.length; i++) {
    if (sameText(list[i], oldText)) {
      list[i] = newText;
      return true;
    }
  }
  return false;
}

function removeFromList(list: string[] | undefined, target: string): boolean {
  if (!list) return false;
  for (let i = 0; i < list.length; i++) {
    if (sameText(list[i], target)) {
      list.splice(i, 1);
      return true;
    }
  }
  return false;
}

function applyReplace(data: ResumeData, original: string, suggested: string) {
  if (data.summary && sameText(data.summary, original)) {
    data.summary = suggested;
    return;
  }
  for (const exp of data.experience || []) {
    if (replaceInList(exp.bullets, original, suggested)) return;
  }
  for (const p of data.projects || []) {
    if (replaceInList(p.bullets, original, suggested)) return;
  }
  for (const ed of data.education || []) {
    if (replaceInList(ed.details, original, suggested)) return;
  }
  for (const cat of data.skills || []) {
    if (replaceInList(cat.skills, original, suggested)) return;
  }
  if (data.certifications) {
    replaceInList(data.certifications, original, suggested);
  }
}

function applyRemoveLine(data: ResumeData, original: string) {
  if (data.summary && sameText(data.summary, original)) {
    data.summary = "";
    return;
  }
  for (const exp of data.experience || []) {
    if (removeFromList(exp.bullets, original)) return;
  }
  for (const p of data.projects || []) {
    if (removeFromList(p.bullets, original)) return;
  }
  for (const ed of data.education || []) {
    if (removeFromList(ed.details, original)) return;
  }
  if (data.certifications) {
    removeFromList(data.certifications, original);
  }
}

function applyAddLine(data: ResumeData, ownerSpec: string, line: string) {
  const parts = ownerSpec.split("::");
  if (parts.length !== 2) return;
  const [sec, idxStr] = parts;
  const idx = parseInt(idxStr, 10);
  if (Number.isNaN(idx)) return;
  const secLower = sec.toLowerCase();
  if (secLower === "experience") {
    const e = (data.experience || [])[idx];
    if (e) { e.bullets = [...(e.bullets || []), line]; }
  } else if (secLower === "projects") {
    const p = (data.projects || [])[idx];
    if (p) { p.bullets = [...(p.bullets || []), line]; }
  } else if (secLower === "education") {
    const ed = (data.education || [])[idx];
    if (ed) { ed.details = [...(ed.details || []), line]; }
  } else if (secLower === "certifications" || secLower === "certification") {
    data.certifications = [...(data.certifications || []), line];
  }
}

function applyReplaceField(data: ResumeData, spec: string, value: string) {
  const parts = spec.split("::");
  if (parts.length !== 3) return;
  const [sec, idxStr, field] = parts;
  const secLower = sec.toLowerCase();
  if (secLower === "contact") {
    data.contact = { ...(data.contact || {}), [field]: value };
    return;
  }
  const idx = parseInt(idxStr, 10);
  if (Number.isNaN(idx)) return;
  if (secLower === "experience" && data.experience?.[idx]) {
    (data.experience[idx] as Record<string, unknown>)[field] = value;
  } else if (secLower === "projects" && data.projects?.[idx]) {
    (data.projects[idx] as Record<string, unknown>)[field] = value;
  } else if (secLower === "education" && data.education?.[idx]) {
    (data.education[idx] as Record<string, unknown>)[field] = value;
  }
}

// ----- Skills modes -----

function findCat(skills: SkillCategory[] | undefined, name: string): SkillCategory | undefined {
  if (!skills) return undefined;
  return skills.find((c) => sameText(c.category, name));
}

function applySkillsMode(data: ResumeData, sg: Suggestion) {
  data.skills = data.skills || [];
  const mode = sg.mode;
  const category = (sg.category || "").trim();
  const skill = (sg.skill || "").trim();
  const targetCategory = (sg.target_category || "").trim();
  const isNewCategory = !!sg.is_new_category;

  if (mode === "replace_section") {
    const next = (sg.new_skills || []).filter((c) => c && c.category);
    data.skills = next.map((c) => ({
      category: c.category,
      skills: [...(c.skills || [])],
    }));
    return;
  }
  if (mode === "delete_category") {
    if (!category) return;
    data.skills = data.skills.filter((c) => !sameText(c.category, category));
    return;
  }
  if (mode === "rename_category") {
    if (!category || !targetCategory) return;
    const cat = findCat(data.skills, category);
    if (cat) cat.category = targetCategory;
    return;
  }
  if (mode === "remove_skill") {
    if (!category || !skill) return;
    const cat = findCat(data.skills, category);
    if (cat) cat.skills = (cat.skills || []).filter((s) => !sameText(s, skill));
    return;
  }
  if (mode === "add_skill") {
    if (!skill) return;
    let destName: string;
    if (isNewCategory && targetCategory) destName = targetCategory;
    else if (category) destName = category;
    else if (targetCategory) destName = targetCategory;
    else destName = "Additional Skills";
    let cat = findCat(data.skills, destName);
    if (!cat) {
      cat = { category: destName, skills: [] };
      data.skills.push(cat);
    }
    if (!cat.skills.some((s) => sameText(s, skill))) {
      cat.skills.push(skill);
    }
    return;
  }
  if (mode === "move_skill") {
    if (!category || !skill || !targetCategory) return;
    const src = findCat(data.skills, category);
    if (!src) return;
    src.skills = src.skills.filter((s) => !sameText(s, skill));
    let dst = findCat(data.skills, targetCategory);
    if (!dst) {
      dst = { category: targetCategory, skills: [] };
      data.skills.push(dst);
    }
    if (!dst.skills.some((s) => sameText(s, skill))) {
      dst.skills.push(skill);
    }
  }
}

export function applySuggestionsClient(
  resume: ResumeData,
  suggestions: Suggestion[],
): ResumeData {
  if (!suggestions.length) return resume;
  const data = clone(resume);
  for (const sg of suggestions) {
    const mode = sg.mode || "replace";
    const section = (sg.section || "").toLowerCase();

    // Skills modes use the explicit-field schema
    if (section.startsWith("skill")) {
      applySkillsMode(data, sg);
      continue;
    }

    const original = (sg.original || "").trim();
    const suggested = (sg.suggested || "").trim();

    if (mode === "replace") {
      if (!original || !suggested) continue;
      applyReplace(data, original, suggested);
    } else if (mode === "remove_line") {
      if (!original) continue;
      applyRemoveLine(data, original);
    } else if (mode === "add_line") {
      if (!original || !suggested) continue;
      applyAddLine(data, original, suggested);
    } else if (mode === "replace_field") {
      if (!original) continue;
      applyReplaceField(data, original, suggested);
    } else if (mode === "replace_bullets") {
      const parts = original.split("::");
      if (parts.length === 2) {
        const [sec, idxStr] = parts;
        const idx = parseInt(idxStr, 10);
        try {
          const newBullets = JSON.parse(suggested);
          if (!Number.isNaN(idx)) {
            const secLower = sec.toLowerCase();
            if (secLower === "experience" && data.experience?.[idx]) {
              data.experience[idx].bullets = newBullets;
            } else if (secLower === "projects" && data.projects?.[idx]) {
              data.projects[idx].bullets = newBullets;
            }
          }
        } catch (e) {
          console.warn("applySuggestionsClient: replace_bullets parse failed", e);
        }
      }
    } else if (mode === "delete_project") {
      if (!original) continue;
      if (data.projects) {
        data.projects = data.projects.filter((p) => !sameText(p.name || "", original));
      }
    }
  }

  // Drop empty skill categories
  if (data.skills) {
    data.skills = data.skills.filter((c) => (c.skills || []).length > 0);
  }
  return data;
}
