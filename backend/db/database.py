"""
db/database.py — Phase 3 updated
Added: User model, user_id FK on Document, ComparisonReport model
"""

from sqlalchemy import create_engine, text, Boolean
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


# ── Enums ─────────────────────────────────────────────────────────────────────

class DocumentStatus(str, enum.Enum):
    PENDING    = "pending"
    PROCESSING = "processing"
    READY      = "ready"
    FAILED     = "failed"

class ClauseType(str, enum.Enum):
    INDEMNIFICATION    = "indemnification"
    TERMINATION        = "termination"
    LIABILITY_CAP      = "liability_cap"
    CONFIDENTIALITY    = "confidentiality"
    GOVERNING_LAW      = "governing_law"
    DISPUTE_RESOLUTION = "dispute_resolution"
    PAYMENT            = "payment"
    IP_OWNERSHIP       = "ip_ownership"
    NON_COMPETE        = "non_compete"
    FORCE_MAJEURE      = "force_majeure"
    AUTO_RENEWAL       = "auto_renewal"
    PENALTY            = "penalty"
    OTHER              = "other"

class RiskLevel(str, enum.Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


# ── Models ────────────────────────────────────────────────────────────────────

class User(Base):
    """Registered user — all documents scoped to a user_id."""
    __tablename__ = "users"

    id         = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email      = Column(String(320), nullable=False, unique=True, index=True)
    name       = Column(String(256), nullable=False)
    hashed_pw  = Column(String(256), nullable=False)
    is_active  = Column(Integer, default=1)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Document(Base):
    __tablename__ = "documents"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id     = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    filename    = Column(String(512), nullable=False)
    storage_key = Column(String(1024), nullable=False)
    status      = Column(Enum(DocumentStatus), default=DocumentStatus.PENDING)
    page_count  = Column(Integer, nullable=True)
    char_count  = Column(Integer, nullable=True)
    metadata_   = Column("metadata", JSONB, default=dict)
    created_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                         onupdate=lambda: datetime.now(timezone.utc))


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_index = Column(Integer, nullable=False)
    section     = Column(String(512), nullable=True)
    content     = Column(Text, nullable=False)
    token_count = Column(Integer, nullable=True)
    embedding   = Column(Vector(1536), nullable=True)
    metadata_   = Column("metadata", JSONB, default=dict)
    created_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ExtractedClause(Base):
    __tablename__ = "extracted_clauses"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id   = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    chunk_id      = Column(UUID(as_uuid=True), ForeignKey("document_chunks.id", ondelete="SET NULL"), nullable=True)
    clause_type   = Column(Enum(ClauseType), nullable=False)
    title         = Column(String(512), nullable=False)
    content       = Column(Text, nullable=False)
    summary       = Column(Text, nullable=True)
    risk_level    = Column(Enum(RiskLevel), nullable=False, default=RiskLevel.LOW)
    risk_score    = Column(Integer, nullable=False, default=0)
    risk_reasons  = Column(JSONB, default=list)
    page_numbers  = Column(JSONB, default=list)
    metadata_     = Column("metadata", JSONB, default=dict)
    created_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class DocumentRiskScore(Base):
    __tablename__ = "document_risk_scores"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id     = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"),
                             nullable=False, unique=True)
    overall_score   = Column(Integer, nullable=False, default=0)
    overall_level   = Column(Enum(RiskLevel), nullable=False, default=RiskLevel.LOW)
    clause_count    = Column(Integer, default=0)
    high_risk_count = Column(Integer, default=0)
    score_breakdown = Column(JSONB, default=dict)
    summary         = Column(Text, nullable=True)
    created_at      = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at      = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc),
                             onupdate=lambda: datetime.now(timezone.utc))


class ComparisonReport(Base):
    """Stores results of a multi-document comparison."""
    __tablename__ = "comparison_reports"

    id            = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id       = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True)
    doc_a_id      = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    doc_b_id      = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    diff_summary  = Column(Text, nullable=True)        # LLM-generated diff narrative
    clause_diffs  = Column(JSONB, default=list)        # per-clause diff objects
    recommendation= Column(Text, nullable=True)        # which doc is better and why
    created_at    = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class QASession(Base):
    __tablename__ = "qa_sessions"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    document_id = Column(UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    question    = Column(Text, nullable=False)
    answer      = Column(Text, nullable=False)
    sources     = Column(JSONB, default=list)
    confidence  = Column(Float, nullable=True)
    created_at  = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


# ── Helpers ───────────────────────────────────────────────────────────────────

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(bind=engine)
    print("✓ Database initialised")
