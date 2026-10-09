"""Phase 11: examination and report workflow end to end. ADDS records to
MySQL, so it only runs with FORGE_X_DB_WRITE_TESTS=1."""
import os
import re

import pytest

from app.db import query_all, query_one, query_value
from tests.conftest import login

pytestmark = [
    pytest.mark.db,
    pytest.mark.db_write,
    pytest.mark.skipif(os.getenv("FORGE_X_DB_WRITE_TESTS") != "1",
                       reason="set FORGE_X_DB_WRITE_TESTS=1 to run tests that write to MySQL"),
]


def test_examination_and_report_workflow(app, client, make_user):
    admin, lead = make_user("Administrator"), make_user("Investigator")
    login(client, admin["username"], admin["password"])
    case_ref = client.post("/cases/new", data={"title": "Pytest exam case", "case_type_id": "1", "priority": "High",
                                               "description": "Examination and report tests.",
                                               "lead_user_id": str(lead["user_id"])}).headers["Location"].rsplit("/", 1)[-1]
    with app.app_context():
        case_id = query_value("SELECT case_id FROM cases WHERE case_reference = %s", (case_ref,))
    ev_code = client.post("/evidence/new", data={"case_id": str(case_id), "evidence_type_id": "8", "description": "Pytest logs",
                                                 "collection_site": "Server", "collected_at": "2026-10-01T09:00",
                                                 "collected_by": str(admin["user_id"]), "collection_condition": "Sealed",
                                                 "original_hash": "cd" * 32, "hash_source": "Computed"}).headers["Location"].rsplit("/", 1)[-1]
    with app.app_context():
        evidence_id = query_value("SELECT evidence_id FROM evidence WHERE evidence_code = %s", (ev_code,))
    client.post("/logout")

    # The lead investigator runs the examination
    login(client, lead["username"], lead["password"])
    r = client.post("/examinations/new", data={"case_id": str(case_id), "examination_type_id": "3",
                                                "examiner_id": str(lead["user_id"]), "evidence_ids": [str(evidence_id)]})
    assert r.status_code == 302, r.get_data(as_text=True)[:400]
    exam_code = r.headers["Location"].rsplit("/", 1)[-1]
    assert re.fullmatch(r"EX-\d{4}-\d{4}", exam_code)
    client.post(f"/examinations/{exam_code}/start")
    refused = client.post(f"/examinations/{exam_code}/submit", follow_redirects=True)
    assert "Record the tools and methods and the findings" in refused.get_data(as_text=True)
    client.post(f"/examinations/{exam_code}/record", data={"tools_methods": "Filtered log export", "observations": "12 failed logons",
                                                            "findings": "Password spraying", "conclusion": "Account targeted",
                                                            "limitations": "Logs rotated"})
    # FORGE-X 2.0 Phase 5: artifacts, then submission for an independent review
    assert client.post(f"/examinations/{exam_code}/artifacts", data={"artifact_type": "Log entry", "evidence_id": str(evidence_id),
                                                                     "description": "12 failed logons from one IP",
                                                                     "location": "auth.log lines 1200-1212", "sha256": ""}
                       ).status_code == 302
    client.post(f"/examinations/{exam_code}/submit")
    assert client.post(f"/examinations/{exam_code}/approve").status_code == 403          # the examiner can't approve
    with app.app_context():
        exam = query_one("SELECT examination_id, status FROM examinations WHERE examination_code = %s", (exam_code,))
        assert exam["status"] == "Under Review"
        assert query_value("SELECT COUNT(*) FROM examination_artifacts WHERE examination_id = %s",
                           (exam["examination_id"],)) == 1

    # Report: create (citing the exam), revise, submit
    r = client.post("/reports/new", data={"case_id": str(case_id), "title": "Pytest report", "methodology": "Log review",
                                           "observations": "12 failed logons", "findings": "Spraying",
                                           "examination_ids": [str(exam["examination_id"])]})
    report_code = r.headers["Location"].rsplit("/", 1)[-1]
    assert re.fullmatch(r"RP-\d{4}-\d{4}", report_code)
    client.post(f"/reports/{report_code}/edit", data={"methodology": "Log review", "observations": "12 failed logons",
                                                       "findings": "Password spraying", "conclusions": "Account targeted",
                                                       "change_note": "Added conclusions"})
    client.post(f"/reports/{report_code}/submit")
    client.post(f"/reports/{report_code}/approve")          # the author can't approve
    with app.app_context():
        row = query_one("SELECT status, (SELECT MAX(version_no) FROM report_versions v WHERE v.report_id = r.report_id) AS v "
                        "FROM forensic_reports r WHERE report_code = %s", (report_code,))
    assert row == {"status": "Under Review", "v": 2}
    client.post("/logout")

    # The administrator (not the examiner, not the author) approves the examination and the report
    login(client, admin["username"], admin["password"])
    assert client.post(f"/examinations/{exam_code}/approve", data={"note": "Reviewed"}).status_code == 302
    with app.app_context():
        done = query_one("SELECT status, reviewed_by, completed_at IS NOT NULL AS completed FROM examinations "
                         "WHERE examination_code = %s", (exam_code,))
    assert (done["status"], done["reviewed_by"], done["completed"]) == ("Completed", admin["user_id"], 1)
    exam_pdf = client.get(f"/examinations/{exam_code}/pdf")
    assert exam_pdf.status_code == 200 and exam_pdf.data.startswith(b"%PDF")
    assert client.post(f"/reports/{report_code}/approve").status_code == 302
    pdf = client.get(f"/reports/{report_code}/pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")
    assert f'{report_code}-v2.pdf' in pdf.headers["Content-Disposition"]
    with app.app_context():
        assert query_value("SELECT status FROM forensic_reports WHERE report_code = %s", (report_code,)) == "Approved"
        actions = {r["action"] for r in query_all("SELECT action FROM audit_logs WHERE entity_ref IN (%s, %s)",
                                                  (exam_code, report_code))}
    assert {"exam.create", "exam.start", "exam.update", "exam.artifact", "exam.submit", "exam.approve", "exam.export",
            "report.create", "report.revise", "report.submit", "report.approve", "report.export"} <= actions
    client.post("/logout")
    login(client, lead["username"], lead["password"])            # completed examinations are final
    assert client.get(f"/examinations/{exam_code}/record").status_code == 403
