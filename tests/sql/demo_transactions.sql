-- =====================================================================
-- FORGE-X : Transaction / ACID demonstration
-- File   : tests/sql/demo_transactions.sql
-- Purpose: Raw, non-procedure START TRANSACTION / COMMIT / ROLLBACK
--          demonstrations, showing exactly why atomicity matters for
--          forensic evidence — a partially-applied custody update is
--          not just a bug, it is a broken legal record.
-- Depends: the full stack through 09_seed_data.sql and 08_triggers.sql.
-- =====================================================================

USE forge_x;

-- =====================================================================
-- DEMO A: SUCCESSFUL TRANSACTION (COMMIT)
--   Registers a new evidence item the same way sp_register_evidence
--   does internally, but spelled out as raw statements: insert the
--   evidence row, insert its first custody entry, insert a timeline
--   event. All three succeed, so all three are made permanent together.
-- =====================================================================
SELECT '--- DEMO A BEFORE ---' AS marker;
SELECT COUNT(*) AS evidence_count FROM evidence WHERE case_id = 1;
SELECT COUNT(*) AS custody_count FROM chain_of_custody cc JOIN evidence e ON cc.evidence_id=e.evidence_id WHERE e.case_id=1;

START TRANSACTION;

INSERT INTO evidence (evidence_number, case_id, evidence_type_id, description,
                       acquisition_method, collected_by, current_custodian_id, collected_at, storage_location_id)
VALUES ('EVD-2026-DEMO-A', 1, 5, 'Demo: additional scanned document located during a follow-up search.',
        'manual_documentation', 4, 4, NOW(), 2);

SET @demo_a_evidence_id = LAST_INSERT_ID();

INSERT INTO chain_of_custody (evidence_id, transferred_from, transferred_to, custody_action, location_id, remarks)
VALUES (@demo_a_evidence_id, NULL, 4, 'collected', 2, 'Demo A: initial collection, part of a successful transaction.');

INSERT INTO case_timeline (case_id, event_type, event_description, related_table, related_record_id, recorded_by)
VALUES (1, 'evidence_collected', 'Demo A: additional evidence registered during a follow-up search.',
        'evidence', @demo_a_evidence_id, 4);

COMMIT;

SELECT '--- DEMO A AFTER COMMIT (both new rows must be present) ---' AS marker;
SELECT COUNT(*) AS evidence_count FROM evidence WHERE case_id = 1;
SELECT COUNT(*) AS custody_count FROM chain_of_custody cc JOIN evidence e ON cc.evidence_id=e.evidence_id WHERE e.case_id=1;

-- =====================================================================
-- DEMO B: FAILED TRANSACTION (ROLLBACK) — proving atomicity
--   Same three-step pattern, but the THIRD statement is deliberately
--   invalid (a duplicate evidence_number, which violates
--   uq_cases_case_number's sibling constraint on evidence). The first
--   two statements succeed individually — this proves the database
--   does NOT keep their effects just because they ran without error;
--   the whole transaction is undone as one unit.
-- =====================================================================
SELECT '--- DEMO B BEFORE ---' AS marker;
SELECT COUNT(*) AS evidence_count FROM evidence WHERE case_id = 1;
SELECT COUNT(*) AS custody_count FROM chain_of_custody cc JOIN evidence e ON cc.evidence_id=e.evidence_id WHERE e.case_id=1;
SELECT COUNT(*) AS timeline_count FROM case_timeline WHERE case_id = 1;

START TRANSACTION;

-- Statement 1: succeeds
INSERT INTO evidence (evidence_number, case_id, evidence_type_id, description,
                       acquisition_method, collected_by, current_custodian_id, collected_at, storage_location_id)
VALUES ('EVD-2026-DEMO-B', 1, 5, 'Demo: this evidence item must NOT survive the rollback below.',
        'manual_documentation', 4, 4, NOW(), 2);

SET @demo_b_evidence_id = LAST_INSERT_ID();

-- Statement 2: succeeds
INSERT INTO chain_of_custody (evidence_id, transferred_from, transferred_to, custody_action, location_id, remarks)
VALUES (@demo_b_evidence_id, NULL, 4, 'collected', 2, 'Demo B: this custody row must NOT survive the rollback below.');

-- Statement 3: FAILS — evidence_number 'EVD-2026-001' already exists
-- (uq_evidence_number). In a real application this error would be
-- caught here and a ROLLBACK issued explicitly; we do that below.
-- INSERT INTO evidence (evidence_number, case_id, evidence_type_id, description,
--                        acquisition_method, collected_by, current_custodian_id, collected_at)
-- VALUES ('EVD-2026-001', 1, 5, 'Duplicate evidence_number - this must fail.',
--         'manual_documentation', 4, 4, NOW());

ROLLBACK;

SELECT '--- DEMO B AFTER ROLLBACK (counts must be UNCHANGED from BEFORE) ---' AS marker;
SELECT COUNT(*) AS evidence_count FROM evidence WHERE case_id = 1;
SELECT COUNT(*) AS custody_count FROM chain_of_custody cc JOIN evidence e ON cc.evidence_id=e.evidence_id WHERE e.case_id=1;
SELECT COUNT(*) AS timeline_count FROM case_timeline WHERE case_id = 1;
SELECT COUNT(*) AS demo_b_evidence_should_be_zero FROM evidence WHERE evidence_number = 'EVD-2026-DEMO-B';

-- =====================================================================
-- WHY THIS MATTERS FOR FORENSIC EVIDENCE (ACID, one property at a time)
-- =====================================================================
-- ATOMICITY   — Demo B above: if the evidence row could be committed
--               without its matching chain_of_custody row (or vice
--               versa), the database would contain evidence with NO
--               recorded origin — legally indefensible. "All or
--               nothing" is what makes every evidence row provably
--               paired with a custody trail from the instant it exists.
--
-- CONSISTENCY — Every CHECK/FK/UNIQUE constraint from 02-03_*.sql
--               stays enforced inside a transaction exactly as outside
--               one: sp_transfer_evidence's rollback tests (Section
--               above, tests/sql — see the "Invalid evidence transfer"
--               tests) never leave the database in a state where
--               transferred_from = transferred_to, or where an evidence
--               item points at a nonexistent custodian.
--
-- ISOLATION   — Two investigators racing to log two different custody
--               transfers for the SAME evidence item at the same
--               moment cannot interleave their writes into a corrupted
--               half-A-half-B row: sp_transfer_evidence's
--               `SELECT ... FOR UPDATE` (Step 1 of the 8-step spec)
--               takes an exclusive row lock for the duration of the
--               transaction, so the second investigator's call simply
--               waits for the first to COMMIT or ROLLBACK before it
--               can even read the current custodian — preventing a
--               lost-update race on the single most safety-critical
--               column in the schema.
--
-- DURABILITY  — Once sp_transfer_evidence COMMITs, InnoDB's redo log
--               guarantees that custody record survives a server crash
--               one millisecond later. A chain-of-custody record that
--               could vanish on a power failure would be worthless as
--               legal evidence; durability is what makes a COMMIT here
--               mean the same thing as a signature on a paper form.
