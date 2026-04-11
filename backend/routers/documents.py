"""
routers/documents.py

Endpoints:
  POST /documents/upload  — upload a PDF, trigger ingestion
  GET  /documents/        — list all documents
  GET  /documents/{id}    — get document details + chunks
  DELETE /documents/{id}  — remove document and all chunks
"""

import os
from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import get_db, Document, DocumentChunk, DocumentStatus
from services.storage_service import save_upload, load_file, delete_file
from services.pdf_service import parse_and_chunk
from services.embedding_service import embed_and_store_chunks
from config import settings


router = APIRouter(prefix="/documents", tags=["documents"])


# ── Response schemas ──────────────────────────────────────────────────────────

class ChunkOut(BaseModel):
    id: str
    chunk_index: int
    section: Optional[str]
    content: str
    token_count: Optional[int]
    page_numbers: List[int]

    class Config:
        from_attributes = True


class DocumentOut(BaseModel):
    id: str
    filename: str
    status: str
    page_count: Optional[int]
    char_count: Optional[int]
    chunk_count: int
    created_at: str

    class Config:
        from_attributes = True


class DocumentDetail(DocumentOut):
    chunks: List[ChunkOut]


# ── Background ingestion task ─────────────────────────────────────────────────

def _ingest_document(document_id: str, storage_key: str, filename: str, db: Session):
    """
    Run after upload returns. Steps:
      1. Load PDF from storage
      2. Parse + chunk
      3. Generate embeddings
      4. Update document status
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        return

    try:
        doc.status = DocumentStatus.PROCESSING
        db.commit()

        # Load the PDF to a local path
        local_path = load_file(storage_key)

        # Parse and chunk
        print(f"[Ingest] Parsing {filename}...")
        parsed = parse_and_chunk(local_path, filename)

        # Generate + store embeddings
        print(f"[Ingest] Embedding {len(parsed.chunks)} chunks...")
        embed_and_store_chunks(UUID(document_id), parsed.chunks, db)

        # Update document metadata
        doc.page_count = parsed.page_count
        doc.char_count = parsed.char_count
        doc.status = DocumentStatus.READY
        db.commit()
        print(f"[Ingest] ✓ Document {document_id} ready")

    except Exception as e:
        print(f"[Ingest] ✗ Failed: {e}")
        doc.status = DocumentStatus.FAILED
        doc.metadata_["error"] = str(e)
        db.commit()


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/upload", response_model=DocumentOut)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """
    Upload a PDF contract. Returns immediately with status=pending.
    Ingestion (parsing + embedding) runs in the background.
    """
    # Validate file type
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    # Validate file size
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    content = await file.read()
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit."
        )

    # Save to storage
    import io
    storage_key = save_upload(io.BytesIO(content), file.filename)

    # Create DB record
    doc = Document(
        filename=file.filename,
        storage_key=storage_key,
        status=DocumentStatus.PENDING,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)

    # Kick off ingestion in background
    # NOTE: In Phase 2, replace this with a Celery task for proper async
    background_tasks.add_task(
        _ingest_document,
        str(doc.id),
        storage_key,
        file.filename,
        db,
    )

    chunk_count = db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).count()
    return _doc_out(doc, chunk_count)


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
            id=str(c.id),
            chunk_index=c.chunk_index,
            section=c.section,
            content=c.content,
            token_count=c.token_count,
            page_numbers=c.metadata_.get("page_numbers", []),
        )
        for c in chunks
    ]

    out = _doc_out(doc, len(chunks))
    return DocumentDetail(**out.model_dump(), chunks=chunk_outs)


@router.delete("/{document_id}", status_code=204)
def delete_document(document_id: UUID, db: Session = Depends(get_db)):
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    delete_file(doc.storage_key)
    db.delete(doc)  # cascades to chunks via FK
    db.commit()


# ── Helper ────────────────────────────────────────────────────────────────────

def _doc_out(doc: Document, chunk_count: int) -> DocumentOut:
    return DocumentOut(
        id=str(doc.id),
        filename=doc.filename,
        status=doc.status.value,
        page_count=doc.page_count,
        char_count=doc.char_count,
        chunk_count=chunk_count,
        created_at=doc.created_at.isoformat(),
    )
