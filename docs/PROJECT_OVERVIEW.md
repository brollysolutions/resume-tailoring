# AI Resume Matcher & Tailoring Engine — Project Overview

> **Status: MVP.** This document is the single reference for the whole product — the
> end-to-end flow, every feature, the architecture, the API surface, and the
> hardening checklist that gates the next phase. The goal before any new feature work
> is a clean, bottleneck-free production deploy. Treat the
> [Hardening Checklist](#10-hardening-checklist-mvp--production) as the live to-do.

---

## 1. What This Product Is

An AI-powered tool that takes a candidate's resume and a target job description (JD),
scores how well they match, and helps the candidate tailor the resume to that JD —
then exports a polished PDF or DOCX.

**Core value loop:**

```
Upload resume  →  Match against a JD  →  Tailor (AI suggestions + edits)  →  Download
```

The original uploaded file is never edited. A canonical `Resume` JSON object is parsed
once at upload, and every later step (scoring, tailoring, rendering) operates on that
JSON. Output is always freshly rendered from the JSON.

---

## 2. End-to-End User Flow

Three pages, handing off state through `localStorage` / `sessionStorage`. The nav bar
is hidden on all three (they are a focused linear funnel).

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 1 — Landing  (/)                                                        │
│    Get Started → ChoiceModal → TemplatePickerModal → ImportResumeModal         │
│    User uploads resume + picks a template.                                      │
│    Writes: home_selected_template, current_resume_id, template_id              │
└───────────────────────────────┬───────────────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 2 — Job Search  (/job-search?resume_id=…)                               │
│    Paste JD → auto-clean → Match → 3-tab results                               │
│    Tabs: Overview · Sections · Suggestions                                      │
│    Suggested roles → LinkedIn job search (with filters)                         │
│    Writes: tailor_jd_text, match_state, linkedin_filters                        │
└───────────────────────────────┬───────────────────────────────────────────────┘
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  STAGE 3 — Tailor  (/tailor)                                                   │
│    3-panel: Resume Editor | Copilot Chat | Live Preview                         │
│    AI suggestions, project/skills generation, ATS check, improvement plan       │
│    Download PDF / DOCX                                                           │
│    Reads: current_resume_id, tailor_jd_text, template_id, tailor_prefetch       │
└─────────────────────────────────────────────────────────────────────────────┘
```

### State handoff keys

| Key | Store | Purpose |
|-----|-------|---------|
| `home_selected_template` | localStorage | Template chosen on landing, persists across pages |
| `current_resume_id` | localStorage | The uploaded resume's Qdrant ID |
| `template_id` | localStorage | Active render template |
| `tailor_jd_text` | localStorage | JD carried from job-search to tailor |
| `match_state` | localStorage | Full match result (score, breakdown, section scores, gaps, diagnosis) |
| `tailor_prefetch` | sessionStorage | Pre-fetched resume JSON for instant tailor-page load |
| `linkedin_filters` | sessionStorage | Job-search filter selections (location, experience, work type, …) |

### Stage detail

- **Stage 1 — Landing (`/`):** "Get Started" CTA opens `ChoiceModal` (Build Resume —
  coming soon; Import Resume — active) → `TemplatePickerModal` (thumbnail grid from
  `/api/tailor/sample-preview`) → `ImportResumeModal` (split pane: `UploadZone` left,
  live `TemplatePreview` right). Upload calls `/api/resume/upload`.
- **Stage 2 — Job Search (`/job-search`):** JD textarea with auto-clean
  then `/api/match/`. Results render as three tabs
  (Overview / Sections / Suggestions). Suggested-role chips link out to LinkedIn with
  the filters panel.
- **Stage 3 — Tailor (`/tailor`):** 3-panel workspace. Suggestions come from
  `/api/tailor/suggestions` (LangGraph). Copilot chat, project/skills generation, ATS
  check, and the improvement-plan sidebar all live here. Download via `/api/tailor/apply`.

---

## 3. Feature Catalog

### Upload & parsing
- Accepts PDF / DOCX, ≤ 10 MB. Raw text via PyMuPDF / python-docx.
- One-shot LLM parse into the canonical `Resume` schema (JSON fallback on failure).
- **Hallucination guard** (`extractor._filter_hallucinated_sections`): drops any
  entry whose identifying field isn't traceable to the raw text; nukes an invented summary.
- URL normalization on contact fields (`url_utils.normalize_url`).
- Embedding (nomic-embed-text-v1.5, 768-dim) stored in Qdrant alongside text + JSON.

### Matching & scoring
- **6-signal hybrid score** (see [§4](#hybrid-scoring)): keyword, skill, n-gram,
  education, seniority, section-weighted cosine.
- **Ceiling detection** — realistic max score for the profile given hard JD requirements.
- **Gap analysis** — missing keywords, section gaps, low sections (each with a reason).
- **AI section diagnosis** — when any section scores < 65, one LLM call writes a
  one-paragraph "why this section is low" per low section (skipped entirely on strong matches).

### Three-tab match results
- **Overview** — overall score (color-coded), ceiling, diagnosis card, experience-gap alert.
- **Sections** — per-section scores with AI prose explanations for low sections.
- **Suggestions** — "fix this first" card targeting the weakest section.
- **Suggested roles** — keyword-derived role chips, clickable into LinkedIn job search.

### Tailoring
- `/api/tailor/suggestions` runs the LangGraph pipeline (analyze → RAG → tailor → critique).
- Per-section tailoring **intensity**: Light / Balanced / Aggressive (global + per-section).
- Accept / reject / inline-edit each suggestion; **regenerate** an alternative for one line.
- Line- and entry-level interactive edits (`/chat-line`, `/chat-entry`).

### Copilot chat
- Stateful LangGraph (`route_intent → dispatch → compose_reply`), per-conversation memory.
- Preset pills: tailor experience, make bullets metrics-driven, align skills, **Run ATS check**.
- Never mutates the resume directly — returns pending suggestions for approval.

### ATS simulation *(new)*
- Rule-based ATS compliance check (`ats_simulator.run_ats_check`).
- Returns: parse score, keyword score, section-recognition map, format warnings,
  missing contact fields, found/missing keywords, ranked action suggestions.
- Surfaced via the "Run ATS check" copilot pill → `/api/tailor/ats-check`.

### Improvement plan *(new)*
- Deterministic (no-LLM) planner (`improvement_planner.build_improvement_plan`).
- Returns current score → achievable ceiling, ranked keyword actions (split skill vs.
  narrative, with estimated point gain per keyword), and blockers (experience /
  education / seniority caps).
- Per-section coaching prose from `/api/match/guidance`.
- Rendered in the "How to improve your match" sidebar on the tailor page.

### Project & skills generation
- **Project synthesis** — two-stage LLM (`analyze_jd_for_projects` → `synthesize_projects`)
  with cross-session dedup via the `generated_projects` Qdrant collection.
- **Skills goldmine** — generate skills from tailored content, refresh on current state,
  or edit manually (category rename/delete/move, skill add/remove).

### Rendering & export
- Templates: `standard` (default) and `modern-blue`. Each has a paired DOCX builder.
- Density presets (`latex-tight`, `compact`, `standard`, `expanded`) + `target_pages`
  auto-selection.
- Section reorder (`section_order`) and hide (`hidden_sections`), honored by HTML + DOCX.
- Export PDF (WeasyPrint) or DOCX.

### Calibration system *(active development)*
- Auto-calibrator background loop tunes the 6 signal weights from implicit labels
  (upload / suggestion / accept events).
- Weights hot-swapped at runtime from `weights_store`; history checkpointed.
- Admin dashboard (HTML, auto-polling) at `/api/admin/dashboard` — **dev-only, no auth**.

---

## 4. Architecture

### Data flow

```
UPLOAD
  PDF/DOCX → raw text → [LLM parse → Resume JSON] + [LLM keywords] + [embedding]
  → Qdrant `resumes` (payload: text, resume_json, original_path, file_ext, filename)

MATCH
  JD text → embedding → 6-signal hybrid score (weights from weights_store)
  → section scores + ceiling + gap analysis (+ AI diagnosis if low sections)

TAILOR
  Resume JSON + JD → LangGraph:
    analyze_jd → retrieve_rag_context (candidate_evidence) → tailor_sections → critique_and_score
  → user approves suggestions → apply_suggestions() → render_html()/render_docx()
```

### Load-bearing design decisions

- **`Resume` Pydantic model** (`backend/app/models/resume_schema.py`) is the single
  source of truth. All list fields have `@field_validator` coercions — route LLM output
  through them, never set raw.
- **Qdrant is the primary (only) store.** Three collections: `resumes`,
  `generated_projects`, `candidate_evidence`. **Postgres/SQLAlchemy/Alembic are present
  in requirements but unused** — don't model new features against a relational schema.
- **LLM module split into 5 files** (`llm_client`, `llm_helpers`, `llm_chat`,
  `llm_synthesis`, `llm_prompts`). All calls funnel through `_chat()` in `llm_client.py`.
  Two model tiers: **fast** (`get_model_name()`, default `llama-3.1-8b-instant`) for
  bulk/edit; **smart** (`get_smart_model()`, default `llama-3.3-70b-versatile`) for
  routing/answers. Prompts live only in `llm_prompts.py`. There is no `llm.py`.
- **Keyword-injection ↔ scoring coupling** via `keyword_utils.py`
  (`_significant_tokens`, `_top_jd_tokens`). The orchestrator injects the same
  JD-top-missing tokens that the scorer rewards — so every accepted honest keyword
  visibly moves the score (~1–2%/token). Noise filtering = stopwords + curated
  generic-vocab block-list + spaCy NER (drops cities/orgs/dates) + `min_freq` floor.
- **Two LangGraph pipelines:** the 4-node **tailor graph** (`tailor_graph.py`,
  `analyze_jd → retrieve_rag_context → tailor_sections → critique_and_score`, loops up
  to `max_iterations=2`) and the 3-node **chat graph** (`tailor_chat_graph.py`,
  `route_intent → dispatch → compose_reply`, `MemorySaver` keyed on resume+jd+`_chat`).

### Hybrid scoring

Six calibrated signals blended in `match_logic/hybrid_scorer.py` (default weights;
hot-swapped from `weights_store.get_weights()`):

| Signal | Weight | What it measures |
|--------|--------|------------------|
| `w_kw` | 0.30 | BM25 keyword coverage (required 70% / preferred 30%) |
| `w_skill` | 0.20 | Skill taxonomy + domain alignment |
| `w_ngram` | 0.10 | Multi-word skill phrases ("machine learning", "CI/CD") |
| `w_edu` | 0.05 | Education / degree-level fit |
| `w_sen` | 0.10 | Seniority / years-of-experience gap |
| `w_cos` | 0.25 | Section-weighted semantic cosine (Skills .40 / Exp .35 / Proj .20 / Summary .05) |

Special rules: n-gram weight is redistributed into `w_kw` when the JD has no phrases;
section-weighted cosine replaces whole-doc cosine when section cosines are available;
raw cosine is remapped through `[p_low, p_high]` gates.

---

## 5. API Reference

Mount points: `/api/resume`, `/api/match`, `/api/tailor`, `/api/admin`.

### `/api/resume`
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/upload` | Parse + embed an uploaded resume (PDF/DOCX, ≤10 MB) → `{resume_id, keywords[]}` |
| POST | `/scaffold` | Create a Qdrant point from the John Doe sample (Build Resume path) |
| GET | `/{resume_id}/text` | Canonical plaintext + filename + ext |
| GET | `/{resume_id}/json` | Parsed `Resume` JSON (lazy-cleans tech fields) |
| PATCH | `/{resume_id}/sections` | Update `section_order` / `hidden_sections` |

### `/api/match`
| Method | Path | Purpose |
|--------|------|---------|
| POST | `/` | Score original resume → score, breakdown, section scores, ceiling, diagnosis, gap_analysis, active_weights |
| POST | `/tailored` | Before/after with suggestions applied → original + tailored (incl. `improvement_plan`) + delta |
| POST | `/guidance` | LLM coaching prose for low sections + blockers (no embeddings) |

### `/api/tailor`
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/templates` | List render templates |
| GET | `/sample-preview` | HTML preview of the sample resume (thumbnail) |
| POST | `/suggestions` | Main tailor graph (analyze → RAG → tailor → critique) |
| POST | `/chat` | Stateful copilot (returns pending suggestions + directives) |
| POST | `/preview` | Render HTML (no storage) |
| POST | `/apply` | Stream PDF/DOCX download |
| POST | `/ats-check` | Rule-based ATS simulation |
| POST | `/regenerate` | Fresh alternative for one suggestion |
| POST | `/chat-line` | Per-line interactive rewrite |
| POST | `/chat-entry` | Per-entry bullets rewrite (keeps count) |
| POST | `/generate-skills` | Wholesale Skills regen from tailored content |
| POST | `/refresh-skills` | Re-run Skills tailor on current state |
| POST | `/generate-projects` | Two-stage project synthesis + dedup |

### `/api/admin` *(dev-only, no auth gate)*
| Method | Path | Purpose |
|--------|------|---------|
| GET | `/calibration` | Active weights + history + per-section stats + last attempt |
| POST | `/calibration/run` | Trigger one calibration cycle synchronously |
| GET | `/dashboard` | Self-contained HTML dashboard (polls every 5s) |

---

## 6. Backend Module Map

| Module | Role |
|--------|------|
| `app/main.py` | FastAPI app, CORS (localhost:3004), startup model preload, calibrator loop |
| `app/api/resume.py` | Upload / scaffold / fetch / section-edit endpoints |
| `app/api/match.py` | Match, tailored (before/after + improvement plan), guidance |
| `app/api/tailor.py` | All tailoring endpoints incl. ATS check |
| `app/api/admin.py` | Calibration endpoints + dashboard |
| `app/api/match_logic/hybrid_scorer.py` | 6-signal calibrated blend |
| `app/api/match_logic/section_scorer.py` | Per-section scores + plaintext |
| `app/api/match_logic/section_embedder.py` | Per-section max-pair cosine |
| `app/api/match_logic/ceiling_detector.py` | Ceiling + hard-requirement parsing |
| `app/api/match_logic/gap_analyzer.py` | Missing keywords / section gaps / low sections |
| `app/api/match_logic/improvement_planner.py` | **New** — deterministic improvement plan |
| `app/api/match_logic/nlp_utils.py` | BM25, skill extraction |
| `app/core/extractor.py` | LLM parse → `Resume` + hallucination guard |
| `app/core/keyword_utils.py` | Shared token logic (injection ↔ scoring); two spaCy pipelines |
| `app/core/llm_client.py` | `_chat()` entrypoint + model tiers |
| `app/core/llm_prompts.py` | All prompt constants |
| `app/core/llm_helpers.py` | Per-section tailors, keywords, `analyze_low_sections` |
| `app/core/llm_chat.py` | Interactive line-edit ops |
| `app/core/llm_synthesis.py` | Project synthesis + humanization |
| `app/core/tailor_graph.py` | LangGraph tailor pipeline (`compiled_tailor_graph`) |
| `app/core/tailor_chat_graph.py` | LangGraph copilot pipeline |
| `app/core/tailor_orchestrator.py` | Helper library for the tailor graph |
| `app/core/rag_service.py` | Section chunking + `candidate_evidence` retrieval |
| `app/core/ats_simulator.py` | **New** — rule-based ATS compliance check |
| `app/core/url_utils.py` | **New** — `normalize_url` for contact fields |
| `app/core/suggestion_applier.py` | Applies accepted edits onto the model |
| `app/core/renderer.py` | HTML/PDF/DOCX render, density presets, templates |
| `app/core/vector_db.py` | Qdrant client + embedding model |
| `app/core/cache.py` | Optional Redis cache (graceful no-op) |
| `app/core/weights_store.py` | Active-weights persistence + history |
| `app/core/auto_calibrator.py` | Background weight tuning |
| `app/core/implicit_labeler.py` | Labels from user actions |
| `app/models/resume_schema.py` | Canonical `Resume` Pydantic model |

---

## 7. Frontend Module Map

| Module | Role |
|--------|------|
| `app/page.tsx` | Landing; mounts ChoiceModal → TemplatePicker → ImportResume |
| `app/job-search/page.tsx` | JD paste + match + 3-tab results + LinkedIn filters |
| `app/tailor/page.tsx` | 3-panel tailor workspace |
| `components/ChoiceModal.tsx` | Build vs. Import choice |
| `components/TemplatePickerModal.tsx` | Template thumbnail grid |
| `components/ImportResumeModal.tsx` | Upload + live preview split pane |
| `components/UploadZone.tsx` | Drag-drop upload (needs `templateId` + `onUploaded`) |
| `components/Stepper.tsx` / `StepContent.tsx` / `steps/*` | Tailor step chrome + bodies |
| `components/DiffViewer.tsx` | Per-suggestion approve/reject/edit |
| `components/CopilotChat.tsx` | Floating copilot panel (incl. ATS report directive) |
| `components/IntensitySelector.tsx` | Light/Balanced/Aggressive (global + per-section) |
| `components/ResumeEditor.tsx` / `ResumePreview.tsx` / `TemplatePreview.tsx` | Edit + live preview |
| `components/Tabs.tsx` | Segmented control for results panel |
| `components/SkillsStep.tsx` / `SkillsAiChat.tsx` / `SkillsRegenStep.tsx` / `SkillsSuggestionsInline.tsx` | Skills flows |
| `components/ErrorBoundary.tsx` | React error boundary |

All API calls target `process.env.NEXT_PUBLIC_API_URL` (default `http://localhost:8004`).

---

## 8. Tech Stack & Ports

| Layer | Tech |
|-------|------|
| Backend | FastAPI (Python), Pydantic, LangGraph |
| Frontend | Next.js 16 / React 19 (TypeScript) |
| Vector store | Qdrant (primary store) |
| Embeddings | nomic-embed-text-v1.5 (768-dim) |
| LLM | Groq (`llama-3.1-8b-instant` / `llama-3.3-70b-versatile`) or OpenAI (`gpt-4o`) |
| Rendering | WeasyPrint (PDF), python-docx (DOCX), Jinja2 templates |
| NLP | spaCy (`en_core_web_sm`), BM25 |
| Cache | Redis (optional; graceful degradation) |

| Service | Local port | Docker-internal |
|---------|-----------|-----------------|
| Backend API | 8004 | — |
| Frontend | 3004 | — |
| Qdrant | 6334 | 6333 |
| Postgres (unused) | 5434 | 5432 |
| Redis (optional) | 6379 | 6379 |

---

## 9. Local Setup & Run

```powershell
# 1. Env: copy .env.example → .env at repo root.
#    Required: LLM_PROVIDER (groq|openai), GROQ_API_KEY or OPENAI_API_KEY.

# 2. Backend
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m spacy download en_core_web_sm
uvicorn app.main:app --host 0.0.0.0 --port 8004 --reload

# 3. Frontend
cd frontend
npm install
npm run dev        # http://localhost:3004
```

Docker (full stack): `docker compose up --build`.

Tests (backend): `cd backend && .\venv\Scripts\Activate.ps1 && pytest`
(`asyncio_mode = auto`; mocks for `_chat`, `get_embedding`, `get_qdrant_client` in
`conftest.py`). **No frontend test runner exists yet.**

---

## 10. Hardening Checklist (MVP → Production)

Living to-do for reaching a clean, bottleneck-free deploy. Items are concerns to
**verify or close**, not confirmed bugs. Check off as resolved.

### Backend correctness
- [ ] Validate every endpoint's error paths (missing resume_id, malformed JD, oversized/corrupt upload).
- [ ] Confirm hallucination guard + field validators cover all `Resume` list fields end-to-end.
- [ ] Verify LangGraph loop termination (`max_iterations`) can't hang or runaway-cost.
- [ ] Confirm `weights_store` atomic writes + mtime cache behave under concurrent requests.

### Security
- [ ] **Gate `/api/admin/*` behind auth** before any non-local deploy (currently no auth).
- [ ] Confirm prompt-injection hardening on JD/resume inputs (delimiter discipline) holds for all LLM calls.
- [ ] Lock CORS to real frontend origin(s) for production (currently localhost:3004).
- [ ] Ensure secrets only via env; no keys in repo or logs.

### UI / UX
- [ ] Error + empty + loading states on all three pages (upload fail, match fail, LLM timeout).
- [ ] ErrorBoundary coverage around the tailor workspace and preview iframe.
- [ ] Mobile / small-viewport pass on the 3-panel tailor layout.
- [ ] Accessibility sweep (focus order, labels, color-contrast on score chips).

### Project-flow integrity
- [ ] Verify every sessionStorage/localStorage handoff key is set and read (no dead-end if a key is missing).
- [ ] Deep-link / refresh resilience on `/job-search` and `/tailor` (state survives reload or degrades cleanly).
- [ ] Template fallback to `standard` when `template_id` is absent or stale (`mimic`).

### Performance / bottlenecks
- [ ] Profile tailor-graph latency (parallel per-section LLM calls); set sane timeouts.
- [ ] Confirm Redis caching actually hits for `/match/tailored` + `/match/guidance`; measure miss cost.
- [ ] Embedding model preload vs. cold-start tradeoff documented per environment.
- [ ] Debounce / cancel in-flight match + preview requests on rapid edits.

### Deployment / ops
- [ ] Production Dockerfiles + compose reviewed; remove the unused Postgres service or justify keeping it.
- [ ] Health-check endpoint(s) + readiness for Qdrant / embedding model.
- [ ] Structured logging + an error-tracking hook on both tiers.
- [ ] Persistent volumes for Qdrant + uploads verified across restarts.

### Testing / observability
- [ ] **Add a frontend test runner** (none exists) — at least smoke tests for the 3 pages.
- [ ] Expand backend integration coverage for the new ATS + improvement-plan paths.
- [ ] Calibration data pipeline sanity checks (no silent corruption of `weights_active.json`).

---

*This document supersedes nothing in `CLAUDE.md` — it complements it as the product-level
overview. When architecture changes, update both.*
ts it as the product-level
overview. When architecture changes, update both.*
