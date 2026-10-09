"""FORGE-X 2.0 Phase 6: the complete core workflow, end to end, through the real web pages.

The 12 steps of the Phase 6 plan, each assertion labelled with its step:
 1. authenticate        2. create a case          3. assign an investigator
 4. register evidence   5. SHA-256 generated and stored
 6. verify integrity    7. review chain-of-custody history
 8. create an examination   9. record methodology and findings
10. complete the examination (submit, independent approval)
11. generate the examination report (PDF)
12. review the audit log

ADDS records to MySQL, so it runs only with FORGE_X_DB_WRITE_TESTS=1 and should be
run against a separate test database (see tools/build_test_database.py). Evidence
files are written to a temporary folder, never to real evidence storage.
"""
import hashlib
import io
import os

import pytest

from app.db import query_all, query_one, query_value
from tests.conftest import login

pytestmark = [
    pytest.mark.db,
    pytest.mark.db_write,
    pytest.mark.skipif(os.getenv("FORGE_X_DB_WRITE_TESTS") != "1",
                       reason="set FORGE_X_DB_WRITE_TESTS=1 to run tests that write to MySQL"),
]

SAMPLE = b"FORGE-X Phase 6 synthetic evidence " * 3000


def test_core_workflow_end_to_end(app, client, make_user, tmp_path):
    app.config["EVIDENCE_STORAGE_DIR"] = str(tmp_path)
    admin, lead, second = make_user("Administrator"), make_user("Investigator"), make_user("Investigator")
    custodian, auditor = make_user("Evidence Custodian"), make_user("Read-Only Auditor")

    # 1. Authenticate as an authorised user
    response = login(client, admin["username"], admin["password"])
    assert client.get("/dashboard").status_code == 200, "step 1: administrator could not reach the dashboard"

    # 2. Create a case
    response = client.post("/cases/new", data={"title": "Phase 6 end-to-end case", "case_type_id": "1", "priority": "High",
                                                "description": "Core workflow stability test.",
                                                "lead_user_id": str(lead["user_id"]), "due_date": "2099-12-31"})
    assert response.status_code == 302, "step 2: case not created"
    reference = response.headers["Location"].rsplit("/", 1)[-1]
    with app.app_context():
        case_id = query_value("SELECT case_id FROM cases WHERE case_reference = %s", (reference,))
    assert case_id, "step 2: case row missing"

    # 3. Assign an investigator
    assert client.post(f"/cases/{reference}/investigators", data={"user_id": str(second["user_id"])}).status_code == 302
    with app.app_context():
        team = {r["user_id"] for r in query_all("SELECT user_id FROM case_investigators WHERE case_id = %s", (case_id,))}
    assert {lead["user_id"], second["user_id"]} <= team, "step 3: investigator not assigned"
    client.post("/logout")

    # 4. Register evidence (with its file) as the custodian
    login(client, custodian["username"], custodian["password"])
    response = client.post("/evidence/new", content_type="multipart/form-data", data={
        "case_id": str(case_id), "evidence_type_id": "8", "description": "Phase 6 log export",
        "collection_site": "Test server", "collected_at": "2026-10-01T09:00", "collected_by": str(custodian["user_id"]),
        "collection_condition": "Exported to sealed USB", "hash_source": "Computed",
        "evidence_file": (io.BytesIO(SAMPLE), "phase6.log")})
    assert response.status_code == 302, "step 4: evidence not registered"
    code = response.headers["Location"].rsplit("/", 1)[-1]

    # 5. SHA-256 generated and stored
    sha = hashlib.sha256(SAMPLE).hexdigest()
    with app.app_context():
        stored = query_one("SELECT e.evidence_id, f.sha256, f.object_id, vi.current_hash_value FROM evidence e "
                           "JOIN evidence_files f ON f.evidence_id = e.evidence_id "
                           "JOIN v_evidence_integrity vi ON vi.evidence_id = e.evidence_id WHERE e.evidence_code = %s", (code,))
    assert stored and stored["sha256"] == sha == stored["current_hash_value"], "step 5: SHA-256 not stored as the reference"
    assert (tmp_path / stored["object_id"][:2] / stored["object_id"]).read_bytes() == SAMPLE, "step 5: stored bytes differ"

    # 6. Verify evidence integrity (from storage)
    assert "Hashes match" in client.post(f"/evidence/{code}/file/verify").get_data(as_text=True), "step 6: not verified"
    with app.app_context():
        assert query_value("SELECT integrity_status FROM v_evidence_integrity WHERE evidence_id = %s",
                           (stored["evidence_id"],)) == "Verified", "step 6: integrity status not Verified"

    # 7. Review chain-of-custody history (and record a download as Exported)
    client.post(f"/custody/{code}/transfer", data={"action": "Received", "to_user_id": str(custodian["user_id"]),
                                                    "location_id": "1", "condition": "Sealed, intact", "reason": "Arrived",
                                                    "expected_custodian_id": str(custodian["user_id"]), "confirm": "y"})
    assert client.get(f"/evidence/{code}/file/download").status_code == 200, "step 7: download failed"
    timeline = client.get(f"/evidence/{code}?tab=custody").get_data(as_text=True)
    for event in ("Collected", "Received", "Exported", "Integrity check"):
        assert event in timeline, f"step 7: {event} missing from the custody timeline"
    log = client.get(f"/custody?q={code}").get_data(as_text=True)
    assert code in log and "Integrity check" in log, "step 7: custody log incomplete"
    client.post("/logout")

    # 8. Create an examination (as the lead investigator)
    login(client, lead["username"], lead["password"])
    response = client.post("/examinations/new", data={"case_id": str(case_id), "examination_type_id": "3",
                                                       "examiner_id": str(lead["user_id"]),
                                                       "evidence_ids": [str(stored["evidence_id"])]})
    assert response.status_code == 302, "step 8: examination not created"
    exam_code = response.headers["Location"].rsplit("/", 1)[-1]

    # 9. Record methodology and findings (plus an artifact)
    client.post(f"/examinations/{exam_code}/start")
    client.post(f"/examinations/{exam_code}/record", data={
        "tools_methods": "Reviewed the verified log export with a text editor on a working copy.",
        "observations": "Twelve failed logons from one address in two minutes.",
        "findings": "Consistent with password guessing.", "conclusion": "Account targeted; no successful logon.",
        "limitations": "Logs before 1 October were rotated."})
    client.post(f"/examinations/{exam_code}/artifacts", data={"artifact_type": "Log entry", "evidence_id": str(stored["evidence_id"]),
                                                              "description": "Failed logon burst", "location": "lines 120-131",
                                                              "sha256": ""})

    # 10. Complete the examination: submit, then independent approval
    client.post(f"/examinations/{exam_code}/submit")
    assert client.post(f"/examinations/{exam_code}/approve").status_code == 403, "step 10: examiner approved own work"
    client.post("/logout")
    login(client, admin["username"], admin["password"])
    client.post(f"/examinations/{exam_code}/approve", data={"note": "Reviewed in the Phase 6 test"})
    with app.app_context():
        exam = query_one("SELECT status, reviewed_by FROM examinations WHERE examination_code = %s", (exam_code,))
    assert exam == {"status": "Completed", "reviewed_by": admin["user_id"]}, "step 10: examination not completed by review"

    # 11. Generate the examination report
    pdf = client.get(f"/examinations/{exam_code}/pdf")
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF"), "step 11: examination PDF not produced"
    client.post("/logout")

    # 12. Review the audit log (as the read-only auditor)
    login(client, auditor["username"], auditor["password"])
    assert client.get(f"/audit-logs?ref={code}").status_code == 200, "step 12: auditor can't open the audit log"
    with app.app_context():
        actions = {r["action"] for r in query_all("SELECT action FROM audit_logs WHERE entity_ref IN (%s, %s, %s)",
                                                  (reference, code, exam_code))}
    expected = {"case.create", "case.assign_investigator", "evidence.register", "evidence.file_store", "hash.verify",
                "evidence.download", "exam.create", "exam.start", "exam.update", "exam.artifact", "exam.submit",
                "exam.approve", "exam.export"}
    missing = expected - actions
    assert not missing, f"step 12: audit log is missing {sorted(missing)}"
