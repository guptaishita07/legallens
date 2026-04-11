"""
services/pdf_service.py

Parses a PDF and splits it into semantically meaningful chunks.

KEY INSIGHT — why we don't chunk by token count:
Legal documents have explicit section headers (e.g. "5. Indemnification",
"CLAUSE 12 — TERMINATION"). Splitting at those boundaries keeps each chunk
self-contained, which dramatically improves retrieval precision.

Strategy (in order):
  1. Try header-based splitting — regex detects clause/section headings.
  2. Fallback to sentence-boundary splitting for unstructured pages.
  3. Enforce a max token cap; split large sections further if needed.
"""

import re
import fitz          # PyMuPDF
import pdfplumber
import tiktoken
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from config import settings


# ── Data structures ───────────────────────────────────────────────────────────

@dataclass
class ParsedChunk:
    chunk_index: int
    content: str
    section: Optional[str]       # heading that introduced this chunk (or None)
    token_count: int
    page_numbers: List[int]      # pages this chunk spans
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ParsedDocument:
    filename: str
    page_count: int
    char_count: int
    chunks: List[ParsedChunk]
    raw_text: str                # full document text (for BM25 index)
    metadata: Dict[str, Any] = field(default_factory=dict)


# ── Tokeniser (shared, cached) ────────────────────────────────────────────────

_tokeniser = tiktoken.get_encoding("cl100k_base")   # same encoding as OpenAI embeds


def count_tokens(text: str) -> int:
    return len(_tokeniser.encode(text))


def split_by_tokens(text: str, max_tokens: int, overlap: int) -> List[str]:
    """Split a string into token-limited segments with overlap."""
    tokens = _tokeniser.encode(text)
    chunks = []
    start = 0
    while start < len(tokens):
        end = min(start + max_tokens, len(tokens))
        chunk_text = _tokeniser.decode(tokens[start:end])
        chunks.append(chunk_text)
        if end == len(tokens):
            break
        start += max_tokens - overlap
    return chunks


# ── Heading detection ─────────────────────────────────────────────────────────

# Matches patterns like:
#   "5. Indemnification"       "CLAUSE 12 — TERMINATION"
#   "Article III: Liability"   "Section 2.4 Governing Law"
#   "DEFINITIONS"  (all-caps short line)
_HEADING_RE = re.compile(
    r"^(?:"
    r"(?:clause|section|article|part|schedule|exhibit|annex|appendix)\s*[\d\w.]*[\s:.\-—]+"
    r"|\d+(?:\.\d+)*\s*[.)]\s+"          # numbered like "5." or "5.1)"
    r"|[A-Z][A-Z\s]{4,40}$"              # ALL CAPS short line
    r")",
    re.IGNORECASE | re.MULTILINE,
)


def is_heading(line: str) -> bool:
    line = line.strip()
    if not line or len(line) > 120:
        return False
    return bool(_HEADING_RE.match(line))


# ── Text extraction ───────────────────────────────────────────────────────────

def extract_text_with_pages(pdf_path: str) -> List[Dict]:
    """
    Returns a list of {page: int, text: str} dicts using PyMuPDF.
    PyMuPDF preserves reading order better than pdfplumber for most contracts.
    pdfplumber is used as fallback for table-heavy pages.
    """
    doc = fitz.open(pdf_path)
    pages = []
    for page_num, page in enumerate(doc, start=1):
        text = page.get_text("text")   # "text" mode: ordered by reading flow
        if len(text.strip()) < 50:
            # Page is likely scanned or image-only — try pdfplumber
            text = _fallback_extract(pdf_path, page_num - 1)
        pages.append({"page": page_num, "text": text})
    doc.close()
    return pages


def _fallback_extract(pdf_path: str, page_index: int) -> str:
    """Use pdfplumber for a specific page (better for tables)."""
    try:
        with pdfplumber.open(pdf_path) as pdf:
            page = pdf.pages[page_index]
            return page.extract_text() or ""
    except Exception:
        return ""


# ── Section-boundary chunking ─────────────────────────────────────────────────

def _split_into_sections(pages: List[Dict]) -> List[Dict]:
    """
    Walk through all lines across pages, start a new section whenever a
    heading is detected. Returns list of {section, content, pages}.
    """
    sections = []
    current_heading: Optional[str] = None
    current_lines: List[str] = []
    current_pages: List[int] = []

    for page_data in pages:
        page_num = page_data["page"]
        for line in page_data["text"].split("\n"):
            stripped = line.strip()
            if not stripped:
                continue
            if is_heading(stripped):
                # Save whatever we accumulated
                if current_lines:
                    sections.append({
                        "section": current_heading,
                        "content": " ".join(current_lines).strip(),
                        "pages": list(set(current_pages)),
                    })
                current_heading = stripped
                current_lines = []
                current_pages = []
            else:
                current_lines.append(stripped)
                if page_num not in current_pages:
                    current_pages.append(page_num)

    # Don't forget the last section
    if current_lines:
        sections.append({
            "section": current_heading,
            "content": " ".join(current_lines).strip(),
            "pages": list(set(current_pages)),
        })

    return sections


# ── Main entry point ──────────────────────────────────────────────────────────

def parse_and_chunk(pdf_path: str, filename: str) -> ParsedDocument:
    """
    Full pipeline:
      PDF → pages → sections → token-capped chunks → ParsedDocument
    """
    max_tokens = settings.CHUNK_SIZE_TOKENS
    overlap    = settings.CHUNK_OVERLAP_TOKENS

    pages = extract_text_with_pages(pdf_path)
    raw_text = "\n".join(p["text"] for p in pages)

    sections = _split_into_sections(pages)

    chunks: List[ParsedChunk] = []
    idx = 0

    for sec in sections:
        text    = sec["content"]
        heading = sec["section"]
        pages_  = sec["pages"]

        if not text.strip():
            continue

        token_count = count_tokens(text)

        if token_count <= max_tokens:
            # Section fits in one chunk
            chunks.append(ParsedChunk(
                chunk_index=idx,
                content=text,
                section=heading,
                token_count=token_count,
                page_numbers=pages_,
            ))
            idx += 1
        else:
            # Section is too large — split by tokens with overlap
            sub_texts = split_by_tokens(text, max_tokens, overlap)
            for sub_idx, sub_text in enumerate(sub_texts):
                chunks.append(ParsedChunk(
                    chunk_index=idx,
                    content=sub_text,
                    section=f"{heading} (part {sub_idx + 1})" if heading else None,
                    token_count=count_tokens(sub_text),
                    page_numbers=pages_,
                    metadata={"is_split": True, "split_index": sub_idx},
                ))
                idx += 1

    return ParsedDocument(
        filename=filename,
        page_count=len(pages),
        char_count=len(raw_text),
        chunks=chunks,
        raw_text=raw_text,
    )
