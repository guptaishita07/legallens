"""
routers/qa.py

Endpoints:
  POST /qa/{document_id}/ask      — ask a question about a contract
  GET  /qa/{document_id}/history  — get past Q&A for a document
"""

from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db, Document, DocumentStatus, QASession
from services.retrieval_service import retrieve
from services.llm_service import answer_question


router = APIRouter(prefix="/qa", tags=["qa"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class QuestionRequest(BaseModel):
    question: str


class SourceOut(BaseModel):
    chunk_id: str
    section: Optional[str]
    excerpt: str
    page_numbers: List[int]
    rrf_score: float


class AnswerOut(BaseModel):
    question: str
    answer: str
    confidence: float
    is_grounded: bool
    sources: List[SourceOut]
    session_id: str


class QAHistoryItem(BaseModel):
    id: str
    question: str
    answer: str
    confidence: Optional[float]
    is_grounded: bool
    created_at: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{document_id}/ask", response_model=AnswerOut)
def ask_question(
    document_id: UUID,
    body: QuestionRequest,
    db: Session = Depends(get_db),
):
    """
    Core RAG endpoint:
      1. Validate document is ready
      2. Hybrid retrieve relevant chunks
      3. Generate + verify answer
      4. Persist Q&A to database
      5. Return answer with sources
    """
    # Check document exists and is indexed
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.status != DocumentStatus.READY:
        raise HTTPException(
            status_code=400,
            detail=f"Document is not ready for Q&A (status: {doc.status.value}). "
                   "Please wait for ingestion to complete."
        )

    question = body.question.strip()
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")
    if len(question) > 1000:
        raise HTTPException(status_code=400, detail="Question too long (max 1000 chars).")

    # Retrieve relevant chunks
    chunks = retrieve(question, document_id, db)

    # Generate answer with faithfulness check
    result = answer_question(question, chunks)

    # Persist Q&A session
    session = QASession(
        document_id=document_id,
        question=question,
        answer=result.answer,
        sources=[s["chunk_id"] for s in result.sources],
        confidence=result.confidence,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    return AnswerOut(
        question=question,
        answer=result.answer,
        confidence=result.confidence,
        is_grounded=result.is_grounded,
        sources=[SourceOut(**s) for s in result.sources],
        session_id=str(session.id),
    )


@router.get("/{document_id}/history", response_model=List[QAHistoryItem])
def get_history(document_id: UUID, db: Session = Depends(get_db)):
    """Return all Q&A sessions for a document, newest first."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    sessions = (
        db.query(QASession)
        .filter(QASession.document_id == document_id)
        .order_by(QASession.created_at.desc())
        .all()
    )

    return [
        QAHistoryItem(
            id=str(s.id),
            question=s.question,
            answer=s.answer,
            confidence=s.confidence,
            is_grounded=s.confidence is not None and s.confidence >= 0.5,
            created_at=s.created_at.isoformat(),
        )
        for s in sessions
    ]
