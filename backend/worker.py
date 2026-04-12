"""
worker.py — Celery task definitions

Replaces FastAPI BackgroundTasks (Phase 1) with a proper task queue.
This means:
  - Jobs survive server restarts
  - Jobs can be monitored (Flower UI)
  - Failed jobs can be retried automatically
  - Multiple workers can process in parallel

Run the worker separately:
  celery -A worker worker --loglevel=info

Monitor with Flower (optional):
  celery -A worker flower --port=5555
"""

from celery import Celery
from celery.utils.log import get_task_logger

from config import settings

# Create Celery app
celery_app = Celery(
    "legallens",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,          # only ack after task completes (prevents loss on crash)
    worker_prefetch_multiplier=1, # one job at a time per worker (LLM calls are slow)
    result_expires=3600,          # keep results for 1 hour
)

logger = get_task_logger(__name__)


# ── Task: Full document ingestion pipeline ────────────────────────────────────

@celery_app.task(
    bind=True,
    name="tasks.ingest_document",
    max_retries=2,
    default_retry_delay=30,
)
def ingest_document_task(self, document_id: str, storage_key: str, filename: str):
    """
    Full ingestion pipeline:
      Phase 1: PDF parse → chunk → embed → pgvector store
      Phase 2: Clause extraction → risk scoring

    Task state is tracked in Redis so the frontend can poll progress.
    """
    # Late imports to avoid circular deps at module load
    from db.database import SessionLocal, Document, DocumentChunk, DocumentStatus
    from services.storage_service import load_file
    from services.pdf_service import parse_and_chunk
    from services.embedding_service import embed_and_store_chunks
    from services.clause_service import extract_all_clauses
    from services.risk_service import compute_document_risk
    from uuid import UUID

    db = SessionLocal()

    def update_state(state: str, meta: dict):
        self.update_state(state=state, meta=meta)

    try:
        doc_uuid = UUID(document_id)

        # ── Step 1: Mark as processing ────────────────────────────────────────
        doc = db.query(Document).filter(Document.id == doc_uuid).first()
        if not doc:
            logger.error(f"Document {document_id} not found")
            return

        doc.status = DocumentStatus.PROCESSING
        db.commit()
        update_state("PROGRESS", {"step": "parsing", "pct": 5})

        # ── Step 2: PDF parsing + chunking ─────────────────────────────────
        logger.info(f"[{document_id}] Parsing PDF: {filename}")
        local_path = load_file(storage_key)
        parsed = parse_and_chunk(local_path, filename)

        doc.page_count = parsed.page_count
        doc.char_count = parsed.char_count
        db.commit()
        update_state("PROGRESS", {"step": "embedding", "pct": 25})

        # ── Step 3: Embeddings + pgvector storage ──────────────────────────
        logger.info(f"[{document_id}] Embedding {len(parsed.chunks)} chunks")
        embed_and_store_chunks(doc_uuid, parsed.chunks, db)
        update_state("PROGRESS", {"step": "extracting_clauses", "pct": 50})

        # ── Step 4: Clause extraction (Phase 2) ────────────────────────────
        logger.info(f"[{document_id}] Extracting clauses")
        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc_uuid)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )
        clauses = extract_all_clauses(doc_uuid, chunks, db)
        update_state("PROGRESS", {"step": "scoring_risk", "pct": 80})

        # ── Step 5: Risk scoring (Phase 2) ─────────────────────────────────
        logger.info(f"[{document_id}] Computing risk score")
        compute_document_risk(doc_uuid, clauses, db)

        # ── Step 6: Done ────────────────────────────────────────────────────
        doc.status = DocumentStatus.READY
        db.commit()
        update_state("SUCCESS", {"step": "ready", "pct": 100})
        logger.info(f"[{document_id}] ✓ Ingestion complete")

        return {"status": "ready", "document_id": document_id}

    except Exception as exc:
        logger.error(f"[{document_id}] Ingestion failed: {exc}", exc_info=True)
        try:
            doc = db.query(Document).filter(Document.id == doc_uuid).first()
            if doc:
                doc.status = DocumentStatus.FAILED
                doc.metadata_["error"] = str(exc)
                db.commit()
        except Exception:
            pass
        raise self.retry(exc=exc)
    finally:
        db.close()


# ── Task: Re-run clause extraction only (useful for re-analysis) ──────────────

@celery_app.task(name="tasks.reanalyse_clauses")
def reanalyse_clauses_task(document_id: str):
    """Re-run clause extraction + risk scoring on an already-indexed document."""
    from db.database import SessionLocal, DocumentChunk, ExtractedClause, DocumentRiskScore
    from services.clause_service import extract_all_clauses
    from services.risk_service import compute_document_risk
    from uuid import UUID

    db = SessionLocal()
    try:
        doc_uuid = UUID(document_id)

        # Clear existing analysis
        db.query(ExtractedClause).filter(ExtractedClause.document_id == doc_uuid).delete()
        db.query(DocumentRiskScore).filter(DocumentRiskScore.document_id == doc_uuid).delete()
        db.commit()

        chunks = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc_uuid)
            .order_by(DocumentChunk.chunk_index)
            .all()
        )

        clauses = extract_all_clauses(doc_uuid, chunks, db)
        compute_document_risk(doc_uuid, clauses, db)
        return {"status": "done", "clauses": len(clauses)}
    finally:
        db.close()
