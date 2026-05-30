import json as _json
import logging
import os
import uuid
import asyncio
import json
import fitz
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List
from fastapi import APIRouter, UploadFile, File, HTTPException
from pydantic import BaseModel

from app.core.vector_db import get_embedding, init_qdrant
from app.core.llm_helpers import generate_keywords, llm_clean_tech_field
from app.core.extractor import extract_resume
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

_UPLOAD_EVENTS_PATH = Path(__file__).resolve().parents[2] / "data" / "upload_events.jsonl"


def _log_upload_event(resume_id: str) -> None:
    """Best-effort append. Never raises."""
    if os.environ.get("TESTING") == "1":
        return
    try:
        _UPLOAD_EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        event = {"ts": datetime.now(timezone.utc).isoformat(), "resume_id": resume_id}
        with _UPLOAD_EVENTS_PATH.open("a", encoding="utf-8") as f:
            f.write(_json.dumps(event) + "\n")
    except Exception as e:
        logger.debug("upload_events log write failed: %s", e)

UPLOAD_DIR = settings.UPLOAD_DIR
os.makedirs(UPLOAD_DIR, exist_ok=True)

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def _extract_text_from_pdf(pdf_path: str) -> tuple[str, dict[str, str]]:
    doc = fitz.open(pdf_path)
    text_parts = []
    link_map = {}
    
    for page in doc:
        # Get blocks to sort them manually by vertical then horizontal position
        # This is more robust for reading order than the default 'text' output.
        blocks = page.get_text("blocks")
        # Sort by y0 (top), then x0 (left)
        blocks.sort(key=lambda b: (b[1], b[0]))
        
        for b in blocks:
            # b[4] is the text content of the block
            block_text = b[4].strip()
            if block_text:
                text_parts.append(block_text)
        
        # Extract links
        for link in page.get_links():
            if link.get("kind") == fitz.LINK_URI:
                uri = link.get("uri")
                rect = link.get("from")
                anchor_text = page.get_textbox(rect).strip()
                if anchor_text and uri:
                    link_map[anchor_text] = uri
                    
    doc.close()
    return "\n".join(text_parts), link_map


def _extract_text_from_docx(docx_path: str) -> tuple[str, dict[str, str]]:
    from docx import Document
    from docx.oxml.ns import qn
    doc = Document(docx_path)
    parts = [p.text for p in doc.paragraphs]
    link_map = {}

    def _extract_links_from_paragraph(p):
        hyperlinks = p._element.xpath('.//w:hyperlink')
        for hl in hyperlinks:
            rId = hl.get(qn('r:id'))
            if rId and rId in p.part.rels:
                url = p.part.rels[rId].target_ref
                anchor_text = "".join([node.text for node in hl.xpath('.//w:t')])
                if anchor_text and url:
                    link_map[anchor_text] = url

    for p in doc.paragraphs:
        _extract_links_from_paragraph(p)

    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
                for p in cell.paragraphs:
                    _extract_links_from_paragraph(p)

    return "\n".join(parts), link_map


@router.post("/upload")
async def upload_resume(file: UploadFile = File(...)):
    """
    Upload flow (clean-template architecture):
      1. Save the file.
      2. Extract raw text and hyperlinks.
      3. Run, in parallel:
           - LLM extraction → structured Resume JSON
           - LLM keyword extraction → suggested job titles
           - Embedding for vector matching
      4. Store everything in Qdrant. The original file is kept only for
         reference; we never edit it.
    """
    resume_id = str(uuid.uuid4())
    file_ext = os.path.splitext(file.filename)[1].lower()

    if file_ext not in [".pdf", ".docx"]:
        raise HTTPException(status_code=400, detail="Only PDF and DOCX files are supported.")

    original_path = os.path.join(UPLOAD_DIR, f"{resume_id}{file_ext}")
    contents = bytearray()
    while chunk := await file.read(1024 * 1024):
        contents.extend(chunk)
        if len(contents) > _MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="File too large. Maximum size is 10 MB.")
    with open(original_path, "wb") as buffer:
        buffer.write(contents)

    try:
        if file_ext == ".pdf":
            raw_text, link_map = _extract_text_from_pdf(original_path)
        else:
            raw_text, link_map = _extract_text_from_docx(original_path)
            
        # Append detected hyperlinks to the text handed to the LLM
        if link_map:
            links_block = "\n\n--- Detected Hyperlinks ---\n"
            for anchor, url in link_map.items():
                links_block += f"{anchor}: {url}\n"
            raw_text += links_block
            
    except Exception as e:
        logger.exception("Text extraction failed")
        raise HTTPException(status_code=500, detail=f"Text extraction failed: {e}")

    async def safe_extract():
        try:
            return await extract_resume(raw_text)
        except Exception:
            logger.exception("Resume extraction failed")
            from app.models.resume_schema import Resume
            return Resume(summary=raw_text[:1500])

    async def safe_keywords():
        try:
            return await generate_keywords(raw_text)
        except Exception as e:
            logger.exception("Keyword generation failed")
            return ["Software Engineer", "Developer"], []

    # Embedding is computed AFTER extraction so it uses the canonical plaintext
    # generated from the Resume JSON. This keeps the stored text/vector consistent
    # with what match.py and the tailored-match endpoint use later.
    resume_obj, (keywords, stack) = await asyncio.gather(safe_extract(), safe_keywords())

    from app.core.renderer import resume_to_plaintext
    canonical_text = resume_to_plaintext(resume_obj)

    try:
        embedding = await get_embedding(canonical_text)
    except Exception as e:
        logger.exception("Embedding generation failed")
        embedding = None

    if embedding is not None:
        try:
            q_client = init_qdrant("resumes")
            from qdrant_client.http.models import PointStruct
            q_client.upsert(
                collection_name="resumes",
                points=[
                    PointStruct(
                        id=resume_id,
                        vector=embedding,
                        payload={
                            "text": canonical_text,
                            "resume_json": resume_obj.model_dump_json(),
                            "original_path": original_path,
                            "file_ext": file_ext,
                            "original_filename": file.filename,
                            "keywords": keywords,
                            "stack": stack,
                        },
                    )
                ],
            )
        except Exception as e:
            logger.exception("Vector storage failed")

    _log_upload_event(resume_id)

    return {
        "message": "Resume uploaded and processed successfully",
        "resume_id": resume_id,
        "keywords": keywords,
        "stack": stack,
        "file_ext": file_ext,
    }


