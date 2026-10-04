-- =====================================================================
-- FORGE-X  |  database/verify_demo.sql
-- Self-checking verification. Prints one row per test with PASS/FAIL,
-- then a summary. Needs the DEMO data: run by install_demo.sql.
--
-- It is NON-DESTRUCTIVE: every statement that should be rejected runs
-- inside START TRANSACTION ... ROLLBACK, and the procedures it calls
-- are expected to fail (and roll themselves back).
-- =====================================================================

USE forge_x_db;

DROP TEMPORARY TABLE IF EXISTS verify_results;
CREATE TEMPORARY TABLE verify_results (
  id        INT AUTO_INCREMENT PRIMARY KEY,
  test_no   VARCHAR(5)   NOT NULL,
  test_name VARCHAR(120) NOT NULL,
  expected  VARCHAR(200) NOT NULL,
  actual    VARCHAR(512) NOT NULL,
  passed    BOOLEAN      NOT NULL
);

DROP PROCEDURE IF EXISTS verify_expect_error;

DELIMITER $$

-- Runs p_sql and records PASS only if it fails with an error whose
-- message contains p_expect (so a typo in the test cannot pass).
CREATE PROCEDURE verify_expect_error(
  IN p_no     VARCHAR(5),
  IN p_name   VARCHAR(120),
  IN p_sql    TEXT,
  IN p_expect VARCHAR(120))
BEGIN
  DECLARE v_msg VARCHAR(512) DEFAULT NULL;
  DECLARE v_tmp VARCHAR(512);
  DECLARE CONTINUE HANDLER FOR SQLEXCEPTION
  BEGIN
    GET DIAGNOSTICS CONDITION 1 v_tmp = MESSAGE_TEXT;
    IF v_msg IS NULL THEN
      SET v_msg = v_tmp;            -- keep only the first error
    END IF;
  END;

  SET @verify_sql = p_sql;
  START TRANSACTION;
  PREPARE verify_stmt FROM @verify_sql;
  EXECUTE verify_stmt;
  DEALLOCATE PREPARE verify_stmt;
  ROLLBACK;

  INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
  VALUES (p_no, p_name, CONCAT('Error containing: ', p_expect),
          COALESCE(v_msg, 'No error: the statement was accepted'),
          v_msg IS NOT NULL AND v_msg LIKE CONCAT('%', p_expect, '%'));
END$$

DELIMITER ;

-- ---------------------------------------------------------------------
-- S. Structure
-- ---------------------------------------------------------------------
INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'S1', 'Base tables', '22',
       COUNT(*), COUNT(*) = 22
  FROM information_schema.TABLES
 WHERE TABLE_SCHEMA = 'forge_x_db' AND TABLE_TYPE = 'BASE TABLE';

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'S2', 'Tables not using InnoDB', '0',
       COUNT(*), COUNT(*) = 0
  FROM information_schema.TABLES
 WHERE TABLE_SCHEMA = 'forge_x_db' AND TABLE_TYPE = 'BASE TABLE' AND ENGINE <> 'InnoDB';

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'S3', 'Views', '8',
       COUNT(*), COUNT(*) = 8
  FROM information_schema.VIEWS WHERE TABLE_SCHEMA = 'forge_x_db';

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'S4', 'Stored procedures / functions', '12 / 2',
       CONCAT(SUM(ROUTINE_TYPE = 'PROCEDURE'), ' / ', SUM(ROUTINE_TYPE = 'FUNCTION')),
       SUM(ROUTINE_TYPE = 'PROCEDURE') = 12 AND SUM(ROUTINE_TYPE = 'FUNCTION') = 2
  FROM information_schema.ROUTINES
 WHERE ROUTINE_SCHEMA = 'forge_x_db' AND ROUTINE_NAME <> 'verify_expect_error';

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'S5', 'Triggers', '22',
       COUNT(*), COUNT(*) = 22
  FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = 'forge_x_db';

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'S6', 'Foreign keys with CASCADE / SET NULL', '0',
       COUNT(*), COUNT(*) = 0
  FROM information_schema.REFERENTIAL_CONSTRAINTS
 WHERE CONSTRAINT_SCHEMA = 'forge_x_db'
   AND (DELETE_RULE NOT IN ('RESTRICT','NO ACTION') OR UPDATE_RULE NOT IN ('RESTRICT','NO ACTION'));

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'S7', 'CHECK constraints', '>= 25',
       COUNT(*), COUNT(*) >= 25
  FROM information_schema.CHECK_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = 'forge_x_db';

