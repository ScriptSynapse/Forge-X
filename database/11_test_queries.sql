-- =====================================================================
-- FORGE-X : Forensic Operations, Records, Governance & Evidence Exchange
-- File   : 11_test_queries.sql
-- Purpose: Validation suite for the seed dataset — row-count checks
--          against the brief's stated minimums, flagship-case checks,
--          full referential-integrity (orphan-row) checks across every
--          relationship, and a set of negative tests proving the
--          constraints from 02/03_constraints.sql are genuinely
--          enforced (each is expected to FAIL with a named MySQL
--          error — that failure IS the passing result).
-- Depends: 01_create_database.sql .. 09_seed_data.sql must already
--          have run.
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
-- SECTION 1 — Row-count validation against the brief's minimums
-- =====================================================================
SELECT
    'cases' AS entity, COUNT(*) AS actual, 5 AS required_minimum,
    IF(COUNT(*) >= 5, 'PASS', 'FAIL') AS result FROM cases
UNION ALL
SELECT 'users (investigators/analysts)', COUNT(*), 10, IF(COUNT(*) >= 10, 'PASS','FAIL') FROM users
UNION ALL
SELECT 'persons', COUNT(*), 10, IF(COUNT(*) >= 10, 'PASS','FAIL') FROM persons
UNION ALL
SELECT 'devices', COUNT(*), 15, IF(COUNT(*) >= 15, 'PASS','FAIL') FROM devices
UNION ALL
SELECT 'evidence', COUNT(*), 30, IF(COUNT(*) >= 30, 'PASS','FAIL') FROM evidence
UNION ALL
SELECT 'chain_of_custody', COUNT(*), 50, IF(COUNT(*) >= 50, 'PASS','FAIL') FROM chain_of_custody
UNION ALL
SELECT 'evidence_examinations', COUNT(*), 20, IF(COUNT(*) >= 20, 'PASS','FAIL') FROM evidence_examinations
UNION ALL
SELECT 'forensic_reports', COUNT(*), 10, IF(COUNT(*) >= 10, 'PASS','FAIL') FROM forensic_reports
UNION ALL
SELECT 'audit_logs', COUNT(*), 100, IF(COUNT(*) >= 100, 'PASS','FAIL') FROM audit_logs
UNION ALL
SELECT 'case_timeline', COUNT(*), 50, IF(COUNT(*) >= 50, 'PASS','FAIL') FROM case_timeline;

-- =====================================================================
-- SECTION 2 — Flagship case (CASE-2026-001) validation
-- =====================================================================
SELECT case_id, case_number, case_title, status, priority
FROM cases WHERE case_number = 'CASE-2026-001';

SELECT
    'persons' AS metric,
    (SELECT COUNT(*) FROM case_persons cp JOIN cases c ON cp.case_id = c.case_id WHERE c.case_number='CASE-2026-001') AS actual,
    3 AS required_minimum
UNION ALL
SELECT 'investigators',
    (SELECT COUNT(*) FROM case_investigators ci JOIN cases c ON ci.case_id = c.case_id WHERE c.case_number='CASE-2026-001'), 3
UNION ALL
SELECT 'devices',
    (SELECT COUNT(*) FROM devices d JOIN cases c ON d.case_id = c.case_id WHERE c.case_number='CASE-2026-001'), 4
UNION ALL
SELECT 'evidence_items',
    (SELECT COUNT(*) FROM evidence e JOIN cases c ON e.case_id = c.case_id WHERE c.case_number='CASE-2026-001'), 8
UNION ALL
SELECT 'custody_records',
    (SELECT COUNT(*) FROM chain_of_custody cc JOIN evidence e ON cc.evidence_id=e.evidence_id
       JOIN cases c ON e.case_id=c.case_id WHERE c.case_number='CASE-2026-001'), 1
UNION ALL
SELECT 'examinations',
    (SELECT COUNT(*) FROM evidence_examinations ex JOIN evidence e ON ex.evidence_id=e.evidence_id
       JOIN cases c ON e.case_id=c.case_id WHERE c.case_number='CASE-2026-001'), 1
UNION ALL
SELECT 'timeline_events',
    (SELECT COUNT(*) FROM case_timeline t JOIN cases c ON t.case_id=c.case_id WHERE c.case_number='CASE-2026-001'), 1
