"""
routers/documents.py — Phase 2 updated

New in Phase 2:
  GET  /documents/{id}/risk       — risk score + signal breakdown
  GET  /documents/{id}/clauses    — extracted clauses list
  POST /documents/{id}/reanalyse  — re-run clause extraction
  GET  /jobs/{task_id}            — Celery job status polling
"""

import io
from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import (
    get_db, Document, DocumentChunk, DocumentStatus,
    ExtractedClause, DocumentRiskScore, ClauseType, RiskLevel
)
from services.storage_service import save_upload, load_file, delete_file
from config import settings

try:
    from worker import ingest_document_task, reanalyse_clauses_task, celery_app
    CELERY_AVAILABLE = True
except Exception:
    CELERY_AVAILABLE = False

router = APIRouter(prefix="/documents", tags=["documents"])


# ── Response schemas ──────────────────────────────────────────────────────────

class ChunkOut(BaseModel):
    id: str
    chunk_index: int
    section: Optional[str]
    content: str
    token_count: Optional[int]
    page_numbers: List[int]

class DocumentOut(BaseModel):
    id: str
    filename: str
    status: str
    page_count: Optional[int]
    char_count: Optional[int]
    chunk_count: int
    has_risk_score: bool
    created_at: str

class DocumentDetail(DocumentOut):
    chunks: List[ChunkOut]

class ClauseOut(BaseModel):
    id: str
    clause_type: str
    title: str
    summary: Optional[str]
    risk_level: str
    risk_score: int
    risk_reasons: List[str]
    page_numbers: List[int]
    content: str

class RiskScoreOut(BaseModel):
    overall_score: int
    overall_level: str
    clause_count: int
    high_risk_count: int
    score_breakdown: dict
    summary: Optional[str]

class JobStatusOut(BaseModel):
    task_id: str
    status: str       # PENDING, PROGRESS, SUCCESS, FAILURE
    step: Optional[str]
    pct: Optional[int]
    error: Optional[str]


# ── Sync fallback ingestion (when Celery/Redis unavailable) ──────────────────

def _sync_ingest(document_id: str, storage_key: str, filename: str, db: Session):
    from db.database import DocumentChunk
    from services.pdf_service import parse_and_chunk
    from services.embedding_service import embed_and_store_chunks
    from services.clause_service import extract_all_clauses
    from services.risk_service import compute_document_risk
    from uuid import UUID as _UUID

    doc_uuid = _UUID(document_id)
    doc = db.query(Document).filter(Document.id == doc_uuid).first()
    if not doc:
        return
    try:
        doc.status = DocumentStatus.PROCESSING
        db.commit()
        local_path = load_file(storage_key)
        parsed = parse_and_chunk(local_path, filename)
        doc.page_count = parsed.page_count
        doc.char_count = parsed.char_count
        db.commit()
        embed_and_store_chunks(doc_uuid, parsed.chunks, db)
        chunks = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc_uuid).all()
        clauses = extract_all_clauses(doc_uuid, chunks, db)
        compute_document_risk(doc_uuid, clauses, db)
        doc.status = DocumentStatus.READY
        db.commit()
    except Exception as e:
        doc.status = DocumentStatus.FAILED
        doc.metadata_["error"] = str(e)
        db.commit()
        print(f"[Ingest] Failed: {e}")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=DocumentOut)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit.")

    storage_key = save_upload(io.BytesIO(content), file.filename)

    doc = Document(filename=file.filename, storage_key=storage_key, status=DocumentStatus.PENDING)
    db.add(doc)
    db.commit()
    db.refresh(doc)

    doc_id = str(doc.id)

    if CELERY_AVAILABLE:
        task = ingest_document_task.delay(doc_id, storage_key, file.filename)
        doc.metadata_["task_id"] = task.id
        db.commit()
    else:
        background_tasks.add_task(_sync_ingest, doc_id, storage_key, file.filename, db)

    count = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).count()
    return _doc_out(doc, count)