-- ---------------------------------------------------------------------
-- D. Seed data and consistency
-- ---------------------------------------------------------------------
INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'D1', 'Row counts: users/cases/evidence/custody/exams/reports', '8/12/20/59/12/6',
       CONCAT_WS('/', (SELECT COUNT(*) FROM users), (SELECT COUNT(*) FROM cases),
                      (SELECT COUNT(*) FROM evidence), (SELECT COUNT(*) FROM chain_of_custody),
                      (SELECT COUNT(*) FROM examinations), (SELECT COUNT(*) FROM forensic_reports)),
       CONCAT_WS('/', (SELECT COUNT(*) FROM users), (SELECT COUNT(*) FROM cases),
                      (SELECT COUNT(*) FROM evidence), (SELECT COUNT(*) FROM chain_of_custody),
                      (SELECT COUNT(*) FROM examinations), (SELECT COUNT(*) FROM forensic_reports)) = '8/12/20/59/12/6';

-- Controlled redundancy check: evidence.current_* must equal the latest custody entry.
INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'D2', 'Evidence current custodian/location match latest custody entry', '0 mismatches',
       CONCAT(COUNT(*), ' mismatches'), COUNT(*) = 0
  FROM evidence e
  LEFT JOIN (SELECT evidence_id, to_custodian_id, location_id,
                    ROW_NUMBER() OVER (PARTITION BY evidence_id ORDER BY occurred_at DESC, custody_id DESC) AS rn
               FROM chain_of_custody) l
         ON l.evidence_id = e.evidence_id AND l.rn = 1
 WHERE l.evidence_id IS NULL
    OR NOT (l.to_custodian_id <=> e.current_custodian_id AND l.location_id <=> e.current_location_id);

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'D3', 'Cases without exactly one lead investigator', '0',
       COUNT(*), COUNT(*) = 0
  FROM cases c
 WHERE (SELECT COUNT(*) FROM case_investigators ci WHERE ci.case_id = c.case_id AND ci.is_lead) <> 1;

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'D4', 'Integrity status distribution (view)', 'Failed=1,Not Verified=2,Pending=3,Verified=14',
       COALESCE(GROUP_CONCAT(CONCAT(integrity_status, '=', n) ORDER BY integrity_status SEPARATOR ','), ''),
       COALESCE(GROUP_CONCAT(CONCAT(integrity_status, '=', n) ORDER BY integrity_status SEPARATOR ','), '')
         = 'Failed=1,Not Verified=2,Pending=3,Verified=14'
  FROM (SELECT integrity_status, COUNT(*) AS n FROM v_evidence_integrity GROUP BY integrity_status) t;

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'D5', 'Verification results consistent with hashes (trigger)', '0 inconsistent',
       CONCAT(COUNT(*), ' inconsistent'), COUNT(*) = 0
  FROM hash_verifications hv
  JOIN evidence_hashes h ON h.hash_id = hv.hash_id
 WHERE hv.result <> IF(hv.computed_hash = h.hash_value, 'Verified', 'Failed');

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'D6', 'Role grants audited by trigger', '9 role.assign rows',
       CONCAT(COUNT(*), ' role.assign rows'), COUNT(*) = 9
  FROM audit_logs WHERE action = 'role.assign';

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'D7', 'Activity feed (UNION view) row count', CONCAT((SELECT COUNT(*) FROM audit_logs) + 15),
       COUNT(*), COUNT(*) = (SELECT COUNT(*) FROM audit_logs) + 15
  FROM v_activity_feed;

