# Testing Guide

How to test this app's **backend endpoints** and **UI** — both the automated
suite and a by-hand walkthrough. Pairs with `PROJECT_OVERVIEW.md` (§5 API
reference, §10 hardening checklist).

- **Backend**: automated endpoint suite (`backend/tests/api/`) + manual curl/PowerShell recipes below.
- **UI**: manual click-through checklist (no frontend test runner exists yet).

---

## A. Prerequisites

1. **Env** — copy `.env.example` → `.env` at repo root. Required: `LLM_PROVIDER`
   (`groq`|`openai`) and `GROQ_API_KEY` or `OPENAI_API_KEY`.
2. **Backend up**:
   ```powershell
   cd backend
   .\venv\Scripts\Activate.ps1
   uvicorn app.main:app --host 0.0.0.0 --port 8004 --reload
   ```
3. **Frontend up** (for UI testing):
   ```powershell
   cd frontend
   npm run dev        # http://localhost:3055
   ```
4. **A `resume_id`** — most endpoints need one. Get it by uploading (B.1) or
   scaffolding the sample (B.2). Save it:
   ```powershell
   $RID = (Invoke-RestMethod -Uri http://localhost:8055/api/resume/scaffold -Method Post -ContentType application/json -Body '{}').resume_id
   $RID
   ```
   All commands below assume `$RID` holds a valid id and `$API = "http://localhost:8055"`.
   ```powershell
   $API = "http://localhost:8055"
   ```

> The JD must be substantial: `/api/match/*` rejects anything under **200 chars**
> or **30 meaningful keywords** (`_validate_jd`). Paste a real job description.

---

## B. Backend — endpoint by endpoint

Health:
```powershell
Invoke-RestMethod "$API/health"                       # {status: ok}
```

### B.1 `POST /api/resume/upload`  (multipart)
```powershell
Invoke-RestMethod "$API/api/resume/upload" -Method Post -Form @{ file = Get-Item .\resume.pdf }
# → { resume_id, keywords[], file_ext }
```
Error paths:
- Non-PDF/DOCX extension → **400** ("Only PDF and DOCX files are supported").
- File > 10 MB → **413**.

### B.2 `POST /api/resume/scaffold`
```powershell
Invoke-RestMethod "$API/api/resume/scaffold" -Method Post -ContentType application/json -Body '{"template_id":"standard"}'
# → { resume_id, keywords[], template_id }
```

### B.3 `GET /api/resume/{id}/text` · `GET /api/resume/{id}/json`
```powershell
Invoke-RestMethod "$API/api/resume/$RID/text"
Invoke-RestMethod "$API/api/resume/$RID/json"
Invoke-RestMethod "$API/api/resume/bad-id/text"       # → 404
```

### B.4 `PATCH /api/resume/{id}/sections`
```powershell
Invoke-RestMethod "$API/api/resume/$RID/sections" -Method Patch -ContentType application/json `
  -Body '{"hidden_sections":["projects"],"section_order":["experience","skills","education"]}'
# → { resume_id, section_order, hidden_sections }
```

### B.5 `POST /api/match/`
```powershell
$jd = Get-Content .\jd.txt -Raw
Invoke-RestMethod "$API/api/match/" -Method Post -ContentType application/json `
  -Body (@{ resume_id = $RID; jd_text = $jd } | ConvertTo-Json)
# → { score, breakdown, section_scores, ceiling, diagnosis, gap_analysis, active_weights }
```
Error paths: unknown `resume_id` → **404**; JD too short → **400**.

### B.6 `POST /api/match/tailored`
```powershell
Invoke-RestMethod "$API/api/match/tailored" -Method Post -ContentType application/json `
  -Body (@{ resume_id = $RID; jd_text = $jd; accepted_suggestions = @(); new_projects = @() } | ConvertTo-Json)
# → { original{...}, tailored{ ..., improvement_plan }, delta }
```

### B.7 `POST /api/match/guidance`
```powershell
Invoke-RestMethod "$API/api/match/guidance" -Method Post -ContentType application/json `
  -Body (@{ resume_id = $RID; jd_text = $jd; section_scores = @{ Experience = 50 } } | ConvertTo-Json)
# → { sections{section: prose}, blockers[] }
```

### B.8 `/api/tailor` family
```powershell
# List templates / sample preview
Invoke-RestMethod "$API/api/tailor/templates"
Invoke-RestMethod "$API/api/tailor/sample-preview?template_id=standard"

# Suggestions (LangGraph; slow — real LLM)
Invoke-RestMethod "$API/api/tailor/suggestions" -Method Post -ContentType application/json `
  -Body (@{ resume_id = $RID; jd_text = $jd; intensity = "balanced" } | ConvertTo-Json)
# → { resume_id, sections{}, suggestions[], project_names[], jd_missing_keywords[] }

# Copilot chat
Invoke-RestMethod "$API/api/tailor/chat" -Method Post -ContentType application/json `
  -Body (@{ resume_id = $RID; jd_text = $jd; user_prompt = "make my experience metrics-driven" } | ConvertTo-Json)
# → { suggestions[], directives[], response }

# Preview (HTML, no storage)
Invoke-RestMethod "$API/api/tailor/preview" -Method Post -ContentType application/json `
  -Body (@{ resume_id = $RID; suggestions = @(); template_id = "standard" } | ConvertTo-Json)

# Apply → download a file (PDF or DOCX)
Invoke-WebRequest "$API/api/tailor/apply" -Method Post -ContentType application/json `
  -Body (@{ resume_id = $RID; suggestions = @(); format = "pdf"; template_id = "standard" } | ConvertTo-Json) `
  -OutFile tailored.pdf