UNION ALL
SELECT 'reports',
    (SELECT COUNT(*) FROM forensic_reports r JOIN cases c ON r.case_id=c.case_id WHERE c.case_number='CASE-2026-001'), 2;

-- =====================================================================
-- SECTION 3 — Referential integrity: orphan-row checks
--   Every row below MUST return 0. A LEFT JOIN ... WHERE parent IS NULL
--   finds any child row whose FK value has no matching parent — which
--   should be structurally impossible given the FK constraints, but
--   this independently re-verifies it at the data level.
-- =====================================================================
SELECT 'orphan_users_role' AS check_name, COUNT(*) AS orphan_count
    FROM users u LEFT JOIN roles r ON u.role_id = r.role_id WHERE r.role_id IS NULL
UNION ALL
SELECT 'orphan_users_department', COUNT(*)
    FROM users u LEFT JOIN departments d ON u.department_id = d.department_id WHERE d.department_id IS NULL
UNION ALL
SELECT 'orphan_cases_case_type', COUNT(*)
    FROM cases c LEFT JOIN case_types t ON c.case_type_id = t.case_type_id WHERE t.case_type_id IS NULL
UNION ALL
SELECT 'orphan_cases_created_by', COUNT(*)
    FROM cases c LEFT JOIN users u ON c.created_by = u.user_id WHERE u.user_id IS NULL
UNION ALL
SELECT 'orphan_devices_case', COUNT(*)
    FROM devices d LEFT JOIN cases c ON d.case_id = c.case_id WHERE c.case_id IS NULL
UNION ALL
SELECT 'orphan_devices_device_type', COUNT(*)
    FROM devices d LEFT JOIN device_types t ON d.device_type_id = t.device_type_id WHERE t.device_type_id IS NULL
UNION ALL
SELECT 'orphan_evidence_case', COUNT(*)
    FROM evidence e LEFT JOIN cases c ON e.case_id = c.case_id WHERE c.case_id IS NULL
UNION ALL
SELECT 'orphan_evidence_device', COUNT(*)
    FROM evidence e LEFT JOIN devices d ON e.device_id = d.device_id
    WHERE e.device_id IS NOT NULL AND d.device_id IS NULL
UNION ALL
SELECT 'orphan_evidence_hashes_evidence', COUNT(*)
    FROM evidence_hashes h LEFT JOIN evidence e ON h.evidence_id = e.evidence_id WHERE e.evidence_id IS NULL
UNION ALL
SELECT 'orphan_custody_evidence', COUNT(*)
    FROM chain_of_custody cc LEFT JOIN evidence e ON cc.evidence_id = e.evidence_id WHERE e.evidence_id IS NULL
UNION ALL
SELECT 'orphan_examinations_evidence', COUNT(*)
    FROM evidence_examinations x LEFT JOIN evidence e ON x.evidence_id = e.evidence_id WHERE e.evidence_id IS NULL
UNION ALL
SELECT 'orphan_examinations_tool', COUNT(*)
    FROM evidence_examinations x LEFT JOIN forensic_tools t ON x.tool_id = t.tool_id WHERE t.tool_id IS NULL
UNION ALL
SELECT 'orphan_reports_case', COUNT(*)
    FROM forensic_reports r LEFT JOIN cases c ON r.case_id = c.case_id WHERE c.case_id IS NULL
UNION ALL
SELECT 'orphan_report_versions_report', COUNT(*)
    FROM report_versions v LEFT JOIN forensic_reports r ON v.report_id = r.report_id WHERE r.report_id IS NULL
UNION ALL
SELECT 'orphan_timeline_case', COUNT(*)
    FROM case_timeline t LEFT JOIN cases c ON t.case_id = c.case_id WHERE c.case_id IS NULL
UNION ALL
SELECT 'orphan_case_investigators_case', COUNT(*)
    FROM case_investigators ci LEFT JOIN cases c ON ci.case_id = c.case_id WHERE c.case_id IS NULL
UNION ALL
SELECT 'orphan_case_investigators_user', COUNT(*)
    FROM case_investigators ci LEFT JOIN users u ON ci.user_id = u.user_id WHERE u.user_id IS NULL
