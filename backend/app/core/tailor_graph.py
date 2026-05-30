import logging
import asyncio
import json
from typing import TypedDict, Annotated, Optional, List, Dict, Any, Literal
from app.models.resume_schema import Resume
from app.core.rag_service import RAGService
from app.core.llm_helpers import (
    extract_jd_hard_requirements,
    tailor_summary,
    tailor_experience,
    tailor_projects,
    tailor_education,
    tailor_skills,
)
from app.core.llm_client import _chat
from app.core.renderer import resume_to_plaintext, apply_suggestions
from app.core.keyword_utils import _significant_tokens, _top_jd_tokens, _drop_fragments
from app.api.match_logic.hybrid_scorer import score_resume_against_jd
from app.api.match_logic.gap_analyzer import compute_gap_analysis
from app.api.match_logic.section_scorer import compute_section_scores

logger = logging.getLogger(__name__)

# Define the state schema for our LangGraph workflow
class TailorGraphState(TypedDict):
    # Setup inputs
    resume_id: str
    jd_text: str
    original_resume: Resume
    intensity: str
    section_intensities: Optional[dict[str, str]]
    
    # Grounding context
    jd_requirements: dict
    retrieved_evidence: dict  # section -> grounding evidence text
    missing_keywords: list[str]
    
    # Modified resume & pending suggestions
    current_resume: Resume
    suggestions: list[dict]
    project_names: list[str]
    
    # Matching metrics
    match_score: int
    section_scores: dict[str, int]
    low_sections: list[dict]
    critique_instructions: dict  # section -> specific instructions for re-write
    
    # Iteration tracking
    iteration: int
    max_iterations: int
    
    # Centralized chat instruction
    user_prompt: Optional[str]

# 1. Node: Analyze JD
async def analyze_jd_node(state: TailorGraphState) -> Dict[str, Any]:
    logger.info("[LangGraph] Node: analyze_jd")
    jd_text = state["jd_text"]
    
    # Extract hard requirements (YOE, degrees)
    try:
        jd_requirements = await extract_jd_hard_requirements(jd_text)
    except Exception as e:
        logger.warning("Failed to extract JD hard requirements: %s", e)
        jd_requirements = {
            "min_years_experience": None,
            "required_degrees": [],
            "seniority_level": None,
            "required_skills_hard": [],
        }

    # Extract missing keywords (seeds for RAG & matching)
    jd_tokens = _significant_tokens(jd_text)
    resume_plaintext = resume_to_plaintext(state["original_resume"])
    resume_tokens = _significant_tokens(resume_plaintext)
    missing = jd_tokens - resume_tokens
    
    top_jd = _top_jd_tokens(jd_text, k=50)
    top_missing = _drop_fragments(sorted(top_jd & missing))[:20]

    return {
        "jd_requirements": jd_requirements,
        "missing_keywords": top_missing,
        "iteration": state.get("iteration", 0) + 1
    }

# 2. Node: Retrieve RAG Context
async def retrieve_rag_context_node(state: TailorGraphState) -> Dict[str, Any]:
    logger.info("[LangGraph] Node: retrieve_rag_context")
    resume_id = state["resume_id"]
    original_resume = state["original_resume"]
    missing_keywords = state.get("missing_keywords", [])
    
    # Eagerly index the original resume in the RAG store if not already present
    try:
        await RAGService.index_resume(resume_id, original_resume)
    except Exception as e:
        logger.error("Failed to index resume in Qdrant RAG store: %s", e)

    # For each section, search candidate evidence matching missing keywords
    retrieved_evidence = {}
    sections_to_retrieve = ["Experience", "Projects", "Summary"]
    
    for section in sections_to_retrieve:
        # Parallel retrieval across all missing keywords for this section
        kw_results = await asyncio.gather(
            *[
                RAGService.retrieve_relevant_evidence(
                    resume_id=resume_id,
                    query=f"Details related to: {kw}",
                    limit=1,
                    section_filter=section,
                )
                for kw in missing_keywords[:5]
            ],
            return_exceptions=True,
        )
        evidence_chunks = []
        for hits in kw_results:
            if isinstance(hits, Exception):
                continue
            for hit in hits:
                evidence_chunks.append(hit["text"])

        # Deduplicate and combine evidence
        unique_chunks = list(set(evidence_chunks))
        retrieved_evidence[section] = "\n".join(unique_chunks) if unique_chunks else "None"

    return {"retrieved_evidence": retrieved_evidence}