# ATS check (rule-based)
Invoke-RestMethod "$API/api/tailor/ats-check" -Method Post -ContentType application/json `
  -Body (@{ resume_id = $RID; jd_text = $jd } | ConvertTo-Json)
# → { parse_score, keyword_score, section_recognition, format_warnings, missing_fields,
#     found_keywords, missing_keywords, suggestions }

# Regenerate one suggestion
Invoke-RestMethod "$API/api/tailor/regenerate" -Method Post -ContentType application/json `
  -Body (@{ jd_text = $jd; section = "Experience"; original = "Led a team"; previous_suggested = "Managed a team" } | ConvertTo-Json)

# Line / entry edits
Invoke-RestMethod "$API/api/tailor/chat-line" -Method Post -ContentType application/json `
  -Body (@{ resume_id = $RID; jd_text = $jd; section = "Experience"; original_line = "Led a team"; user_prompt = "add metrics" } | ConvertTo-Json)
Invoke-RestMethod "$API/api/tailor/chat-entry" -Method Post -ContentType application/json `
  -Body (@{ resume_id = $RID; jd_text = $jd; section = "Experience"; entry_index = 0; original_bullets = @("a","b"); header_context = @{ title = "Dev" }; user_prompt = "tighten" } | ConvertTo-Json)

# Skills / projects generation
Invoke-RestMethod "$API/api/tailor/generate-skills"  -Method Post -ContentType application/json -Body (@{ resume_id = $RID; jd_text = $jd } | ConvertTo-Json)
Invoke-RestMethod "$API/api/tailor/refresh-skills"   -Method Post -ContentType application/json -Body (@{ resume_id = $RID; jd_text = $jd } | ConvertTo-Json)
Invoke-RestMethod "$API/api/tailor/generate-projects" -Method Post -ContentType application/json -Body (@{ resume_id = $RID; jd_text = $jd; count = 3 } | ConvertTo-Json)
```
Common error paths: unknown `resume_id` → **404**; empty `jd_text`/`user_prompt`/
`original`/`original_bullets` → **400**.

### B.9 `/api/admin` (dev-only, no auth)
```powershell
Invoke-RestMethod "$API/api/admin/calibration"
Invoke-RestMethod "$API/api/admin/calibration/run" -Method Post
Start-Process "$API/api/admin/dashboard"              # opens the HTML dashboard
```

---

## C. UI — manual click-through checklist

Run frontend at `http://localhost:3055`. Walk each page; for each, check the
golden path **and** the error/empty/loading states. Open DevTools → Application →
Local/Session Storage to verify the handoff keys.

### Stage 1 — Landing (`/`)
- [ ] "Get Started" opens **ChoiceModal**; "Build Resume" disabled, "Import Resume" active.
- [ ] **TemplatePickerModal** shows thumbnails (from `/sample-preview`); a template is selectable.
- [ ] **ImportResumeModal**: upload a PDF/DOCX → live `TemplatePreview` renders on the right.
- [ ] **Error**: upload a `.txt` or a >10 MB file → user-facing error, no navigation.
- [ ] On continue, `localStorage` has `current_resume_id`, `template_id`, `home_selected_template`.

### Stage 2 — Job Search (`/job-search`)
- [ ] Paste a JD → match results appear.
- [ ] **Match** → 3 tabs render: **Overview** (color-coded score, ceiling, diagnosis),
      **Sections** (per-section scores + AI prose for low sections),
      **Suggestions** ("fix this first" card).
- [ ] Suggested-role chips link out to LinkedIn with filters applied.
- [ ] **Empty/short JD**: a JD under ~200 chars surfaces the 400 message, not a crash.
- [ ] **Loading**: spinner/skeleton while matching; **error**: LLM/timeout shows a retry affordance.
- [ ] `localStorage` has `tailor_jd_text`, `match_state`; `sessionStorage` has `linkedin_filters`.

### Stage 3 — Tailor (`/tailor`)
- [ ] 3-panel layout: Resume Editor · Copilot Chat · Live Preview.
- [ ] Suggestions load; accept / reject / inline-edit / **regenerate** each work.
- [ ] Copilot pills: tailor experience, metrics-driven bullets, align skills, **Run ATS check**.
- [ ] **Generate projects** and **generate/refresh skills** return reviewable items.
- [ ] Density / `target_pages` selector changes the preview; section reorder + hide reflect in preview.
- [ ] **Download** PDF and DOCX both succeed and open.
- [ ] **Refresh resilience**: reload mid-flow — state survives or degrades cleanly (no dead-end).
- [ ] **Template fallback**: clear or corrupt `template_id` (or set `mimic`) → falls back to `standard`.
- [ ] ErrorBoundary catches a preview/iframe failure without blanking the page.

---

## D. Running the automated suites

```powershell
cd backend
.\venv\Scripts\Activate.ps1

pytest tests/api/ -v            # HTTP-layer endpoint tests (this guide's automation)
pytest tests/unit/              # pure-function unit tests
pytest                          # everything
```

The endpoint suite (`tests/api/`) mocks the three external boundaries — Qdrant
storage, the embedding model, and the LLM client (`get_llm_client`) — so it runs
offline and fast (~9s). Fixtures live in `tests/api/conftest.py`. It does **not**
start the app lifespan (no embedding preload, no calibrator loop), so it never
hits the network. Run it before every push and in CI.
