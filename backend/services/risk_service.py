"""
services/risk_service.py

Computes an aggregate risk score for an entire document from its extracted clauses.

The 7-signal model (inspired by the project brief but adapted for contract risk):

  Signal                  Weight   Trigger
  ─────────────────────────────────────────────────────────────
  Uncapped liability       25%     No liability cap found
  Unilateral termination   20%     Party can terminate without cause
  Missing indemnification  15%     No indemnification clause at all
  Auto-renewal trap        15%     Auto-renewal with short notice window
  One-sided IP assignment  10%     All IP assigned with no carve-outs
  Punitive penalties       10%     Liquidated damages > 2× contract value
  Unlimited confidentiality 5%    NDA with no time limit or very long duration

These signals are evaluated against the extracted clauses and combined with the
per-clause risk scores to produce a final 0-100 score.
"""

import json
from typing import List
from uuid import UUID

from openai import OpenAI
from sqlalchemy.orm import Session

from config import settings
from db.database import ExtractedClause, DocumentRiskScore, ClauseType, RiskLevel


# ── Signal evaluation ─────────────────────────────────────────────────────────

def _check_signals(clauses: List[ExtractedClause]) -> dict:
    """
    Evaluate each of the 7 signals against the extracted clauses.
    Returns a dict of {signal_name: score_contribution (0-25)}.
    """
    clause_map = {c.clause_type: c for c in clauses}
    signals = {}

    # Signal 1 — Uncapped liability (25 pts)
    if ClauseType.LIABILITY_CAP not in clause_map:
        signals["uncapped_liability"] = 25
    else:
        cap_clause = clause_map[ClauseType.LIABILITY_CAP]
        # If LLM scored it high risk, partial penalty
        signals["uncapped_liability"] = int(cap_clause.risk_score * 0.25)

    # Signal 2 — Unilateral termination (20 pts)
    if ClauseType.TERMINATION in clause_map:
        term = clause_map[ClauseType.TERMINATION]
        # High risk termination = likely unilateral
        signals["unilateral_termination"] = int(term.risk_score * 0.20)
    else:
        signals["unilateral_termination"] = 0  # no termination clause is neutral

    # Signal 3 — Missing indemnification (15 pts)
    if ClauseType.INDEMNIFICATION not in clause_map:
        signals["missing_indemnification"] = 15
    else:
        indem = clause_map[ClauseType.INDEMNIFICATION]
        signals["missing_indemnification"] = int(indem.risk_score * 0.15)

    # Signal 4 — Auto-renewal trap (15 pts)
    if ClauseType.AUTO_RENEWAL in clause_map:
        ar = clause_map[ClauseType.AUTO_RENEWAL]
        signals["auto_renewal_trap"] = max(10, int(ar.risk_score * 0.15))
    else:
        signals["auto_renewal_trap"] = 0

    # Signal 5 — One-sided IP assignment (10 pts)
    if ClauseType.IP_OWNERSHIP in clause_map:
        ip = clause_map[ClauseType.IP_OWNERSHIP]
        signals["onesided_ip"] = int(ip.risk_score * 0.10)
    else:
        signals["onesided_ip"] = 0

    # Signal 6 — Punitive penalties (10 pts)
    if ClauseType.PENALTY in clause_map:
        pen = clause_map[ClauseType.PENALTY]
        signals["punitive_penalties"] = max(5, int(pen.risk_score * 0.10))
    else:
        signals["punitive_penalties"] = 0

    # Signal 7 — Unlimited confidentiality (5 pts)
    if ClauseType.CONFIDENTIALITY in clause_map:
        conf = clause_map[ClauseType.CONFIDENTIALITY]
        signals["unlimited_confidentiality"] = int(conf.risk_score * 0.05)
    else:
        signals["unlimited_confidentiality"] = 0

    return signals


