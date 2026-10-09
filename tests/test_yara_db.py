"""FORGE-X 2.0 Phase 7 against MySQL: migration 008. Read-only."""
import pytest

from app.db import query_value

pytestmark = pytest.mark.db


def test_migration_008_is_installed(app, db_available):
    with app.app_context():
        for table in ("yara_rules", "yara_rule_versions", "yara_rule_cases", "yara_scans", "yara_scan_rules", "yara_matches"):
            assert query_value("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() "
                               "AND TABLE_NAME = %s", (table,)) == 1, f"{table} missing: run database/migrations/008_yara.sql"
        entity = query_value("SELECT COLUMN_TYPE FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
                             "AND TABLE_NAME = 'audit_logs' AND COLUMN_NAME = 'entity_type'")
        assert "'YARA rule'" in entity
