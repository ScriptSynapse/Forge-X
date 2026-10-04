"""Phase 10: hashes and custody end to end. ADDS users, a case, evidence,
hashes and custody entries to MySQL: runs only with FORGE_X_DB_WRITE_TESTS=1."""
import io
import hashlib
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

SAMPLE = b"pytest forensic sample " * 1000


@pytest.fixture
def setup_item(app, client, make_user):
    """A case (lead investigator) and one evidence item with no hash, collected by a custodian."""
    admin, lead, custodian = make_user("Administrator"), make_user("Investigator"), make_user("Evidence Custodian")
    login(client, admin["username"], admin["password"])
    case_ref = client.post("/cases/new", data={"title": "Pytest custody case", "case_type_id": "5", "priority": "Low",
                                               "description": "Integrity and custody tests.",
                                               "lead_user_id": str(lead["user_id"])}).headers["Location"].rsplit("/", 1)[-1]
    with app.app_context():
        case_id = query_value("SELECT case_id FROM cases WHERE case_reference = %s", (case_ref,))
        location_id = query_value("SELECT MIN(location_id) FROM storage_locations WHERE is_active = TRUE")
    code = client.post("/evidence/new", data={
        "case_id": str(case_id), "evidence_type_id": "6", "description": "Pytest disk image",
        "collection_site": "Test bench", "collected_at": "2026-10-01T09:00", "collected_by": str(custodian["user_id"]),
        "collection_condition": "Sealed, intact", "hash_source": "Computed"}).headers["Location"].rsplit("/", 1)[-1]
    client.post("/logout")
    return {"code": code, "lead": lead, "custodian": custodian, "location_id": location_id}


def evidence_row(app, code):
    with app.app_context():
        return query_one("SELECT e.evidence_id, e.current_status, e.current_custodian_id, e.current_location_id, "
                         "vi.integrity_status FROM evidence e JOIN v_evidence_integrity vi ON vi.evidence_id = e.evidence_id "
                         "WHERE e.evidence_code = %s", (code,))


def test_record_and_verify_hash_from_sample_files(app, client, setup_item):
    code, custodian = setup_item["code"], setup_item["custodian"]
    login(client, custodian["username"], custodian["password"])
    assert evidence_row(app, code)["integrity_status"] == "Not Verified"

    r = client.post(f"/evidence/{code}/hash/record", content_type="multipart/form-data",
                    data={"method": "sample", "sample_file": (io.BytesIO(SAMPLE), "image.dd")})
    assert r.status_code == 302
    with app.app_context():
        stored = query_value("SELECT hash_value FROM evidence_hashes h JOIN evidence e ON e.evidence_id = h.evidence_id "
                             "WHERE e.evidence_code = %s", (code,))
    assert stored == hashlib.sha256(SAMPLE).hexdigest()
    assert evidence_row(app, code)["integrity_status"] == "Pending"

    same = client.post(f"/evidence/{code}/hash/verify", content_type="multipart/form-data",
                       data={"method": "sample", "sample_file": (io.BytesIO(SAMPLE), "image.dd")})
    assert "Hashes match" in same.get_data(as_text=True)
    assert evidence_row(app, code)["integrity_status"] == "Verified"

    changed = client.post(f"/evidence/{code}/hash/verify", content_type="multipart/form-data",
                          data={"method": "sample", "sample_file": (io.BytesIO(SAMPLE + b"!"), "image.dd")})
    assert "do NOT match" in changed.get_data(as_text=True)
    assert evidence_row(app, code)["integrity_status"] == "Failed"           # latest check decides

    # A correction supersedes the old hash; the old one stays on record.
    new_hash = hashlib.sha256(SAMPLE + b"!").hexdigest()
    assert client.post(f"/evidence/{code}/hash/correct", data={
        "method": "manual", "hash_value": new_hash, "notes": "Re-acquired image",
        "reason": "Original acquisition was incomplete"}).status_code == 302
    with app.app_context():
        assert query_value("SELECT COUNT(*) FROM evidence_hashes h JOIN evidence e ON e.evidence_id = h.evidence_id "
                           "WHERE e.evidence_code = %s", (code,)) == 2
        actions = {r["action"] for r in query_all("SELECT action FROM audit_logs WHERE entity_ref = %s", (code,))}
    assert {"hash.record", "hash.verify", "hash.correct"} <= actions
    assert evidence_row(app, code)["integrity_status"] == "Pending"          # new reference not yet checked


def test_custody_transfers_and_correction(app, client, setup_item):
    code, custodian, lead, location = setup_item["code"], setup_item["custodian"], setup_item["lead"], setup_item["location_id"]
    login(client, custodian["username"], custodian["password"])
    item = evidence_row(app, code)
    assert item["current_status"] == "In Transit"

    form = {"action": "Received", "to_user_id": str(custodian["user_id"]), "location_id": str(location),
            "condition": "Sealed, intact", "reason": "Arrived at the lab", "confirm": "y",
            "expected_custodian_id": str(custodian["user_id"])}
    assert client.post(f"/custody/{code}/transfer", data=form).status_code == 302
    item = evidence_row(app, code)
    assert (item["current_status"], item["current_location_id"]) == ("In Storage", location)

    # The same (now stale) form again: the item is no longer In Transit, so 'Received' isn't offered
    assert client.post(f"/custody/{code}/transfer", data=form).status_code == 200
    # A stale expected custodian is refused by the procedure
    stale = dict(form, action="Checked Out", to_user_id=str(lead["user_id"]), expected_custodian_id=str(lead["user_id"]))
    assert "Custodian changed" in client.post(f"/custody/{code}/transfer", data=stale).get_data(as_text=True)

    # Check out to the lead investigator, who then records Examined, but may not Store it
    out = dict(form, action="Checked Out", to_user_id=str(lead["user_id"]), reason="For examination")
    assert client.post(f"/custody/{code}/transfer", data=out).status_code == 302
    client.post("/logout")
    login(client, lead["username"], lead["password"])
    examined = dict(form, action="Examined", to_user_id=str(lead["user_id"]), expected_custodian_id=str(lead["user_id"]),
                    location_id="0", location_note="Examination bench", reason="Examination started")
    assert client.post(f"/custody/{code}/transfer", data=examined).status_code == 302
    assert evidence_row(app, code)["current_status"] == "Under Examination"
    stored = dict(examined, action="Stored", location_id=str(location))
    assert client.post(f"/custody/{code}/transfer", data=stored).status_code == 200       # not offered to investigators
    client.post("/logout")

    # The custodian corrects the latest entry; the original stays unchanged
    login(client, custodian["username"], custodian["password"])
    with app.app_context():
        latest = query_one("SELECT custody_id, location_note FROM chain_of_custody WHERE evidence_id = %s "
                           "ORDER BY custody_id DESC LIMIT 1", (item["evidence_id"],))
    r = client.post(f"/custody/{code}/entries/{latest['custody_id']}/correct", data={
        "to_user_id": str(lead["user_id"]), "location_id": "0", "location_note": "Examination Lab 1",
        "condition": "Seal opened for examination", "reason": "The bench was in Lab 1, not unspecified"})
    assert r.status_code == 302
    with app.app_context():
        assert query_value("SELECT location_note FROM chain_of_custody WHERE custody_id = %s",
                           (latest["custody_id"],)) == latest["location_note"]                  # untouched
        assert query_value("SELECT COUNT(*) FROM chain_of_custody WHERE corrects_custody_id = %s",
                           (latest["custody_id"],)) == 1
