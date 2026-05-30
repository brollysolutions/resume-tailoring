import logging
import re
import uuid
import json
from typing import List, Dict, Any, Optional
from qdrant_client.http import models as qmodels
from app.core.vector_db import init_qdrant, get_qdrant_client, get_embedding
from app.models.resume_schema import Resume

logger = logging.getLogger(__name__)

COLLECTION_NAME = "candidate_evidence"
JD_COLLECTION_NAME = "jd_clauses"

# Section header patterns for JD role classification (first match wins).
_JD_ROLE_PATTERNS = [
    (re.compile(r'\b(?:responsibilit|duties|what you.ll do|you will)', re.I), "responsibility"),
    (re.compile(r'\b(?:preferred|nice.to.have|bonus|desired)', re.I), "qualification"),
    (re.compile(r'\b(?:requirement|required|must.have|essential|minimum qualif)', re.I), "requirement"),
]


def _split_jd_clauses(jd_text: str) -> List[Dict[str, Any]]:
    """Split JD into line-level clauses with role detection.

    Tracks the active section (requirement/responsibility/qualification) as
    headers are encountered and stamps each substantive line with that role.
    Lines shorter than 20 chars are skipped (labels/noise)."""
    current_role = "requirement"
    clauses: List[Dict[str, Any]] = []
    for clause_index, line in enumerate(jd_text.splitlines()):
        text = line.strip()
        if not text:
            continue
        # Update active role when a section header is detected.
        if len(text) <= 80:
            for pat, role in _JD_ROLE_PATTERNS:
                if pat.search(text):
                    current_role = role
                    break
        if len(text) >= 20:
            clauses.append({"text": text, "clause_index": clause_index, "role": current_role})
    return clauses

