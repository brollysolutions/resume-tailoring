import json
import logging
import re
import time
from io import BytesIO
from typing import Literal, Optional
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)
from pydantic import BaseModel

from app.core.tailor_orchestrator import (
    generate_section_suggestions,
    build_skills_contexts,
)
from app.core.llm_helpers import (
    tailor_skills,
    extract_jd_hard_requirements,
    generate_skills_from_tailored,
)
from app.core.llm_synthesis import (
    humanize_project_bullets,
)
from app.core.llm_chat import (
    regenerate_one_suggestion,
)
from app.core.renderer import (
    render_html,
    render_pdf,
    render_docx,
    apply_suggestions,
    resume_to_plaintext,
    list_templates,
)
from app.models.resume_schema import Resume

router = APIRouter()

DOCX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MEDIA_TYPE = "application/pdf"


# Geo-modifier scrub used when feeding the candidate's existing bullets back to
# the project synthesizer. Without this, the LLM mimics "X-based" phrasing in
# the user's resume and produces names like "Bangalore-based Onboarding System".
_GEO_TOKENS = (
    "bangalore", "hyderabad", "chennai", "mumbai", "delhi", "pune", "kolkata",
    "noida", "gurgaon", "gurugram", "bengaluru",
    "new york", "san francisco", "seattle", "london", "berlin", "paris",
    "tokyo", "singapore", "sydney", "toronto", "dublin", "amsterdam",
    "india", "usa", "us", "uk", "europe",
)
_GEO_HYPHEN_RE = re.compile(r"\b\w+-based\b", re.IGNORECASE)
_GEO_TOKEN_RE = re.compile(
    r"\b(" + "|".join(re.escape(t) for t in _GEO_TOKENS) + r")\b",
    re.IGNORECASE,
)


def _scrub_locations(text: str) -> str:
    """Strip geographic qualifiers from a string."""
    if not text:
        return text
    out = _GEO_HYPHEN_RE.sub("", text)
    out = _GEO_TOKEN_RE.sub("", out)
    return re.sub(r"\s{2,}", " ", out).strip(" -–,")


# Prepositions that should never end a project name (dangling "Event-Driven System for").
_DANGLING_PREPOSITIONS = frozenset({
    "for", "of", "with", "in", "to", "by", "on", "at", "from", "and",
    "or", "the", "a", "an", "via", "using", "into", "onto", "as",
})


def _fix_project_name(name: str) -> str:
    """Trim any trailing prepositions/articles from a project name.
    Returns empty string if name becomes too short to be useful."""
    if not name:
        return name
    words = name.strip().split()
    while words and words[-1].lower() in _DANGLING_PREPOSITIONS:
        words = words[:-1]
    result = " ".join(words).strip(" -–,")
    # Require at least 2 words so "Kafka" alone isn't a project name.
    return result if len(words) >= 2 else ""


class TailorRequest(BaseModel):
    resume_id: str
    jd_text: str


class PreviewRequest(BaseModel):
    resume_id: str
    suggestions: list = []
    template_id: Optional[str] = "modern"
    new_projects: Optional[list] = None
    layout_density: Optional[str] = None  # compact | standard | expanded | None (auto)


class ApplyRequest(BaseModel):
    resume_id: str
    suggestions: list
    format: Literal["pdf", "docx"] = "pdf"
    template_id: Optional[str] = "modern"
    new_projects: Optional[list] = None
    layout_density: Optional[str] = None  # compact | standard | expanded | None (auto)


class GenerateProjectsRequest(BaseModel):
    resume_id: str
    jd_text: str
    count: int = 3
    exclude_names: list = []


class RegenerateRequest(BaseModel):
    jd_text: str
    section: str
    original: str
    previous_suggested: str
    mode: Literal["replace", "add_skill"] = "replace"


class RefreshSkillsRequest(BaseModel):
    resume_id: str
    jd_text: str
    accepted_suggestions: list = []
    new_projects: Optional[list] = None
    next_id: int = 1
    user_prompt: Optional[str] = None


