"""Forensic report PDF, generated with ReportLab from MySQL records only.

Nothing is hard-coded: every value comes from the report, version,
case, examination and evidence rows passed in. The PDF is built in memory
and streamed to the browser; it is not stored on disk.
"""
from datetime import datetime
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..ui import integrity_label

NAVY = colors.HexColor("#07111F")
BLUE = colors.HexColor("#1677FF")
CYAN = colors.HexColor("#35BFFF")
INK = colors.HexColor("#1B2733")
MUTED = colors.HexColor("#5B6B7D")
RULE = colors.HexColor("#D5DDE6")
FACT_BG = colors.HexColor("#F2F5F8")
INTERP_BG = colors.HexColor("#EAF4FF")


def _styles():
    base = getSampleStyleSheet()
    s = {
        "title": ParagraphStyle("title", parent=base["Title"], fontName="Helvetica-Bold", fontSize=18, leading=22,
                                alignment=TA_LEFT, textColor=INK, spaceAfter=2),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=10, leading=13, textColor=MUTED),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=INK,
                             spaceBefore=10, spaceAfter=4),
        "label": ParagraphStyle("label", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=MUTED),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13.5, textColor=INK),
        "small": ParagraphStyle("small", fontName="Helvetica", fontSize=8, leading=10.5, textColor=MUTED),
        "mono": ParagraphStyle("mono", fontName="Courier", fontSize=7.5, leading=9.5, textColor=INK),
        "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.5, leading=11, textColor=INK),
        "cellb": ParagraphStyle("cellb", fontName="Helvetica-Bold", fontSize=8.5, leading=11, textColor=INK),
    }
    return s


def _text(value, empty="Not recorded."):
    """Escape user text for ReportLab's mini-markup and keep line breaks."""
    if value is None or str(value).strip() == "":
        return f"<i>{empty}</i>"
    return escape(str(value)).replace("\n", "<br/>")


def _fmt(value):
    return value.strftime("%d %b %Y %H:%M") if isinstance(value, datetime) else (str(value) if value else "—")


def _draw_logo(canvas, x, y, size):
    """The FORGE-X hexagon-and-fingerprint mark, drawn with vector shapes."""
    s = size / 40.0
    canvas.saveState()
    canvas.setLineWidth(1.6 * s)
    canvas.setStrokeColor(CYAN)
    pts = [(20, 3), (35, 11.5), (35, 28.5), (20, 37), (5, 28.5), (5, 11.5)]
    path = canvas.beginPath()
    path.moveTo(x + pts[0][0] * s, y + (40 - pts[0][1]) * s)
    for px, py in pts[1:]:
        path.lineTo(x + px * s, y + (40 - py) * s)
    path.close()
    canvas.drawPath(path, stroke=1, fill=0)
    canvas.setStrokeColor(BLUE)
    canvas.arc(x + 12.5 * s, y + (40 - 30.5) * s, x + 27.5 * s, y + (40 - 15.5) * s, 0, 180)
    canvas.setStrokeColor(INK)
    canvas.arc(x + 16 * s, y + (40 - 31) * s, x + 24 * s, y + (40 - 20) * s, 0, 180)
    canvas.setStrokeColor(CYAN)
    canvas.line(x + 20 * s, y + (40 - 23.5) * s, x + 20 * s, y + (40 - 29.5) * s)
    canvas.restoreState()


