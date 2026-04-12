"""
services/comparison_service.py

Compares two contracts side-by-side:
  1. Align clauses by type across both documents
  2. For each shared clause type, produce a structured diff
  3. LLM generates a plain-English narrative for each diff
  4. Produce an overall recommendation (which contract is better and why)

The clause alignment is the key design decision: we compare by clause TYPE
(e.g. both documents' termination clauses) rather than by position/section
number, because clause ordering varies wildly across contracts.
"""

import json
from typing import List, Optional, Dict
from uuid import UUID
from dataclasses import dataclass, field

from openai import OpenAI
from sqlalchemy.orm import Session

from config import settings
from db.database import (
    Document, ExtractedClause, DocumentRiskScore,
    ComparisonReport, ClauseType
)


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ClauseDiff:
    clause_type: str
    label: str                        # human-readable clause name
    doc_a_score: Optional[int]        # None if clause absent
    doc_b_score: Optional[int]
    doc_a_summary: Optional[str]
    doc_b_summary: Optional[str]
    doc_a_risks: List[str] = field(default_factory=list)
    doc_b_risks: List[str] = field(default_factory=list)
    winner: Optional[str] = None      # "a", "b", "tie", or "missing_both"
    narrative: Optional[str] = None   # LLM-generated comparison text


CLAUSE_LABELS = {
    "indemnification":   "Indemnification",
    "termination":       "Termination",
    "liability_cap":     "Liability cap",
    "confidentiality":   "Confidentiality / NDA",
    "governing_law":     "Governing law",
    "dispute_resolution":"Dispute resolution",
    "payment":           "Payment terms",
    "ip_ownership":      "IP ownership",
    "non_compete":       "Non-compete",
    "force_majeure":     "Force majeure",
    "auto_renewal":      "Auto-renewal",
    "penalty":           "Penalty / damages",
}


# ── LLM helpers ───────────────────────────────────────────────────────────────

def _call_llm(system: str, user: str, max_tokens: int = 600) -> str:
    if settings.LLM_PROVIDER == "anthropic":
        import anthropic
        c = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        r = c.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return r.content[0].text.strip()

    c = OpenAI(api_key=settings.OPENAI_API_KEY)
    r = c.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user}],
        max_tokens=max_tokens,
        temperature=0.1,
    )
    return r.choices[0].message.content.strip()


# ── Per-clause diff narrative ─────────────────────────────────────────────────

DIFF_SYSTEM = """You are a legal contract analyst comparing two contracts.
Given the same clause type from two different contracts, write a concise comparison 
(2-3 sentences max) explaining:
- The key difference between the two versions
- Which version is more favourable to the signing party and why
Be direct and use plain English. No legalese."""


def _generate_clause_narrative(
    clause_type: str,
    a_summary: Optional[str],
    b_summary: Optional[str],
    a_score: Optional[int],
    b_score: Optional[int],
) -> str:
    if not a_summary and not b_summary:
        return "This clause is absent from both contracts."
    if not a_summary:
        return f"Contract A has no {clause_type} clause. Contract B's version scores {b_score}/100 risk."
    if not b_summary:
        return f"Contract B has no {clause_type} clause. Contract A's version scores {a_score}/100 risk."

    prompt = (
        f"CLAUSE TYPE: {clause_type}\n\n"
        f"CONTRACT A (risk score {a_score}/100):\n{a_summary}\n\n"
        f"CONTRACT B (risk score {b_score}/100):\n{b_summary}"
    )
    try:
        return _call_llm(DIFF_SYSTEM, prompt, max_tokens=200)
    except Exception:
        # Fallback to deterministic comparison
        if a_score is not None and b_score is not None:
            winner = "A" if a_score < b_score else "B" if b_score < a_score else "neither"
            return f"Contract {winner} has lower risk on this clause ({min(a_score, b_score)} vs {max(a_score, b_score)}/100)."
        return "Unable to compare — insufficient data."


# ── Overall recommendation ────────────────────────────────────────────────────

RECOMMEND_SYSTEM = """You are a legal risk analyst. Given a side-by-side comparison of 
two contracts, write a clear recommendation (3-4 sentences) stating:
1. Which contract is overall more favourable to the signing party
2. The top 2 reasons why
3. One major caution or negotiation point in the recommended contract

Be direct. Start with "Contract A is..." or "Contract B is...". Plain English only."""


def _generate_recommendation(
    doc_a_name: str,
    doc_b_name: str,
    a_score: int,
    b_score: int,
    diffs: List[ClauseDiff],
) -> str:
    a_wins = sum(1 for d in diffs if d.winner == "a")
    b_wins = sum(1 for d in diffs if d.winner == "b")
    high_risk_clauses_a = [d.label for d in diffs if d.doc_a_score and d.doc_a_score >= 60]
    high_risk_clauses_b = [d.label for d in diffs if d.doc_b_score and d.doc_b_score >= 60]

    prompt = (
        f"Contract A: '{doc_a_name}' — overall risk {a_score}/100, wins {a_wins} clause comparisons\n"
        f"High-risk clauses in A: {', '.join(high_risk_clauses_a) or 'none'}\n\n"
        f"Contract B: '{doc_b_name}' — overall risk {b_score}/100, wins {b_wins} clause comparisons\n"
        f"High-risk clauses in B: {', '.join(high_risk_clauses_b) or 'none'}"
    )
    try:
        return _call_llm(RECOMMEND_SYSTEM, prompt, max_tokens=250)
    except Exception:
        winner = "A" if a_score < b_score else "B"
        return (
            f"Contract {winner} appears more favourable with a lower overall risk score "
            f"({min(a_score, b_score)} vs {max(a_score, b_score)}/100). "
            "Review all high-risk clauses carefully before signing either contract."
        )


