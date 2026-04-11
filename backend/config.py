"""
config.py
Centralised settings loaded from .env.
"""

from pydantic_settings import BaseSettings
from functools import lru_cache
import os


class Settings(BaseSettings):
    # OpenAI
    OPENAI_API_KEY: str = ""
    ANTHROPIC_API_KEY: str = ""
    LLM_PROVIDER: str = "openai"          # "openai" | "anthropic"
    EMBEDDING_MODEL: str = "text-embedding-3-small"
    LLM_MODEL: str = "gpt-4o-mini"        # cheap but capable for dev

    # Database
    DATABASE_URL: str = "postgresql://postgres:postgres@localhost:5432/legallens"

    # Storage
    STORAGE_BACKEND: str = "local"        # "local" | "s3"
    LOCAL_UPLOAD_DIR: str = "./uploads"
    AWS_S3_BUCKET: str = ""
    AWS_REGION: str = "ap-south-1"

    # RAG tuning
    CHUNK_SIZE_TOKENS: int = 512          # target tokens per chunk
    CHUNK_OVERLAP_TOKENS: int = 64        # overlap between adjacent chunks
    RETRIEVAL_TOP_K: int = 20             # candidates fetched from vector DB
    RERANK_TOP_N: int = 5                 # chunks passed to LLM after reranking

    # App
    APP_ENV: str = "development"
    SECRET_KEY: str = "dev-secret-change-me"
    MAX_UPLOAD_SIZE_MB: int = 20

    class Config:
        env_file = ".env"
        extra = "ignore"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Create local upload dir if needed
if settings.STORAGE_BACKEND == "local":
    os.makedirs(settings.LOCAL_UPLOAD_DIR, exist_ok=True)