class GenerateSkillsTailoredBlock(BaseModel):
    summary: Optional[str] = None
    experience: list[dict] = []
    projects: list[dict] = []
    education: list[dict] = []


class GenerateSkillsRequest(BaseModel):
    resume_id: str
    jd_text: str
    tailored: Optional[GenerateSkillsTailoredBlock] = None


class ChatLineRequest(BaseModel):
    resume_id: str
    jd_text: str
    section: str
    original_line: str
    user_prompt: str
    accepted_suggestions: list = []
    new_projects: Optional[list] = None


class ChatEntryRequest(BaseModel):
    """RAG-style rewrite of a whole entry's bullets as a coherent unit.
    Section is Experience or Projects; the LLM gets the entry header
    (role/company or project name/tech) as read-only context plus the full
    tailored resume so its rewrites stay grounded."""
    resume_id: str
    jd_text: str
    section: Literal["Experience", "Projects"]
    entry_index: int
    original_bullets: list[str]
    header_context: dict
    user_prompt: str
    accepted_suggestions: list = []
    new_projects: Optional[list] = None


def _replace_projects(resume: Resume, new_projects: list) -> Resume:
    """Replace existing projects 1-to-1 by index.
    The k-th new project replaces the k-th existing project.
    Existing projects past the new list are kept; new projects past existing are appended."""
    from app.models.resume_schema import ProjectEntry
    new_entries = [
        ProjectEntry(
            name=p.get("name", ""),
            tech=p.get("tech") or None,
            bullets=p.get("bullets", []),
        )
        for p in new_projects
    ]
    existing = list(resume.projects)
    merged = []
    for i in range(max(len(existing), len(new_entries))):
        if i < len(new_entries):
            merged.append(new_entries[i])
        else:
            merged.append(existing[i])
    return resume.model_copy(update={"projects": merged})


def _load_resume(resume_id: str) -> tuple[Resume, str]:
    from app.core.vector_db import init_qdrant
    q_client = init_qdrant("resumes")
    results = q_client.retrieve(collection_name="resumes", ids=[resume_id], with_payload=True)
    if not results:
        raise HTTPException(status_code=404, detail="Resume not found.")
    payload = results[0].payload
    raw_json = payload.get("resume_json")
    if not raw_json:
        raise HTTPException(status_code=500, detail="Resume has not been parsed yet.")
    try:
        resume = Resume.model_validate(json.loads(raw_json))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stored resume JSON is invalid: {e}")
    original_filename = payload.get("original_filename") or "resume"
    return resume, original_filename


@router.get("/templates")
async def get_templates():
    return {"templates": list_templates()}