-- ---------------------------------------------------------------------
-- T. Trigger computes verification results (inside a rolled-back txn)
-- ---------------------------------------------------------------------
START TRANSACTION;
INSERT INTO hash_verifications (hash_id, computed_hash, method, notes, verified_by)
VALUES (11, REPEAT('0', 64), 'Manual entry', 'verify.sql: deliberate mismatch', 4);
SET @t1 = (SELECT result FROM hash_verifications WHERE verification_id = LAST_INSERT_ID());
INSERT INTO hash_verifications (hash_id, computed_hash, method, notes, verified_by)
VALUES (11, '3b7f1c9e04a2d58e6f91c2a7b34d0e85f1c6a9d2e7b40f38c5a1d9e62b7f0c4a', 'Manual entry', 'verify.sql: deliberate match', 4);
SET @t2 = (SELECT result FROM hash_verifications WHERE verification_id = LAST_INSERT_ID());
ROLLBACK;

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
VALUES ('T1', 'Trigger marks a mismatching hash as Failed', 'Failed', COALESCE(@t1, 'NULL'), @t1 <=> 'Failed'),
       ('T2', 'Trigger marks a matching hash as Verified', 'Verified', COALESCE(@t2, 'NULL'), @t2 <=> 'Verified');

-- ---------------------------------------------------------------------
-- E. Statements that MUST be rejected
-- ---------------------------------------------------------------------
SET @coc_before   = (SELECT COUNT(*) FROM chain_of_custody);
SET @audit_before = (SELECT COUNT(*) FROM audit_logs);
SET @evseq_before = (SELECT last_number FROM reference_sequences WHERE seq_name = 'EVIDENCE' AND seq_year = 2026);

CALL verify_expect_error('E01', 'Custody entries cannot be edited',
  "UPDATE chain_of_custody SET reason = 'edited' WHERE custody_id = 1", 'cannot be edited');
CALL verify_expect_error('E02', 'Audit records cannot be deleted',
  "DELETE FROM audit_logs WHERE audit_id = 1", 'cannot be deleted');
CALL verify_expect_error('E03', 'Recorded hashes cannot be edited',
  "UPDATE evidence_hashes SET hash_value = REPEAT('a', 64) WHERE hash_id = 1", 'cannot be edited');
CALL verify_expect_error('E04', 'No self-assigned roles (CHECK)',
  "INSERT INTO user_roles (user_id, role_id, assigned_by) VALUES (6, 1, 6)", 'chk_ur_not_self');
CALL verify_expect_error('E05', 'Only one lead per case (UNIQUE on generated column)',
  "INSERT INTO case_investigators (case_id, user_id, is_lead, assigned_by) VALUES (22, 8, TRUE, 1)", 'uq_ci_one_lead');
CALL verify_expect_error('E06', 'Request cannot reuse an existing username (trigger)',
  "INSERT INTO account_requests (full_name, email, username, password_hash) VALUES ('Test', 'new.person@example.edu', 'rohan.iyer', 'x')", 'already belongs');
CALL verify_expect_error('E07', 'One pending request per email (UNIQUE on generated column)',
  "INSERT INTO account_requests (full_name, email, username, password_hash) VALUES ('Test', 'neha.desai@example.edu', 'neha.two', 'x')", 'uq_ar_pending_email');
CALL verify_expect_error('E08', 'Closed cases are read-only (trigger)',
  "UPDATE cases SET title = 'edited' WHERE case_id = 13", 'read-only');
CALL verify_expect_error('E09', 'Examination cannot cover evidence from another case',
  "INSERT INTO examination_evidence (examination_id, evidence_id) VALUES (31, 58)", 'different cases');
CALL verify_expect_error('E10', 'Author cannot approve own report (CHECK)',
  "UPDATE forensic_reports SET status = 'Approved', approved_by = 3, approved_at = NOW() WHERE report_id = 12", 'chk_rep_independent');
CALL verify_expect_error('E11', 'Hash must be 64 lowercase hex characters (CHECK)',
  "INSERT INTO evidence_hashes (evidence_id, hash_value, source, recorded_by) VALUES (48, REPEAT('A', 64), 'Computed', 4)", 'chk_eh_format');
