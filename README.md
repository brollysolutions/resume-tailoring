# AI Resume Matcher & Tailoring Engine

Upload a resume, paste a job description, get LLM-powered edit suggestions, and download a tailored PDF or DOCX.

## Features

- **Resume parsing** — PDF and DOCX extraction into a structured JSON schema (PyMuPDF / python-docx)
- **Hybrid match scoring** — 6-signal blend: keyword coverage, skill taxonomy, n-gram matching, education fit, seniority gap, section-weighted cosine similarity
- **AI tailoring** — LangGraph pipeline with RAG-grounded suggestions, critique loop, and per-section intensity control
- **Copilot chat** — multi-turn resume editing via natural language
- **Portfolio project synthesis** — generates new projects from JD requirements with dedup across sessions
- **Auto-calibration** — background weight tuner that improves scoring from user acceptance patterns
- **PDF + DOCX export** — WeasyPrint rendering with density presets and target-page control

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI, LangGraph, spaCy, sentence-transformers |
| Embedding | `nomic-ai/nomic-embed-text-v1.5` (768-dim, CPU) |
| LLM | Groq (llama-3.1-8b / llama-3.3-70b) or OpenAI |
| Vector store | Qdrant |
| Caching | Redis (optional, degrades gracefully) |
| Frontend | Next.js 16 (React 19), Tailwind CSS |
| Rendering | WeasyPrint (PDF), python-docx (DOCX) |

## Quick Start (Docker)

```bash
cp .env.example .env
# Fill in GROQ_API_KEY or OPENAI_API_KEY in .env
docker compose up --build
```

- Frontend: http://localhost:3055
- Backend API: http://localhost:8055
- API docs: http://localhost:8055/docs

The HuggingFace embedding model (~270 MB) downloads automatically on first backend startup and is cached in the `hf_cache` Docker volume.

## Local Development

**Backend:**
```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python -m spacy download en_core_web_sm
uvicorn app.main:app --host 0.0.0.0 --port 8055 --reload
```

Set `PRELOAD_EMBEDDING_MODEL=False` in `.env` for instant restarts during development.

**Frontend:**
```powershell
cd frontend
npm install
npm run dev   # http://localhost:3055
```

## Environment Variables

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `LLM_PROVIDER` | Yes | `groq` | `groq` or `openai` |
| `GROQ_API_KEY` | If using Groq | — | |
| `OPENAI_API_KEY` | If using OpenAI | — | |
| `QDRANT_HOST` | Yes | `localhost` | |
| `QDRANT_PORT` | Yes | `6355` (local) / `6333` (Docker) | |
| `NEXT_PUBLIC_API_URL` | Yes | `http://localhost:8055` | **Baked into frontend build** |
| `CORS_ALLOWED_ORIGINS` | Yes | `http://localhost:3055` | Comma-separated |
| `REDIS_HOST` / `REDIS_PORT` | No | `localhost:6379` | |
| `CACHE_ENABLED` | No | `True` | Set `False` to skip Redis |
| `PRELOAD_EMBEDDING_MODEL` | No | `True` | Set `False` locally for fast restarts |

## Architecture Overview

```
Upload → Extract (PyMuPDF/docx) → LLM parse → Resume JSON → Qdrant

Match  → JD embedding → 6-signal hybrid score → gap analysis + AI section diagnosis

Tailor → LangGraph: analyze_jd → RAG retrieval → tailor_sections → critique_and_score
       → User approves suggestions → apply → render PDF/DOCX
```

All resume data lives in Qdrant (three collections: `resumes`, `generated_projects`, `candidate_evidence`). The `Resume` Pydantic model (`backend/app/models/resume_schema.py`) is the canonical data shape across the entire pipeline.

## Admin Dashboard

`GET /api/admin/dashboard` — calibration status, active weights, scoring history. No auth gate; restrict at the network/proxy level in production.

## Tests

```powershell
cd backend
.\venv\Scripts\Activate.ps1
pytest tests/unit/         # fast, no external services
pytest tests/integration/  # requires live Qdrant
```
