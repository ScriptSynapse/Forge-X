"""Phase 10: custody queries against MySQL. Read-only (SELECT only)."""
import pytest

from app.access import Scope
from app.custody import services
from app.db import query_value

pytestmark = pytest.mark.db

ADMIN = {"user_id": 1, "roles": ["Administrator"]}


def test_custody_log_matches_sql(app, db_available):
    with app.app_context():
        page = services.custody_log(Scope(ADMIN), services.CustodyFilters(), 1, 20)
        # FORGE-X 2.0 Phase 4: the log shows custody entries AND integrity checks.
        assert page.total == query_value("SELECT (SELECT COUNT(*) FROM chain_of_custody) "
                                         "+ (SELECT COUNT(*) FROM hash_verifications)")
        checks = services.custody_log(Scope(ADMIN), services.CustodyFilters(action="Integrity check"), 1, 20)
        assert checks.total == query_value("SELECT COUNT(*) FROM hash_verifications")
        collected = services.custody_log(Scope(ADMIN), services.CustodyFilters(action="Collected"), 1, 20)
        assert collected.total == query_value("SELECT COUNT(*) FROM chain_of_custody WHERE action = 'Collected'")


def test_out_of_storage_matches_dashboard_rule(app, db_available):
    with app.app_context():
        rows = services.out_of_storage(Scope(ADMIN))
        assert len(rows) == query_value(
            "SELECT COUNT(*) FROM evidence WHERE current_status IN ('Checked Out', 'In Transit')")


def test_every_evidence_item_has_a_collected_entry_first(app, db_available):
    with app.app_context():
        bad = query_value(
            """SELECT COUNT(*) FROM evidence e WHERE NOT EXISTS (
                 SELECT 1 FROM chain_of_custody c WHERE c.evidence_id = e.evidence_id AND c.action = 'Collected'
                 AND c.occurred_at = (SELECT MIN(c2.occurred_at) FROM chain_of_custody c2 WHERE c2.evidence_id = e.evidence_id))""")
        assert bad == 0



def test_migration_006_and_export_entries_keep_custody_consistent(app, db_available):
    with app.app_context():
        column = query_value("SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
                             "AND TABLE_NAME = 'chain_of_custody' AND COLUMN_NAME = 'action'")
        assert "'Exported'" in column, "run database/migrations/006_custody_exported.sql"
        # An export never changes who holds the original or where it is.
        assert query_value("SELECT COUNT(*) FROM chain_of_custody WHERE action = 'Exported' "
                           "AND NOT (from_custodian_id <=> to_custodian_id)") == 0


def test_oldest_first_is_chronological(app, db_available):
    with app.app_context():
        rows = services.custody_log(Scope(ADMIN), services.CustodyFilters(order="oldest"), 1, 50).items
        times = [r["occurred_at"] for r in rows]
        assert times == sorted(times)
