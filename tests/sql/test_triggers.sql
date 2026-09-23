-- =====================================================================
-- FORGE-X : Trigger test suite (database/08_triggers.sql)
-- Run against a database already loaded with 01-04, 09 (seed), and 08
-- (triggers). Each block shows BEFORE -> OPERATION -> AFTER, matching
-- what was manually verified live during Step 4 development.
-- =====================================================================

USE forge_x;

-- =====================================================================
-- TEST 1: TRIGGER 1 — Evidence custody audit
-- =====================================================================
SELECT '--- TEST 1 BEFORE ---' AS marker;
SELECT e.evidence_number, e.current_custodian_id, u.full_name AS current_custodian
FROM evidence e LEFT JOIN users u ON e.current_custodian_id = u.user_id
WHERE e.evidence_number = 'EVD-2026-002';

SET @forgex_actor_id = 4; -- Karthik Iyer (supervisor) initiates the hand-off
UPDATE evidence SET current_custodian_id = 9 WHERE evidence_number = 'EVD-2026-002';

SELECT '--- TEST 1 AFTER: current_custodian_id ---' AS marker;
SELECT e.evidence_number, e.current_custodian_id, u.full_name AS current_custodian
FROM evidence e LEFT JOIN users u ON e.current_custodian_id = u.user_id
WHERE e.evidence_number = 'EVD-2026-002';

SELECT '--- TEST 1 AFTER: auto-created chain_of_custody row ---' AS marker;
SELECT cc.custody_action, cc.transferred_from, cc.transferred_to, cc.remarks
FROM chain_of_custody cc JOIN evidence e ON cc.evidence_id = e.evidence_id
WHERE e.evidence_number = 'EVD-2026-002' ORDER BY cc.custody_id DESC LIMIT 1;

SELECT '--- TEST 1 AFTER: auto-created audit_logs row ---' AS marker;
SELECT user_id, table_name, action_type, old_values, new_values
FROM audit_logs WHERE table_name = 'evidence'
  AND record_id = (SELECT evidence_id FROM evidence WHERE evidence_number = 'EVD-2026-002')
ORDER BY audit_id DESC LIMIT 1;

-- =====================================================================
-- TEST 2: TRIGGER 2 — Case status change
-- =====================================================================
SELECT '--- TEST 2 BEFORE ---' AS marker;
SELECT case_number, status FROM cases WHERE case_number = 'CASE-2026-002';

SET @forgex_actor_id = 5;
UPDATE cases SET status = 'pending_review' WHERE case_number = 'CASE-2026-002';

SELECT '--- TEST 2 AFTER: status ---' AS marker;
SELECT case_number, status FROM cases WHERE case_number = 'CASE-2026-002';

SELECT '--- TEST 2 AFTER: auto-created case_timeline row ---' AS marker;
SELECT event_type, event_description, recorded_by
FROM case_timeline WHERE case_id = (SELECT case_id FROM cases WHERE case_number = 'CASE-2026-002')
ORDER BY timeline_id DESC LIMIT 1;

-- =====================================================================
-- TEST 3: TRIGGER 3 — Evidence (reference) hash change
--   NOTE: look up hash_id first, then UPDATE by hash_id directly.
--   (UPDATE ... WHERE evidence_id = (SELECT ... FROM evidence ...) in
--   the SAME statement fails with ERROR 1442 — the trigger tries to
--   update `evidence` while the invoking statement already touched
--   `evidence` in its own subquery. Not a trigger bug; just don't
--   self-reference the target table inside the same statement.)
-- =====================================================================
SELECT '--- TEST 3 BEFORE ---' AS marker;
SELECT eh.hash_id, e.evidence_number, e.integrity_status
FROM evidence_hashes eh JOIN evidence e ON eh.evidence_id = e.evidence_id
WHERE e.evidence_number = 'EVD-2026-013' AND eh.is_original = 1;

SET @forgex_actor_id = 6;
-- Substitute the hash_id printed above (13 for a fresh EVD-2026-013 load)
UPDATE evidence_hashes SET hash_value = SHA2('re-acquired-value-mismatch', 256) WHERE hash_id = 13;

SELECT '--- TEST 3 AFTER: integrity_status ---' AS marker;
SELECT evidence_number, integrity_status FROM evidence WHERE evidence_number = 'EVD-2026-013';

SELECT '--- TEST 3 AFTER: auto-created audit_logs row ---' AS marker;
SELECT user_id, table_name, old_values, new_values
FROM audit_logs WHERE table_name = 'evidence_hashes' ORDER BY audit_id DESC LIMIT 1;

-- =====================================================================
-- TEST 4: TRIGGER 4 — Protect evidence from deletion
-- =====================================================================
SELECT '--- TEST 4a: evidence WITH custody history -> DELETE must fail ---' AS marker;
-- Expect: ERROR 1644 (45000) Evidence cannot be deleted because it has
-- chain-of-custody history.
-- DELETE FROM evidence WHERE evidence_number = 'EVD-2026-001';

SELECT '--- TEST 4b: evidence with NO custody history -> DELETE must succeed ---' AS marker;
INSERT INTO evidence (evidence_number, case_id, evidence_type_id, description, acquisition_method, collected_by, collected_at)
VALUES ('EVD-2026-TEST-DEL', 1, 4, 'Throwaway evidence item for Trigger 4 validation only.', 'manual_documentation', 1, NOW());
DELETE FROM evidence WHERE evidence_number = 'EVD-2026-TEST-DEL'; -- should succeed silently
SELECT COUNT(*) AS should_be_zero FROM evidence WHERE evidence_number = 'EVD-2026-TEST-DEL';

-- =====================================================================
-- TEST 5: TRIGGER 5 — Audit important evidence metadata changes
-- =====================================================================
SELECT '--- TEST 5 BEFORE ---' AS marker;
SELECT evidence_number, description, integrity_status FROM evidence WHERE evidence_number = 'EVD-2026-021';

SET @forgex_actor_id = 3;
UPDATE evidence
   SET description = 'Full mobile backup extracted from the suspect device; chain-of-custody note updated after legal review.',
       integrity_status = 'under_verification'
 WHERE evidence_number = 'EVD-2026-021';

SELECT '--- TEST 5 AFTER: evidence row ---' AS marker;
SELECT evidence_number, description, integrity_status FROM evidence WHERE evidence_number = 'EVD-2026-021';

SELECT '--- TEST 5 AFTER: auto-created audit_logs row ---' AS marker;
SELECT user_id, action_type, old_values, new_values
FROM audit_logs WHERE table_name = 'evidence'
  AND record_id = (SELECT evidence_id FROM evidence WHERE evidence_number = 'EVD-2026-021')
ORDER BY audit_id DESC LIMIT 1;
