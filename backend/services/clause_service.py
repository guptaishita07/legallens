"""
services/clause_service.py

Extracts structured clause information from a document's chunks.

Approach:
  1. First pass — scan ALL chunks and classify which clause types are present
  2. Second pass — for each detected clause type, extract full content + generate
     a plain-English summary using a structured LLM prompt
  3. Return typed ExtractedClause objects ready to be risk-scored

This two-pass design avoids missing clauses that span multiple chunks and
reduces hallucination by giving the model one focused task at a time.
"""

import json
from typing import List, Optional
from uuid import UUID

from openai import OpenAI
from sqlalchemy.orm import Session

from config import settings
from db.database import DocumentChunk, ExtractedClause, ClauseType, RiskLevel


# ── Clause definitions — what we look for ─────────────────────────────────────

CLAUSE_DEFINITIONS = {
    ClauseType.INDEMNIFICATION: {
        "name": "Indemnification",
        "description": "One party agrees to compensate the other for losses, damages, or legal costs",
        "keywords": ["indemnif", "hold harmless", "defend", "losses", "damages"],
    },
    ClauseType.TERMINATION: {
        "name": "Termination",
        "description": "Conditions under which the contract can be ended by either party",
        "keywords": ["terminat", "cancel", "end of term", "notice period", "breach"],
    },
    ClauseType.LIABILITY_CAP: {
        "name": "Liability cap",
        "description": "Maximum financial liability either party can face",
        "keywords": ["liability", "cap", "maximum", "limit", "exceed", "aggregate"],
    },
    ClauseType.CONFIDENTIALITY: {
        "name": "Confidentiality / NDA",
        "description": "Restrictions on sharing or using confidential information",
        "keywords": ["confidential", "proprietary", "non-disclosure", "nda", "trade secret"],
    },
    ClauseType.GOVERNING_LAW: {
        "name": "Governing law",
        "description": "Which jurisdiction's laws apply to the contract",
        "keywords": ["governing law", "jurisdiction", "courts of", "laws of"],
    },
    ClauseType.DISPUTE_RESOLUTION: {
        "name": "Dispute resolution",
        "description": "How disputes between parties will be resolved (arbitration, litigation, etc.)",
        "keywords": ["arbitration", "mediation", "dispute", "resolution", "adr"],
    },
    ClauseType.PAYMENT: {
        "name": "Payment terms",
        "description": "Payment amounts, schedules, late fees, and invoicing terms",
        "keywords": ["payment", "invoice", "due", "fee", "pricing", "overdue", "interest"],
    },
    ClauseType.IP_OWNERSHIP: {
        "name": "IP ownership",
        "description": "Who owns intellectual property created under the contract",
        "keywords": ["intellectual property", "ip", "copyright", "ownership", "work for hire", "assignment"],
    },
    ClauseType.NON_COMPETE: {
        "name": "Non-compete",
        "description": "Restrictions on working with competitors after the contract ends",
        "keywords": ["non-compete", "non compete", "competing", "competitor", "solicitation"],
    },
    ClauseType.FORCE_MAJEURE: {
        "name": "Force majeure",
        "description": "Exclusions for unforeseeable events beyond a party's control",
        "keywords": ["force majeure", "act of god", "unforeseeable", "beyond control"],
    },
    ClauseType.AUTO_RENEWAL: {
        "name": "Auto-renewal",
        "description": "Contract automatically renews unless notice is given",
        "keywords": ["auto-renew", "automatic renewal", "evergreen", "rollover", "unless notice"],
    },
    ClauseType.PENALTY: {
        "name": "Penalty / liquidated damages",
        "description": "Pre-agreed financial penalties for specific breaches",
        "keywords": ["penalty", "liquidated damages", "breach fee", "forfeit"],
    },
}


# ── LLM helpers ───────────────────────────────────────────────────────────────

def _call_llm(system: str, user: str, max_tokens: int = 1200) -> str:
    if settings.LLM_PROVIDER == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
        r = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return r.content[0].text.strip()
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    r = client.chat.completions.create(
        model=settings.LLM_MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
        max_tokens=max_tokens,
        temperature=0.0,
    )
    return r.choices[0].message.content.strip()


# ── Pass 1: Detect which clause types are present ─────────────────────────────

DETECT_SYSTEM = """You are a legal document analyst. Given contract text, identify which 
clause types are present. Respond with a JSON array of clause type keys only.
Available types: indemnification, termination, liability_cap, confidentiality, 
governing_law, dispute_resolution, payment, ip_ownership, non_compete, 
force_majeure, auto_renewal, penalty.
Only include types that are clearly present. Respond with JSON array only."""


def detect_clause_types(chunks: List[DocumentChunk]) -> List[ClauseType]:
    """
    Quick scan of all chunks to identify which clause types exist in the doc.
    Uses a compact prompt to avoid burning too many tokens on Pass 1.
    """
    # Combine chunk content with section labels for detection
    # Use every chunk but truncate each to save tokens
    context_parts = []
    for c in chunks:
        label = f"[{c.section}]" if c.section else ""
        context_parts.append(f"{label} {c.content[:400]}")
    context = "\n\n".join(context_parts)[:8000]  # cap at 8k chars

    try:
        raw = _call_llm(DETECT_SYSTEM, f"CONTRACT TEXT:\n{context}")
        raw = raw.strip().removeprefix("```json").removesuffix("```").strip()
        detected_keys = json.loads(raw)

        result = []
        for key in detected_keys:
            try:
                result.append(ClauseType(key))
            except ValueError:
                pass
        return result
    except Exception as e:
        print(f"  [Clause] Detection failed: {e} — falling back to keyword scan")
        return _keyword_detect(chunks)


