import logging
import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    from app.core.config import settings
    if settings.PRELOAD_EMBEDDING_MODEL:
        logger.info("Preloading embedding model...")
        try:
            from app.core.vector_db import preload_embedding_model
            preload_embedding_model()
            logger.info("Embedding model ready.")
        except Exception as e:
            logger.warning(f"Embedding preload failed (will lazy-load on first request): {e}")
    else:
        logger.info("Skipping embedding preload (lazy-load on first request).")

    # Background auto-calibrator: derives labels from acceptance events and
    # re-fits scoring weights when ≥ TRIGGER_NEW_UPLOADS new resume uploads accumulate.
    calibrator_task: asyncio.Task | None = None
    try:
        from app.core.auto_calibrator import watcher_loop
        calibrator_task = asyncio.create_task(watcher_loop())
    except Exception as e:
        logger.warning(f"auto_calibrator failed to start (non-fatal): {e}")

    try:
        yield
    finally:
        if calibrator_task is not None:
            calibrator_task.cancel()
            try:
                await calibrator_task
            except (asyncio.CancelledError, Exception):
                pass


# ROOT_PATH lets FastAPI generate correct URLs when served under a sub-path
# e.g. BACKEND_ROOT_PATH=/resume-tailor/api → /docs works at brollysolutions.in/resume-tailor/api/docs
root_path = os.environ.get("BACKEND_ROOT_PATH", "")

app = FastAPI(
    title="AI Resume Matcher & Tailoring Engine",
    description="API for parsing resumes, matching with jobs, and generating tailored content.",
    version="1.0.0",
    lifespan=lifespan,
    root_path=root_path,
)

# Load CORS settings from environment/config
from app.core.config import settings
cors_origins = [origin.strip() for origin in settings.CORS_ALLOWED_ORIGINS.split(",")]

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}


from app.api import resume, match, tailor, admin

app.include_router(resume.router, prefix="/api/resume", tags=["Resume"])
app.include_router(match.router, prefix="/api/match", tags=["Match"])
app.include_router(tailor.router, prefix="/api/tailor", tags=["Tailor"])
app.include_router(admin.router, prefix="/api/admin", tags=["Admin"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8055, reload=True)
