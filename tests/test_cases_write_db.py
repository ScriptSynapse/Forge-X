"""Phase 8: the case workflow end to end. ADDS cases to MySQL, so it only
runs with FORGE_X_DB_WRITE_TESTS=1 (cases can never be deleted, by design)."""
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


def create_case(client, lead_id=None, title="Pytest suspicious login alerts"):
    data = {"title": title, "case_type_id": "5", "priority": "Medium",
            "description": "Automated test case created by pytest."}
    if lead_id:
        data["lead_user_id"] = str(lead_id)
    response = client.post("/cases/new", data=data)
    assert response.status_code == 302, response.get_data(as_text=True)[:500]
    return response.headers["Location"].rsplit("/", 1)[-1]


def test_admin_registers_case_with_chosen_lead(app, client, make_user):
    admin, lead = make_user("Administrator"), make_user("Investigator")
    login(client, admin["username"], admin["password"])
    reference = create_case(client, lead_id=lead["user_id"])
    assert re.fullmatch(r"FX-\d{4}-\d{4}", reference)
    with app.app_context():
        row = query_one("SELECT c.status, ci.user_id FROM cases c JOIN case_investigators ci "
                        "ON ci.case_id = c.case_id AND ci.is_lead WHERE c.case_reference = %s", (reference,))
        assert row == {"status": "Open", "user_id": lead["user_id"]}
        assert query_value("SELECT COUNT(*) FROM audit_logs WHERE action = 'case.create' AND entity_ref = %s",
                           (reference,)) == 1


def test_investigator_becomes_lead_of_own_case(app, client, make_user):
    inv, other = make_user("Investigator"), make_user("Investigator")
    login(client, inv["username"], inv["password"])
    reference = create_case(client, lead_id=other["user_id"])          # the lead field is ignored
    with app.app_context():
        lead = query_value("SELECT ci.user_id FROM cases c JOIN case_investigators ci ON ci.case_id = c.case_id "
                           "AND ci.is_lead WHERE c.case_reference = %s", (reference,))
    assert lead == inv["user_id"]


def test_edit_status_investigators_and_close(app, client, make_user):
    lead, helper = make_user("Investigator"), make_user("Investigator")
    login(client, lead["username"], lead["password"])
    reference = create_case(client)
    with app.app_context():
        row = query_one("SELECT case_id, updated_at FROM cases WHERE case_reference = %s", (reference,))
        case_id, updated = row["case_id"], row["updated_at"]

    # Edit (with the version token), then a stale edit is refused
    form = {"title": "Pytest edited title", "case_type_id": "5", "priority": "High",
            "description": "Automated test case, edited.", "version": updated.isoformat()}
    assert client.post(f"/cases/{reference}/edit", data=form).status_code == 302
    stale = client.post(f"/cases/{reference}/edit", data=dict(form, title="Lost update"))
    assert "changed by someone else" in stale.get_data(as_text=True)

    # Status, assign, make lead, remove
    client.post(f"/cases/{reference}/status", data={"status": "In Progress"})
    client.post(f"/cases/{reference}/investigators", data={"user_id": str(helper["user_id"])})
    with app.app_context():
        assert query_one("SELECT title, priority, status FROM cases WHERE case_id = %s", (case_id,)) == \
            {"title": "Pytest edited title", "priority": "High", "status": "In Progress"}
        assert query_value("SELECT COUNT(*) FROM case_investigators WHERE case_id = %s", (case_id,)) == 2
        actions = {r["action"] for r in query_all(
            "SELECT DISTINCT action FROM audit_logs WHERE entity_ref = %s", (reference,))}
    assert {"case.create", "case.update", "case.status", "case.assign_investigator"} <= actions

    client.post(f"/cases/{reference}/investigators/{helper['user_id']}/remove")
    with app.app_context():
        assert query_value("SELECT COUNT(*) FROM case_investigators WHERE case_id = %s", (case_id,)) == 1

    # Close, then everything is read-only
    response = client.post(f"/cases/{reference}/close", data={"summary": "Pytest closure summary.", "confirm": "y"})
    assert response.status_code == 302
    with app.app_context():
        assert query_value("SELECT status FROM cases WHERE case_id = %s", (case_id,)) == "Closed"
    assert client.get(f"/cases/{reference}/edit").status_code == 302       # bounced back: read-only
    assert "Closed cases are read-only" in client.get(f"/cases/{reference}").get_data(as_text=True)


def test_non_lead_investigator_cannot_change_case(app, client, make_user):
    lead, member = make_user("Investigator"), make_user("Investigator")
    login(client, lead["username"], lead["password"])
    reference = create_case(client)
    client.post(f"/cases/{reference}/investigators", data={"user_id": str(member["user_id"])})
    client.post("/logout")

    login(client, member["username"], member["password"])
    assert client.get(f"/cases/{reference}").status_code == 200            # can view
    assert client.get(f"/cases/{reference}/edit").status_code == 403       # can't edit
    assert client.post(f"/cases/{reference}/status", data={"status": "On Hold"}).status_code == 403


def test_unassigned_investigator_gets_404(app, client, make_user):
    lead, outsider = make_user("Investigator"), make_user("Investigator")
    login(client, lead["username"], lead["password"])
    reference = create_case(client)
    client.post("/logout")
    login(client, outsider["username"], outsider["password"])
    assert client.get(f"/cases/{reference}").status_code == 404


# ---------------------------------------------------------------------------
# FORGE-X 2.0 Phase 2: due dates and notes, end to end
# ---------------------------------------------------------------------------
def test_due_date_notes_and_corrections(app, client, make_user):
    admin, lead, outsider = make_user("Administrator"), make_user("Investigator"), make_user("Investigator")
    login(client, admin["username"], admin["password"])
    reference = client.post("/cases/new", data={"title": "Pytest notes case", "case_type_id": "1", "priority": "High",
                                                "description": "Phase 2 notes and due dates.",
                                                "lead_user_id": str(lead["user_id"]), "due_date": "2099-12-31"}
                            ).headers["Location"].rsplit("/", 1)[-1]
    with app.app_context():
        case_id = query_value("SELECT case_id FROM cases WHERE case_reference = %s", (reference,))
        assert str(query_value("SELECT due_date FROM cases WHERE case_id = %s", (case_id,))) == "2099-12-31"
    client.post("/logout")

    login(client, lead["username"], lead["password"])
    assert client.post(f"/cases/{reference}/notes", data={"note_text": "Spoke to the IT manager",
                                                          "reference": "TICKET-1"}).status_code == 302
    with app.app_context():
        first = query_value("SELECT MAX(note_id) FROM case_notes WHERE case_id = %s", (case_id,))
    client.post(f"/cases/{reference}/notes", data={"note_text": "Correction: the deputy IT manager",
                                                   "corrects_note_id": str(first)})
    page = client.get(f"/cases/{reference}?tab=notes").get_data(as_text=True)
    assert f"Corrected by #{first + 1}" in page or "Corrected by #" in page
    client.post("/logout")

    login(client, outsider["username"], outsider["password"])
    assert client.post(f"/cases/{reference}/notes", data={"note_text": "Not my case"}).status_code == 404
    with app.app_context():
        assert query_value("SELECT COUNT(*) FROM case_notes WHERE case_id = %s", (case_id,)) == 2
        assert query_value("SELECT COUNT(*) FROM audit_logs WHERE action = 'case.note' AND entity_ref = %s",
                           (reference,)) == 2