def _keyword_detect(chunks: List[DocumentChunk]) -> List[ClauseType]:
    """Keyword-based fallback when LLM detection fails."""
    full_text = " ".join(c.content.lower() for c in chunks)
    found = []
    for clause_type, defn in CLAUSE_DEFINITIONS.items():
        if any(kw in full_text for kw in defn["keywords"]):
            found.append(clause_type)
    return found


# ── Pass 2: Extract + summarise each clause ───────────────────────────────────

EXTRACT_SYSTEM = """You are a legal document analyst. Extract and analyse a specific 
clause type from the provided contract excerpts.

Respond with a single JSON object — no markdown, no preamble:
{
  "title": "clause title with section reference if available",
  "content": "verbatim text of the most relevant clause passage (max 600 chars)",
  "summary": "plain English explanation of what this clause means for a non-lawyer (2-3 sentences)",
  "risk_score": 0-100,
  "risk_reasons": ["reason 1", "reason 2"]
}

Risk scoring guide:
  0-30: Balanced, standard clause — protects both parties fairly
  31-59: Somewhat one-sided or has terms that need attention
  60-79: Significantly one-sided or missing important protections  
  80-100: Extreme terms — unlimited liability, no cap, unilateral termination, etc.

Only output the JSON object. No other text."""


def extract_clause(
    clause_type: ClauseType,
    relevant_chunks: List[DocumentChunk],
) -> Optional[dict]:
    """
    Extract and analyse a single clause type from the most relevant chunks.
    Returns raw dict (will be converted to DB model by caller).
    """
    if not relevant_chunks:
        return None

    defn = CLAUSE_DEFINITIONS[clause_type]
    context = "\n\n---\n\n".join(
        f"[{c.section or 'Excerpt'}]\n{c.content}" for c in relevant_chunks[:4]
    )

    prompt = (
        f"CLAUSE TYPE TO EXTRACT: {defn['name']}\n"
        f"Definition: {defn['description']}\n\n"
        f"CONTRACT EXCERPTS:\n{context}"
    )

    try:
        raw = _call_llm(EXTRACT_SYSTEM, prompt, max_tokens=800)
        raw = raw.strip().removeprefix("```json").removesuffix("```").strip()
        return json.loads(raw)
    except Exception as e:
        print(f"  [Clause] Extraction failed for {clause_type}: {e}")
        return None


# ── Find relevant chunks for each clause type ─────────────────────────────────

def _find_relevant_chunks(
    clause_type: ClauseType,
    chunks: List[DocumentChunk],
    top_n: int = 4,
) -> List[DocumentChunk]:
    """
    Simple keyword filtering to find chunks most likely to contain a clause.
    In Phase 3, this will use vector similarity instead.
    """
    defn = CLAUSE_DEFINITIONS[clause_type]
    keywords = defn["keywords"]

    scored = []
    for chunk in chunks:
        text = chunk.content.lower()
        section = (chunk.section or "").lower()
        score = sum(1 for kw in keywords if kw in text or kw in section)
        if score > 0:
            scored.append((chunk, score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [c for c, _ in scored[:top_n]]


# ── Risk level mapping ────────────────────────────────────────────────────────

def score_to_level(score: int) -> RiskLevel:
    if score >= 80:
        return RiskLevel.CRITICAL
    if score >= 60:
        return RiskLevel.HIGH
    if score >= 30:
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


# ── Main entry point ──────────────────────────────────────────────────────────

def extract_all_clauses(
    document_id: UUID,
    chunks: List[DocumentChunk],
    db: Session,
) -> List[ExtractedClause]:
    """
    Full two-pass extraction pipeline.
    Saves results to the database and returns the list of extracted clauses.
    """
    print(f"  [Clause] Starting extraction for document {document_id}")

    # Pass 1: detect which clause types are present
    detected_types = detect_clause_types(chunks)
    print(f"  [Clause] Detected types: {[t.value for t in detected_types]}")

    db_clauses = []

    # Pass 2: extract each detected clause
    for clause_type in detected_types:
        relevant = _find_relevant_chunks(clause_type, chunks)
        if not relevant:
            continue

        result = extract_clause(clause_type, relevant)
        if not result:
            continue

        risk_score = max(0, min(100, int(result.get("risk_score", 0))))
        chunk_id = relevant[0].id if relevant else None

        db_clause = ExtractedClause(
            document_id=document_id,
            chunk_id=chunk_id,
            clause_type=clause_type,
            title=result.get("title", CLAUSE_DEFINITIONS[clause_type]["name"]),
            content=result.get("content", ""),
            summary=result.get("summary", ""),
            risk_level=score_to_level(risk_score),
            risk_score=risk_score,
            risk_reasons=result.get("risk_reasons", []),
            page_numbers=relevant[0].metadata_.get("page_numbers", []) if relevant else [],
        )
        db_clauses.append(db_clause)
        print(f"    ✓ {clause_type.value} — score {risk_score}")

    db.bulk_save_objects(db_clauses)
    db.commit()
    print(f"  [Clause] Saved {len(db_clauses)} clauses")
    return db_clauses
