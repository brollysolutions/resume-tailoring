import logging
import os
import uuid
import asyncio
import json
import fitz
from fastapi import APIRouter, UploadFile, File, HTTPException

from app.core.vector_db import get_embedding, init_qdrant
from app.core.llm_helpers import generate_keywords
from app.core.extractor import extract_resume
from app.core.config import settings

logger = logging.getLogger(__name__)
router = APIRouter()

UPLOAD_DIR = settings.UPLOAD_DIR
os.makedirs(UPLOAD_DIR, exist_ok=True)

_MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def _extract_text_from_pdf(pdf_path: str) -> str:
    doc = fitz.open(pdf_path)
    text = ""
    for page in doc:
        text += page.get_text("text", sort=True) + "\n"
    doc.close()
    return text


def _extract_text_from_docx(docx_path: str) -> str:
    from docx import Document
    doc = Document(docx_path)
    parts = [p.text for p in doc.paragraphs]
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                parts.append(cell.text)
    return "\n".join(parts)


@router.post("/upload")
async def upload_resume(file: UploadFile = File(...)):
    """
    Upload flow (clean-template architecture):
      1. Save the file.
      2. Extract raw text (PyMuPDF for PDF, python-docx for DOCX).
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
    contents = await file.read()
    if len(contents) > _MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large. Maximum size is 10 MB.")
    with open(original_path, "wb") as buffer:
        buffer.write(contents)

    try:
        if file_ext == ".pdf":
            raw_text = _extract_text_from_pdf(original_path)
        else:
            raw_text = _extract_text_from_docx(original_path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Text extraction failed: {e}")

    async def safe_extract():
        try:
            return await extract_resume(raw_text)
        except Exception as e:
            logger.exception("Resume extraction failed")
            from app.models.resume_schema import Resume
            return Resume(summary=raw_text[:1500])

    async def safe_keywords():
        try:
            return await generate_keywords(raw_text)
        except Exception as e:
            logger.exception("Keyword generation failed")
            return ["Software Engineer", "Developer"]

    # Embedding is computed AFTER extraction so it uses the canonical plaintext
    # generated from the Resume JSON. This keeps the stored text/vector consistent
    # with what match.py and the tailored-match endpoint use later.
    resume_obj, keywords = await asyncio.gather(safe_extract(), safe_keywords())

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
                        },
                    )
                ],
            )
        except Exception as e:
            logger.exception("Vector storage failed")

    return {
        "message": "Resume uploaded and processed successfully",
        "resume_id": resume_id,
        "keywords": keywords,
        "file_ext": file_ext,
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
        return json.loads(payload.get("resume_json", "{}"))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
