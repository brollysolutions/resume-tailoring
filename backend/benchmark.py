import asyncio
import time
import json
from pathlib import Path

from app.core.sample_resume import build_sample_resume
from app.models.resume_schema import Resume

# We will conditionally import score_resume_against_jd because its signature will change to async
import app.api.match_logic.hybrid_scorer as hs

JD_DIR = Path("backend/tests/data/jds")

def load_jd(filename: str) -> str:
    path = JD_DIR / filename
    # Handle if run from inside backend/ or root/
    if not path.exists():
        path = Path("tests/data/jds") / filename
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

async def run_benchmark():
    print("Initializing Benchmark...")
    resume = build_sample_resume()
    resume_text = resume.to_plaintext() if hasattr(resume, 'to_plaintext') else ""
    if not resume_text:
        # Fallback if to_plaintext isn't on the model
        from app.api.match_logic.section_scorer import _section_text, _SECTIONS
        resume_text = "\n".join(_section_text(resume, s) for s in _SECTIONS)

    resume_json = resume.model_dump()
    
    jds = {
        "Technical": load_jd("technical.md"),
        "Management": load_jd("management.md")
    }

    dummy_emb_res = [0.1] * 768
    dummy_emb_jd = [0.1] * 768

    print(f"\n{'='*40}\nStarting Benchmark\n{'='*40}")
    
    is_async = asyncio.iscoroutinefunction(hs.score_resume_against_jd)

    for name, jd_text in jds.items():
        print(f"\n--- Testing JD: {name} ---")
        start_time = time.time()
        
        try:
            if is_async:
                res = await hs.score_resume_against_jd(
                    resume_text=resume_text,
                    resume_json=resume_json,
                    jd_text=jd_text,
                    resume_embedding=dummy_emb_res,
                    jd_embedding=dummy_emb_jd,
                    log_event=False
                )
            else:
                res = hs.score_resume_against_jd(
                    resume_text=resume_text,
                    resume_json=resume_json,
                    jd_text=jd_text,
                    resume_embedding=dummy_emb_res,
                    jd_embedding=dummy_emb_jd,
                    log_event=False
                )
            
            elapsed = time.time() - start_time
            print(f"Time Taken  : {elapsed:.3f} seconds")
            print(f"Total Score : {res['score']}%")
            print(f"Edu Fit     : {res['breakdown']['education']}%")
            print(f"Seniority   : {res['breakdown']['seniority']}%")
            print(f"Skill Fit   : {res['breakdown']['skill_coverage']}%")
        except Exception as e:
            print(f"Error during scoring: {e}")

if __name__ == "__main__":
    asyncio.run(run_benchmark())
