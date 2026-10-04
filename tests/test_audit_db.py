"""Phase 12: audit-log and user-administration queries against MySQL. Read-only."""
import pytest

from app.audit_logs import services as audit_logs
from app.db import query_value
from app.users import services as users

pytestmark = pytest.mark.db


def test_timeline_contains_every_audit_and_login_row(app, db_available):
    with app.app_context():
        page = audit_logs.list_events(audit_logs.AuditFilters(), 1, 20)
        assert page.total == query_value("SELECT (SELECT COUNT(*) FROM audit_logs) + (SELECT COUNT(*) FROM login_attempts)")


def test_outcome_filter_and_summary(app, db_available):
    with app.app_context():
        failures = audit_logs.list_events(audit_logs.AuditFilters(outcome="Failure"), 1, 20)
        expected = query_value("SELECT (SELECT COUNT(*) FROM audit_logs WHERE outcome = 'Failure') "
                               "+ (SELECT COUNT(*) FROM login_attempts WHERE success = FALSE)")
        assert failures.total == expected
        assert int(audit_logs.summary(audit_logs.AuditFilters())["failures"]) == expected


def test_security_queries_run(app, db_available):
    with app.app_context():
        locked = audit_logs.locked_accounts()
        by_identifier, by_ip = audit_logs.repeated_failures()
        assert all(int(r["failures"]) >= app.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"] for r in locked)
        assert all(int(r["failures"]) >= 3 for r in by_identifier + by_ip)
        audit_logs.denied_actions()


def test_user_list_and_inactive_filter(app, db_available):
    with app.app_context():
        assert users.list_users(users.UserFilters(), 1, 20).total == query_value("SELECT COUNT(*) FROM users")
        inactive = users.list_users(users.UserFilters(inactive=True), 1, 100)
        assert inactive.total == query_value(
            "SELECT COUNT(*) FROM users WHERE account_status = 'Deactivated' OR last_login_at IS NULL "
            "OR last_login_at < NOW() - INTERVAL 30 DAY")
        users.reviewed_requests()