UNION ALL
SELECT 'orphan_case_persons_case', COUNT(*)
    FROM case_persons cp LEFT JOIN cases c ON cp.case_id = c.case_id WHERE c.case_id IS NULL
UNION ALL
SELECT 'orphan_case_persons_person', COUNT(*)
    FROM case_persons cp LEFT JOIN persons p ON cp.person_id = p.person_id WHERE p.person_id IS NULL
UNION ALL
SELECT 'orphan_audit_logs_user', COUNT(*)
    FROM audit_logs a LEFT JOIN users u ON a.user_id = u.user_id
    WHERE a.user_id IS NOT NULL AND u.user_id IS NULL;

-- =====================================================================
-- SECTION 4 — Negative tests: constraints must actively REJECT bad data
--   Each statement below is EXPECTED TO FAIL with the named MySQL
--   error. Run them individually (not inside the seed transaction) —
--   an error here is the correct, passing outcome, proving the
--   constraint is really enforced by the engine and not just declared.
-- =====================================================================

-- Every statement in this section was executed live against MySQL 8.0.46
-- during development and confirmed to fail with exactly the error shown.
-- They are left commented here so this file can still be run start-to-
-- finish without interrupting Sections 1-3; uncomment one line at a
-- time against a scratch copy of the database to reproduce.

-- 4.1 Duplicate case_number -> uq_cases_case_number
--     CONFIRMED: ERROR 1062 (23000) Duplicate entry 'CASE-2026-001' for key 'cases.uq_cases_case_number'
-- INSERT INTO cases (case_number, case_title, case_type_id, created_by)
--   VALUES ('CASE-2026-001', 'Duplicate Test', 1, 1);

-- 4.2 Duplicate user email -> uq_users_email
--     CONFIRMED: ERROR 1062 (23000) Duplicate entry 'a.sharma@forgex.gov.in' for key 'users.uq_users_email'
-- INSERT INTO users (badge_number, username, email, password_hash, full_name, role_id, department_id)
--   VALUES ('FX-B-9999','dupuser','a.sharma@forgex.gov.in', REPEAT('x',60), 'Duplicate Email', 1, 1);

-- 4.3 Invalid case status value -> rejected by the ENUM domain itself
--     (fires before chk_cases_status_valid_values is even evaluated)
--     CONFIRMED: ERROR 1265 (01000) Data truncated for column 'status' at row 1
-- INSERT INTO cases (case_number, case_title, case_type_id, status, created_by)
--   VALUES ('CASE-2026-999', 'Bad Status', 1, 'not_a_real_status', 1);

-- 4.4 closed_at before opened_at -> chk_cases_closed_after_opened
--     CONFIRMED: ERROR 3819 (HY000) Check constraint 'chk_cases_closed_after_opened' is violated.
-- INSERT INTO cases (case_number, case_title, case_type_id, created_by, opened_at, closed_at)
--   VALUES ('CASE-2026-998', 'Bad Dates', 1, 1, '2026-06-01', '2026-01-01');

-- 4.5 Delete evidence that still has custody history -> fk_custody_evidence
--     CONFIRMED: ERROR 1451 (23000) Cannot delete or update a parent row: a foreign
--     key constraint fails (chain_of_custody, CONSTRAINT fk_custody_evidence ...)
--     This is the concrete proof of "evidence with custody history must never
--     disappear accidentally."
-- DELETE FROM evidence WHERE evidence_id = 1;

-- 4.6 Delete a case that still has devices/evidence -> fk_devices_case
--     CONFIRMED: ERROR 1451 (23000) Cannot delete or update a parent row: a foreign
--     key constraint fails (devices, CONSTRAINT fk_devices_case ...)
-- DELETE FROM cases WHERE case_id = 1;

-- 4.7 Custody transferred_from = transferred_to -> chk_custody_from_ne_to
--     CONFIRMED: ERROR 3819 (HY000) Check constraint 'chk_custody_from_ne_to' is violated.
-- INSERT INTO chain_of_custody (evidence_id, transferred_from, transferred_to, custody_action, location_id)
--   VALUES (1, 1, 1, 'transferred', 1);

SELECT 'Validation suite ready. Sections 1-3 run directly; Section 4 statements are commented - uncomment one at a time to confirm it is rejected.' AS status;
