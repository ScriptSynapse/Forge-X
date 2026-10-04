"""Phase 14: the application's MySQL account can do exactly what
database/app_user.sql grants, and nothing more. Read-only and harmless:

* writes use WHERE 1 = 0, so they match no rows even if a privilege were
  (wrongly) present; MySQL still checks the privilege first;
* DDL probes name a table that does not exist, so nothing real can be dropped.
"""
import pytest

from app.db import DatabaseError, execute

pytestmark = pytest.mark.db

DENIED = {1142, 1044, 1227, 1410}       # table / database / global privilege errors
APPEND_ONLY = ("audit_logs", "login_attempts", "chain_of_custody", "evidence_hashes", "hash_verifications",
               "report_versions", "examination_evidence", "report_examinations")
NO_DELETE = ("users", "evidence", "examinations", "forensic_reports", "account_requests",
             "storage_locations", "reference_sequences") + APPEND_ONLY
# Granted UPDATE, with a column to use in the harmless control statement.
UPDATABLE = {"users": "created_at", "cases": "created_at", "evidence": "registered_at",
             "examinations": "created_at", "forensic_reports": "created_at", "storage_locations": "description"}


def denied(sql):
    try:
        execute(sql)
    except DatabaseError as err:
        if err.errno in DENIED:
            return True
        raise
    return False


@pytest.mark.parametrize("table", APPEND_ONLY)
def test_append_only_tables_cannot_be_updated(app, db_available, table):
    column = {"audit_logs": "details", "login_attempts": "ip_address", "chain_of_custody": "reason",
              "evidence_hashes": "source_notes", "hash_verifications": "notes", "report_versions": "change_note",
              "examination_evidence": "linked_at", "report_examinations": "linked_at"}[table]
    with app.app_context():
        assert denied(f"UPDATE {table} SET {column} = {column} WHERE 1 = 0"), f"app account can UPDATE {table}"


@pytest.mark.parametrize("table", NO_DELETE)
def test_records_cannot_be_deleted(app, db_available, table):
    with app.app_context():
        assert denied(f"DELETE FROM {table} WHERE 1 = 0"), f"app account can DELETE from {table}"


def test_cases_can_be_deleted_but_only_empty_ones(app, db_available):
    """DELETE on `cases` is granted (empty cases registered by mistake). Cases
    with evidence, examinations or reports stay protected by RESTRICT foreign
    keys, which test_cases_write_db checks end to end."""
    with app.app_context():
        assert not denied("DELETE FROM cases WHERE 1 = 0")


@pytest.mark.parametrize("table,column", UPDATABLE.items())
def test_probe_is_valid_where_update_is_granted(app, db_available, table, column):
    """Control: the same kind of statement succeeds where app_user.sql grants it,
    so the refusals above really are privilege refusals."""
    with app.app_context():
        assert not denied(f"UPDATE {table} SET {column} = {column} WHERE 1 = 0")


@pytest.mark.parametrize("sql", [
    "CREATE TABLE pytest_privilege_probe (x INT)",
    "DROP TABLE pytest_table_that_does_not_exist",
    "CREATE USER 'pytest_probe'@'localhost' IDENTIFIED BY 'Probe#2026probe'",
    "GRANT SELECT ON forge_x_db.* TO 'forge_x_app'@'localhost'",
])
def test_no_ddl_or_account_management(app, db_available, sql):
    with app.app_context():
        assert denied(sql), f"app account was allowed: {sql}"
