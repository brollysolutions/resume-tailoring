import logging
import uuid
import json
from typing import List, Dict, Any, Optional
from qdrant_client.http import models as qmodels
from app.core.vector_db import init_qdrant, get_qdrant_client, get_embedding
from app.models.resume_schema import Resume

logger = logging.getLogger(__name__)

COLLECTION_NAME = "candidate_evidence"

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
            bullets = " ".join([b.strip() for b in (exp.bullets or []) if b.strip()])
            
            text_parts = [f"Experience Entry: {title} at {company}"]
            if location:
                text_parts.append(f"({location})")
            if bullets:
                text_parts.append(f"Responsibilities and achievements: {bullets}")
            
            chunks.append({
                "text": "\n".join(text_parts),
                "metadata": {
                    "section": "Experience",
                    "entry_index": idx,
                    "title": title,
                    "company": company
                }
            })

        # 3. Project Chunks
        for idx, proj in enumerate(resume.projects or []):
            name = (proj.name or "").strip()
            tech = (proj.tech or "").strip()
            bullets = " ".join([b.strip() for b in (proj.bullets or []) if b.strip()])
            
            text_parts = [f"Project Entry: {name}"]
            if tech:
                text_parts.append(f"Technologies: {tech}")
            if bullets:
                text_parts.append(f"Details and scope: {bullets}")
                
            chunks.append({
                "text": "\n".join(text_parts),
                "metadata": {
                    "section": "Projects",
                    "entry_index": idx,
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

        # 3. Generate embeddings and upload
        points = []
        for chunk in chunks:
            try:
                embedding = await get_embedding(chunk["text"])
                point_id = str(uuid.uuid4())
                
                # Combine payload with resume reference
                payload = {
                    "resume_id": resume_id,
                    "text": chunk["text"],
                    **chunk["metadata"]
                }
                
                points.append(
                    qmodels.PointStruct(
                        id=point_id,
                        vector=embedding,
                        payload=payload
                    )
                )
            except Exception as embed_err:
                logger.error("Failed to embed chunk in resume indexing: %s", embed_err)

        if points:
            q_client.upsert(collection_name=COLLECTION_NAME, points=points)
            logger.info("Upserted %d evidence chunks for resume_id: %s", len(points), resume_id)

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
