-- =====================================================================
-- FORGE-X  |  database/verify.sql
-- Data-independent verification: works on an EMPTY lab (the normal
-- installation) and on any later data. Prints PASS/FAIL per test, then
-- a summary. Run as root.
--
-- It is NON-DESTRUCTIVE. Rejected statements run inside transactions
-- that are rolled back. (Rolled-back inserts can leave harmless gaps in
-- AUTO_INCREMENT numbers.)
--
-- verify_demo.sql is the fuller 40-test suite; it needs the demo data
-- from seed_demo.sql and is run by install_demo.sql.
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
DROP PROCEDURE IF EXISTS verify_capture_error;

DELIMITER $$

-- Runs p_sql in its own rolled-back transaction; PASS only if it fails
-- with an error containing p_expect.
CREATE PROCEDURE verify_expect_error(IN p_no VARCHAR(5), IN p_name VARCHAR(120),
                                     IN p_sql TEXT, IN p_expect VARCHAR(120))
BEGIN
  DECLARE v_msg VARCHAR(512) DEFAULT NULL;
  DECLARE v_tmp VARCHAR(512);
  DECLARE CONTINUE HANDLER FOR SQLEXCEPTION
  BEGIN
    GET DIAGNOSTICS CONDITION 1 v_tmp = MESSAGE_TEXT;
    IF v_msg IS NULL THEN SET v_msg = v_tmp; END IF;
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

-- Runs p_sql inside the CALLER's transaction and stores the first error
-- message in @verify_msg (NULL if none). Used to test triggers on a row
-- the caller inserted in that same transaction.
CREATE PROCEDURE verify_capture_error(IN p_sql TEXT)
BEGIN
  DECLARE v_tmp VARCHAR(512);
  DECLARE CONTINUE HANDLER FOR SQLEXCEPTION
  BEGIN
    GET DIAGNOSTICS CONDITION 1 v_tmp = MESSAGE_TEXT;
    IF @verify_msg IS NULL THEN SET @verify_msg = v_tmp; END IF;
  END;
  SET @verify_msg = NULL;
  SET @verify_sql = p_sql;
  PREPARE verify_stmt FROM @verify_sql;
  EXECUTE verify_stmt;
  DEALLOCATE PREPARE verify_stmt;
END$$

DELIMITER ;

-- ---------------------------------------------------------------------
-- S. Structure
-- ---------------------------------------------------------------------
INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'S1', 'Base tables', '22', COUNT(*), COUNT(*) = 22
  FROM information_schema.TABLES WHERE TABLE_SCHEMA = 'forge_x_db' AND TABLE_TYPE = 'BASE TABLE';
INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'S2', 'Tables not using InnoDB', '0', COUNT(*), COUNT(*) = 0
  FROM information_schema.TABLES WHERE TABLE_SCHEMA = 'forge_x_db' AND TABLE_TYPE = 'BASE TABLE' AND ENGINE <> 'InnoDB';
INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'S3', 'Views', '8', COUNT(*), COUNT(*) = 8 FROM information_schema.VIEWS WHERE TABLE_SCHEMA = 'forge_x_db';
INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'S4', 'Stored procedures / functions', '12 / 2',
       CONCAT(SUM(ROUTINE_TYPE = 'PROCEDURE'), ' / ', SUM(ROUTINE_TYPE = 'FUNCTION')),
       SUM(ROUTINE_TYPE = 'PROCEDURE') = 12 AND SUM(ROUTINE_TYPE = 'FUNCTION') = 2
  FROM information_schema.ROUTINES
 WHERE ROUTINE_SCHEMA = 'forge_x_db' AND ROUTINE_NAME NOT IN ('verify_expect_error', 'verify_capture_error');
INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'S5', 'Triggers', '22', COUNT(*), COUNT(*) = 22 FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA = 'forge_x_db';
INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'S6', 'Foreign keys with CASCADE / SET NULL', '0', COUNT(*), COUNT(*) = 0
  FROM information_schema.REFERENTIAL_CONSTRAINTS
 WHERE CONSTRAINT_SCHEMA = 'forge_x_db'
   AND (DELETE_RULE NOT IN ('RESTRICT','NO ACTION') OR UPDATE_RULE NOT IN ('RESTRICT','NO ACTION'));
INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'S7', 'CHECK constraints', '>= 25', COUNT(*), COUNT(*) >= 25
  FROM information_schema.CHECK_CONSTRAINTS WHERE CONSTRAINT_SCHEMA = 'forge_x_db';