def build_report_pdf(report, version, examinations, evidence, generated_by, generated_at):
    """Return the PDF as bytes."""
    st = _styles()
    buffer = BytesIO()
    approved = report["status"] == "Approved"
    is_latest = version["version_no"] == report["latest_version_no"]
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=28 * mm,
                            bottomMargin=20 * mm, title=f"{report['report_code']} v{version['version_no']}",
                            author=report["author_name"], subject=report["title"], creator="FORGE-X")

    def decorate(canvas, doc_):
        width, height = A4
        canvas.saveState()
        canvas.setFillColor(NAVY)
        canvas.rect(0, height - 18 * mm, width, 18 * mm, stroke=0, fill=1)
        _draw_logo(canvas, 18 * mm, height - 15.5 * mm, 13 * mm)
        canvas.setFillColor(colors.white)
        canvas.setFont("Helvetica-Bold", 12)
        canvas.drawString(34 * mm, height - 9.5 * mm, "FORGE-X")
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(34 * mm, height - 13.5 * mm, "Digital Forensics Evidence Management System")
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawRightString(width - 18 * mm, height - 9.5 * mm, f"{report['report_code']}  version {version['version_no']}")
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(width - 18 * mm, height - 13.5 * mm, f"Status: {report['status']}")
        if not (approved and is_latest):
            canvas.setFillColor(colors.Color(0.94, 0.32, 0.32, alpha=0.10))
            canvas.setFont("Helvetica-Bold", 64)
            canvas.translate(width / 2, height / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "NOT APPROVED" if not approved else "SUPERSEDED VERSION")
            canvas.rotate(-35)
            canvas.translate(-width / 2, -height / 2)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(18 * mm, 10 * mm, f"Generated {generated_at:%d %b %Y %H:%M} by {generated_by} from "
                                            f"FORGE-X records. Synthetic academic project data.")
        canvas.drawRightString(width - 18 * mm, 10 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    story = [Paragraph(_text(report["title"]), st["title"]),
             Paragraph(f"Case {escape(report['case_reference'])}: {_text(report['case_title'])}", st["subtitle"]),
             Spacer(1, 6)]

    meta = [
        ["Report", report["report_code"], "Case", report["case_reference"]],
        ["Author", report["author_name"], "Created", _fmt(report["created_at"])],
        ["Version", f"{version['version_no']} of {report['latest_version_no']}", "Version saved",
         f"{_fmt(version['created_at'])} by {version['created_by_name']}"],
        ["Status", report["status"], "Approved",
         f"{_fmt(report['approved_at'])} by {report['approved_by_name']}" if approved else "Not approved"],
    ]
    meta_rows = [[Paragraph(a, st["label"]), Paragraph(_text(b), st["cell"]),
                  Paragraph(c, st["label"]), Paragraph(_text(d), st["cell"])] for a, b, c, d in meta]
    meta_table = Table(meta_rows, colWidths=[22 * mm, 58 * mm, 26 * mm, 68 * mm])
    meta_table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                                    ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [meta_table, Spacer(1, 4)]
    if not is_latest:
        story.append(Paragraph(f"This is version {version['version_no']}. A newer version "
                               f"({report['latest_version_no']}) exists.", st["small"]))

    def section(title, value, kind=None):
        heading = title
        if kind == "fact":
            heading += '  <font size="7.5" color="#5B6B7D">RECORDED OBSERVATION</font>'
        elif kind == "interp":
            heading += '  <font size="7.5" color="#1677FF">EXAMINER INTERPRETATION</font>'
        para = Paragraph(_text(value), st["body"])
        if kind:
            box = Table([[para]], colWidths=[174 * mm])
            box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), FACT_BG if kind == "fact" else INTERP_BG),
                                     ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                     ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            para = box
        return KeepTogether([Paragraph(heading, st["h2"]), para])

    story += [section("1. Methodology", version["methodology"]),
              section("2. Observations", version["observations"], "fact"),
              section("3. Findings", version["findings"], "interp"),
              section("4. Conclusions", version["conclusions"], "interp"),
              section("5. Limitations", version["limitations"])]

    story.append(Paragraph("6. Examinations cited", st["h2"]))
    if examinations:
        rows = [[Paragraph(h, st["cellb"]) for h in ("Exam ID", "Type", "Examiner", "Status", "Completed")]]
        rows += [[Paragraph(escape(x["examination_code"]), st["cell"]), Paragraph(escape(x["examination_type"]), st["cell"]),
                  Paragraph(escape(x["examiner_name"]), st["cell"]), Paragraph(escape(x["status"]), st["cell"]),
                  Paragraph(_fmt(x["completed_at"]), st["cell"])] for x in examinations]
        story.append(_grid(rows, [26 * mm, 52 * mm, 38 * mm, 24 * mm, 34 * mm]))
    else:
        story.append(Paragraph("<i>No examinations are cited by this report.</i>", st["small"]))

    story.append(Paragraph("7. Evidence referenced", st["h2"]))
    if evidence:
        rows = [[Paragraph(h, st["cellb"]) for h in ("Evidence ID", "Type / description", "Integrity", "Current reference SHA-256")]]
        rows += [[Paragraph(escape(e["evidence_code"]), st["cell"]),
                  Paragraph(f"{escape(e['evidence_type'])}<br/>{_text(e['description'])}", st["cell"]),
                  Paragraph(escape(integrity_label(e["integrity_status"])), st["cell"]),
                  Paragraph(escape(e["current_hash_value"] or "None recorded"), st["mono"])] for e in evidence]
        story.append(_grid(rows, [36 * mm, 44 * mm, 22 * mm, 72 * mm]))
        story.append(Spacer(1, 4))
        story.append(Paragraph("A matching hash shows the content was identical when it was compared. On its own it "
                               "does not prove authenticity, ownership or a complete chain of custody.", st["small"]))
    else:
        story.append(Paragraph("<i>No evidence is linked through the cited examinations.</i>", st["small"]))

    story.append(Spacer(1, 8))
    story.append(Paragraph(f"Version note: {_text(version['change_note'])}", st["small"]))
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()


def _grid(rows, widths):
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), FACT_BG), ("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table
