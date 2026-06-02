from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = "postgres"
    POSTGRES_DB: str = "resumedb"
    POSTGRES_HOST: str = "localhost" # For local development
    POSTGRES_PORT: int = 5434

    @property
    def DATABASE_URL(self) -> str:
        return f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"

    # Upload directory (override for local dev; inside Docker this is /app/uploads)
    UPLOAD_DIR: str = "/app/uploads"

    # Qdrant
    QDRANT_HOST: str = "localhost"
    QDRANT_PORT: int = 6334

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    CACHE_ENABLED: bool = True

    # LLM
    LLM_PROVIDER: str = "groq"
    GROQ_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None

    # Groq model tiers (free open-source). FAST = bulk edits (low latency / high TPM),
    # SMART = obedience-critical nodes (router, answer) where instruction-following matters.
    GROQ_MODEL_FAST: str = "llama-3.1-8b-instant"
    GROQ_MODEL_SMART: str = "llama-3.3-70b-versatile"

    # Set to false in dev so restarts are instant; model lazy-loads on first request
    PRELOAD_EMBEDDING_MODEL: bool = True

    # CORS allowed origins (comma-separated or from env var)
    CORS_ALLOWED_ORIGINS: str = "http://localhost:3004,http://127.0.0.1:3004,https://brollysolutions.in"

    class Config:
        env_file = "../.env" # Points to the root .env file
        extra = "ignore" # Ignore frontend vars like NEXT_PUBLIC_API_URL

settings = Settings()