def _score_to_level(score: int) -> RiskLevel:
    if score >= 80: return RiskLevel.CRITICAL
    if score >= 60: return RiskLevel.HIGH
    if score >= 30: return RiskLevel.MEDIUM
    return RiskLevel.LOW


# ── Executive summary generation ──────────────────────────────────────────────

SUMMARY_SYSTEM = """You are a legal risk analyst. Given a contract's extracted clauses 
and overall risk score, write a concise executive summary (3-4 sentences) that:
1. States the overall risk level and score
2. Names the top 2-3 most concerning clauses with specific reasons
3. Gives one actionable recommendation

Write in plain English for a business executive, not a lawyer. Be direct."""


def _generate_summary(clauses: List[ExtractedClause], overall_score: int) -> str:
    try:
        clause_lines = []
        for c in sorted(clauses, key=lambda x: x.risk_score, reverse=True)[:5]:
            clause_lines.append(
                f"- {c.title}: score {c.risk_score}/100 — {'; '.join(c.risk_reasons[:2])}"
            )

        prompt = (
            f"Overall risk score: {overall_score}/100\n\n"
            f"Top clauses by risk:\n" + "\n".join(clause_lines)
        )

        if settings.LLM_PROVIDER == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            r = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=300,
                system=SUMMARY_SYSTEM,
                messages=[{"role": "user", "content": prompt}],
            )
            return r.content[0].text.strip()
        else:
            client = OpenAI(api_key=settings.OPENAI_API_KEY)
            r = client.chat.completions.create(
                model=settings.LLM_MODEL,
                messages=[
                    {"role": "system", "content": SUMMARY_SYSTEM},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=300,
                temperature=0.2,
            )
            return r.choices[0].message.content.strip()
    except Exception as e:
        print(f"  [Risk] Summary generation failed: {e}")
        level = _score_to_level(overall_score)
        return (
            f"This contract has an overall risk score of {overall_score}/100 ({level.value} risk). "
            f"Review the flagged clauses carefully before signing."
        )


# ── Main entry point ──────────────────────────────────────────────────────────

def compute_document_risk(
    document_id: UUID,
    clauses: List[ExtractedClause],
    db: Session,
) -> DocumentRiskScore:
    """
    Compute aggregate risk score for a document from its extracted clauses.
    Saves and returns a DocumentRiskScore record.
    """
    print(f"  [Risk] Computing aggregate score for {document_id}")

    # Evaluate 7-signal model
    signals = _check_signals(clauses)
    signal_total = sum(signals.values())

    # Also factor in the raw clause scores (weighted average)
    if clauses:
        clause_avg = sum(c.risk_score for c in clauses) / len(clauses)
    else:
        clause_avg = 0

    # Combine: 60% signal model + 40% clause average
    overall_score = min(100, int(signal_total * 0.6 + clause_avg * 0.4))
    overall_level = _score_to_level(overall_score)
    high_risk_count = sum(1 for c in clauses if c.risk_score >= 60)

    # Build per-clause-type breakdown for the UI
    breakdown = {c.clause_type.value: c.risk_score for c in clauses}
    breakdown["_signals"] = signals

    # Generate executive summary
    summary = _generate_summary(clauses, overall_score)

    # Upsert — replace any existing score for this document
    existing = (
        db.query(DocumentRiskScore)
        .filter(DocumentRiskScore.document_id == document_id)
        .first()
    )
    if existing:
        db.delete(existing)
        db.commit()

    risk_record = DocumentRiskScore(
        document_id=document_id,
        overall_score=overall_score,
        overall_level=overall_level,
        clause_count=len(clauses),
        high_risk_count=high_risk_count,
        score_breakdown=breakdown,
        summary=summary,
    )
    db.add(risk_record)
    db.commit()
    db.refresh(risk_record)

    print(f"  [Risk] Score: {overall_score}/100 ({overall_level.value}) — {high_risk_count} high-risk clauses")
    return risk_record