# 3. Node: Tailor Sections (Parallel execution)
async def tailor_sections_node(state: TailorGraphState) -> Dict[str, Any]:
    logger.info("[LangGraph] Node: tailor_sections (iteration=%d)", state.get("iteration", 1))
    resume = state["current_resume"]
    jd_text = state["jd_text"]
    top_missing = state.get("missing_keywords", [])
    retrieved_evidence = state.get("retrieved_evidence", {})
    critique_instructions = state.get("critique_instructions", {})
    user_prompt = state.get("user_prompt")
    global_intensity = state.get("intensity", "balanced")
    section_intensities = state.get("section_intensities") or {}

    exp_intensity = section_intensities.get("experience", global_intensity)
    proj_intensity = section_intensities.get("projects", global_intensity)
    sum_intensity = section_intensities.get("summary", global_intensity)
    edu_intensity = section_intensities.get("education", global_intensity)

    # Build dynamically enriched JD Text incorporating RAG grounding & critiques
    def enrich_jd_context(section_name: str) -> str:
        enriched = jd_text
        evidence = retrieved_evidence.get(section_name)
        critique = critique_instructions.get(section_name)
        
        if evidence and evidence != "None":
            enriched += f"\n\n[GROUNDING EVIDENCE FOR {section_name.upper()} - Use these actual achievements as facts. Do not invent new skills or credentials outside this list]:\n{evidence}"
        
        if critique:
            enriched += f"\n\n[CRITIQUE & RE-WRITE INSTRUCTIONS FOR {section_name.upper()} - Strictly adhere to this request]:\n{critique}"
        
        if user_prompt:
            enriched += f"\n\n[USER DIRECT CHAT INSTRUCTION - Prioritize these requests]:\n{user_prompt}"
            
        return enriched

    # Fan-out parallel tailoring tasks
    tasks = [
        tailor_experience([e.model_dump() for e in resume.experience], enrich_jd_context("Experience"), keywords_to_inject=top_missing, intensity=exp_intensity),
        tailor_projects([p.model_dump() for p in resume.projects], enrich_jd_context("Projects"), keywords_to_inject=top_missing, intensity=proj_intensity),
        tailor_summary(resume.summary, enrich_jd_context("Summary"), keywords_to_inject=top_missing, intensity=sum_intensity),
        tailor_education([e.model_dump() for e in resume.education], enrich_jd_context("Education"), keywords_to_inject=top_missing, intensity=edu_intensity)
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    exp_r = results[0] if not isinstance(results[0], Exception) else []
    proj_r = results[1] if not isinstance(results[1], Exception) else []
    sum_r = results[2] if not isinstance(results[2], Exception) else []
    edu_r = results[3] if not isinstance(results[3], Exception) else []

    # Flatten and generate standard IDs
    raw_suggestions = {
        "Summary": sum_r,
        "Experience": exp_r,
        "Projects": proj_r,
        "Education": edu_r
    }
    
    flat_suggestions = []
    id_counter = 1
    for section_label, suggs in raw_suggestions.items():
        for s in suggs:
            s["id"] = id_counter
            s["section"] = section_label
            id_counter += 1
            flat_suggestions.append(s)

    project_names = [p.name or f"Project {i+1}" for i, p in enumerate(resume.projects)]

    # Apply the fanned-out suggestions to build the tailored candidate profile JSON
    next_resume = apply_suggestions(resume, flat_suggestions)

    return {
        "current_resume": next_resume,
        "suggestions": flat_suggestions,
        "project_names": project_names,
        # Clear chat inputs once consumed
        "user_prompt": None
    }

# 4. Node: Align Skills
async def align_skills_node(state: TailorGraphState) -> Dict[str, Any]:
    logger.info("[LangGraph] Node: align_skills")
    resume = state["current_resume"]
    jd_text = state["jd_text"]
    
    # Call core tailor_skills to align categories, moving, deleting, or adding.
    # It incorporates the now-tailored Experience/Projects as context.
    try:
        from app.core.tailor_orchestrator import build_skills_contexts
        exp_ctx, proj_ctx, cert_ctx = build_skills_contexts(resume)
        
        global_intensity = state.get("intensity", "balanced")
        section_intensities = state.get("section_intensities") or {}
        skills_intensity = section_intensities.get("skills", global_intensity)

        flat_skills = [s.model_dump() for s in resume.skills]
        skills_suggestions = await tailor_skills(
            skills=flat_skills,
            jd_text=jd_text,
            keywords_to_inject=state.get("missing_keywords", []),
            experience_ctx=exp_ctx,
            projects_ctx=proj_ctx,
            certifications_ctx=cert_ctx,
            user_prompt=None,
            intensity=skills_intensity,
        )
        
        # Deterministic ADD additions based on newly tailored bullets
        from app.core.tailor_orchestrator import _derive_skill_additions
        tailored_text = resume_to_plaintext(resume)
        skill_adds = _derive_skill_additions(resume, tailored_text, jd_text, id_start=5000)
        
        all_skills_suggs = skills_suggestions + skill_adds
        
        # Merge skills suggestions into overall suggestions list
        current_suggs = list(state.get("suggestions", []))
        id_start = max([s.get("id", 0) for s in current_suggs], default=0) + 1
        
        for idx, s in enumerate(all_skills_suggs):
            s["id"] = id_start + idx
            current_suggs.append(s)
            
        # Apply skills updates
        next_resume = apply_suggestions(resume, all_skills_suggs)
        
        return {
            "current_resume": next_resume,
            "suggestions": current_suggs
        }
    except Exception as e:
        logger.error("Align skills node failed: %s", e)
        return {}

# 5. Node: Evaluate & Score
async def evaluate_and_score_node(state: TailorGraphState) -> Dict[str, Any]:
    logger.info("[LangGraph] Node: evaluate_and_score")
    resume = state["current_resume"]
    jd_text = state["jd_text"]
    resume_plaintext = resume_to_plaintext(resume)
    
    # Calculate global score + breakdown
    try:
        score_res = score_resume_against_jd(
            resume_text=resume_plaintext,
            resume_json=resume.model_dump(),
            jd_text=jd_text,
            log_event=False
        )
        match_score = score_res.get("score", 0)
    except Exception as e:
        logger.error("Scoring failed in evaluate node: %s", e)
        match_score = 50

    # Calculate section-level scores
    try:
        section_scores = compute_section_scores(resume, jd_text)
    except Exception as e:
        logger.warning("Section scoring failed: %s", e)
        section_scores = {"Experience": 50, "Projects": 50, "Skills": 50, "Summary": 50}

    # Identify low-scoring sections with specific gap analysis
    try:
        gap_res = compute_gap_analysis(resume, resume_plaintext, jd_text, section_scores)
        low_sections = gap_res.get("low_sections", [])
    except Exception as e:
        logger.warning("Gap analysis failed: %s", e)
        low_sections = []

    logger.info("[LangGraph] Iteration %d - Match Score: %d%%", state.get("iteration", 1), match_score)
    return {
        "match_score": match_score,
        "section_scores": section_scores,
        "low_sections": low_sections
    }

# 6. Node: Critique Low Sections (Self-Correction Creator)
async def critique_low_sections_node(state: TailorGraphState) -> Dict[str, Any]:
    logger.info("[LangGraph] Node: critique_low_sections")
    low_sections = state.get("low_sections", [])
    jd_text = state["jd_text"]
    
    if not low_sections:
        return {"critique_instructions": {}, "iteration": state.get("iteration", 1) + 1}
        
    critique_instructions = {}
    sect_text = resume_to_plaintext(state["current_resume"])

    async def _critique_one(section_info: dict) -> tuple[str, str]:
        sect = section_info["section"]
        prompt = (
            f"You are a Senior Technical Recruiter criticking a resume section.\n"
            f"The candidate's '{sect}' section scored low ({section_info['score']}/100) because it lacks keyword relevance or depth.\n"
            f"Review the JD requirements and the resume text, and write exactly 2-3 specific, actionable instructions on how to re-write "
            f"the details to align better with the JD without fabricating credentials.\n\n"
            f"JOB DESCRIPTION:\n{jd_text[:1500]}\n\n"
            f"CANDIDATE SECTION CONTENT:\n{sect_text[:1500]}\n\n"
            f"Provide ONLY clear, concise bullet points of critique instructions. Do not output JSON or conversational filler."
        )
        critique = await _chat([{"role": "user", "content": prompt}], json_mode=False)
        return sect, critique.strip()

    # Parallel critique calls for the worst 2 sections
    critique_results = await asyncio.gather(
        *[_critique_one(s) for s in low_sections[:2]],
        return_exceptions=True,
    )
    for res in critique_results:
        if isinstance(res, Exception):
            logger.warning("Failed to generate critique: %s", res)
            continue
        sect, critique = res
        critique_instructions[sect] = critique
        logger.info("[LangGraph] Generated critique for %s:\n%s", sect, critique[:100] + "...")
            
    return {
        "critique_instructions": critique_instructions,
        "iteration": state.get("iteration", 1) + 1
    }

# Conditional Routing Edge
def route_tailoring(state: TailorGraphState) -> Literal["critique_low_sections", "__end__"]:
    score = state.get("match_score", 0)
    iteration = state.get("iteration", 1)
    max_iterations = state.get("max_iterations", 2)
    low_sections = state.get("low_sections", [])
    
    # Auto-correct loop condition: score < 78% and iterations limit not exceeded
    if score < 78 and iteration < max_iterations and low_sections:
        logger.info("[LangGraph] Score (%d%%) is below target. Re-routing to critique loop.", score)
        return "critique_low_sections"
        
    logger.info("[LangGraph] Flow completed successfully. Proceeding to end.", score)
    return "__end__"

# Assemble and compile the LangGraph workflow
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

def compile_tailor_graph():
    workflow = StateGraph(TailorGraphState)
    
    # Add Nodes
    workflow.add_node("analyze_jd", analyze_jd_node)
    workflow.add_node("retrieve_rag_context", retrieve_rag_context_node)
    workflow.add_node("tailor_sections", tailor_sections_node)
    workflow.add_node("align_skills", align_skills_node)
    workflow.add_node("evaluate_and_score", evaluate_and_score_node)
    workflow.add_node("critique_low_sections", critique_low_sections_node)
    
    # Add Edge Transitions
    workflow.add_edge(START, "analyze_jd")
    workflow.add_edge("analyze_jd", "retrieve_rag_context")
    workflow.add_edge("retrieve_rag_context", "tailor_sections")
    workflow.add_edge("tailor_sections", "align_skills")
    workflow.add_edge("align_skills", "evaluate_and_score")
    
    # Add Conditional Edge from Scorer -> Loop OR End
    workflow.add_conditional_edges(
        "evaluate_and_score",
        route_tailoring
    )
    
    # Critique loops back to tailoring
    workflow.add_edge("critique_low_sections", "tailor_sections")
    
    # Compile with local memory saving
    checkpointer = MemorySaver()
    return workflow.compile(checkpointer=checkpointer)

# Shared singleton compiled graph instance
compiled_tailor_graph = compile_tailor_graph()