class ScaffoldRequest(BaseModel):
    template_id: Optional[str] = None


@router.post("/scaffold")
async def scaffold_resume(body: ScaffoldRequest):
    """Create a Qdrant point seeded with a John Doe Resume so the user can
    proceed through /job-search → /tailor without uploading a file."""
    from app.core.sample_resume import build_sample_resume
    from app.core.renderer import resume_to_plaintext

    resume_id = str(uuid.uuid4())
    resume_obj = build_sample_resume()
    canonical_text = resume_to_plaintext(resume_obj)

    try:
        embedding = await get_embedding(canonical_text)
    except Exception:
        logger.exception("Embedding generation failed for scaffold")
        embedding = None

    keywords = ["Software Engineer", "Backend Engineer", "Full Stack Engineer"]
    stack = ["Python", "Django", "React"]

    if embedding is not None:
        try:
            q_client = init_qdrant("resumes")
            from qdrant_client.http.models import PointStruct
            q_client.upsert(
                collection_name="resumes",
                points=[
                    PointStruct(
                        id=resume_id,
                        vector=embedding,
                        payload={
                            "text": canonical_text,
                            "resume_json": resume_obj.model_dump_json(),
                            "original_path": "",
                            "file_ext": "",
                            "original_filename": "sample_resume",
                            "keywords": keywords,
                            "stack": stack,
                        },
                    )
                ],
            )
        except Exception:
            logger.exception("Vector storage failed for scaffold")

    _log_upload_event(resume_id)

    return {
        "message": "Scaffold resume created.",
        "resume_id": resume_id,
        "keywords": keywords,
        "stack": stack,
        "template_id": body.template_id,
    }


@router.get("/{resume_id}/text")

async def get_resume_text(resume_id: str):
    try:
        q_client = init_qdrant("resumes")
        results = q_client.retrieve(collection_name="resumes", ids=[resume_id], with_payload=True)
        if not results:
            raise HTTPException(status_code=404, detail="Resume not found.")
        payload = results[0].payload
        return {
            "resume_id": resume_id,
            "raw_text": payload.get("text", ""),
            "filename": payload.get("original_filename", ""),
            "file_ext": payload.get("file_ext", ""),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{resume_id}/json")
async def get_resume_json(resume_id: str):
    """Returns the parsed Resume JSON for inspection / debugging."""
    try:
        q_client = init_qdrant("resumes")
        results = q_client.retrieve(collection_name="resumes", ids=[resume_id], with_payload=True)
        if not results:
            raise HTTPException(status_code=404, detail="Resume not found.")
        payload = results[0].payload
        raw = payload.get("resume_json", "{}")
        
        from app.models.resume_schema import Resume
        # Validate through model to ensure on-the-fly normalization (e.g. flat skills fix)
        resume_obj = Resume.model_validate_json(raw)

        # Lazy-migrate: LLM-clean project tech fields on first load, save back to Qdrant.
        tech_cleaned = False
        for proj in (resume_obj.projects or []):
            if proj.tech:
                cleaned = await llm_clean_tech_field(proj.tech)
                if cleaned != proj.tech:
                    proj.tech = cleaned
                    tech_cleaned = True
        if tech_cleaned:
            q_client.set_payload(
                collection_name="resumes",
                payload={"resume_json": resume_obj.model_dump_json()},
                points=[resume_id],
            )

        return resume_obj.model_dump()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SectionsPatch(BaseModel):
    section_order: Optional[List[str]] = None
    hidden_sections: Optional[List[str]] = None


@router.patch("/{resume_id}/sections")
async def patch_resume_sections(resume_id: str, body: SectionsPatch):
    """Update section_order and/or hidden_sections on a stored Resume."""
    from app.models.resume_schema import Resume
    try:
        q_client = init_qdrant("resumes")
        results = q_client.retrieve(collection_name="resumes", ids=[resume_id], with_payload=True)
        if not results:
            raise HTTPException(status_code=404, detail="Resume not found.")
        point = results[0]
        payload = dict(point.payload or {})
        raw = payload.get("resume_json")
        if not raw:
            raise HTTPException(status_code=500, detail="Stored resume JSON missing.")
        resume = Resume.model_validate(json.loads(raw))

        update_data = {}
        if body.section_order is not None:
            update_data["section_order"] = body.section_order
        if body.hidden_sections is not None:
            update_data["hidden_sections"] = body.hidden_sections
        if update_data:
            resume = resume.model_copy(update=update_data)

        payload["resume_json"] = resume.model_dump_json()
        q_client.set_payload(
            collection_name="resumes",
            payload=payload,
            points=[resume_id],
        )
        return {
            "resume_id": resume_id,
            "section_order": resume.section_order,
            "hidden_sections": resume.hidden_sections,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("PATCH sections failed")
        raise HTTPException(status_code=500, detail=str(e))
