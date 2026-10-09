"""FORGE-X 2.0 Phase 2 against MySQL: migration 004, custody tab, filters,
last activity and the case-notes triggers. Read-only: the trigger probe
runs inside a transaction that is always rolled back."""
import pytest

from app.access import Scope
from app.cases import services
from app.db import BusinessRuleError, query_one, query_value, transaction

pytestmark = pytest.mark.db

ADMIN = Scope({"user_id": 1, "roles": ["Administrator"]})


def test_migration_004_is_installed(app, db_available):
    with app.app_context():
        assert query_value("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() "
                           "AND TABLE_NAME = 'case_notes'") == 1, "run database/migrations/004_case_notes_and_due_date.sql"
        assert query_value("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
                           "AND TABLE_NAME = 'cases' AND COLUMN_NAME = 'due_date'") == 1


def test_case_filters_match_sql(app, db_available):
    with app.app_context():
        overdue = services.list_cases(ADMIN, services.CaseFilters(overdue=True), 1, 50)
        assert overdue.total == query_value("SELECT COUNT(*) FROM cases WHERE status <> 'Closed' AND due_date < CURDATE()")
        investigator = query_value("SELECT MIN(user_id) FROM case_investigators")
        if investigator:
            mine = services.list_cases(ADMIN, services.CaseFilters(investigator_id=investigator), 1, 50)
            assert mine.total == query_value("SELECT COUNT(DISTINCT case_id) FROM case_investigators WHERE user_id = %s",
                                             (investigator,))
        page = services.list_cases(ADMIN, services.CaseFilters(sort="-activity"), 1, 50)
        for row in page.items:                       # last activity is never earlier than the case's own update
            assert row["last_activity"] >= query_value("SELECT updated_at FROM cases WHERE case_id = %s", (row["case_id"],))


def test_case_custody_and_counts_match_sql(app, db_available):
    with app.app_context():
        case_id = query_value("SELECT e.case_id FROM evidence e GROUP BY e.case_id ORDER BY COUNT(*) DESC LIMIT 1")
        if case_id is None:
            pytest.skip("no evidence yet")
        expected = query_value("SELECT COUNT(*) FROM chain_of_custody coc JOIN evidence e ON e.evidence_id = coc.evidence_id "
                               "WHERE e.case_id = %s", (case_id,))
        assert len(services.case_custody(case_id, limit=10_000)) == expected
        counts = services.tab_counts(case_id)
        assert counts["custody"] == expected
        assert counts["notes"] == query_value("SELECT COUNT(*) FROM case_notes WHERE case_id = %s", (case_id,))


class _Rollback(Exception):
    pass


def test_trigger_refuses_notes_on_a_closed_case(app, db_available):
    with app.app_context():
        closed = query_one("SELECT case_id FROM cases WHERE status = 'Closed' LIMIT 1")
        author = query_value("SELECT MIN(user_id) FROM users")
        if closed is None or author is None:
            pytest.skip("no closed case yet")
        with pytest.raises(BusinessRuleError, match="closed case"):
            try:
                with transaction() as cur:          # nothing is ever committed here
                    cur.execute("INSERT INTO case_notes (case_id, note_text, author_id) VALUES (%s, 'probe', %s)",
                                (closed["case_id"], author))
                    raise _Rollback()
            except _Rollback:
                pytest.fail("the trigger accepted a note on a closed case")