# ── Clause alignment ──────────────────────────────────────────────────────────

def _align_clauses(
    clauses_a: List[ExtractedClause],
    clauses_b: List[ExtractedClause],
) -> List[ClauseDiff]:
    """
    Build a ClauseDiff for every clause type that appears in either document.
    Types absent from one doc get None scores.
    """
    map_a: Dict[str, ExtractedClause] = {c.clause_type.value: c for c in clauses_a}
    map_b: Dict[str, ExtractedClause] = {c.clause_type.value: c for c in clauses_b}
    all_types = sorted(set(list(map_a.keys()) + list(map_b.keys())))

    diffs = []
    for ct in all_types:
        ca = map_a.get(ct)
        cb = map_b.get(ct)

        a_score = ca.risk_score if ca else None
        b_score = cb.risk_score if cb else None

        # Determine winner (lower risk = better for signing party)
        if a_score is None and b_score is None:
            winner = "missing_both"
        elif a_score is None:
            winner = "b"    # B has a clause, A doesn't — B is more complete
        elif b_score is None:
            winner = "a"
        elif a_score < b_score:
            winner = "a"
        elif b_score < a_score:
            winner = "b"
        else:
            winner = "tie"

        narrative = _generate_clause_narrative(
            CLAUSE_LABELS.get(ct, ct),
            ca.summary if ca else None,
            cb.summary if cb else None,
            a_score, b_score,
        )

        diffs.append(ClauseDiff(
            clause_type=ct,
            label=CLAUSE_LABELS.get(ct, ct),
            doc_a_score=a_score,
            doc_b_score=b_score,
            doc_a_summary=ca.summary if ca else None,
            doc_b_summary=cb.summary if cb else None,
            doc_a_risks=ca.risk_reasons if ca else [],
            doc_b_risks=cb.risk_reasons if cb else [],
            winner=winner,
            narrative=narrative,
        ))

    return diffs


# ── Main entry point ──────────────────────────────────────────────────────────

def compare_documents(
    doc_a_id: UUID,
    doc_b_id: UUID,
    db: Session,
    user_id: Optional[UUID] = None,
) -> ComparisonReport:
    """
    Full comparison pipeline:
      1. Load both documents' clauses + risk scores
      2. Align clauses by type
      3. Generate per-clause narratives
      4. Generate overall recommendation
      5. Persist and return ComparisonReport
    """
    # Load documents
    doc_a = db.query(Document).filter(Document.id == doc_a_id).first()
    doc_b = db.query(Document).filter(Document.id == doc_b_id).first()
    if not doc_a or not doc_b:
        raise ValueError("One or both documents not found")

    clauses_a = db.query(ExtractedClause).filter(ExtractedClause.document_id == doc_a_id).all()
    clauses_b = db.query(ExtractedClause).filter(ExtractedClause.document_id == doc_b_id).all()
    risk_a = db.query(DocumentRiskScore).filter(DocumentRiskScore.document_id == doc_a_id).first()
    risk_b = db.query(DocumentRiskScore).filter(DocumentRiskScore.document_id == doc_b_id).first()

    score_a = risk_a.overall_score if risk_a else 50
    score_b = risk_b.overall_score if risk_b else 50

    print(f"[Compare] Aligning clauses for {doc_a.filename} vs {doc_b.filename}")
    diffs = _align_clauses(clauses_a, clauses_b)

    print(f"[Compare] Generating recommendation")
    recommendation = _generate_recommendation(
        doc_a.filename, doc_b.filename, score_a, score_b, diffs
    )

    # Serialise diffs to JSON for storage
    clause_diffs_json = [
        {
            "clause_type":   d.clause_type,
            "label":         d.label,
            "doc_a_score":   d.doc_a_score,
            "doc_b_score":   d.doc_b_score,
            "doc_a_summary": d.doc_a_summary,
            "doc_b_summary": d.doc_b_summary,
            "doc_a_risks":   d.doc_a_risks,
            "doc_b_risks":   d.doc_b_risks,
            "winner":        d.winner,
            "narrative":     d.narrative,
        }
        for d in diffs
    ]

    diff_summary = (
        f"Compared {len(diffs)} clause types across {doc_a.filename} and {doc_b.filename}. "
        f"Contract A overall risk: {score_a}/100. Contract B overall risk: {score_b}/100."
    )

    report = ComparisonReport(
        user_id=user_id,
        doc_a_id=doc_a_id,
        doc_b_id=doc_b_id,
        diff_summary=diff_summary,
        clause_diffs=clause_diffs_json,
        recommendation=recommendation,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    print(f"[Compare] ✓ Report {report.id} saved")
    return report
