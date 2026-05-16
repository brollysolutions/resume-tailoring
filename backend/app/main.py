import logging
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
    yield


app = FastAPI(
    title="AI Resume Matcher & Tailoring Engine",
    description="API for parsing resumes, matching with jobs, and generating tailored content.",
    version="1.0.0",
    lifespan=lifespan,
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


from app.api import resume, match, tailor

app.include_router(resume.router, prefix="/api/resume", tags=["Resume"])
app.include_router(match.router, prefix="/api/match", tags=["Match"])
app.include_router(tailor.router, prefix="/api/tailor", tags=["Tailor"])


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8004, reload=True)
