"""Phase 9: evidence workflow end to end. ADDS evidence, cases and locations
to MySQL, so it only runs with FORGE_X_DB_WRITE_TESTS=1."""
import os
import re
import uuid

import pytest

from app.db import query_one, query_value
from tests.conftest import login

pytestmark = [
    pytest.mark.db,
    pytest.mark.db_write,
    pytest.mark.skipif(os.getenv("FORGE_X_DB_WRITE_TESTS") != "1",
                       reason="set FORGE_X_DB_WRITE_TESTS=1 to run tests that write to MySQL"),
]


def new_case(client, lead_id):
    response = client.post("/cases/new", data={"title": "Pytest evidence case", "case_type_id": "5",
                                                "priority": "Low", "description": "Case for evidence tests.",
                                                "lead_user_id": str(lead_id)})
    assert response.status_code == 302
    return response.headers["Location"].rsplit("/", 1)[-1]


def evidence_form(case_id, collector_id, **extra):
    data = {"case_id": str(case_id), "evidence_type_id": "8", "description": "Pytest log export",
            "collection_site": "Test server", "collected_at": "2026-10-01T09:30", "collected_by": str(collector_id),
            "collection_condition": "Exported to sealed USB", "seal_number": "FX-S-TEST",
            "original_hash": "ab" * 32, "hash_source": "Computed"}
    data.update(extra)
    return data


def test_custodian_registers_evidence_with_hash(app, client, make_user):
    admin, lead, custodian = make_user("Administrator"), make_user("Investigator"), make_user("Evidence Custodian")
    login(client, admin["username"], admin["password"])
    reference = new_case(client, lead["user_id"])
    client.post("/logout")
    with app.app_context():
        case_id = query_value("SELECT case_id FROM cases WHERE case_reference = %s", (reference,))

    login(client, custodian["username"], custodian["password"])
    response = client.post("/evidence/new", data=evidence_form(case_id, custodian["user_id"]))
    assert response.status_code == 302, response.get_data(as_text=True)[:400]
    code = response.headers["Location"].rsplit("/", 1)[-1]
    assert re.fullmatch(r"FX-EV-\d{4}-\d{5}", code)
    with app.app_context():
        item = query_one("SELECT evidence_id, current_status, current_custodian_id FROM evidence WHERE evidence_code = %s", (code,))
        assert item["current_status"] == "In Transit" and item["current_custodian_id"] == custodian["user_id"]
        first = query_one("SELECT action, from_custodian_id FROM chain_of_custody WHERE evidence_id = %s", (item["evidence_id"],))
        assert first == {"action": "Collected", "from_custodian_id": None}
        assert query_value("SELECT hash_value FROM evidence_hashes WHERE evidence_id = %s", (item["evidence_id"],)) == "ab" * 32
        assert query_value("SELECT COUNT(*) FROM audit_logs WHERE action = 'evidence.register' AND entity_ref = %s", (code,)) == 1

    # Edit, then a stale edit is refused
    with app.app_context():
        updated = query_value("SELECT updated_at FROM evidence WHERE evidence_code = %s", (code,))
    form = {"description": "Pytest log export (edited)", "source_details": "CSV", "size_bytes": "2048",
            "collection_site": "Test server room", "version": updated.isoformat()}
    assert client.post(f"/evidence/{code}/edit", data=form).status_code == 302
    assert "changed by someone else" in client.post(f"/evidence/{code}/edit", data=dict(form, description="Lost")).get_data(as_text=True)
    with app.app_context():
        assert query_value("SELECT description FROM evidence WHERE evidence_code = %s", (code,)) == "Pytest log export (edited)"


def test_future_collection_time_is_refused(app, client, make_user):
    admin, lead = make_user("Administrator"), make_user("Investigator")
    login(client, admin["username"], admin["password"])
    reference = new_case(client, lead["user_id"])
    with app.app_context():
        case_id = query_value("SELECT case_id FROM cases WHERE case_reference = %s", (reference,))
    page = client.post("/evidence/new", data=evidence_form(case_id, admin["user_id"], collected_at="2099-01-01T10:00"))
    assert "can't be in the future" in page.get_data(as_text=True)


def test_investigator_cannot_register_for_unassigned_case(app, client, make_user):
    admin, lead, outsider = make_user("Administrator"), make_user("Investigator"), make_user("Investigator")
    login(client, admin["username"], admin["password"])
    reference = new_case(client, lead["user_id"])
    client.post("/logout")
    with app.app_context():
        case_id = query_value("SELECT case_id FROM cases WHERE case_reference = %s", (reference,))
        before = query_value("SELECT COUNT(*) FROM evidence")
    login(client, outsider["username"], outsider["password"])
    response = client.post("/evidence/new", data=evidence_form(case_id, outsider["user_id"]))
    assert response.status_code == 200                      # refused: the case isn't a valid choice for them
    with app.app_context():
        assert query_value("SELECT COUNT(*) FROM evidence") == before


def test_admin_manages_storage_locations(app, client, make_user):
    admin = make_user("Administrator")
    login(client, admin["username"], admin["password"])
    name = f"Pytest Locker {uuid.uuid4().hex[:6]}"
    assert client.post("/admin/locations", data={"location_name": name, "location_type": "Evidence Room"}).status_code == 302
    assert "already exists" in client.post("/admin/locations", data={"location_name": name, "location_type": "Vault"}).get_data(as_text=True)
    with app.app_context():
        location_id = query_value("SELECT location_id FROM storage_locations WHERE location_name = %s", (name,))
    client.post(f"/admin/locations/{location_id}/status", data={"action": "deactivate"})
    with app.app_context():
        assert query_value("SELECT is_active FROM storage_locations WHERE location_id = %s", (location_id,)) == 0
        assert query_value("SELECT COUNT(*) FROM audit_logs WHERE entity_type = 'Storage location' AND entity_ref = %s",
                           (name,)) == 2
