"""Phase 11: examination/report rules and PDF generation (no MySQL needed)."""
from datetime import datetime

from app.access import (can_create_examination, can_edit_report, can_review_report, can_work_on_examination,
                        can_write_report)
from app.reports.pdf import build_report_pdf

ADMIN = {"user_id": 1, "roles": ["Administrator"]}
AUTHOR = {"user_id": 2, "roles": ["Investigator"]}
OTHER = {"user_id": 3, "roles": ["Investigator"]}
OPEN = {"status": "In Progress"}
CLOSED = {"status": "Closed"}


def test_examination_permissions():
    assert can_create_examination(ADMIN, OPEN, False) and can_create_examination(AUTHOR, OPEN, True)
    assert not can_create_examination(AUTHOR, OPEN, False) and not can_create_examination(ADMIN, CLOSED, False)
    exam = {"status": "In Progress", "case_status": "In Progress", "examiner_id": 2, "lead_user_id": 9}
    assert can_work_on_examination(AUTHOR, exam) and can_work_on_examination(ADMIN, exam)
    assert not can_work_on_examination(OTHER, exam)
    assert not can_work_on_examination(AUTHOR, dict(exam, status="Completed"))
    assert not can_work_on_examination(ADMIN, dict(exam, case_status="Closed"))


def test_report_permissions_and_independent_review():
    draft = {"status": "Draft", "case_status": "In Progress", "author_id": 2}
    assert can_write_report(AUTHOR, OPEN, True) and not can_write_report(AUTHOR, OPEN, False)
    assert can_edit_report(AUTHOR, draft) and can_edit_report(ADMIN, draft) and not can_edit_report(OTHER, draft)
    review = dict(draft, status="Under Review")
    assert not can_edit_report(AUTHOR, review)
    assert can_review_report(ADMIN, review)
    assert not can_review_report(dict(ADMIN, user_id=2), review)            # an admin who wrote it can't approve it
    assert not can_review_report(AUTHOR, review)


def test_pdf_is_built_from_the_given_records_and_escapes_text():
    now = datetime(2026, 10, 4, 11, 0)
    report = {"report_code": "RP-2026-0001", "title": "Title with <b>tags</b> & ampersands", "case_reference": "FX-2026-0001",
              "case_title": "Case <script>", "author_name": "Inv", "created_at": now, "status": "Draft",
              "approved_at": None, "approved_by_name": None, "latest_version_no": 1}
    version = {"version_no": 1, "created_at": now, "created_by_name": "Inv", "methodology": "Line 1\nLine 2",
               "observations": "<para>not markup</para>", "findings": None, "conclusions": "C", "limitations": "",
               "change_note": "First draft"}
    evidence = [{"evidence_code": "FX-EV-2026-00001", "evidence_type": "Log File", "description": "Logs & more",
                 "integrity_status": "Verified", "current_hash_value": "ab" * 32}]
    data = build_report_pdf(report, version, [], evidence, "Paulson", now)
    assert data.startswith(b"%PDF") and len(data) > 1500


def test_pages_require_login(client):
    for path in ("/examinations", "/examinations/new", "/examinations/EX-2026-0001", "/reports", "/reports/new",
                 "/reports/RP-2026-0001", "/reports/RP-2026-0001/pdf"):
        response = client.get(path)
        assert response.status_code == 302 and "/login" in response.headers["Location"], path
