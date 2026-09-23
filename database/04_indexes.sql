-- =====================================================================
-- FORGE-X : Forensic Operations, Records, Governance & Evidence Exchange
-- File   : 04_indexes.sql
-- Purpose: Explicit, justified indexes for the query patterns FORGE-X's
--          dashboards and investigation workflows rely on most.
-- Depends: 01_create_database.sql, 02_tables.sql, 03_constraints.sql.
--
-- IMPORTANT — READ BEFORE ADDING AN INDEX HERE
--   InnoDB automatically creates an index on every foreign-key column
--   at CREATE TABLE time (that's how MySQL enforces the FK efficiently).
--   Several of the columns this project brief asks to index are
--   *already* indexed this way. Creating a second, functionally
--   identical index on the same leading column would be a genuine
--   anti-pattern: it doubles storage and write-amplification for zero
--   query benefit (MySQL will not pick a redundant index over the one
--   already serving the same leftmost column). Part A below documents
--   those "already covered" cases explicitly instead of duplicating
--   them. Part B creates the indexes that are genuinely missing.
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
-- PART A — Requested targets already satisfied by an auto-generated
--          foreign-key index (no new index created; verified by query
--          at the bottom of 03_constraints.sql / this file's footer)
-- =====================================================================
--   "case type"      -> cases.case_type_id     already indexed via fk_cases_case_type
--   "evidence case"   -> evidence.case_id        already indexed via fk_evidence_case
--   "custody evidence" -> chain_of_custody.evidence_id already indexed via fk_custody_evidence
--   "timeline case"    -> case_timeline.case_id   already indexed via fk_timeline_case
-- =====================================================================

-- =====================================================================
-- PART B — New indexes for columns not already covered
-- =====================================================================

-- ---------------------------------------------------------------------
-- 1. Case status
-- Purpose: Powers the primary case-list dashboard filter/tab
--          ("Open", "Under Investigation", "Closed", ...) and the
--          GROUP BY status caseload report in 10_advanced_queries.sql.
--          Without this, every status filter is a full table scan of
--          `cases` as the table grows across years of case history.
-- ---------------------------------------------------------------------
CREATE INDEX idx_cases_status ON cases (status);

-- ---------------------------------------------------------------------
-- 2. Case priority
-- Purpose: Powers "show me all CRITICAL/HIGH priority cases" triage
--          views for supervisors — a query run constantly in an active
--          forensics unit, independent of status.
-- ---------------------------------------------------------------------
CREATE INDEX idx_cases_priority ON cases (priority);

-- ---------------------------------------------------------------------
-- 2b. Composite: status + priority (bonus, beyond the minimum list)
-- Purpose: The single most common real dashboard query is a combination
--          of both ("open AND high-priority cases"). A composite index
--          lets MySQL satisfy that filter with one index lookup instead
--          of intersecting two separate single-column indexes.
-- ---------------------------------------------------------------------
CREATE INDEX idx_cases_status_priority ON cases (status, priority);

-- ---------------------------------------------------------------------
-- 3. Evidence status (evidence.integrity_status — see 03_constraints.sql
--    note on naming: evidence has no separate generic "status" column)
-- Purpose: Lets an integrity-audit sweep instantly find every evidence
--          item flagged 'compromised' or 'under_verification' across
--          the whole system, without scanning all evidence rows.
-- ---------------------------------------------------------------------
CREATE INDEX idx_evidence_integrity_status ON evidence (integrity_status);

-- ---------------------------------------------------------------------
-- 4. Evidence hash
-- Purpose: Looking up evidence by a *known* hash value (e.g. matching
--          against a threat-intel hash list, or confirming "has this
--          exact file been seen in any other case") is a cross-evidence
--          search on hash_value alone. The existing UNIQUE constraint
--          on (evidence_id, hash_algorithm, hash_value) is leftmost-
--          prefixed on evidence_id, so it cannot serve a hash_value-only
--          lookup efficiently — a dedicated index is genuinely needed.
-- ---------------------------------------------------------------------
CREATE INDEX idx_evidence_hashes_hash_value ON evidence_hashes (hash_value);

-- ---------------------------------------------------------------------
-- 5. Custody date
-- Purpose: Chain-of-custody reports are almost always date-ranged
--          ("show all custody transfers in the last 30 days", or
--          reconstructing a timeline for a specific date range for
--          court disclosure). Sorting/filtering 50+ (and, in
--          production, potentially millions of) custody rows by
--          custody_timestamp needs its own index.
-- ---------------------------------------------------------------------
CREATE INDEX idx_custody_timestamp ON chain_of_custody (custody_timestamp);

-- ---------------------------------------------------------------------
-- 6. Audit entity (table_name + record_id together)
-- Purpose: The core audit-trail query is always "show me the full
--          history of THIS row in THIS table" (e.g. table_name='cases',
--          record_id=42). audit_logs.record_id is not FK-enforced
--          (it's a polymorphic reference — see 02_tables.sql), so it
--          gets no automatic index at all; this composite index is the
--          single most important index in the whole audit subsystem.
-- ---------------------------------------------------------------------
CREATE INDEX idx_audit_logs_entity ON audit_logs (table_name, record_id);

-- ---------------------------------------------------------------------
-- 7. Person name
-- Purpose: Investigators search persons by name far more often than by
--          person_id ("has a Ramesh Chandran appeared in any other
--          case?"). last_name leads the composite since surname search
--          ("find all Sharmas") is the more common partial-match entry
--          point, with first_name as a secondary filter.
-- ---------------------------------------------------------------------
CREATE INDEX idx_persons_name ON persons (last_name, first_name);

-- ---------------------------------------------------------------------
-- 8. Device serial number
-- Purpose: "Has this serial number been seized before, in any case?"
--          is a standard cross-case device lookup during intake, run
--          against a nullable, non-unique column (the same physical
--          device can legitimately be seized more than once across
--          separate cases over time, so this is a plain index, not a
--          UNIQUE constraint — see 05_Relational_Schema.md §3).
-- ---------------------------------------------------------------------
CREATE INDEX idx_devices_serial_number ON devices (serial_number);

-- ---------------------------------------------------------------------
-- 9. Device IMEI
-- Purpose: Mobile-device intake and cross-case correlation by IMEI is
--          a distinct, very common forensic lookup path from serial
--          number (IMEI identifies the phone hardware/radio itself and
--          is frequently the only identifier recoverable from network
--          / carrier records), so it gets its own dedicated index.
-- ---------------------------------------------------------------------
CREATE INDEX idx_devices_imei_number ON devices (imei_number);

SELECT 'Part B: 9 new indexes created.' AS status;

-- =====================================================================
-- FOOTER — Verification: list every index now on the schema, grouped
-- ("PRIMARY"/"FK-auto"/"explicit") so the effect of this file is
-- auditable at a glance.
-- =====================================================================
SELECT
    s.TABLE_NAME,
    s.INDEX_NAME,
    GROUP_CONCAT(s.COLUMN_NAME ORDER BY s.SEQ_IN_INDEX SEPARATOR ', ') AS indexed_columns,
    CASE
        WHEN s.INDEX_NAME = 'PRIMARY' THEN 'PRIMARY KEY'
        WHEN s.INDEX_NAME LIKE 'fk\_%' ESCAPE '\\' THEN 'AUTO (foreign key)'
        WHEN s.INDEX_NAME LIKE 'uq\_%' ESCAPE '\\' THEN 'UNIQUE constraint'
        ELSE 'EXPLICIT (04_indexes.sql)'
    END AS index_origin
FROM information_schema.STATISTICS s
WHERE s.TABLE_SCHEMA = 'forge_x'
GROUP BY s.TABLE_NAME, s.INDEX_NAME
ORDER BY s.TABLE_NAME, index_origin, s.INDEX_NAME;
