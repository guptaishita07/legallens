"""
services/retrieval_service.py

Hybrid retrieval pipeline:
  1. Dense retrieval  — pgvector cosine similarity search
  2. Sparse retrieval — BM25 keyword matching
  3. Fusion           — Reciprocal Rank Fusion (RRF) merges both ranked lists
  4. (Phase 2) Re-ranking — cross-encoder re-scores top-20 → top-5

WHY HYBRID?
  Dense search handles semantic queries:
    "what are my liability protections?" → finds clause even without exact words
  BM25 handles exact queries:
    "find clause 12.3" or specific legal terms → dense may miss these
  RRF combines rankings without needing score normalisation.
"""

from typing import List, Tuple, Optional
from uuid import UUID
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from config import settings
from services.embedding_service import embed_query, get_bm25
from db.database import DocumentChunk


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    content: str
    section: Optional[str]
    page_numbers: List[int]
    rrf_score: float      # higher = more relevant


# ── Dense retrieval (pgvector) ────────────────────────────────────────────────

def dense_retrieve(
    query_embedding: List[float],
    document_id: UUID,
    db: Session,
    top_k: int = 20,
) -> List[Tuple[DocumentChunk, float]]:
    """
    Uses pgvector's <=> (cosine distance) operator.
    Returns (chunk, similarity_score) tuples sorted by relevance.
    """
    # pgvector cosine distance: 0 = identical, 2 = opposite
    # Convert to similarity: 1 - distance
    sql = text("""
        SELECT id, content, section, metadata_, token_count,
               1 - (embedding <=> CAST(:embedding AS vector)) AS similarity
        FROM document_chunks
        WHERE document_id = :doc_id
          AND embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:embedding AS vector)
        LIMIT :k
    """)

    result = db.execute(sql, {
        "embedding": str(query_embedding),
        "doc_id":    str(document_id),
        "k":         top_k,
    })

    rows = result.fetchall()
    return [(row, row.similarity) for row in rows]


# ── Sparse retrieval (BM25) ───────────────────────────────────────────────────

def sparse_retrieve(
    query: str,
    document_id: UUID,
    db: Session,
    top_k: int = 20,
) -> List[Tuple[str, float]]:
    """
    BM25 keyword search against the in-memory index.
    Returns (chunk_index, bm25_score) tuples.
    """
    bm25 = get_bm25(str(document_id))
    if bm25 is None:
        # BM25 index not in memory (server restart) — rebuild it
        _rebuild_bm25(document_id, db)
        bm25 = get_bm25(str(document_id))
        if bm25 is None:
            return []

    tokenised_query = query.lower().split()
    scores = bm25.get_scores(tokenised_query)

    # Get chunk IDs ordered by chunk_index from DB
    chunks = (
        db.query(DocumentChunk.id, DocumentChunk.chunk_index)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )

    scored = [(str(chunk.id), scores[i]) for i, chunk in enumerate(chunks) if i < len(scores)]
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_k]


def _rebuild_bm25(document_id: UUID, db: Session) -> None:
    """Rebuild BM25 index from DB (called after server restart)."""
    from rank_bm25 import BM25Okapi
    from services.embedding_service import _bm25_store

    chunks = (
        db.query(DocumentChunk.content)
        .filter(DocumentChunk.document_id == document_id)
        .order_by(DocumentChunk.chunk_index)
        .all()
    )
    tokenised = [c.content.lower().split() for c in chunks]
    _bm25_store[str(document_id)] = BM25Okapi(tokenised)


# ── Reciprocal Rank Fusion ────────────────────────────────────────────────────

RRF_K = 60   # standard constant; reduces impact of very high-ranked results


def reciprocal_rank_fusion(
    dense_results: List[Tuple],      # [(row, score), ...]
    sparse_results: List[Tuple[str, float]],  # [(chunk_id, bm25_score), ...]
) -> List[Tuple[str, float]]:
    """
    Combines two ranked lists into a single ranking.
    RRF score = Σ 1 / (k + rank_in_list)
    No score normalisation needed — ranks are directly combinable.
    """
    rrf_scores: dict[str, float] = {}

    # Dense ranks
    for rank, (row, _) in enumerate(dense_results, start=1):
        chunk_id = str(row.id)
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1 / (RRF_K + rank)

    # Sparse ranks
    for rank, (chunk_id, _) in enumerate(sparse_results, start=1):
        rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0) + 1 / (RRF_K + rank)

    return sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)


# ── Main retrieval pipeline ───────────────────────────────────────────────────

def retrieve(
    query: str,
    document_id: UUID,
    db: Session,
    top_n: Optional[int] = None,
) -> List[RetrievedChunk]:
    """
    Full hybrid retrieval:
      1. Embed query
      2. Dense + sparse retrieval
      3. RRF fusion
      4. Fetch full chunk data for top-N results

    Returns RetrievedChunk list ordered by relevance.
    """
    top_k = settings.RETRIEVAL_TOP_K
    top_n = top_n or settings.RERANK_TOP_N

    # 1. Embed query
    query_vec = embed_query(query)

    # 2. Retrieve from both indexes
    dense  = dense_retrieve(query_vec, document_id, db, top_k)
    sparse = sparse_retrieve(query, document_id, db, top_k)

    # 3. Fuse rankings
    fused = reciprocal_rank_fusion(dense, sparse)[:top_n]
    top_chunk_ids = [chunk_id for chunk_id, _ in fused]
    rrf_map = {chunk_id: score for chunk_id, score in fused}

    # 4. Fetch full chunk data for the top IDs
    if not top_chunk_ids:
        return []

    chunks = (
        db.query(DocumentChunk)
        .filter(DocumentChunk.id.in_(top_chunk_ids))
        .all()
    )

    # Sort by RRF score (DB query doesn't preserve order)
    chunk_map = {str(c.id): c for c in chunks}
    results = []
    for chunk_id in top_chunk_ids:
        if chunk_id not in chunk_map:
            continue
        c = chunk_map[chunk_id]
        results.append(RetrievedChunk(
            chunk_id=str(c.id),
            document_id=str(c.document_id),
            content=c.content,
            section=c.section,
            page_numbers=c.metadata_.get("page_numbers", []),
            rrf_score=rrf_map[chunk_id],
        ))

    return results
