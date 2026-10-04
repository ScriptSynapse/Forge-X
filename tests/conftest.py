"""Shared pytest fixtures."""
import uuid

import pytest

from app import create_app
from app.config import TestingConfig
from app.db import DatabaseError, check_connection


@pytest.fixture
def app():
    return create_app(TestingConfig())


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(scope="session")
def db_available():
    """Skip database tests (with the reason shown) when MySQL is unreachable.
    A skipped test is NOT a passed test: Phase 5 is only verified when the
    tests in test_db.py show as passed."""
    app = create_app(TestingConfig())
    with app.app_context():
        try:
            return check_connection()
        except DatabaseError as err:
            pytest.skip(f"MySQL not reachable ({err.detail or err}). Check .env and the MySQL service.")


# ---------------------------------------------------------------------------
# Helpers for the opt-in tests that write to MySQL (FORGE_X_DB_WRITE_TESTS=1)
# ---------------------------------------------------------------------------
ROLE = {"Administrator": 1, "Investigator": 2, "Evidence Custodian": 3, "Read-Only Auditor": 4}


def login(client, username, password):
    return client.post("/login", data={"login": username, "password": password})


def first_admin_id():
    """The lowest-numbered active administrator (e.g. the account made by
    flask create-admin). Call inside an app context."""
    from app.db import query_value
    return query_value(
        "SELECT MIN(u.user_id) FROM users u JOIN user_roles ur ON ur.user_id = u.user_id "
        "JOIN roles r ON r.role_id = ur.role_id WHERE r.role_name = 'Administrator' AND u.account_status = 'Active'")


@pytest.fixture
def admin_id(app, db_available):
    with app.app_context():
        found = first_admin_id()
    if found is None:
        pytest.skip("no active administrator yet: run flask --app run create-admin <username>")
    return found


@pytest.fixture
def demo_data(app, db_available):
    """Skip tests that check specific demonstration records when the demo
    data (database/install_demo.sql) isn't installed."""
    from app.db import query_value
    with app.app_context():
        if not query_value("SELECT COUNT(*) FROM cases WHERE case_reference = 'FX-2026-0022'"):
            pytest.skip("demo data not installed (database/install_demo.sql)")


def sign_in_as(app, client, user_id):
    """Create a valid session for an existing user without needing a password.
    Skips when that user still has a temporary password."""
    from app.db import query_one
    with app.app_context():
        row = query_one("SELECT session_version, must_change_password FROM users WHERE user_id = %s", (user_id,))
    if row is None or row["must_change_password"]:
        pytest.skip("that account has a temporary password; set one with flask set-password")
    with client.session_transaction() as session:
        session["uid"], session["sv"] = user_id, row["session_version"]


@pytest.fixture
def make_user(app, admin_id):
    """Create an active user directly (as the first administrator) and return its credentials."""
    from app.users import services as admin
    ADMIN_ID = admin_id

    def _make(role="Investigator", must_change=False):
        suffix = uuid.uuid4().hex[:8]
        username, password = f"pytest_{suffix}", f"Test-Passw0rd-{suffix}"
        with app.app_context():
            user_id = admin.create_user(f"Pytest User {suffix}", f"{username}@example.test", username,
                                        ROLE[role], password, must_change, ADMIN_ID)
        return {"user_id": user_id, "username": username, "password": password, "full_name": f"Pytest User {suffix}"}
    return _make
