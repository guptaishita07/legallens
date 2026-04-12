"""
routers/comparison.py

Endpoints:
  POST /compare/               — run comparison between two documents
  GET  /compare/               — list all comparison reports for current user
  GET  /compare/{report_id}    — get full comparison report
"""

from uuid import UUID
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db.database import (
    get_db, Document, DocumentStatus,
    ExtractedClause, DocumentRiskScore, ComparisonReport
)
from services.comparison_service import compare_documents
from services.auth_service import get_optional_user
from db.database import User

router = APIRouter(prefix="/compare", tags=["comparison"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class CompareRequest(BaseModel):
    doc_a_id: str
    doc_b_id: str


class ClauseDiffOut(BaseModel):
    clause_type: str
    label: str
    doc_a_score: Optional[int]
    doc_b_score: Optional[int]
    doc_a_summary: Optional[str]
    doc_b_summary: Optional[str]
    doc_a_risks: List[str]
    doc_b_risks: List[str]
    winner: Optional[str]
    narrative: Optional[str]


class ComparisonOut(BaseModel):
    id: str
    doc_a_id: str
    doc_a_name: str
    doc_b_id: str
    doc_b_name: str
    doc_a_score: Optional[int]
    doc_b_score: Optional[int]
    diff_summary: Optional[str]
    recommendation: Optional[str]
    clause_diffs: List[ClauseDiffOut]
    created_at: str


class ComparisonListItem(BaseModel):
    id: str
    doc_a_name: str
    doc_b_name: str
    doc_a_score: Optional[int]
    doc_b_score: Optional[int]
    created_at: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/", response_model=ComparisonOut)
def run_comparison(
    body: CompareRequest,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """
    Compare two documents. Both must be in 'ready' status with extracted clauses.
    Returns a full ComparisonReport immediately (LLM calls are synchronous here;
    move to Celery in production for long-running comparisons).
    """
    doc_a_id = UUID(body.doc_a_id)
    doc_b_id = UUID(body.doc_b_id)

    if doc_a_id == doc_b_id:
        raise HTTPException(status_code=400, detail="Cannot compare a document with itself.")

    for doc_id in [doc_a_id, doc_b_id]:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if not doc:
            raise HTTPException(status_code=404, detail=f"Document {doc_id} not found.")
        if doc.status != DocumentStatus.READY:
            raise HTTPException(
                status_code=400,
                detail=f"Document '{doc.filename}' is not ready (status: {doc.status.value})."
            )
        clauses = db.query(ExtractedClause).filter(ExtractedClause.document_id == doc_id).count()
        if clauses == 0:
            raise HTTPException(
                status_code=400,
                detail=f"Document '{doc.filename}' has no extracted clauses. Run analysis first."
            )

    user_id = current_user.id if current_user else None
    report = compare_documents(doc_a_id, doc_b_id, db, user_id)
    return _report_out(report, db)


@router.get("/", response_model=List[ComparisonListItem])
def list_comparisons(
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_optional_user),
):
    """List all comparison reports, newest first."""
    q = db.query(ComparisonReport)
    if current_user:
        q = q.filter(ComparisonReport.user_id == current_user.id)
    reports = q.order_by(ComparisonReport.created_at.desc()).limit(20).all()

    result = []
    for r in reports:
        doc_a = db.query(Document).filter(Document.id == r.doc_a_id).first()
        doc_b = db.query(Document).filter(Document.id == r.doc_b_id).first()
        risk_a = db.query(DocumentRiskScore).filter(DocumentRiskScore.document_id == r.doc_a_id).first()
        risk_b = db.query(DocumentRiskScore).filter(DocumentRiskScore.document_id == r.doc_b_id).first()
        result.append(ComparisonListItem(
            id=str(r.id),
            doc_a_name=doc_a.filename if doc_a else "Unknown",
            doc_b_name=doc_b.filename if doc_b else "Unknown",
            doc_a_score=risk_a.overall_score if risk_a else None,
            doc_b_score=risk_b.overall_score if risk_b else None,
            created_at=r.created_at.isoformat(),
        ))
    return result


@router.get("/{report_id}", response_model=ComparisonOut)
def get_comparison(report_id: UUID, db: Session = Depends(get_db)):
    report = db.query(ComparisonReport).filter(ComparisonReport.id == report_id).first()
    if not report:
        raise HTTPException(status_code=404, detail="Comparison report not found.")
    return _report_out(report, db)


# ── Helper ────────────────────────────────────────────────────────────────────

def _report_out(report: ComparisonReport, db: Session) -> ComparisonOut:
    doc_a = db.query(Document).filter(Document.id == report.doc_a_id).first()
    doc_b = db.query(Document).filter(Document.id == report.doc_b_id).first()
    risk_a = db.query(DocumentRiskScore).filter(DocumentRiskScore.document_id == report.doc_a_id).first()
    risk_b = db.query(DocumentRiskScore).filter(DocumentRiskScore.document_id == report.doc_b_id).first()

    diffs = [ClauseDiffOut(**d) for d in (report.clause_diffs or [])]

    return ComparisonOut(
        id=str(report.id),
        doc_a_id=str(report.doc_a_id),
        doc_a_name=doc_a.filename if doc_a else "Unknown",
        doc_b_id=str(report.doc_b_id),
        doc_b_name=doc_b.filename if doc_b else "Unknown",
        doc_a_score=risk_a.overall_score if risk_a else None,
        doc_b_score=risk_b.overall_score if risk_b else None,
        diff_summary=report.diff_summary,
        recommendation=report.recommendation,
        clause_diffs=diffs,
        created_at=report.created_at.isoformat(),
    )