class RAGService:
    """
    RAG Service to chunk, embed, store, and retrieve candidate resume elements in Qdrant.
    It chunks resumes logically by section entry to maintain high semantic coherence.
    """

    @staticmethod
    def initialize_collection() -> None:
        """Eagerly initialize the candidate_evidence collection."""
        try:
            init_qdrant(COLLECTION_NAME, vector_size=768)
            logger.info("Qdrant collection '%s' initialized.", COLLECTION_NAME)
        except Exception as e:
            logger.error("Failed to initialize Qdrant collection: %s", e)

    @staticmethod
    def _create_chunks(resume: Resume) -> List[Dict[str, Any]]:
        """
        Segment the structured resume into logical text chunks with metadata tags.
        """
        chunks = []

        # 1. Summary Chunk
        if resume.summary and resume.summary.strip():
            chunks.append({
                "text": f"Summary: {resume.summary.strip()}",
                "metadata": {
                    "section": "Summary",
                    "entry_index": 0
                }
            })

        # 2. Experience Chunks
        for idx, exp in enumerate(resume.experience or []):
            title = (exp.title or "").strip()
            company = (exp.company or "").strip()
            location = (exp.location or "").strip()
            bullet_list = [b.strip() for b in (exp.bullets or []) if b.strip()]
            bullets_text = " ".join(bullet_list)

            text_parts = [f"Experience Entry: {title} at {company}"]
            if location:
                text_parts.append(f"({location})")
            if bullets_text:
                text_parts.append(f"Responsibilities and achievements: {bullets_text}")

            # Entry-summary chunk (keeps existing retrieval behavior)
            chunks.append({
                "text": "\n".join(text_parts),
                "metadata": {
                    "section": "Experience",
                    "entry_index": idx,
                    "title": title,
                    "company": company
                }
            })
            # Per-bullet chunks for fine-grained retrieval
            for b_idx, bullet in enumerate(bullet_list):
                chunks.append({
                    "text": f"Experience Bullet ({title} at {company}): {bullet}",
                    "metadata": {
                        "section": "Experience",
                        "entry_index": idx,
                        "bullet_index": b_idx,
                        "title": title,
                        "company": company
                    }
                })

        # 3. Project Chunks
        for idx, proj in enumerate(resume.projects or []):
            name = (proj.name or "").strip()
            tech = (proj.tech or "").strip()
            bullet_list = [b.strip() for b in (proj.bullets or []) if b.strip()]
            bullets_text = " ".join(bullet_list)

            text_parts = [f"Project Entry: {name}"]
            if tech:
                text_parts.append(f"Technologies: {tech}")
            if bullets_text:
                text_parts.append(f"Details and scope: {bullets_text}")

            # Entry-summary chunk
            chunks.append({
                "text": "\n".join(text_parts),
                "metadata": {
                    "section": "Projects",
                    "entry_index": idx,
                    "name": name,
                    "tech": tech
                }
            })
            # Per-bullet chunks
            for b_idx, bullet in enumerate(bullet_list):
                chunks.append({
                    "text": f"Project Bullet ({name}): {bullet}",
                    "metadata": {
                        "section": "Projects",
                        "entry_index": idx,
                        "bullet_index": b_idx,
                        "name": name,
                        "tech": tech
                    }
                })

        # 4. Certifications Chunk
        certs = [c.strip() for c in (resume.certifications or []) if c.strip()]
        if certs:
            chunks.append({
                "text": f"Certifications & Credentials: {', '.join(certs)}",
                "metadata": {
                    "section": "Certifications",
                    "entry_index": 0
                }
            })

        return chunks

    @classmethod
    async def index_resume(cls, resume_id: str, resume: Resume) -> None:
        """
        Chunk and embed a candidate's resume, storing chunks in Qdrant with filters.
        """
        cls.initialize_collection()
        q_client = get_qdrant_client()
        
        # 1. Clear any existing chunks for this specific resume to prevent duplication
        try:
            q_client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=qmodels.Filter(
                    must=[
                        qmodels.FieldCondition(
                            key="resume_id",
                            match=qmodels.MatchValue(value=resume_id)
                        )
                    ]
                )
            )
        except Exception as delete_err:
            logger.warning("Error clearing prior chunks for resume %s: %s", resume_id, delete_err)

        # 2. Segment into logical chunks
        chunks = cls._create_chunks(resume)
        if not chunks:
            logger.info("No chunks parsed for resume %s", resume_id)
            return

        # 3. Generate embeddings and upload (parallel across all chunks)
        import asyncio
        embeddings = await asyncio.gather(
            *[get_embedding(c["text"]) for c in chunks],
            return_exceptions=True,
        )
        points = []
        for chunk, embedding in zip(chunks, embeddings):
            if isinstance(embedding, Exception):
                logger.error("Failed to embed chunk in resume indexing: %s", embedding)
                continue
            payload = {
                "resume_id": resume_id,
                "text": chunk["text"],
                **chunk["metadata"]
            }
            points.append(
                qmodels.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embedding,
                    payload=payload,
                )
            )

        if points:
            q_client.upsert(collection_name=COLLECTION_NAME, points=points)
            logger.info("Upserted %d evidence chunks for resume_id: %s", len(points), resume_id)

    @classmethod
    async def refresh_from_resume(cls, resume_id: str, resume: Resume) -> None:
        """Re-index candidate evidence after accepted edits — prevents stale RAG grounding."""
        await cls.index_resume(resume_id, resume)

    # ------------------------------------------------------------------
    # JD indexing
    # ------------------------------------------------------------------

    @staticmethod
    def initialize_jd_collection() -> None:
        """Eagerly initialize the jd_clauses collection."""
        try:
            init_qdrant(JD_COLLECTION_NAME, vector_size=768)
            logger.info("Qdrant collection '%s' initialized.", JD_COLLECTION_NAME)
        except Exception as e:
            logger.error("Failed to initialize jd_clauses collection: %s", e)

    @classmethod
    async def index_jd(cls, jd_hash: str, jd_text: str) -> None:
        """Chunk and embed a JD, storing clauses in the jd_clauses collection.

        Idempotent: skips indexing if jd_hash is already present."""
        cls.initialize_jd_collection()
        q_client = get_qdrant_client()

        # Idempotency guard — skip if this JD is already indexed
        try:
            count_result = q_client.count(
                collection_name=JD_COLLECTION_NAME,
                count_filter=qmodels.Filter(
                    must=[qmodels.FieldCondition(
                        key="jd_hash", match=qmodels.MatchValue(value=jd_hash)
                    )]
                )
            )
            if count_result.count > 0:
                logger.debug("JD %s already indexed (%d clauses) — skipping.", jd_hash, count_result.count)
                return
        except Exception as check_err:
            logger.warning("JD index idempotency check failed (%s) — proceeding with index.", check_err)

        clauses = _split_jd_clauses(jd_text)
        if not clauses:
            logger.info("No clauses extracted for jd_hash %s", jd_hash)
            return

        import asyncio
        texts = [c["text"] for c in clauses]
        embeddings = await asyncio.gather(
            *[get_embedding(t) for t in texts],
            return_exceptions=True,
        )
        points = []
        for clause, embedding in zip(clauses, embeddings):
            if isinstance(embedding, Exception):
                logger.error("Failed to embed JD clause: %s", embedding)
                continue
            points.append(
                qmodels.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=embedding,
                    payload={
                        "jd_hash": jd_hash,
                        "text": clause["text"],
                        "clause_index": clause["clause_index"],
                        "role": clause["role"],
                    },
                )
            )

        if points:
            q_client.upsert(collection_name=JD_COLLECTION_NAME, points=points)
            logger.info("Upserted %d JD clauses for jd_hash: %s", len(points), jd_hash)

    @classmethod
    async def retrieve_relevant_evidence(
        cls,
        resume_id: str,
        query: str,
        limit: int = 3,
        section_filter: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Retrieve semantically relevant chunks of candidate history matching a requirement.
        """
        cls.initialize_collection()
        q_client = get_qdrant_client()
        
        try:
            query_vector = await get_embedding(query)
            
            # Construct strict filter for this candidate's thread
            filter_conditions = [
                qmodels.FieldCondition(
                    key="resume_id",
                    match=qmodels.MatchValue(value=resume_id)
                )
            ]
            
            if section_filter:
                filter_conditions.append(
                    qmodels.FieldCondition(
                        key="section",
                        match=qmodels.MatchValue(value=section_filter)
                    )
                )

            results = q_client.search(
                collection_name=COLLECTION_NAME,
                query_vector=query_vector,
                query_filter=qmodels.Filter(must=filter_conditions),
                limit=limit
            )
            
            evidence = []
            for hit in results:
                evidence.append({
                    "score": hit.score,
                    "text": hit.payload.get("text", ""),
                    "section": hit.payload.get("section", ""),
                    "entry_index": hit.payload.get("entry_index", 0),
                    "metadata": {k: v for k, v in hit.payload.items() if k not in ("resume_id", "text")}
                })
            
            return evidence
        except Exception as search_err:
            logger.error("Error performing RAG semantic search: %s", search_err)
            return []
