"""
routers/reports.py

Endpoints:
  GET /reports/{document_id}/pdf   — generate + download PDF risk report
"""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from db.database import (
    get_db, Document, DocumentStatus,
    ExtractedClause, DocumentRiskScore, QASession
)
from services.report_generator import generate_risk_report

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/{document_id}/pdf")
def download_pdf_report(
    document_id: UUID,
    db: Session = Depends(get_db),
):
    """
    Generates a PDF risk report on the fly and streams it to the browser.
    No file is saved to disk — generated in memory via ReportLab.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if doc.status != DocumentStatus.READY:
        raise HTTPException(status_code=400, detail="Document not ready.")

    risk = db.query(DocumentRiskScore).filter(
        DocumentRiskScore.document_id == document_id
    ).first()
    if not risk:
        raise HTTPException(
            status_code=404,
            detail="Risk score not found. Run analysis first."
        )

    clauses = (
        db.query(ExtractedClause)
        .filter(ExtractedClause.document_id == document_id)
        .order_by(ExtractedClause.risk_score.desc())
        .all()
    )

    qa_sessions = (
        db.query(QASession)
        .filter(QASession.document_id == document_id)
        .order_by(QASession.created_at.desc())
        .limit(10)
        .all()
    )

    pdf_bytes = generate_risk_report(
        filename=doc.filename,
        risk=risk,
        clauses=clauses,
        qa_sessions=qa_sessions if qa_sessions else None,
    )

    safe_name = doc.filename.replace(" ", "_").replace(".pdf", "")
    disposition = f'attachment; filename="LegalLens_{safe_name}_report.pdf"'

    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": disposition},
    )
