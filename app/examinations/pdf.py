"""Examination report PDF (FORGE-X 2.0 Phase 5).

Built in memory from database records only, with the same layout, colours
and text escaping as the forensic report PDF (app/reports/pdf.py), so the
two documents look like one family and user text can't inject markup.
"""
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from ..reports.pdf import FACT_BG, INTERP_BG, MUTED, NAVY, RULE, _draw_logo, _fmt, _grid, _styles, _text
from ..ui import integrity_label


def build_examination_pdf(exam, evidence, artifacts, custody, generated_by, generated_at):
    st = _styles()
    buffer = BytesIO()
    final = exam["status"] == "Completed" and exam.get("reviewed_by")
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=28 * mm,
                            bottomMargin=20 * mm, title=f"{exam['examination_code']} examination report",
                            author=exam["examiner_name"], creator="FORGE-X")

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
        canvas.drawString(34 * mm, height - 13.5 * mm, "Examination report")
        canvas.setFont("Helvetica-Bold", 9)
        canvas.drawRightString(width - 18 * mm, height - 9.5 * mm, exam["examination_code"])
        canvas.setFont("Helvetica", 7.5)
        canvas.drawRightString(width - 18 * mm, height - 13.5 * mm, f"Status: {exam['status']}")
        if not final:
            canvas.setFillColor(colors.Color(0.94, 0.32, 0.32, alpha=0.10))
            canvas.setFont("Helvetica-Bold", 60)
            canvas.translate(width / 2, height / 2)
            canvas.rotate(35)
            canvas.drawCentredString(0, 0, "NOT REVIEWED")
            canvas.rotate(-35)
            canvas.translate(-width / 2, -height / 2)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 7)
        canvas.drawString(18 * mm, 10 * mm, f"Generated {generated_at:%d %b %Y %H:%M} by {generated_by} from FORGE-X "
                                            "records. Synthetic academic project data.")
        canvas.drawRightString(width - 18 * mm, 10 * mm, f"Page {doc_.page}")
        canvas.restoreState()

    story = [Paragraph(f"{escape(exam['type_name'])}: {escape(exam['examination_code'])}", st["title"]),
             Paragraph(f"Case {escape(exam['case_reference'])}: {_text(exam['case_title'])}", st["subtitle"]),
             Spacer(1, 6)]
    review = (f"{_fmt(exam['reviewed_at'])} by {exam['reviewer_name']}" if exam.get("reviewer_name")
              else ("Completed before independent review was introduced" if exam["status"] == "Completed" else "Not reviewed"))
    meta = [["Examination", exam["examination_code"], "Case", exam["case_reference"]],
            ["Examiner", exam["examiner_name"], "Status", exam["status"]],
            ["Started", _fmt(exam["started_at"]), "Completed", _fmt(exam["completed_at"])],
            ["Reviewed", review, "Due date", _fmt(exam["due_date"])]]
    rows = [[Paragraph(a, st["label"]), Paragraph(_text(b), st["cell"]), Paragraph(c, st["label"]),
             Paragraph(_text(d), st["cell"])] for a, b, c, d in meta]
    table = Table(rows, colWidths=[24 * mm, 60 * mm, 22 * mm, 68 * mm])
    table.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.4, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [table, Spacer(1, 4)]

    def section(title, value, kind=None):
        heading = title + ('  <font size="7.5" color="#5B6B7D">RECORDED OBSERVATION</font>' if kind == "fact" else
                           '  <font size="7.5" color="#1677FF">EXAMINER INTERPRETATION</font>' if kind == "interp" else "")
        para = Paragraph(_text(value), st["body"])
        if kind:
            box = Table([[para]], colWidths=[174 * mm])
            box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), FACT_BG if kind == "fact" else INTERP_BG),
                                     ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                                     ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
            para = box
        return KeepTogether([Paragraph(heading, st["h2"]), para])

    story += [section("1. Tools and methodology", exam["tools_methods"]),
              section("2. Observations", exam["observations"], "fact"),
              section("3. Findings", exam["findings"], "interp"),
              section("4. Conclusion", exam["conclusion"], "interp"),
              section("5. Limitations", exam["limitations"])]

    story.append(Paragraph("6. Evidence examined", st["h2"]))
    if evidence:
        rows = [[Paragraph(h, st["cellb"]) for h in ("Evidence ID", "Type / description", "Integrity", "Reference SHA-256")]]
        rows += [[Paragraph(escape(e["evidence_code"]), st["cell"]),
                  Paragraph(f"{escape(e['evidence_type'])}<br/>{_text(e['description'])}", st["cell"]),
                  Paragraph(escape(integrity_label(e["integrity_status"])), st["cell"]),
                  Paragraph(escape(e.get("current_hash_value") or "None recorded"), st["mono"])] for e in evidence]
        story.append(_grid(rows, [36 * mm, 44 * mm, 22 * mm, 72 * mm]))
    else:
        story.append(Paragraph("<i>No evidence is linked to this examination.</i>", st["small"]))

    story.append(Paragraph("7. Artifacts", st["h2"]))
    if artifacts:
        rows = [[Paragraph(h, st["cellb"]) for h in ("#", "Type", "Description and location", "Evidence", "SHA-256")]]
        for a in artifacts:
            note = f"<br/><font color='#5B6B7D'>Corrects #{a['corrects_artifact_id']}</font>" if a["corrects_artifact_id"] else ""
            if a["corrected_by"]:
                note += "<br/><font color='#5B6B7D'>Corrected by " + ", ".join(f"#{c}" for c in a["corrected_by"]) + "</font>"
            rows.append([Paragraph(str(a["artifact_id"]), st["cell"]), Paragraph(escape(a["artifact_type"]), st["cell"]),
                         Paragraph(_text(a["description"]) + (f"<br/>{_text(a['location'])}" if a["location"] else "") + note,
                                   st["cell"]),
                         Paragraph(escape(a["evidence_code"] or "—"), st["cell"]),
                         Paragraph(escape(a["sha256"] or "—"), st["mono"])])
        story.append(_grid(rows, [8 * mm, 22 * mm, 58 * mm, 36 * mm, 50 * mm]))
    else:
        story.append(Paragraph("<i>No artifacts were recorded.</i>", st["small"]))

    story.append(Paragraph("8. Custody references", st["h2"]))
    if custody:
        rows = [[Paragraph(h, st["cellb"]) for h in ("Evidence ID", "Entry", "Action", "When", "Held by")]]
        rows += [[Paragraph(escape(c["evidence_code"]), st["cell"]), Paragraph(f"#{c['custody_id']}", st["cell"]),
                  Paragraph(escape(c["action"]), st["cell"]), Paragraph(_fmt(c["occurred_at"]), st["cell"]),
                  Paragraph(escape(c["to_name"]), st["cell"])] for c in custody]
        story.append(_grid(rows, [36 * mm, 18 * mm, 30 * mm, 40 * mm, 50 * mm]))
        story.append(Paragraph("The latest custody entries of each item. The full chain of custody is in FORGE-X.", st["small"]))
    story.append(Spacer(1, 6))
    story.append(Paragraph("A matching hash shows the content was identical when compared. On its own it does not prove "
                           "authenticity, ownership or a complete chain of custody. FORGE-X records examination work; it "
                           "does not run forensic tools.", st["small"]))
    doc.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return buffer.getvalue()
