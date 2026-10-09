"""FORGE-X 2.0 Phase 5 against MySQL: migration 007 and the examination
review trigger. Read-only: every probe runs in a transaction that is
always rolled back."""
import pytest

from app.db import BusinessRuleError, query_one, query_value, transaction

pytestmark = pytest.mark.db


class _Rollback(Exception):
    pass


def _probe(sql, params):
    """Run one statement in a transaction that never commits; return the refusal."""
    with pytest.raises(BusinessRuleError) as refused:
        try:
            with transaction() as cur:
                cur.execute(sql, params)
                raise _Rollback()
        except _Rollback:
            pytest.fail(f"MySQL accepted: {sql}")
    return str(refused.value)


def test_migration_007_is_installed(app, db_available):
    with app.app_context():
        status = query_value("SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
                             "AND TABLE_NAME = 'examinations' AND COLUMN_NAME = 'status'")
        assert "'Under Review'" in status, "run database/migrations/007_examination_review_artifacts.sql"
        for column in ("conclusion", "submitted_at", "reviewed_by", "reviewed_at", "review_note"):
            assert query_value("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
                               "AND TABLE_NAME = 'examinations' AND COLUMN_NAME = %s", (column,)) == 1, column
        assert query_value("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() "
                           "AND TABLE_NAME = 'examination_artifacts'") == 1


def test_completed_examinations_are_final(app, db_available):
    with app.app_context():
        done = query_one("SELECT examination_id FROM examinations WHERE status = 'Completed' LIMIT 1")
        if done is None:
            pytest.skip("no completed examination yet")
        message = _probe("UPDATE examinations SET limitations = CONCAT(COALESCE(limitations, ''), ' x') "
                         "WHERE examination_id = %s", (done["examination_id"],))
        assert "cannot be changed" in message


def test_completion_requires_an_independent_review(app, db_available):
    with app.app_context():
        open_exam = query_one("SELECT examination_id FROM examinations WHERE status = 'In Progress' "
                              "AND tools_methods IS NOT NULL AND findings IS NOT NULL LIMIT 1")
        if open_exam is None:
            pytest.skip("no examination in progress with findings recorded")
        message = _probe("UPDATE examinations SET status = 'Completed', completed_at = NOW() WHERE examination_id = %s",
                         (open_exam["examination_id"],))
        assert "independent review" in message
