"""Phase 12: audit access and CSV export end to end. ADDS users and audit
rows to MySQL: runs only with FORGE_X_DB_WRITE_TESTS=1."""
import csv
import io
import os

import pytest

from app.db import query_value
from tests.conftest import login

pytestmark = [
    pytest.mark.db,
    pytest.mark.db_write,
    pytest.mark.skipif(os.getenv("FORGE_X_DB_WRITE_TESTS") != "1",
                       reason="set FORGE_X_DB_WRITE_TESTS=1 to run tests that write to MySQL"),
]


def test_auditor_reads_and_exports_investigator_is_denied(app, client, make_user):
    auditor, investigator = make_user("Read-Only Auditor"), make_user("Investigator")
    login(client, investigator["username"], investigator["password"])
    assert client.get("/audit-logs").status_code == 403
    client.post("/logout")

    login(client, auditor["username"], auditor["password"])
    page = client.get(f"/audit-logs?ref={investigator['username']}&outcome=Denied").get_data(as_text=True)
    assert "GET /audit-logs" in page                      # the refusal above was audited
    response = client.get("/audit-logs/export.csv?outcome=Denied")
    assert response.status_code == 200 and response.mimetype == "text/csv"
    rows = list(csv.reader(io.StringIO(response.get_data(as_text=True).lstrip("\ufeff"))))
    assert rows[0][:3] == ["occurred_at", "user_name", "action"] and all(r[5] == "Denied" for r in rows[1:])
    with app.app_context():
        assert query_value("SELECT COUNT(*) FROM audit_logs a JOIN users u ON u.user_id = a.user_id "
                           "WHERE a.action = 'audit.export' AND u.username = %s", (auditor["username"],)) == 1


def test_admin_finds_users_by_search(client, make_user):
    admin, target = make_user("Administrator"), make_user("Investigator")
    login(client, admin["username"], admin["password"])
    page = client.get(f"/admin/users?q={target['username']}").get_data(as_text=True)
    assert target["username"] in page and "Showing 1 to 1 of 1 users" in page