-- ---------------------------------------------------------------------
-- G. Reference data and consistency (true for empty and full databases)
-- ---------------------------------------------------------------------
INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'G1', 'Reference data: roles / case, evidence, exam types / locations', '4 / >0 / >0 / >0 / >0',
       CONCAT_WS(' / ', (SELECT COUNT(*) FROM roles), (SELECT COUNT(*) FROM case_types),
                 (SELECT COUNT(*) FROM evidence_types), (SELECT COUNT(*) FROM examination_types),
                 (SELECT COUNT(*) FROM storage_locations)),
       (SELECT COUNT(*) FROM roles) = 4 AND (SELECT COUNT(*) FROM case_types) > 0
       AND (SELECT COUNT(*) FROM evidence_types) > 0 AND (SELECT COUNT(*) FROM examination_types) > 0
       AND (SELECT COUNT(*) FROM storage_locations) > 0;

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'G2', 'Evidence current custodian/location match latest custody entry', '0 mismatches',
       CONCAT(COUNT(*), ' mismatches'), COUNT(*) = 0
  FROM evidence e
  LEFT JOIN (SELECT evidence_id, to_custodian_id, location_id,
                    ROW_NUMBER() OVER (PARTITION BY evidence_id ORDER BY occurred_at DESC, custody_id DESC) AS rn
               FROM chain_of_custody) l ON l.evidence_id = e.evidence_id AND l.rn = 1
 WHERE l.evidence_id IS NULL
    OR NOT (l.to_custodian_id <=> e.current_custodian_id AND l.location_id <=> e.current_location_id);

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'G3', 'Cases without exactly one lead investigator', '0', COUNT(*), COUNT(*) = 0
  FROM cases c WHERE (SELECT COUNT(*) FROM case_investigators ci WHERE ci.case_id = c.case_id AND ci.is_lead) <> 1;

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'G4', 'Verification results consistent with hashes', '0 inconsistent',
       CONCAT(COUNT(*), ' inconsistent'), COUNT(*) = 0
  FROM hash_verifications hv JOIN evidence_hashes h ON h.hash_id = hv.hash_id
 WHERE hv.result <> IF(hv.computed_hash = h.hash_value, 'Verified', 'Failed');

INSERT INTO verify_results (test_no, test_name, expected, actual, passed)
SELECT 'G5', 'Activity feed = audit_logs + login_attempts',
       CONCAT((SELECT COUNT(*) FROM audit_logs) + (SELECT COUNT(*) FROM login_attempts)),
       COUNT(*), COUNT(*) = (SELECT COUNT(*) FROM audit_logs) + (SELECT COUNT(*) FROM login_attempts)
  FROM v_activity_feed;

-- ---------------------------------------------------------------------
-- E. Statements that MUST be rejected (no existing data needed)
-- ---------------------------------------------------------------------
SET @audit_before = (SELECT COUNT(*) FROM audit_logs);
SET @login_before = (SELECT COUNT(*) FROM login_attempts);
SET @evseq_before = COALESCE((SELECT last_number FROM reference_sequences
                               WHERE seq_name = 'EVIDENCE' AND seq_year = YEAR(CURDATE())), -1);

CALL verify_expect_error('E01', 'Username format enforced (CHECK)',
  "INSERT INTO users (full_name, email, username, password_hash) VALUES ('Probe', 'probe@example.edu', 'bad name!', 'x')", 'chk_users_username');
CALL verify_expect_error('E02', 'Email format enforced (CHECK)',
  "INSERT INTO users (full_name, email, username, password_hash) VALUES ('Probe', 'not-an-email', 'probe.user', 'x')", 'chk_users_email');
CALL verify_expect_error('E03', 'Role names are unique (UNIQUE)',
  "INSERT INTO roles (role_name, description) VALUES ('Administrator', 'duplicate')", 'uq_roles_name');
CALL verify_expect_error('E04', 'Only admins or investigators register cases (procedure)',
  "CALL sp_register_case('Probe', 'Probe', 1, 'Low', 0, 0, @c, @r)", 'Only administrators and investigators');
CALL verify_expect_error('E05', 'Only administrators approve account requests (procedure)',
  "CALL sp_approve_account_request(0, 1, 0, @u)", 'Only administrators');
