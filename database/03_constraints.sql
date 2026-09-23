-- =====================================================================
-- FORGE-X : Forensic Operations, Records, Governance & Evidence Exchange
-- File   : 03_constraints.sql
-- Purpose: (A) Add explicit, named CHECK constraints for the four
--              domain-validity rules called out by name in the project
--              brief (case status, case priority, evidence integrity
--              status). (B) Provide an INFORMATION_SCHEMA-based
--              verification section that lists every PK / FK / UNIQUE /
--              CHECK constraint already defined inline in 02_tables.sql,
--              for documentation and viva reference.
-- Depends: 01_create_database.sql and 02_tables.sql must already have run.
--
-- WHY THESE CHECKS ARE "ADDITIONAL" RATHER THAN THE ONLY PROTECTION
--   cases.status, cases.priority and evidence.integrity_status are
--   already restricted to a closed set of values by their MySQL ENUM
--   type (declared in 02_tables.sql) — ENUM *is* a domain constraint.
--   The named CHECK constraints added below are deliberate
--   defense-in-depth: they document the valid-value business rule
--   explicitly and by name (so `SHOW CREATE TABLE` / INFORMATION_SCHEMA
--   surfaces a constraint literally called
--   chk_cases_status_valid_values, not just an implicit ENUM type),
--   and they demonstrate the CHECK constraint feature the brief asks
--   for directly, independent of the column's underlying type choice.
--
-- NOTE ON "evidence status"
--   The evidence table's status-like column is named integrity_status
--   (intact / compromised / under_verification) — there is no separate
--   generic "status" column on evidence itself (devices, examinations,
--   and reports each have their own distinctly-named status column).
--   Wherever this project's brief says "evidence status", it maps to
--   evidence.integrity_status.
-- =====================================================================

USE forge_x;

-- Defensive: ensures THIS session sends/receives utf8mb4 regardless of
-- how the client was invoked (protects against a classic gotcha: running
-- `mysql -u root < this_file.sql` without --default-character-set=utf8mb4
-- silently corrupts any non-ASCII literal in this file via latin1
-- misinterpretation at write time -- discovered and fixed during Step 6
-- backend integration testing).
SET NAMES utf8mb4;

-- =====================================================================
-- PART A — Explicit named CHECK constraints (domain validity)
-- =====================================================================

-- 1) Case status must use valid values
ALTER TABLE cases
    ADD CONSTRAINT chk_cases_status_valid_values
    CHECK (status IN ('open','under_investigation','pending_review','closed','archived','cold'));

-- 2) Case priority must use valid values
ALTER TABLE cases
    ADD CONSTRAINT chk_cases_priority_valid_values
    CHECK (priority IN ('low','medium','high','critical'));

-- 3) Evidence integrity status ("evidence status") must use valid values
ALTER TABLE evidence
    ADD CONSTRAINT chk_evidence_integrity_status_valid_values
    CHECK (integrity_status IN ('intact','compromised','under_verification'));

-- 4) Device status must use valid values (same pattern, extra coverage
--    beyond the four explicitly named examples, applied consistently)
ALTER TABLE devices
    ADD CONSTRAINT chk_devices_status_valid_values
    CHECK (device_status IN ('seized','in_lab','under_examination','returned','disposed','archived'));

SELECT 'Part A: explicit domain CHECK constraints added.' AS status;

-- =====================================================================
-- PART B — Constraint inventory (verification / documentation queries)
--   Run these to see every constraint MySQL is actually enforcing on
--   the forge_x schema — this is the "Show constraint definitions"
--   evidence requested at the end of this phase.
-- =====================================================================

-- B1. Every PRIMARY KEY (including composite keys) ------------------------
SELECT
    tc.TABLE_NAME,
    GROUP_CONCAT(kcu.COLUMN_NAME ORDER BY kcu.ORDINAL_POSITION SEPARATOR ', ') AS primary_key_columns,
    COUNT(*) AS key_column_count
FROM information_schema.TABLE_CONSTRAINTS tc
JOIN information_schema.KEY_COLUMN_USAGE kcu
    ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
   AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
   AND tc.TABLE_NAME = kcu.TABLE_NAME
WHERE tc.TABLE_SCHEMA = 'forge_x'
  AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
GROUP BY tc.TABLE_NAME
ORDER BY tc.TABLE_NAME;

