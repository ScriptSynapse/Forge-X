"""FORGE-X 2.0 Phase 3 end to end: store, download, verify, tamper, attach.
ADDS records to MySQL (FORGE_X_DB_WRITE_TESTS=1) and writes files only to a
temporary folder, never to your real evidence storage."""
import hashlib
import io
import os
import stat

import pytest

from app.db import query_one, query_value
from tests.conftest import login

pytestmark = [
    pytest.mark.db,
    pytest.mark.db_write,
    pytest.mark.skipif(os.getenv("FORGE_X_DB_WRITE_TESTS") != "1",
                       reason="set FORGE_X_DB_WRITE_TESTS=1 to run tests that write to MySQL"),
]

DATA = b"pytest synthetic evidence " * 5000


def _case(client, lead_id):
    return client.post("/cases/new", data={"title": "Pytest stored files", "case_type_id": "1", "priority": "Low",
                                           "description": "Phase 3 stored evidence files.",
                                           "lead_user_id": str(lead_id)}).headers["Location"].rsplit("/", 1)[-1]


def _register(client, case_id, collector_id, upload=None, original_hash=""):
    data = {"case_id": str(case_id), "evidence_type_id": "6", "description": "Pytest image",
            "collection_site": "Lab", "collected_at": "2026-10-01T09:00", "collected_by": str(collector_id),
            "collection_condition": "Sealed", "hash_source": "Computed", "original_hash": original_hash}
    if upload is not None:
        data["evidence_file"] = (io.BytesIO(upload), "pytest image.dd")
    return client.post("/evidence/new", data=data, content_type="multipart/form-data")


def test_store_download_verify_and_detect_tampering(app, client, make_user, tmp_path):
    app.config["EVIDENCE_STORAGE_DIR"] = str(tmp_path)
    admin, lead, custodian, auditor = (make_user("Administrator"), make_user("Investigator"),
                                       make_user("Evidence Custodian"), make_user("Read-Only Auditor"))
    login(client, admin["username"], admin["password"])
    reference = _case(client, lead["user_id"])
    client.post("/logout")
    with app.app_context():
        case_id = query_value("SELECT case_id FROM cases WHERE case_reference = %s", (reference,))

    login(client, custodian["username"], custodian["password"])
    response = _register(client, case_id, custodian["user_id"], DATA)
    assert response.status_code == 302, response.get_data(as_text=True)[:300]
    code = response.headers["Location"].rsplit("/", 1)[-1]
    sha = hashlib.sha256(DATA).hexdigest()
    with app.app_context():
        row = query_one("SELECT f.object_id, f.sha256, f.size_bytes, vi.current_hash_value FROM evidence_files f "
                        "JOIN evidence e ON e.evidence_id = f.evidence_id "
                        "JOIN v_evidence_integrity vi ON vi.evidence_id = e.evidence_id WHERE e.evidence_code = %s", (code,))
    assert (row["sha256"], row["size_bytes"], row["current_hash_value"]) == (sha, len(DATA), sha)
    stored = tmp_path / row["object_id"][:2] / row["object_id"]
    assert stored.read_bytes() == DATA

    download = client.get(f"/evidence/{code}/file/download")
    assert download.status_code == 200 and download.data == DATA and download.mimetype == "application/octet-stream"
    assert "Hashes match" in client.post(f"/evidence/{code}/file/verify").get_data(as_text=True)

    os.chmod(stored, stat.S_IREAD | stat.S_IWRITE)
    stored.write_bytes(DATA + b"tampered")
    assert "do NOT match" in client.post(f"/evidence/{code}/file/verify").get_data(as_text=True)
    with app.app_context():
        assert query_value("SELECT integrity_status FROM v_evidence_integrity vi JOIN evidence e "
                           "ON e.evidence_id = vi.evidence_id WHERE e.evidence_code = %s", (code,)) == "Failed"
        assert query_value("SELECT current_hash_value FROM v_evidence_integrity vi JOIN evidence e "
                           "ON e.evidence_id = vi.evidence_id WHERE e.evidence_code = %s", (code,)) == sha
        assert query_value("SELECT COUNT(*) FROM hash_verifications hv JOIN evidence_hashes h ON h.hash_id = hv.hash_id "
                           "JOIN evidence e ON e.evidence_id = h.evidence_id WHERE e.evidence_code = %s "
                           "AND hv.method = 'Stored file'", (code,)) == 2
        assert query_value("SELECT COUNT(*) FROM audit_logs WHERE action = 'evidence.download' AND entity_ref = %s",
                           (code,)) == 1
        # FORGE-X 2.0 Phase 4: the download is an Exported custody entry; the original didn't move.
        export = query_one("SELECT coc.custody_id, coc.from_custodian_id, coc.to_custodian_id, coc.location_id, "
                           "e.current_custodian_id, e.current_location_id FROM chain_of_custody coc "
                           "JOIN evidence e ON e.evidence_id = coc.evidence_id "
                           "WHERE e.evidence_code = %s AND coc.action = 'Exported'", (code,))
        assert export["from_custodian_id"] == export["to_custodian_id"] == export["current_custodian_id"]
        assert export["location_id"] == export["current_location_id"]
    refused = client.post(f"/custody/{code}/entries/{export['custody_id']}/correct",
                          data={"to_user_id": str(custodian["user_id"]), "location_id": "0", "location_note": "Elsewhere",
                                "condition": "Sealed", "reason": "Trying to correct an export record"}, follow_redirects=True)
    assert "can&#39;t be corrected" in refused.get_data(as_text=True) or "can't be corrected" in refused.get_data(as_text=True)
    client.post("/logout")
    login(client, auditor["username"], auditor["password"])
    assert client.get(f"/evidence/{code}/file/download").status_code == 403


def test_mismatched_hash_and_attach(app, client, make_user, tmp_path):
    app.config["EVIDENCE_STORAGE_DIR"] = str(tmp_path)
    admin, lead = make_user("Administrator"), make_user("Investigator")
    login(client, admin["username"], admin["password"])
    reference = _case(client, lead["user_id"])
    with app.app_context():
        case_id = query_value("SELECT case_id FROM cases WHERE case_reference = %s", (reference,))
    refused = _register(client, case_id, admin["user_id"], DATA, original_hash="ab" * 32)
    assert refused.status_code == 200 and "match the original hash" in refused.get_data(as_text=True)
    assert not any(tmp_path.rglob("*-*-*-*-*"))                      # the refused file was removed

    code = _register(client, case_id, admin["user_id"]).headers["Location"].rsplit("/", 1)[-1]   # metadata only
    assert client.post(f"/evidence/{code}/file", data={"evidence_file": (io.BytesIO(DATA), "later.dd")},
                       content_type="multipart/form-data").status_code == 302
    with app.app_context():
        assert query_value("SELECT current_hash_value FROM v_evidence_integrity vi JOIN evidence e "
                           "ON e.evidence_id = vi.evidence_id WHERE e.evidence_code = %s", (code,)) == \
            hashlib.sha256(DATA).hexdigest()
    again = client.post(f"/evidence/{code}/file", data={"evidence_file": (io.BytesIO(b"other"), "x.dd")},
                        content_type="multipart/form-data", follow_redirects=True)
    assert "never replaced" in again.get_data(as_text=True)