@router.post("/suggestions")
async def get_tailoring_suggestions(request: TailorRequest):
    if not request.jd_text.strip():
        raise HTTPException(status_code=400, detail="Job description cannot be empty.")
    t0 = time.perf_counter()
    try:
        t_load = time.perf_counter()
        resume, _ = _load_resume(request.resume_id)
        logger.info("[TIMING] suggestions: load_resume=%.3fs", time.perf_counter() - t_load)

        t_llm = time.perf_counter()
        result = await generate_section_suggestions(resume, request.jd_text)
        logger.info("[TIMING] suggestions: llm_sections=%.3fs", time.perf_counter() - t_llm)

        logger.info("[TIMING] suggestions: TOTAL=%.3fs  returned=%d suggestions  missing_kw=%d",
                    time.perf_counter() - t0, len(result.get("suggestions", [])),
                    len(result.get("jd_missing_keywords", [])))

        # Log total suggestions per (resume_id, jd_hash) — used by implicit_labeler
        # to compute acceptance ratio against the /apply event.
        try:
            import hashlib as _h
            from app.core.implicit_labeler import log_suggestion_event
            jd_hash = _h.sha256(request.jd_text.encode("utf-8", errors="ignore")).hexdigest()[:16]
            log_suggestion_event(
                "suggestions_generated",
                resume_id=request.resume_id,
                jd_hash=jd_hash,
                total=len(result.get("suggestions", [])),
            )
        except Exception as e:
            logger.debug("suggestion event log failed (non-fatal): %s", e)

        return {
            "resume_id": request.resume_id,
            "sections": result["sections"],
            "suggestions": result["suggestions"],
            "project_names": result.get("project_names", []),
            "jd_missing_keywords": result.get("jd_missing_keywords", []),
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/preview")
async def preview_tailoring(request: PreviewRequest):
    t0 = time.perf_counter()
    try:
        t_load = time.perf_counter()
        resume, _ = _load_resume(request.resume_id)
        logger.info("[TIMING] preview: load_resume=%.3fs", time.perf_counter() - t_load)

        if request.new_projects is not None:
            resume = _replace_projects(resume, request.new_projects)

        t_render = time.perf_counter()
        tailored = apply_suggestions(resume, request.suggestions)
        html = render_html(tailored, request.template_id, layout_density=request.layout_density)
        logger.info("[TIMING] preview: render=%.3fs  template=%s",
                    time.perf_counter() - t_render, request.template_id)

        logger.info("[TIMING] preview: TOTAL=%.3fs", time.perf_counter() - t0)
        return {"type": "html", "html": html}
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/apply")
async def apply_tailoring(request: ApplyRequest):
    t0 = time.perf_counter()
    try:
        resume, original_filename = _load_resume(request.resume_id)
        if request.new_projects is not None:
            resume = _replace_projects(resume, request.new_projects)
        tailored = apply_suggestions(resume, request.suggestions)
        raw_base = original_filename.rsplit(".", 1)[0] if "." in original_filename else original_filename
        # Strip characters that would break the Content-Disposition header value
        safe_base = re.sub(r'[^\w\-. ]', '_', raw_base).strip() or "resume"

        t_render = time.perf_counter()
        if request.format == "pdf":
            data = render_pdf(tailored, request.template_id, layout_density=request.layout_density)
            filename = f"{safe_base}_tailored.pdf"
            media_type = PDF_MEDIA_TYPE
        else:
            data = render_docx(tailored, request.template_id, layout_density=request.layout_density)
            filename = f"{safe_base}_tailored.docx"
            media_type = DOCX_MEDIA_TYPE
        logger.info("[TIMING] apply: render_%s=%.3fs  TOTAL=%.3fs",
                    request.format, time.perf_counter() - t_render, time.perf_counter() - t0)

        # Implicit-label event: user downloaded a tailored resume — count this
        # as acceptance signal. accepted_count = len(suggestions sent at /apply).
        return StreamingResponse(
            BytesIO(data),
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/regenerate")
async def regenerate_suggestion(request: RegenerateRequest):
    """Produce a fresh alternative for one suggestion. The user already saw
    `previous_suggested` and wants a different angle."""
    if not request.jd_text.strip():
        raise HTTPException(status_code=400, detail="Job description cannot be empty.")
    if not request.original.strip():
        raise HTTPException(status_code=400, detail="Original text cannot be empty.")
    t0 = time.perf_counter()
    try:
        new_text = await regenerate_one_suggestion(
            section=request.section,
            original=request.original,
            previous_suggested=request.previous_suggested,
            jd_text=request.jd_text,
            mode=request.mode,
        )
        logger.info("[TIMING] regenerate: TOTAL=%.3fs  section=%s",
                    time.perf_counter() - t0, request.section)
        return {"suggested": new_text}
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat-line")
async def chat_line(request: ChatLineRequest):
    """RAG-style per-line rewrite. Loads the current resume, applies any
    already-accepted suggestions + kept projects, then feeds the WHOLE tailored
    resume + JD as context to the LLM so the rewrite stays grounded."""
    if not request.original_line.strip():
        raise HTTPException(status_code=400, detail="original_line cannot be empty.")
    if not request.user_prompt.strip():
        raise HTTPException(status_code=400, detail="user_prompt cannot be empty.")
    t0 = time.perf_counter()
    try:
        from app.core.llm_chat import chat_improve_line

        resume, _ = _load_resume(request.resume_id)
        if request.new_projects:
            resume = _replace_projects(resume, request.new_projects)
        if request.accepted_suggestions:
            resume = apply_suggestions(resume, request.accepted_suggestions)
        resume_context = resume_to_plaintext(resume)

        # Compute top JD keywords missing from current resume — inject into prompt
        from app.core.keyword_utils import _significant_tokens, _top_jd_tokens
        jd_tokens = _significant_tokens(request.jd_text)
        resume_tokens = _significant_tokens(resume_context)
        missing = jd_tokens - resume_tokens
        top_jd = _top_jd_tokens(request.jd_text, k=40)
        keywords_to_inject = sorted(top_jd & missing)[:15]

        rewritten = await chat_improve_line(
            section=request.section,
            original_line=request.original_line,
            user_prompt=request.user_prompt,
            jd_text=request.jd_text,
            resume_context=resume_context,
            keywords_to_inject=keywords_to_inject,
        )
        logger.info("[TIMING] chat-line: TOTAL=%.3fs  section=%s",
                    time.perf_counter() - t0, request.section)
        return {"rewritten": rewritten}
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/chat-entry")
async def chat_entry(request: ChatEntryRequest):
    """RAG-style rewrite of an entry's bullets as a coherent unit. The LLM
    returns exactly len(original_bullets) bullets in order; if it drifts on
    count we pad/truncate against the originals so the frontend can pair 1:1."""
    if not request.original_bullets:
        raise HTTPException(status_code=400, detail="original_bullets cannot be empty.")
    if not request.user_prompt.strip():
        raise HTTPException(status_code=400, detail="user_prompt cannot be empty.")
    t0 = time.perf_counter()
    try:
        from app.core.llm_chat import chat_improve_entry

        resume, _ = _load_resume(request.resume_id)
        if request.new_projects:
            resume = _replace_projects(resume, request.new_projects)
        if request.accepted_suggestions:
            resume = apply_suggestions(resume, request.accepted_suggestions)
        resume_context = resume_to_plaintext(resume)

        # Compute top JD keywords missing from current resume — inject into prompt
        from app.core.keyword_utils import _significant_tokens, _top_jd_tokens
        jd_tokens = _significant_tokens(request.jd_text)
        resume_tokens = _significant_tokens(resume_context)
        missing = jd_tokens - resume_tokens
        top_jd = _top_jd_tokens(request.jd_text, k=40)
        keywords_to_inject = sorted(top_jd & missing)[:15]

        rewritten = await chat_improve_entry(
            section=request.section,
            header_context=request.header_context or {},
            original_bullets=request.original_bullets,
            user_prompt=request.user_prompt,
            jd_text=request.jd_text,
            resume_context=resume_context,
            keywords_to_inject=keywords_to_inject,
        )

        logger.info("[TIMING] chat-entry: TOTAL=%.3fs  section=%s  bullets=%d",
                    time.perf_counter() - t0, request.section, len(rewritten))
        return {"rewritten_bullets": rewritten}
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-skills")
async def generate_skills(request: GenerateSkillsRequest):
    """Wholesale AI regen of the Skills section, grounded in the tailored
    Summary/Experience/Projects/Education the candidate has produced. Returns
    a complete Skills section; frontend applies it via a replace_section
    pseudo-suggestion through the existing approved queue."""
    if not request.jd_text.strip():
        raise HTTPException(status_code=400, detail="Job description cannot be empty.")
    t0 = time.perf_counter()
    try:
        resume, _ = _load_resume(request.resume_id)
        tailored = request.tailored or GenerateSkillsTailoredBlock()

        # Fall back to the stored resume content for any block the client did
        # not send. The candidate may regen Skills before touching another
        # section — that's fine, the original content is honest evidence too.
        summary = tailored.summary if tailored.summary is not None else (resume.summary or "")
        experience = tailored.experience or [e.model_dump() for e in resume.experience]
        projects = tailored.projects or [p.model_dump() for p in resume.projects]
        education = tailored.education or [e.model_dump() for e in resume.education]

        result = await generate_skills_from_tailored(
            jd_text=request.jd_text,
            tailored_summary=summary,
            tailored_experience=experience,
            tailored_projects=projects,
            tailored_education=education,
        )

        logger.info(
            "[TIMING] generate-skills: TOTAL=%.3fs  categories=%d",
            time.perf_counter() - t0,
            len(result.get("skills", [])),
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/refresh-skills")
async def refresh_skills(request: RefreshSkillsRequest):
    """Re-run only the Skills tailor against the current resume state.
    Projects accepted / generated since the initial /suggestions call are
    folded in first so the LLM sees the up-to-date evidence."""
    if not request.jd_text.strip():
        raise HTTPException(status_code=400, detail="Job description cannot be empty.")
    t0 = time.perf_counter()
    try:
        resume, _ = _load_resume(request.resume_id)
        if request.new_projects is not None:
            resume = _replace_projects(resume, request.new_projects)
        if request.accepted_suggestions:
            resume = apply_suggestions(resume, request.accepted_suggestions)

        try:
            hard_reqs = await extract_jd_hard_requirements(request.jd_text)
        except Exception as e:
            logger.warning("[refresh-skills] hard-req extraction failed: %s", e)
            hard_reqs = {"required_skills_hard": []}
        required_skills_hard = hard_reqs.get("required_skills_hard") or []

        experience_ctx, projects_ctx, certifications_ctx = build_skills_contexts(resume)
        from app.core.renderer import resume_to_plaintext
        from app.core.tailor_orchestrator import _derive_skill_additions, _drop_fragments

        # LLM: rename/delete/move only (no ADD mode — handled deterministically).
        lm_raw = await tailor_skills(
            [s.model_dump() for s in resume.skills],
            request.jd_text,
            keywords_to_inject=[],
            experience_ctx=experience_ctx,
            projects_ctx=projects_ctx,
            certifications_ctx=certifications_ctx,
            user_prompt=request.user_prompt,
        )
        lm_non_add = [s for s in (lm_raw or []) if s.get("mode") != "add_skill"]

        # Deterministic ADD: grounded in the now-tailored resume text.
        tailored_text = resume_to_plaintext(resume)
        skill_adds = _derive_skill_additions(resume, tailored_text, request.jd_text, id_start=5000)

        raw = lm_non_add + skill_adds

        next_id = max(1, int(request.next_id))
        for s in raw:
            s["id"] = next_id
            next_id += 1

        logger.info("[TIMING] refresh-skills: TOTAL=%.3fs  skills=%d",
                    time.perf_counter() - t0, len(raw))
        return {
            "suggestions": raw,
            "next_id": next_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/generate-projects")
async def generate_projects(request: GenerateProjectsRequest):
    """Two-stage LLM project generation with Qdrant-backed dedup."""
    if not request.jd_text.strip():
        raise HTTPException(status_code=400, detail="Job description cannot be empty.")
    t0 = time.perf_counter()
    try:
        import hashlib
        import uuid as uuid_mod
        from qdrant_client.http.models import PointStruct
        from app.core.vector_db import init_qdrant, get_embedding
        from app.core.llm_synthesis import analyze_jd_for_projects, synthesize_projects
        from app.core.keyword_utils import _significant_tokens, _top_jd_tokens
        from app.core.renderer import resume_to_plaintext

        from app.api.match_logic.ceiling_detector import estimate_years_experience

        resume, _ = _load_resume(request.resume_id)
        candidate_skills = [s for cat in resume.skills for s in cat.skills]


        jd_tokens = _significant_tokens(request.jd_text)
        resume_tokens = _significant_tokens(resume_to_plaintext(resume))
        missing = jd_tokens - resume_tokens
        top_jd = _top_jd_tokens(request.jd_text, k=50)
        missing_keywords = sorted(top_jd & missing)[:15]

        # Seniority bucket — calibrates the scale of metrics the LLM is allowed to invent.
        yoe = estimate_years_experience(resume) or 0.0
        if yoe < 1:
            seniority = "fresher"
        elif yoe < 3:
            seniority = "junior"
        elif yoe < 6:
            seniority = "mid"
        else:
            seniority = "senior"

        # Style sample from the candidate's existing project bullets.
        existing_bullets = []
        for p in resume.projects[:3]:
            existing_bullets.extend([b for b in (p.bullets or []) if b])
        existing_bullets = existing_bullets[:6]
        if existing_bullets:
            avg_words = max(8, round(sum(len(b.split()) for b in existing_bullets) / len(existing_bullets)))
        else:
            avg_words = 18
        # Scrub geo qualifiers so the LLM doesn't imitate them in generated names.
        scrubbed_bullets = [_scrub_locations(b) for b in existing_bullets[:4]]
        bullet_style_sample = "\n".join(f"- {b}" for b in scrubbed_bullets if b)

        logger.info("[generate-projects] skills=%d  count=%d  yoe=%.1f  seniority=%s  avg_words=%d",
                    len(candidate_skills), request.count, yoe, seniority, avg_words)

        t_stage_a = time.perf_counter()
        jd_analysis = await analyze_jd_for_projects(request.jd_text)
        logger.info("[TIMING] generate-projects: stage_a=%.3fs", time.perf_counter() - t_stage_a)

        q_client = init_qdrant("generated_projects")
        exclude_names = list(request.exclude_names)
        final_projects: list = []

        for attempt in range(3):
            if len(final_projects) >= request.count:
                break

            seed = hashlib.sha256(
                f"{request.jd_text[:200]}{request.resume_id}{uuid_mod.uuid4()}{attempt}".encode()
            ).hexdigest()[:8]

            t_stage_b = time.perf_counter()
            candidates = await synthesize_projects(
                jd_analysis=jd_analysis,
                candidate_skills=candidate_skills,
                seed=seed,
                exclude_names=exclude_names,
                count=request.count,
                seniority=seniority,
                avg_words=avg_words,
                bullet_style_sample=bullet_style_sample,
                missing_keywords=missing_keywords
            )
            logger.info("[TIMING] generate-projects: stage_b attempt=%d  got=%d  elapsed=%.3fs",
                        attempt, len(candidates), time.perf_counter() - t_stage_b)

            for proj in candidates:
                if len(final_projects) >= request.count:
                    break
                name = proj.get("name", "").strip()
                # Strip geographic modifiers then dangling prepositions.
                scrubbed = _scrub_locations(name)
                fixed = _fix_project_name(scrubbed)
                if fixed != name:
                    logger.info("[generate-projects] name fix: %r -> %r", name, fixed)
                    name = fixed
                    proj["name"] = fixed
                if not name or name in exclude_names:
                    continue

                proj_text = f"{name} {' '.join(proj.get('bullets', []))}"
                fingerprint = hashlib.sha256(proj_text.encode()).hexdigest()[:16]
                proj["fingerprint"] = fingerprint

                # Dedup against ledger — errors are non-fatal so generation never blocks
                try:
                    proj_vector = await get_embedding(proj_text)
                    similar = q_client.search(
                        collection_name="generated_projects",
                        query_vector=proj_vector,
                        limit=1,
                        score_threshold=0.85,
                    )
                    if similar:
                        exclude_names.append(name)
                        continue
                    point_id = str(uuid_mod.uuid5(uuid_mod.NAMESPACE_DNS, fingerprint))
                    q_client.upsert(
                        collection_name="generated_projects",
                        points=[PointStruct(
                            id=point_id,
                            vector=proj_vector,
                            payload={
                                "resume_id": request.resume_id,
                                "project_name": name,
                                "fingerprint": fingerprint,
                            },
                        )],
                    )
                except Exception as dedup_err:
                    logger.warning("[generate-projects] dedup/store error (ignored): %s", dedup_err)

                final_projects.append(proj)
                exclude_names.append(name)

        chosen = final_projects[:request.count]

        t_humanize = time.perf_counter()
        chosen = await humanize_project_bullets(chosen, avg_words=avg_words, seniority=seniority)
        logger.info("[TIMING] generate-projects: humanize=%.3fs", time.perf_counter() - t_humanize)

        logger.info("[TIMING] generate-projects: TOTAL=%.3fs  returned=%d",
                    time.perf_counter() - t0, len(chosen))
        return {
            "projects": chosen,
            "jd_analysis": jd_analysis,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback; traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
