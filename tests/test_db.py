"""Phase 5: live MySQL connection. Needs the database from Phase 4 and the
forge_x_app account configured in .env. These tests change no data."""
import uuid

import pytest

from app.db import (EXPECTED_OBJECTS, BusinessRuleError, can_delete_audit_logs, call_proc,
                    query_one, query_value, transaction, triggers_active)

pytestmark = pytest.mark.db


def test_mysql_version_supports_check_constraints(db_available):
    assert db_available["version_tuple"] >= (8, 0, 16)


def test_connected_as_application_account_not_root(db_available):
    assert not db_available["current_user_name"].lower().startswith("root@")


def test_schema_objects_present(db_available):
    assert db_available["objects"] == EXPECTED_OBJECTS


def test_triggers_are_active(app, db_available):
    # The app account cannot list triggers (no TRIGGER privilege), so test one by behaviour.
    with app.app_context():
        before = query_value("SELECT COUNT(*) FROM hash_verifications")
        result = triggers_active()
        if result is None:
            pytest.skip("no evidence hash yet to run the trigger probe against (empty lab)")
        assert result is True
        assert query_value("SELECT COUNT(*) FROM hash_verifications") == before   # probe was rolled back


def test_session_time_zone(app, db_available):
    with app.app_context():
        assert query_value("SELECT @@session.time_zone") == app.config["DB_TIME_ZONE"]


def test_parameterized_query_and_injection_attempt(app, db_available):
    with app.app_context():
        row = query_one("SELECT role_name FROM roles WHERE role_name = %s", ("Administrator",))
        assert row == {"role_name": "Administrator"}
        # The classic injection string is treated as plain data, so it matches nothing.
        assert query_one("SELECT role_id FROM roles WHERE role_name = %s", ("' OR '1'='1",)) is None


def test_transaction_rolls_back_on_error(app, db_available):
    name = f"pytest-rollback-{uuid.uuid4().hex[:8]}"
    with app.app_context():
        with pytest.raises(RuntimeError):
            with transaction() as cur:
                cur.execute(
                    "INSERT INTO storage_locations (location_name, location_type) VALUES (%s, 'Other')",
                    (name,),
                )
                raise RuntimeError("simulated failure after the insert")
        assert query_one("SELECT location_id FROM storage_locations WHERE location_name = %s", (name,)) is None


def test_procedure_rule_becomes_business_rule_error(app, db_available):
    with app.app_context():
        with pytest.raises(BusinessRuleError, match="Case not found"):
            call_proc("sp_close_case", (0, "pytest check", 0))


def test_least_privilege_blocks_delete_on_audit_logs(app, db_available):
    with app.app_context():
        assert can_delete_audit_logs() is False


def test_healthz_ok(client, db_available):
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.get_json() == {"status": "ok", "database": "ok"}
