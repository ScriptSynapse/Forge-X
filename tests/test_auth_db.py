"""Phase 6: the full authentication workflow against MySQL.

These tests ADD rows (pytest_* account requests and users, login attempts,
audit records). Append-only tables cannot be cleaned up by design, so they
only run when you opt in:

    set FORGE_X_DB_WRITE_TESTS=1        (Command Prompt)
    pytest tests/test_auth_db.py -v

Rebuild the demo data afterwards with database/install_all.sql if you like.
"""
import os
import uuid

import pytest

from app.db import query_one, query_value
from app.users import services as admin

pytestmark = [
    pytest.mark.db,
    pytest.mark.db_write,
    pytest.mark.skipif(os.getenv("FORGE_X_DB_WRITE_TESTS") != "1",
                       reason="set FORGE_X_DB_WRITE_TESTS=1 to run tests that write to MySQL"),
]

from tests.conftest import ROLE, login  # noqa: E402


def test_signup_creates_pending_request_that_cannot_log_in(app, client, db_available):
    suffix = uuid.uuid4().hex[:8]
    username, password = f"pytest_req_{suffix}", f"Signup-Passw0rd-{suffix}"
    response = client.post("/signup", data={
        "full_name": "Pytest Applicant", "email": f"{username}@example.test", "username": username,
        "password": password, "confirm": password, "reason": "automated test"})
    assert response.status_code == 302 and response.headers["Location"].endswith("/signup/submitted")
    with app.app_context():
        row = query_one("SELECT request_status, password_hash FROM account_requests WHERE username = %s", (username,))
    assert row["request_status"] == "Pending"
    assert row["password_hash"] != password          # stored hashed, never in plain text
    assert "Incorrect username or password" in login(client, username, password).get_data(as_text=True)


def test_signup_rejects_existing_username(app, client, admin_id):
    with app.app_context():
        existing = query_value("SELECT username FROM users WHERE user_id = %s", (admin_id,))
    response = client.post("/signup", data={
        "full_name": "Copy Cat", "email": f"cc_{uuid.uuid4().hex[:6]}@example.test", "username": existing,
        "password": "Another-Passw0rd-1", "confirm": "Another-Passw0rd-1"})
    assert response.status_code == 200
    assert "taken" in response.get_data(as_text=True)


def test_approved_request_can_log_in(app, client, admin_id):
    suffix = uuid.uuid4().hex[:8]
    username, password = f"pytest_ok_{suffix}", f"Approve-Passw0rd-{suffix}"
    client.post("/signup", data={"full_name": "Pytest Approved", "email": f"{username}@example.test",
                                 "username": username, "password": password, "confirm": password})
    with app.app_context():
        request_id = query_value("SELECT request_id FROM account_requests WHERE username = %s", (username,))
        user_id = admin.approve_request(request_id, ROLE["Investigator"], admin_id)
        assert query_value("SELECT password_hash FROM account_requests WHERE request_id = %s", (request_id,)) is None
    assert login(client, username, password).status_code == 302
    page = client.get("/account").get_data(as_text=True)
    assert username in page and "Investigator" in page
    assert user_id


def test_wrong_password_is_generic_and_recorded(app, client, make_user):
    user = make_user()
    page = login(client, user["username"], "Wrong-Passw0rd-000").get_data(as_text=True)
    assert "Incorrect username or password." in page
    with app.app_context():
        attempt = query_one("SELECT success, failure_reason FROM login_attempts WHERE username_or_email = %s "
                            "ORDER BY attempt_id DESC LIMIT 1", (user["username"],))
    assert attempt == {"success": 0, "failure_reason": "invalid_credentials"}


def test_rate_limit_after_five_failures(client, make_user):
    user = make_user()
    for _ in range(5):
        login(client, user["username"], "Wrong-Passw0rd-000")
    response = login(client, user["username"], user["password"])   # even the right password
    assert response.status_code == 429
    assert "Too many failed attempts" in response.get_data(as_text=True)


def test_logout_invalidates_a_copied_session_cookie(client, make_user):
    user = make_user()
    assert login(client, user["username"], user["password"]).status_code == 302
    stolen = client.get_cookie("forge_x_session").value
    client.post("/logout")
    client.set_cookie("forge_x_session", stolen)            # replay the old cookie
    response = client.get("/account")
    assert response.status_code == 302 and "/login" in response.headers["Location"]


def test_deactivated_account_cannot_log_in(app, client, make_user, admin_id):
    user = make_user()
    with app.app_context():
        admin.set_active(user["user_id"], False, admin_id)
    assert "Incorrect username or password" in login(client, user["username"], user["password"]).get_data(as_text=True)


def test_non_admin_is_denied_and_audited(app, client, make_user):
    user = make_user("Investigator")
    login(client, user["username"], user["password"])
    assert client.get("/admin/users").status_code == 403
    with app.app_context():
        outcome = query_value("SELECT outcome FROM audit_logs WHERE action = 'access.denied' AND entity_ref = %s "
                              "ORDER BY audit_id DESC LIMIT 1", (user["username"],))
    assert outcome == "Denied"


def test_admin_cannot_change_own_roles(app, client, make_user):
    me = make_user("Administrator")
    login(client, me["username"], me["password"])
    client.post(f"/admin/users/{me['user_id']}/roles", data={"role_id": ROLE["Investigator"]})
    with app.app_context():
        roles = query_value("SELECT COUNT(*) FROM user_roles WHERE user_id = %s", (me["user_id"],))
    assert roles == 1


def test_temporary_password_forces_a_change(client, make_user):
    user = make_user(must_change=True)
    response = login(client, user["username"], user["password"])
    assert response.status_code == 302
    assert client.get("/account").headers["Location"].endswith("/account/password")
    new_password = "Brand-New-Passw0rd-77"
    response = client.post("/account/password", data={
        "current_password": user["password"], "new_password": new_password, "confirm": new_password})
    assert response.status_code == 302
    assert client.get("/account").status_code == 200
