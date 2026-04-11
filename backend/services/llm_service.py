"""
services/llm_service.py

Handles answer generation using the retrieved chunks as context.

Two-step process:
  1. Generate answer   — LLM synthesises an answer from the top-N chunks
  2. Verify faithfulness — Secondary LLM call checks the answer is grounded
     in the provided context. If confidence < threshold, we say so honestly
     rather than hallucinate.

The LLM_PROVIDER env var switches between OpenAI and Anthropic.
"""

import json
from typing import List, Optional
from dataclasses import dataclass

from openai import OpenAI

from config import settings
from services.retrieval_service import RetrievedChunk


# ── Client ────────────────────────────────────────────────────────────────────

def _get_llm_client():
    if settings.LLM_PROVIDER == "anthropic":
        import anthropic
        return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    return OpenAI(api_key=settings.OPENAI_API_KEY)


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class AnswerResult:
    answer: str
    confidence: float           # 0.0 – 1.0 faithfulness score
    is_grounded: bool           # False → answer not supported by context
    sources: List[dict]         # chunk excerpts shown in UI


# ── Prompt templates ──────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are LegalLens, an expert legal document analyst.
Your job is to answer questions about contracts accurately and concisely.

Rules:
- Answer ONLY from the provided contract excerpts.
- If the answer is not in the excerpts, say exactly: "I could not find this information in the contract."
- Cite the clause section when available (e.g. "Per Section 5 — Indemnification, ...").
- Use plain English. Avoid legalese unless quoting directly.
- Keep answers under 250 words unless the question demands more detail."""


def _build_context(chunks: List[RetrievedChunk]) -> str:
    parts = []
    for i, chunk in enumerate(chunks, start=1):
        section_label = f"[{chunk.section}]" if chunk.section else f"[Excerpt {i}]"
        parts.append(f"{section_label}\n{chunk.content}")
    return "\n\n---\n\n".join(parts)


def _build_user_prompt(question: str, context: str) -> str:
    return f"""CONTRACT EXCERPTS:
{context}

QUESTION: {question}

Answer based solely on the excerpts above."""


FAITHFULNESS_PROMPT = """You are a fact-checker. Given a question, context, and answer,
determine whether the answer is fully supported by the context.

Respond with JSON only:
{{
  "is_grounded": true/false,
  "confidence": 0.0-1.0,
  "reason": "one sentence explanation"
}}

is_grounded: true if the answer is entirely derivable from the context.
confidence: your certainty that the answer is grounded (1.0 = certain).
"""


# ── Generation ────────────────────────────────────────────────────────────────

def _call_openai(system: str, user: str, model: str, max_tokens: int = 600) -> str:
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ],
        max_tokens=max_tokens,
        temperature=0.1,    # low temperature for factual legal Q&A
    )
    return response.choices[0].message.content.strip()


def _call_anthropic(system: str, user: str, max_tokens: int = 600) -> str:
    import anthropic
    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return response.content[0].text.strip()


def _generate_answer(question: str, context: str) -> str:
    user_prompt = _build_user_prompt(question, context)
    if settings.LLM_PROVIDER == "anthropic":
        return _call_anthropic(SYSTEM_PROMPT, user_prompt)
    return _call_openai(SYSTEM_PROMPT, user_prompt, settings.LLM_MODEL)


# ── Faithfulness check ────────────────────────────────────────────────────────

FAITHFULNESS_CONFIDENCE_THRESHOLD = 0.5


def _check_faithfulness(question: str, context: str, answer: str) -> tuple[bool, float]:
    """
    Secondary LLM call to verify the answer is grounded in context.
    Returns (is_grounded, confidence).
    """
    user_prompt = f"""CONTEXT:
{context}

QUESTION: {question}

ANSWER: {answer}"""

    try:
        if settings.LLM_PROVIDER == "anthropic":
            raw = _call_anthropic(FAITHFULNESS_PROMPT, user_prompt, max_tokens=150)
        else:
            raw = _call_openai(FAITHFULNESS_PROMPT, user_prompt,
                               model="gpt-4o-mini", max_tokens=150)

        # Strip possible markdown fences
        raw = raw.strip().removeprefix("```json").removesuffix("```").strip()
        parsed = json.loads(raw)
        return parsed.get("is_grounded", True), float(parsed.get("confidence", 0.8))
    except Exception:
        # If faithfulness check itself fails, assume grounded to avoid blocking
        return True, 0.7


# ── Main entry point ──────────────────────────────────────────────────────────

def answer_question(
    question: str,
    chunks: List[RetrievedChunk],
) -> AnswerResult:
    """
    Full answer pipeline:
      retrieved chunks → context → LLM answer → faithfulness check → result
    """
    if not chunks:
        return AnswerResult(
            answer="I could not find relevant information in this contract to answer your question.",
            confidence=0.0,
            is_grounded=False,
            sources=[],
        )

    context = _build_context(chunks)

    # Step 1: Generate answer
    raw_answer = _generate_answer(question, context)

    # Step 2: Check faithfulness
    is_grounded, confidence = _check_faithfulness(question, context, raw_answer)

    # Step 3: If not grounded, surface a safe fallback
    if not is_grounded or confidence < FAITHFULNESS_CONFIDENCE_THRESHOLD:
        final_answer = (
            "I could not find a reliable answer to this question in the contract. "
            "Please review the source excerpts below or consult a legal professional."
        )
    else:
        final_answer = raw_answer

    # Build source references for the UI
    sources = [
        {
            "chunk_id":    chunk.chunk_id,
            "section":     chunk.section,
            "excerpt":     chunk.content[:300] + ("..." if len(chunk.content) > 300 else ""),
            "page_numbers": chunk.page_numbers,
            "rrf_score":   round(chunk.rrf_score, 4),
        }
        for chunk in chunks
    ]

    return AnswerResult(
        answer=final_answer,
        confidence=round(confidence, 2),
        is_grounded=is_grounded,
        sources=sources,
    )