CALL verify_expect_error('E12', 'Transfer rejected when the custodian has changed',
  "CALL sp_transfer_evidence(55, 4, 'Returned', 4, 1, NULL, 'Sealed, intact', NULL, 'test', NULL, 4, @x)", 'Custodian changed');
CALL verify_expect_error('E13', 'Case with open examinations cannot be closed',
  "CALL sp_close_case(22, 'test', 1)", 'Complete or cancel');
CALL verify_expect_error('E14', 'No new versions for an approved report',
  "INSERT INTO report_versions (report_id, version_no, change_note, created_by) VALUES (10, 3, 'x', 3)", 'only be added while');
CALL verify_expect_error('E15', 'Only Collected entries may lack a previous custodian (CHECK)',
  "INSERT INTO chain_of_custody (evidence_id, action, from_custodian_id, to_custodian_id, location_id, evidence_condition, reason, occurred_at, recorded_by) VALUES (52, 'Received', NULL, 4, 1, 'ok', 'x', '2026-10-01 10:00:00', 4)", 'chk_coc_from');
CALL verify_expect_error('E16', 'Only investigators can be assigned to cases',
  "CALL sp_assign_investigator(22, 6, FALSE, 1)", 'Only active investigators');
CALL verify_expect_error('E17', 'Invalid custody transition is rejected',
  "CALL sp_transfer_evidence(52, 4, 'Examined', 4, 7, NULL, 'ok', NULL, 'x', NULL, 4, @x)", 'not allowed while');
CALL verify_expect_error('E18', 'Only administrators approve account requests',
  "CALL sp_approve_account_request(44, 2, 3, @u)", 'Only administrators');
CALL verify_expect_error('E19', 'Cannot verify against a superseded hash',
  "INSERT INTO hash_verifications (hash_id, computed_hash, method, notes, verified_by) VALUES (12, REPEAT('0', 64), 'Manual entry', 'x', 4)", 'superseded');
CALL verify_expect_error('E20', 'Case reference format enforced (CHECK)',
  "INSERT INTO cases (case_reference, title, description, case_type_id, created_by) VALUES ('FX-26-1', 'x', 'x', 1, 1)", 'chk_cases_reference');
CALL verify_expect_error('E21', 'Evidence cannot be added to a closed case',
  "CALL sp_register_evidence(13, 1, 'x', NULL, NULL, '2026-10-01 10:00:00', 5, 'site', 'ok', NULL, NULL, 'Computed', NULL, 4, @e, @c)", 'closed case');

-- ---------------------------------------------------------------------
-- R. Rollback left no partial changes behind
-- ---------------------------------------------------------------------
INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
VALUES
 ('R1', 'Failed transfers left no custody rows',
        CONCAT(@coc_before, ' rows'), CONCAT((SELECT COUNT(*) FROM chain_of_custody), ' rows'),
        (SELECT COUNT(*) FROM chain_of_custody) = @coc_before),
 ('R2', 'Failed procedures left no audit rows',
        CONCAT(@audit_before, ' rows'), CONCAT((SELECT COUNT(*) FROM audit_logs), ' rows'),
        (SELECT COUNT(*) FROM audit_logs) = @audit_before),
 ('R3', 'Rolled-back registration did not consume an evidence number',
        CONCAT('last_number ', @evseq_before),
        CONCAT('last_number ', (SELECT last_number FROM reference_sequences WHERE seq_name = 'EVIDENCE' AND seq_year = 2026)),
        (SELECT last_number FROM reference_sequences WHERE seq_name = 'EVIDENCE' AND seq_year = 2026) = @evseq_before);

-- ---------------------------------------------------------------------
-- Results
-- ---------------------------------------------------------------------
SELECT test_no, IF(passed, 'PASS', 'FAIL') AS result, test_name, expected, actual
  FROM verify_results
 ORDER BY id;

SELECT COUNT(*) AS total_tests,
       SUM(passed) AS passed,
       COUNT(*) - SUM(passed) AS failed
  FROM verify_results;

DROP PROCEDURE IF EXISTS verify_expect_error;
