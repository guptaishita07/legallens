"""
services/report_generator.py

Generates a professional PDF risk report for a contract using ReportLab.

Output structure:
  Cover page — document name, date, overall risk score
  Executive summary — LLM-generated paragraph
  Risk score breakdown — 7-signal bar chart
  Clause analysis — one section per clause, colour-coded by risk
  Appendix — Q&A history (if any)
"""

import io
from datetime import datetime, timezone
from typing import List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether,
)
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.graphics import renderPDF

from db.database import ExtractedClause, DocumentRiskScore, QASession


# ── Colour palette ─────────────────────────────────────────────────────────────

C_ACCENT  = colors.HexColor("#185FA5")
C_TEXT    = colors.HexColor("#1a1a18")
C_MUTED   = colors.HexColor("#6b6b68")
C_BORDER  = colors.HexColor("#e5e5e3")
C_BG      = colors.HexColor("#f9f9f8")

RISK_COLORS = {
    "low":      colors.HexColor("#3B6D11"),
    "medium":   colors.HexColor("#854F0B"),
    "high":     colors.HexColor("#A32D2D"),
    "critical": colors.HexColor("#500000"),
}
RISK_BG = {
    "low":      colors.HexColor("#EAF3DE"),
    "medium":   colors.HexColor("#FAEEDA"),
    "high":     colors.HexColor("#FCEBEB"),
    "critical": colors.HexColor("#FFD6D6"),
}


# ── Styles ────────────────────────────────────────────────────────────────────

def _make_styles():
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("title",
            fontSize=22, fontName="Helvetica-Bold",
            textColor=C_TEXT, spaceAfter=6, leading=28),
        "h2": ParagraphStyle("h2",
            fontSize=14, fontName="Helvetica-Bold",
            textColor=C_ACCENT, spaceBefore=16, spaceAfter=6, leading=18),
        "h3": ParagraphStyle("h3",
            fontSize=11, fontName="Helvetica-Bold",
            textColor=C_TEXT, spaceBefore=10, spaceAfter=4, leading=14),
        "body": ParagraphStyle("body",
            fontSize=9.5, fontName="Helvetica",
            textColor=C_TEXT, spaceAfter=4, leading=14),
        "muted": ParagraphStyle("muted",
            fontSize=8.5, fontName="Helvetica",
            textColor=C_MUTED, leading=12),
        "risk_badge": ParagraphStyle("risk_badge",
            fontSize=9, fontName="Helvetica-Bold",
            alignment=TA_CENTER),
        "cover_sub": ParagraphStyle("cover_sub",
            fontSize=11, fontName="Helvetica",
            textColor=C_MUTED, spaceAfter=4, alignment=TA_CENTER),
        "cover_title": ParagraphStyle("cover_title",
            fontSize=28, fontName="Helvetica-Bold",
            textColor=C_TEXT, spaceAfter=12, alignment=TA_CENTER, leading=34),
    }


# ── Score donut (simple bar chart via ReportLab Drawing) ─────────────────────

def _score_bar_chart(score: int, level: str) -> Drawing:
    """A horizontal progress bar showing the risk score."""
    w, h = 200, 20
    d = Drawing(w, h)
    # Background
    d.add(Rect(0, 4, w, 12, fillColor=C_BORDER, strokeColor=None))
    # Fill
    fill_w = int(w * score / 100)
    d.add(Rect(0, 4, fill_w, 12,
               fillColor=RISK_COLORS.get(level, C_ACCENT), strokeColor=None))
    # Label
    d.add(String(w + 8, 6, f"{score}/100",
                 fontSize=9, fontName="Helvetica-Bold",
                 fillColor=RISK_COLORS.get(level, C_ACCENT)))
    return d


# ── Signal breakdown table ────────────────────────────────────────────────────

SIGNAL_LABELS = {
    "uncapped_liability":       ("Uncapped liability", 25),
    "unilateral_termination":   ("Unilateral termination", 20),
    "missing_indemnification":  ("Missing indemnification", 15),
    "auto_renewal_trap":        ("Auto-renewal trap", 15),
    "onesided_ip":              ("One-sided IP assignment", 10),
    "punitive_penalties":       ("Punitive penalties", 10),
    "unlimited_confidentiality":("Unlimited confidentiality", 5),
}


