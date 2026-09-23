# FORGE-X — Database

MySQL 8.0+ DDL/DML/advanced-SQL scripts, numbered in execution order.

| File | Purpose | Status |
|---|---|---|
| 01_create_database.sql | Database creation, charset/collation | ✅ |
| 02_tables.sql | Core tables (21 tables, full schema) | ✅ |
| 03_constraints.sql | Explicit CHECK constraints + verification queries | ✅ |
| 04_indexes.sql | 9 explicit indexes + documentation of auto-generated ones | ✅ |
| 05_views.sql | 5 views (vw_active_cases, vw_evidence_custody, vw_investigator_workload, vw_case_summary, vw_evidence_integrity) | ✅ |
| 06_functions.sql | 5 stored functions | ✅ |
| 07_procedures.sql | 6 stored procedures, incl. sp_transfer_evidence | ✅ |
| 08_triggers.sql | 5 triggers + 2 schema extensions | ✅ |
| 09_seed_data.sql | Realistic demo data (30 evidence, 76 custody records, 5 cases, etc.) | ✅ |
| 10_advanced_queries.sql | JOINs, GROUP BY/HAVING, subqueries, CTEs, window functions | ⏳ upcoming |
| 11_test_queries.sql | Constraint, FK, and validation test suite | ✅ |

## Loading order

```bash
mysql -u root --default-character-set=utf8mb4 < 01_create_database.sql
mysql -u root --default-character-set=utf8mb4 < 02_tables.sql
mysql -u root --default-character-set=utf8mb4 < 03_constraints.sql
mysql -u root --default-character-set=utf8mb4 < 04_indexes.sql
mysql -u root --default-character-set=utf8mb4 forge_x < 09_seed_data.sql
mysql -u root --default-character-set=utf8mb4 forge_x < 08_triggers.sql
mysql -u root --default-character-set=utf8mb4 forge_x < 06_functions.sql
mysql -u root --default-character-set=utf8mb4 forge_x < 05_views.sql
mysql -u root --default-character-set=utf8mb4 forge_x < 07_procedures.sql
```

**Always pass `--default-character-set=utf8mb4`** when loading any of these
files via the `mysql` CLI. Without it, the client defaults to `latin1`
for `character_set_client`, and any non-ASCII byte in the file — an
em dash, a curly quote, an accented name — gets silently
double-encoded (mojibake) at `INSERT`/`CREATE` time, even though the
table itself is correctly `utf8mb4`. This was discovered and fixed
during Step 6 backend integration testing (a stored procedure's
`SIGNAL` message and two seed report titles were corrupted this way).
Every file also now starts with `SET NAMES utf8mb4;` as a second,
session-level line of defense.

