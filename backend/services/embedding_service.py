"""
services/embedding_service.py

Generates embeddings for document chunks and stores them in pgvector.
Also builds a BM25 index per document for hybrid retrieval (Phase 1 prep).

Design decisions:
  - Batch embeds in groups of 100 to stay within OpenAI rate limits.
  - Stores embeddings directly on the DocumentChunk row (pgvector column).
  - BM25 index is held in memory and keyed by document_id for now;
    in production you'd serialise it to Redis (Phase 2).
"""

import time
from typing import List, Dict, Optional
from uuid import UUID

from openai import OpenAI
from sqlalchemy.orm import Session
from rank_bm25 import BM25Okapi

from config import settings
from db.database import DocumentChunk
from services.pdf_service import ParsedChunk


# ── Clients ───────────────────────────────────────────────────────────────────

_openai_client: Optional[OpenAI] = None

def _get_openai() -> OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_client


# ── In-memory BM25 store (replace with Redis serialisation in Phase 2) ────────

_bm25_store: Dict[str, BM25Okapi] = {}


def get_bm25(document_id: str) -> Optional[BM25Okapi]:
    return _bm25_store.get(document_id)


# ── Embedding generation ──────────────────────────────────────────────────────

EMBED_BATCH_SIZE = 100   # OpenAI allows up to 2048 inputs per call, but 100 is safe


def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Embed a list of strings using OpenAI text-embedding-3-small.
    Returns a list of 1536-dimensional float vectors.
    """
    client = _get_openai()
    all_embeddings = []

    for i in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[i : i + EMBED_BATCH_SIZE]
        response = client.embeddings.create(
            model=settings.EMBEDDING_MODEL,
            input=batch,
        )
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)

        # Respect rate limits in production — remove sleep for dev speed
        if i + EMBED_BATCH_SIZE < len(texts):
            time.sleep(0.1)

    return all_embeddings


# ── Persist chunks + embeddings ───────────────────────────────────────────────

def embed_and_store_chunks(
    document_id: UUID,
    chunks: List[ParsedChunk],
    db: Session,
) -> None:
    """
    Takes parsed chunks, generates embeddings in batches, saves to DB.
    Also builds and caches a BM25 index for the document.
    """
    texts = [chunk.content for chunk in chunks]

    print(f"  Generating embeddings for {len(texts)} chunks...")
    vectors = embed_texts(texts)

    # Persist to database
    db_chunks = []
    for chunk, vector in zip(chunks, vectors):
        db_chunk = DocumentChunk(
            document_id=document_id,
            chunk_index=chunk.chunk_index,
            section=chunk.section,
            content=chunk.content,
            token_count=chunk.token_count,
            embedding=vector,
            metadata_={
                "page_numbers": chunk.page_numbers,
                **chunk.metadata,
            },
        )
        db_chunks.append(db_chunk)

    db.bulk_save_objects(db_chunks)
    db.commit()
    print(f"  ✓ Saved {len(db_chunks)} chunks with embeddings")

    # Build BM25 index (tokenise by whitespace for simplicity)
    tokenised = [text.lower().split() for text in texts]
    _bm25_store[str(document_id)] = BM25Okapi(tokenised)
    print(f"  ✓ BM25 index built for document {document_id}")


# ── Query embedding ───────────────────────────────────────────────────────────

def embed_query(query: str) -> List[float]:
    """Embed a single query string."""
    return embed_texts([query])[0]