CALL verify_expect_error('E06', 'Closing a missing case is refused (procedure)',
  "CALL sp_close_case(0, 'probe', 0)", 'Case not found');
CALL verify_expect_error('E07', 'Transfer of a missing item is refused (procedure)',
  "CALL sp_transfer_evidence(0, 0, 'Received', 0, NULL, NULL, 'ok', NULL, 'probe', NULL, 0, @x)", 'Evidence item not found');
CALL verify_expect_error('E08', 'Evidence for a missing case is refused, counter rolled back',
  "CALL sp_register_evidence(0, 1, 'probe', NULL, NULL, '2026-01-01 10:00:00', 0, 'site', 'ok', NULL, NULL, 'Computed', NULL, 0, @e, @c)", 'Case not found');

-- Append-only triggers: insert a probe row, try to change it, roll back.
START TRANSACTION;
INSERT INTO login_attempts (username_or_email, success, failure_reason, ip_address)
VALUES ('verify.sql probe', FALSE, 'invalid_credentials', '127.0.0.1');
SET @probe = LAST_INSERT_ID();
CALL verify_capture_error('UPDATE login_attempts SET ip_address = ''tampered'' WHERE attempt_id = @probe');
SET @t1 = @verify_msg;
CALL verify_capture_error('DELETE FROM login_attempts WHERE attempt_id = @probe');
SET @t2 = @verify_msg;
INSERT INTO audit_logs (action, entity_type, outcome, details) VALUES ('verify.probe', 'User', 'Success', 'verify.sql probe');
SET @probe = LAST_INSERT_ID();
CALL verify_capture_error('UPDATE audit_logs SET outcome = ''Failure'' WHERE audit_id = @probe');
SET @t3 = @verify_msg;
CALL verify_capture_error('DELETE FROM audit_logs WHERE audit_id = @probe');
SET @t4 = @verify_msg;
ROLLBACK;

INSERT INTO verify_results (test_no, test_name, expected, actual, passed) VALUES
 ('T1', 'Login attempts cannot be edited (trigger)', 'Error containing: cannot be edited', COALESCE(@t1, 'No error'), COALESCE(@t1 LIKE '%cannot be edited%', FALSE)),
 ('T2', 'Login attempts cannot be deleted (trigger)', 'Error containing: cannot be deleted', COALESCE(@t2, 'No error'), COALESCE(@t2 LIKE '%cannot be deleted%', FALSE)),
 ('T3', 'Audit records cannot be edited (trigger)', 'Error containing: cannot be edited', COALESCE(@t3, 'No error'), COALESCE(@t3 LIKE '%cannot be edited%', FALSE)),
 ('T4', 'Audit records cannot be deleted (trigger)', 'Error containing: cannot be deleted', COALESCE(@t4, 'No error'), COALESCE(@t4 LIKE '%cannot be deleted%', FALSE));

-- ---------------------------------------------------------------------
-- R. Nothing was left behind
-- ---------------------------------------------------------------------
INSERT INTO verify_results (test_no, test_name, expected, actual, passed) VALUES
 ('R1', 'Rolled-back probes left no audit rows', CONCAT(@audit_before, ' rows'),
        CONCAT((SELECT COUNT(*) FROM audit_logs), ' rows'), (SELECT COUNT(*) FROM audit_logs) = @audit_before),
 ('R2', 'Rolled-back probes left no login rows', CONCAT(@login_before, ' rows'),
        CONCAT((SELECT COUNT(*) FROM login_attempts), ' rows'), (SELECT COUNT(*) FROM login_attempts) = @login_before),
 ('R3', 'Failed registration did not consume an evidence number', CONCAT('counter ', @evseq_before),
        CONCAT('counter ', COALESCE((SELECT last_number FROM reference_sequences
                                      WHERE seq_name = 'EVIDENCE' AND seq_year = YEAR(CURDATE())), -1)),
        COALESCE((SELECT last_number FROM reference_sequences
                   WHERE seq_name = 'EVIDENCE' AND seq_year = YEAR(CURDATE())), -1) = @evseq_before);

SELECT test_no, IF(passed, 'PASS', 'FAIL') AS result, test_name, expected, actual
  FROM verify_results ORDER BY id;
SELECT COUNT(*) AS total_tests, SUM(passed) AS passed, COUNT(*) - SUM(passed) AS failed FROM verify_results;

DROP PROCEDURE IF EXISTS verify_expect_error;
DROP PROCEDURE IF EXISTS verify_capture_error;
