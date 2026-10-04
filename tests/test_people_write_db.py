"""Editing people's details and deleting empty cases, end to end. ADDS
records to MySQL, so it only runs with FORGE_X_DB_WRITE_TESTS=1."""
import os
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


def test_admin_edits_a_users_details(app, client, make_user):
    admin, person, other = make_user("Administrator"), make_user("Investigator"), make_user("Investigator")
    login(client, admin["username"], admin["password"])
    new_name = f"pytest_renamed_{uuid.uuid4().hex[:6]}"
    form = {"full_name": "Pytest Renamed Person", "email": f"{new_name}@example.test", "username": new_name}
    assert client.post(f"/admin/users/{person['user_id']}/edit", data=form).status_code == 302
    with app.app_context():
        row = query_one("SELECT full_name, email, username FROM users WHERE user_id = %s", (person["user_id"],))
        assert row == {"full_name": "Pytest Renamed Person", "email": form["email"], "username": new_name}
        assert query_value("SELECT COUNT(*) FROM audit_logs WHERE action = 'user.update' AND entity_ref = %s",
                           (new_name,)) == 1
    taken = dict(form, username=other["username"])
    page = client.post(f"/admin/users/{person['user_id']}/edit", data=taken).get_data(as_text=True)
    assert "already used by another account" in page
    client.post("/logout")
    login(client, new_name, person["password"])          # the person logs in with the new username
    assert client.get("/dashboard").status_code == 200


def test_investigator_cannot_edit_people(client, make_user):
    investigator, person = make_user("Investigator"), make_user("Investigator")
    login(client, investigator["username"], investigator["password"])
    assert client.get(f"/admin/users/{person['user_id']}/edit").status_code == 403


def _new_case(client, lead_id, title="Pytest case to delete"):
    response = client.post("/cases/new", data={"title": title, "case_type_id": "1", "priority": "Low",
                                                "description": "Registered by mistake.", "lead_user_id": str(lead_id)})
    return response.headers["Location"].rsplit("/", 1)[-1]


def test_admin_deletes_an_empty_case_and_it_is_audited(app, client, make_user):
    admin, lead = make_user("Administrator"), make_user("Investigator")
    login(client, admin["username"], admin["password"])
    reference = _new_case(client, lead["user_id"])
    wrong = client.post(f"/cases/{reference}/delete", data={"reason": "Registered twice by mistake",
                                                             "confirm_reference": "FX-0000-0000"}, follow_redirects=True)
    assert "exactly to confirm" in wrong.get_data(as_text=True)
    response = client.post(f"/cases/{reference}/delete", data={"reason": "Registered twice by mistake",
                                                                "confirm_reference": reference})
    assert response.status_code == 302
    with app.app_context():
        assert query_value("SELECT COUNT(*) FROM cases WHERE case_reference = %s", (reference,)) == 0
        details = query_value("SELECT details FROM audit_logs WHERE action = 'case.delete' AND entity_ref = %s",
                              (reference,))
        assert "Registered twice by mistake" in details


def test_case_with_evidence_cannot_be_deleted(app, client, make_user):
    admin, lead = make_user("Administrator"), make_user("Investigator")
    login(client, admin["username"], admin["password"])
    reference = _new_case(client, lead["user_id"], "Pytest case with evidence")
    with app.app_context():
        case_id = query_value("SELECT case_id FROM cases WHERE case_reference = %s", (reference,))
    client.post("/evidence/new", data={"case_id": str(case_id), "evidence_type_id": "8", "description": "Pytest logs",
                                       "collection_site": "Server", "collected_at": "2026-10-01T09:00",
                                       "collected_by": str(admin["user_id"]), "collection_condition": "Sealed",
                                       "hash_source": "Computed"})
    page = client.post(f"/cases/{reference}/delete", data={"reason": "Trying to delete history",
                                                           "confirm_reference": reference}, follow_redirects=True)
    assert "can&#39;t be deleted" in page.get_data(as_text=True) or "can't be deleted" in page.get_data(as_text=True)
    with app.app_context():
        assert query_value("SELECT COUNT(*) FROM cases WHERE case_reference = %s", (reference,)) == 1


def test_investigator_cannot_delete_cases(client, make_user):
    admin, lead = make_user("Administrator"), make_user("Investigator")
    login(client, admin["username"], admin["password"])
    reference = _new_case(client, lead["user_id"])
    client.post("/logout")
    login(client, lead["username"], lead["password"])
    assert client.post(f"/cases/{reference}/delete", data={"reason": "Not my decision to make",
                                                           "confirm_reference": reference}).status_code == 403
