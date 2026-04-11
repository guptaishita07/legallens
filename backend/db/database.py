"""
db/database.py
Handles PostgreSQL connection and pgvector extension setup.
"""

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from sqlalchemy import Column, String, Integer, DateTime, Float, Text, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector
import uuid
import enum
from datetime import datetime, timezone
from config import settings


engine = create_engine(settings.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


# ── Enums ────────────────────────────────────────────────────────────────────

class DocumentStatus(str, enum.Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    READY      = "ready"
    FAILED     = "failed"


# ── Models ───────────────────────────────────────────────────────────────────

class Document(Base):
    """One uploaded contract PDF."""
    __tablename__ = "documents"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    filename    = Column(String(512), nullable=False)
    storage_key = Column(String(1024), nullable=False)   # S3 key or local path
    status      = Column(Enum(DocumentStatus), default=DocumentStatus.PENDING)
    page_count  = Column(Integer, nullable=True)
    char_count  = Column(Integer, nullable=True)
    metadata_   = Column("metadata", JSONB, default=dict)
    created_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))


class DocumentChunk(Base):
    """
    A semantically meaningful piece of a document.
    Each chunk has its own embedding vector stored via pgvector.
    """
    __tablename__ = "document_chunks"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)         # order within document
    section     = Column(String(512), nullable=True)      # clause heading if detected
    content     = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=True)
    embedding   = Column(Vector(1536), nullable=True)     # OpenAI text-embedding-3-small = 1536 dims
    metadata_   = Column("metadata", JSONB, default=dict)
    created_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class QASession(Base):
    """Stores Q&A history per document."""
    __tablename__ = "qa_sessions"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    question    = Column(Text, nullable=False)
    answer      = Column(Text, nullable=False)
    sources     = Column(JSONB, default=list)     # list of chunk_ids used
    confidence  = Column(Float, nullable=True)    # faithfulness score 0-1
    created_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ── Helpers ──────────────────────────────────────────────────────────────────

def get_db():
    """FastAPI dependency — yields a DB session and closes it after the request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """
    Create tables and enable the pgvector extension.
    Call this once at startup (or run Alembic migrations in production).
    """
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    print("✓ Database tables created with pgvector extension")