-- B2. Every FOREIGN KEY, with its ON DELETE / ON UPDATE action ------------
SELECT
    kcu.CONSTRAINT_NAME,
    kcu.TABLE_NAME       AS child_table,
    kcu.COLUMN_NAME       AS child_column,
    kcu.REFERENCED_TABLE_NAME  AS parent_table,
    kcu.REFERENCED_COLUMN_NAME AS parent_column,
    rc.DELETE_RULE,
    rc.UPDATE_RULE
FROM information_schema.KEY_COLUMN_USAGE kcu
JOIN information_schema.REFERENTIAL_CONSTRAINTS rc
    ON kcu.CONSTRAINT_NAME = rc.CONSTRAINT_NAME
   AND kcu.TABLE_SCHEMA = rc.CONSTRAINT_SCHEMA
WHERE kcu.TABLE_SCHEMA = 'forge_x'
  AND kcu.REFERENCED_TABLE_NAME IS NOT NULL
ORDER BY kcu.TABLE_NAME, kcu.COLUMN_NAME;

-- B3. Every UNIQUE constraint (candidate keys) ----------------------------
SELECT
    tc.TABLE_NAME,
    tc.CONSTRAINT_NAME,
    GROUP_CONCAT(kcu.COLUMN_NAME ORDER BY kcu.ORDINAL_POSITION SEPARATOR ', ') AS unique_columns
FROM information_schema.TABLE_CONSTRAINTS tc
JOIN information_schema.KEY_COLUMN_USAGE kcu
    ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
   AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
   AND tc.TABLE_NAME = kcu.TABLE_NAME
WHERE tc.TABLE_SCHEMA = 'forge_x'
  AND tc.CONSTRAINT_TYPE = 'UNIQUE'
GROUP BY tc.TABLE_NAME, tc.CONSTRAINT_NAME
ORDER BY tc.TABLE_NAME;

-- B4. Every CHECK constraint, with its exact expression -------------------
SELECT
    tc.TABLE_NAME,
    cc.CONSTRAINT_NAME,
    cc.CHECK_CLAUSE
FROM information_schema.TABLE_CONSTRAINTS tc
JOIN information_schema.CHECK_CONSTRAINTS cc
    ON tc.CONSTRAINT_NAME = cc.CONSTRAINT_NAME
   AND tc.TABLE_SCHEMA = cc.CONSTRAINT_SCHEMA
WHERE tc.TABLE_SCHEMA = 'forge_x'
  AND tc.CONSTRAINT_TYPE = 'CHECK'
ORDER BY tc.TABLE_NAME, cc.CONSTRAINT_NAME;

-- B5. Every NOT NULL column, grouped by table (1 row per table) ----------
SELECT
    TABLE_NAME,
    COUNT(*) AS not_null_column_count,
    GROUP_CONCAT(COLUMN_NAME ORDER BY ORDINAL_POSITION SEPARATOR ', ') AS not_null_columns
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'forge_x'
  AND IS_NULLABLE = 'NO'
GROUP BY TABLE_NAME
ORDER BY TABLE_NAME;

-- B6. Every column carrying a DEFAULT value -------------------------------
SELECT
    TABLE_NAME,
    COLUMN_NAME,
    COLUMN_DEFAULT,
    DATA_TYPE
FROM information_schema.COLUMNS
WHERE TABLE_SCHEMA = 'forge_x'
  AND COLUMN_DEFAULT IS NOT NULL
ORDER BY TABLE_NAME, ORDINAL_POSITION;

-- B7. Composite-key tables specifically (2NF discussion reference) -------
SELECT
    tc.TABLE_NAME,
    GROUP_CONCAT(kcu.COLUMN_NAME ORDER BY kcu.ORDINAL_POSITION SEPARATOR ', ') AS composite_pk_columns
FROM information_schema.TABLE_CONSTRAINTS tc
JOIN information_schema.KEY_COLUMN_USAGE kcu
    ON tc.CONSTRAINT_NAME = kcu.CONSTRAINT_NAME
   AND tc.TABLE_SCHEMA = kcu.TABLE_SCHEMA
   AND tc.TABLE_NAME = kcu.TABLE_NAME
WHERE tc.TABLE_SCHEMA = 'forge_x'
  AND tc.CONSTRAINT_TYPE = 'PRIMARY KEY'
GROUP BY tc.TABLE_NAME
HAVING COUNT(*) > 1
ORDER BY tc.TABLE_NAME;

SELECT 'Part B: constraint inventory queries ready to run.' AS status;
