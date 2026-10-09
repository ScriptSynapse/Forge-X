"""FORGE-X 2.0 Phase 6: the live database has exactly the structure database/schema.sql
describes. A failure here usually means a migration (database/migrations/) wasn't run.
Read-only (information_schema only)."""
import pathlib
import re

import pytest

from app.db import query_all

pytestmark = pytest.mark.db

SCHEMA = (pathlib.Path(__file__).resolve().parent.parent / "database" / "schema.sql").read_text(encoding="utf-8")
NOT_COLUMNS = ("PRIMARY", "UNIQUE", "KEY", "INDEX", "CONSTRAINT", "--", "FOREIGN", "CHECK")


def _expected():
    tables = {}
    for name, body in re.findall(r"CREATE TABLE (\w+) \((.*?)\n\) ENGINE", SCHEMA, re.S):
        cols = set()
        for line in body.splitlines():
            stripped = line.strip()
            if stripped and not stripped.startswith(NOT_COLUMNS):
                match = re.match(r"([a-z_]+)\s", stripped)
                if match:
                    cols.add(match.group(1))
        tables[name] = cols
    checks = set(re.findall(r"CONSTRAINT (chk_\w+)", SCHEMA))
    return tables, checks


def test_every_table_and_column_exists(app, db_available):
    tables, _ = _expected()
    with app.app_context():
        rows = query_all("SELECT TABLE_NAME AS t, COLUMN_NAME AS c FROM information_schema.COLUMNS "
                         "WHERE TABLE_SCHEMA = DATABASE()")
    live = {}
    for row in rows:
        live.setdefault(row["t"], set()).add(row["c"])
    missing_tables = sorted(set(tables) - set(live))
    assert not missing_tables, f"tables missing (run the migrations in database/migrations/): {missing_tables}"
    missing_columns = {t: sorted(cols - live[t]) for t, cols in tables.items() if cols - live[t]}
    assert not missing_columns, f"columns missing (run the migrations in database/migrations/): {missing_columns}"


def test_every_check_constraint_exists(app, db_available):
    _, checks = _expected()
    with app.app_context():
        live = {r["n"] for r in query_all("SELECT CONSTRAINT_NAME AS n FROM information_schema.CHECK_CONSTRAINTS "
                                          "WHERE CONSTRAINT_SCHEMA = DATABASE()")}
    assert not checks - live, f"CHECK constraints missing: {sorted(checks - live)}"