def _signal_table(signals: dict, styles: dict):
    rows = [["Signal", "Score", "Max"]]
    for key, (label, max_val) in SIGNAL_LABELS.items():
        val = signals.get(key, 0)
        rows.append([label, str(val), str(max_val)])

    t = Table(rows, colWidths=[100*mm, 20*mm, 20*mm])
    t.setStyle(TableStyle([
        ("FONTNAME",    (0, 0), (-1, 0),  "Helvetica-Bold"),
        ("FONTSIZE",    (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR",   (0, 0), (-1, 0),  colors.white),
        ("BACKGROUND",  (0, 0), (-1, 0),  C_ACCENT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [C_BG, colors.white]),
        ("GRID",        (0, 0), (-1, -1), 0.3, C_BORDER),
        ("ALIGN",       (1, 0), (-1, -1), "CENTER"),
        ("TOPPADDING",  (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]))
    return t


# ── Main generator ────────────────────────────────────────────────────────────

def generate_risk_report(
    filename: str,
    risk: DocumentRiskScore,
    clauses: List[ExtractedClause],
    qa_sessions: Optional[List[QASession]] = None,
) -> bytes:
    """
    Generate a PDF risk report and return it as bytes.
    Caller writes to disk or streams to HTTP response.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=20*mm, rightMargin=20*mm,
        topMargin=20*mm, bottomMargin=20*mm,
    )

    styles = _make_styles()
    story = []
    W = A4[0] - 40*mm   # usable width

    # ── Cover page ────────────────────────────────────────────────────────────
    story.append(Spacer(1, 30*mm))
    story.append(Paragraph("LegalLens", ParagraphStyle("logo",
        fontSize=13, fontName="Helvetica-Bold", textColor=C_ACCENT,
        alignment=TA_CENTER, spaceAfter=8)))
    story.append(Paragraph("Contract Risk Report", styles["cover_title"]))
    story.append(Paragraph(filename, styles["cover_sub"]))
    story.append(Spacer(1, 6*mm))

    # Big score pill
    level = risk.overall_level.value
    score_color = RISK_COLORS.get(level, C_ACCENT)
    score_bg    = RISK_BG.get(level, C_BG)
    story.append(Table(
        [[Paragraph(f"{risk.overall_score}/100  ·  {level.upper()} RISK",
                    ParagraphStyle("score_pill",
                        fontSize=16, fontName="Helvetica-Bold",
                        textColor=score_color, alignment=TA_CENTER))]],
        colWidths=[W],
        style=TableStyle([
            ("BACKGROUND", (0,0), (-1,-1), score_bg),
            ("TOPPADDING", (0,0), (-1,-1), 10),
            ("BOTTOMPADDING", (0,0), (-1,-1), 10),
            ("ROUNDEDCORNERS", [6]),
        ]),
    ))
    story.append(Spacer(1, 4*mm))
    story.append(Paragraph(
        f"Generated {datetime.now(timezone.utc).strftime('%d %B %Y, %H:%M UTC')}  ·  "
        f"{risk.clause_count} clauses analysed  ·  {risk.high_risk_count} high-risk",
        ParagraphStyle("meta", fontSize=8, fontName="Helvetica",
                       textColor=C_MUTED, alignment=TA_CENTER)
    ))
    story.append(PageBreak())

    # ── Executive summary ──────────────────────────────────────────────────────
    story.append(Paragraph("Executive summary", styles["h2"]))
    story.append(HRFlowable(width=W, thickness=0.5, color=C_BORDER, spaceAfter=8))
    if risk.summary:
        story.append(Paragraph(risk.summary, styles["body"]))
    story.append(Spacer(1, 6*mm))

    # ── Risk signal breakdown ──────────────────────────────────────────────────
    story.append(Paragraph("7-signal risk breakdown", styles["h2"]))
    story.append(HRFlowable(width=W, thickness=0.5, color=C_BORDER, spaceAfter=8))
    signals = (risk.score_breakdown or {}).get("_signals", {})
    if signals:
        story.append(_signal_table(signals, styles))
    story.append(Spacer(1, 6*mm))

    # ── Clause analysis ────────────────────────────────────────────────────────
    story.append(Paragraph("Clause analysis", styles["h2"]))
    story.append(HRFlowable(width=W, thickness=0.5, color=C_BORDER, spaceAfter=8))

    sorted_clauses = sorted(clauses, key=lambda c: c.risk_score, reverse=True)
    for clause in sorted_clauses:
        lv = clause.risk_level.value
        c_color = RISK_COLORS.get(lv, C_ACCENT)
        c_bg    = RISK_BG.get(lv, C_BG)

        block = []
        # Clause header row
        header = Table(
            [[
                Paragraph(clause.title, ParagraphStyle("ch",
                    fontSize=10, fontName="Helvetica-Bold", textColor=C_TEXT)),
                Paragraph(f"{clause.risk_score}/100  {lv.upper()}",
                    ParagraphStyle("cs", fontSize=9, fontName="Helvetica-Bold",
                                   textColor=c_color, alignment=TA_RIGHT)),
            ]],
            colWidths=[W * 0.75, W * 0.25],
            style=TableStyle([
                ("BACKGROUND", (0,0), (-1,-1), c_bg),
                ("TOPPADDING", (0,0), (-1,-1), 6),
                ("BOTTOMPADDING", (0,0), (-1,-1), 6),
                ("LEFTPADDING", (0,0), (0,-1), 8),
            ]),
        )
        block.append(header)

        if clause.summary:
            block.append(Paragraph(clause.summary,
                ParagraphStyle("cs2", fontSize=9, fontName="Helvetica",
                               textColor=C_TEXT, leftIndent=8, spaceBefore=4,
                               spaceAfter=2, leading=13)))

        if clause.risk_reasons:
            reasons_text = "  ·  ".join(clause.risk_reasons[:3])
            block.append(Paragraph(f"⚠ {reasons_text}",
                ParagraphStyle("cr", fontSize=8, fontName="Helvetica",
                               textColor=c_color, leftIndent=8, spaceAfter=4)))

        block.append(Spacer(1, 3*mm))
        story.append(KeepTogether(block))

    # ── Q&A appendix ──────────────────────────────────────────────────────────
    if qa_sessions:
        story.append(PageBreak())
        story.append(Paragraph("Appendix — Q&A history", styles["h2"]))
        story.append(HRFlowable(width=W, thickness=0.5, color=C_BORDER, spaceAfter=8))
        for s in qa_sessions[:10]:   # cap at 10
            story.append(Paragraph(f"Q: {s.question}", styles["h3"]))
            story.append(Paragraph(s.answer, styles["body"]))
            story.append(Spacer(1, 3*mm))

    doc.build(story)
    return buf.getvalue()
