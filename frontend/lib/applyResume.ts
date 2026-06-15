/**
 * Client-side mirror of `backend/app/core/suggestion_applier.py::apply_suggestions`.
 *
 * Keeps the editor view in sync with what the backend's preview endpoint
 * produces. The backend is the source of truth for the rendered PDF/DOCX;
 * any client-side miss just means the editor view shows the un-applied
 * original until the next preview re-render catches up.
 *
 * Supported modes (must mirror backend):
 *   - Non-Skills: replace, set_summary, remove_line, add_line, replace_field, delete_project,
 *                 add_entry, delete_entry, toggle_hidden
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
  for (const v of data.volunteer || []) {
    if (replaceInList(v.bullets, original, suggested)) return;
  }
  for (const xs of data.extra_sections || []) {
    for (const it of xs.items || []) {
      if (replaceInList(it.bullets, original, suggested)) return;
      if (it.text && sameText(it.text, original)) {
        it.text = suggested;
        return;
      }
    }
  }
  if (data.certifications) {
    for (const cert of data.certifications) {
      if (cert.name && sameText(cert.name, original)) {
        cert.name = suggested;
        return;
      }
    }
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
  for (const v of data.volunteer || []) {
    if (removeFromList(v.bullets, original)) return;
  }
  for (const xs of data.extra_sections || []) {
    for (const it of xs.items || []) {
      if (removeFromList(it.bullets, original)) return;
      if (it.text && sameText(it.text, original)) {
        it.text = "";
        return;
      }
    }
  }
  if (data.certifications) {
    for (let i = 0; i < data.certifications.length; i++) {
      if (sameText(data.certifications[i].name || "", original)) {
        data.certifications.splice(i, 1);
        return;
      }
    }
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
  } else if (secLower === "volunteer") {
    const v = (data.volunteer || [])[idx];
    if (v) { v.bullets = [...(v.bullets || []), line]; }
  } else if (secLower === "certifications" || secLower === "certification") {
    data.certifications = [...(data.certifications || []), { name: line }];
  }
}

function applyReplaceBullets(data: ResumeData, spec: string, bulletsJson: string) {
  const parts = spec.split("::");
  if (parts.length !== 2) return;
  const [sec, idxStr] = parts;
  const idx = parseInt(idxStr, 10);
  if (Number.isNaN(idx)) return;
  let bullets: string[];
  try {
    bullets = JSON.parse(bulletsJson);
  } catch {
    return;
  }
  if (!Array.isArray(bullets)) return;
  const secLower = sec.toLowerCase();
  if (secLower === "experience" && data.experience?.[idx]) {
    data.experience[idx].bullets = bullets;
  } else if (secLower === "projects" && data.projects?.[idx]) {
    data.projects[idx].bullets = bullets;
  } else if (secLower === "education" && data.education?.[idx]) {
    data.education[idx].details = bullets;
  } else if (secLower === "volunteer" && data.volunteer?.[idx]) {
    data.volunteer[idx].bullets = bullets;
  }
}

const SCALAR_SECTIONS = new Set([
  "experience", "projects", "education",
  "publications", "awards", "languages",
  "volunteer", "patents", "talks", "extra_sections",
  "custom_links",
]);

function applyReplaceField(data: ResumeData, spec: string, value: string) {
  const parts = spec.split("::");
  if (parts.length !== 3) return;
  const [sec, idxStr, field] = parts;
  const secLower = sec.toLowerCase();
  if (secLower === "contact") {
    data.contact = { ...(data.contact || {}), [field]: value };
    return;
  }
  if (secLower === "resume") {
    // Top-level scalars on the Resume itself (e.g. name).
    (data as Record<string, unknown>)[field] = value;
    return;
  }
  const idx = parseInt(idxStr, 10);
  if (Number.isNaN(idx)) return;
  if (!SCALAR_SECTIONS.has(secLower)) return;
  const list = (data as unknown as Record<string, unknown[]>)[secLower];
  if (!Array.isArray(list)) return;
  const entry = list[idx] as Record<string, unknown> | undefined;
  if (!entry) return;
  entry[field] = value;
}

function _blankEntry(section: string): Record<string, unknown> {
  switch (section) {
    case "experience":
      return { title: "", company: "", location: "", start_date: "", end_date: "", bullets: [] };
    case "education":
      return { institution: "", degree: "", field: "", location: "", start_date: "", end_date: "", gpa: "", details: [] };
    case "projects":
      return { name: "", tech: "", date: "", bullets: [] };
    case "publications":
      return { title: "New publication", authors: "", venue: "", year: "", doi: "", url: "" };
    case "awards":
      return { title: "New award", issuer: "", date: "", description: "" };
    case "languages":
      return { name: "New language", proficiency: "" };
    case "volunteer":
      return { role: "New role", organization: "", location: "", start_date: "", end_date: "", bullets: [] };
    case "patents":
      return { title: "New patent", number: "", date: "", status: "", authors: "" };
    case "talks":
      return { title: "New talk", venue: "", date: "", type: "" };
    case "extra_sections":
      return { title: "New Section", content_type: "entries", items: [] };
    case "custom_links":
      return { label: "Link", url: "" };
    default:
      return {};
  }
}

const ADDABLE_SECTIONS = new Set([
  "experience", "education", "projects",
  "publications", "awards", "languages",
  "volunteer", "patents", "talks", "extra_sections",
  "custom_links",
]);

function applyAddEntry(data: ResumeData, sectionKey: string, initialJson: string) {
  const sec = (sectionKey || "").toLowerCase();
  if (!ADDABLE_SECTIONS.has(sec)) return;
  let initial: Record<string, unknown> | null = null;
  if (initialJson && initialJson !== "{}") {
    try {
      const parsed = JSON.parse(initialJson);
      if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
        initial = parsed as Record<string, unknown>;
      }
    } catch {
      // ignore — fall back to blank
    }
  }
  const entry = { ..._blankEntry(sec), ...(initial || {}) };
  const bag = data as unknown as Record<string, unknown[]>;
  if (!Array.isArray(bag[sec])) bag[sec] = [];
  bag[sec].push(entry);
  // ExtraSections render via `extra:<title>` keys in section_order. Inject one so the new entry shows up.
  if (sec === "extra_sections") {
    const title = ((entry as { title?: string }).title || "New Section").trim();
    const tag = `extra:${title}`;
    const order = (data.section_order = [...(data.section_order || [])]);
    if (!order.includes(tag)) order.push(tag);
  }
}

function applyDeleteEntry(data: ResumeData, spec: string) {
  const parts = spec.split("::");
  if (parts.length !== 2) return;
  const [sec, idxStr] = parts;
  const secLower = sec.toLowerCase();
  if (!ADDABLE_SECTIONS.has(secLower)) return;
  const idx = parseInt(idxStr, 10);
  if (Number.isNaN(idx)) return;
  const list = (data as unknown as Record<string, unknown[]>)[secLower];
  if (!Array.isArray(list)) return;
  if (idx < 0 || idx >= list.length) return;
  list.splice(idx, 1);
}

function applyToggleHidden(data: ResumeData, sectionKey: string, action: string) {
  const sec = (sectionKey || "").toLowerCase();
  if (!sec) return;
  const hidden = (data.hidden_sections = [...(data.hidden_sections || [])]);
  const has = hidden.includes(sec);
  const want = action.toLowerCase();
  if (want === "hide" && !has) hidden.push(sec);
  else if (want === "show" && has) data.hidden_sections = hidden.filter((s) => s !== sec);
  else if (want === "toggle") {
    data.hidden_sections = has ? hidden.filter((s) => s !== sec) : [...hidden, sec];
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
    const next = sg.new_skills || [];
    data.skills = next.map((c) => ({
      category: c.category || "Skills",
      skills: Array.isArray(c.skills) ? [...c.skills] : [],
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

    if (mode === "reorder_sections") {
      try {
        const nextOrder = JSON.parse(suggested);
        if (Array.isArray(nextOrder)) {
          data.section_order = nextOrder;
        }
      } catch {
        // ignore parse error
      }
      continue;
    }

    if (mode === "add_entry") {
      if (!original) continue;
      applyAddEntry(data, original, sg.suggested ?? "");
      continue;
    }
    if (mode === "delete_entry") {
      if (!original) continue;
      applyDeleteEntry(data, original);
      continue;
    }
    if (mode === "toggle_hidden") {
      if (!original) continue;
      applyToggleHidden(data, original, suggested || "toggle");
      continue;
    }

    if (mode === "set_summary") {
      if (suggested) data.summary = suggested;
      continue;
    }

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
      if (!original || !suggested) continue;
      applyReplaceBullets(data, original, suggested);
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