@router.get("/", response_model=List[DocumentOut])
def list_documents(db: Session = Depends(get_db)):
    docs = db.query(Document).order_by(Document.created_at.desc()).all()
    result = []
    for doc in docs:
        count = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).count()
        result.append(_doc_out(doc, count))
    return result


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(document_id: UUID, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    chunk_outs = [
        ChunkOut(
            id=str(c.id), chunk_index=c.chunk_index, section=c.section,
            content=c.content, token_count=c.token_count,
            page_numbers=c.metadata_.get("page_numbers", []),
        )
        for c in chunks
    ]
    out = _doc_out(doc, len(chunks))
    return DocumentDetail(**out.model_dump(), chunks=chunk_outs)


@router.get("/{document_id}/clauses", response_model=List[ClauseOut])
def get_clauses(document_id: UUID, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    clauses = (
        db.query(ExtractedClause)
        .filter(ExtractedClause.document_id == document_id)
        .order_by(ExtractedClause.risk_score.desc())
        .all()
    )
    return [
        ClauseOut(
            id=str(c.id),
            clause_type=c.clause_type.value,
            title=c.title,
            summary=c.summary,
            risk_level=c.risk_level.value,
            risk_score=c.risk_score,
            risk_reasons=c.risk_reasons or [],
            page_numbers=c.page_numbers or [],
            content=c.content,
        )
        for c in clauses
    ]


@router.get("/{document_id}/risk", response_model=RiskScoreOut)
def get_risk_score(document_id: UUID, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    risk = db.query(DocumentRiskScore).filter(DocumentRiskScore.document_id == document_id).first()
    if not risk:
        raise HTTPException(status_code=404, detail="Risk score not yet computed.")

    return RiskScoreOut(
        overall_score=risk.overall_score,
        overall_level=risk.overall_level.value,
        clause_count=risk.clause_count,
        high_risk_count=risk.high_risk_count,
        score_breakdown=risk.score_breakdown,
        summary=risk.summary,
    )


@router.post("/{document_id}/reanalyse", status_code=202)
def reanalyse(document_id: UUID, db: Session = Depends(get_db)):
    """Re-run clause extraction + risk scoring without re-embedding."""
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.status != DocumentStatus.READY:
        raise HTTPException(status_code=400, detail="Document must be in 'ready' state.")

    if CELERY_AVAILABLE:
        task = reanalyse_clauses_task.delay(str(document_id))
        return {"task_id": task.id, "message": "Reanalysis queued"}
    raise HTTPException(status_code=503, detail="Celery not available. Start Redis to enable async jobs.")


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: UUID, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    delete_file(doc.storage_key)
    db.delete(doc)
    db.commit()


# ── Job status endpoint ───────────────────────────────────────────────────────

@router.get("/jobs/{task_id}", response_model=JobStatusOut)
def job_status(task_id: str):
    """Poll Celery task status — used by frontend progress bar."""
    if not CELERY_AVAILABLE:
        return JobStatusOut(task_id=task_id, status="UNKNOWN", step=None, pct=None, error=None)

    from celery.result import AsyncResult
    result = AsyncResult(task_id, app=celery_app)

    step = pct = error = None
    if result.state == "PROGRESS" and isinstance(result.info, dict):
        step = result.info.get("step")
        pct = result.info.get("pct")
    elif result.state == "FAILURE":
        error = str(result.info)

    return JobStatusOut(
        task_id=task_id,
        status=result.state,
        step=step,
        pct=pct,
        error=error,
    )


# ── Helper ────────────────────────────────────────────────────────────────────

def _doc_out(doc: Document, chunk_count: int) -> DocumentOut:
    has_risk = doc.metadata_.get("has_risk", False) if doc.metadata_ else False
    return DocumentOut(
        id=str(doc.id),
        filename=doc.filename,
        status=doc.status.value,
        page_count=doc.page_count,
        char_count=doc.char_count,
        chunk_count=chunk_count,
        has_risk_score=has_risk,
        created_at=doc.created_at.isoformat(),
    )
