"""FORGE-X 2.0 Phase 3 against MySQL: migration 005 and the Evidence Vault columns. Read-only."""
import pytest

from app.access import Scope
from app.db import query_value
from app.evidence import services

pytestmark = pytest.mark.db

ADMIN = Scope({"user_id": 1, "roles": ["Administrator"]})


def test_migration_005_is_installed(app, db_available):
    with app.app_context():
        assert query_value("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() "
                           "AND TABLE_NAME = 'evidence_files'") == 1, "run database/migrations/005_evidence_files.sql"
        method_type = query_value("SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
                                  "AND TABLE_NAME = 'hash_verifications' AND COLUMN_NAME = 'method'")
        assert "'Stored file'" in method_type


def test_vault_columns_and_filters_match_sql(app, db_available):
    with app.app_context():
        with_file = services.list_evidence(ADMIN, services.EvidenceFilters(has_file="yes"), 1, 50)
        assert with_file.total == query_value("SELECT COUNT(*) FROM evidence_files")
        without = services.list_evidence(ADMIN, services.EvidenceFilters(has_file="no"), 1, 50)
        assert with_file.total + without.total == query_value("SELECT COUNT(*) FROM evidence")
        page = services.list_evidence(ADMIN, services.EvidenceFilters(), 1, 50)
        for row in page.items:
            expected = query_value("SELECT current_hash_value FROM v_evidence_integrity WHERE evidence_id = %s",
                                   (row["evidence_id"],))
            assert row["current_hash"] == expected
            assert row["exam_status"] in (None, "Pending", "In Progress", "Completed")


def test_migration_009_is_installed(app, db_available):
    with app.app_context():
        assert query_value("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() "
                           "AND TABLE_NAME = 'evidence_file_locations'") == 1, \
            "run database/migrations/009_evidence_file_locations.sql"
