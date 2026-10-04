-- =====================================================================
-- FORGE-X  |  database/triggers.sql
-- Run after schema.sql. Uses DELIMITER, so run it with the mysql
-- command-line client or MySQL Workbench (not mysql-connector).
--
-- Trigger groups
--   A. Append-only guards (6 tables x UPDATE/DELETE = 12 triggers)
--   B. Integrity rules CHECK constraints cannot express (8 triggers)
--   C. Database-level audit of role changes (2 triggers)
--
-- Limitations (documented for the viva):
--   * Triggers do not fire for TRUNCATE or DROP. The application
--     account has no privilege for either (see app_user.sql).
--   * A user with SUPER/DROP TRIGGER privilege can remove triggers.
--     These guards protect against ordinary application use and
--     accidental edits, not against a malicious database administrator.
--   * Group C reads @app_user_id and @app_ip, which Flask sets on each
--     connection. If they are unset, the audit row records NULL.
-- =====================================================================

USE forge_x_db;

DELIMITER $$

-- ---------------------------------------------------------------------
-- A. Append-only guards
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_coc_no_update BEFORE UPDATE ON chain_of_custody FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Custody entries cannot be edited. Record a correction instead.';
END$$

CREATE TRIGGER trg_coc_no_delete BEFORE DELETE ON chain_of_custody FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Custody entries cannot be deleted.';
END$$

CREATE TRIGGER trg_eh_no_update BEFORE UPDATE ON evidence_hashes FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Recorded hashes cannot be edited. Record a superseding hash instead.';
END$$

CREATE TRIGGER trg_eh_no_delete BEFORE DELETE ON evidence_hashes FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Recorded hashes cannot be deleted.';
END$$

CREATE TRIGGER trg_hv_no_update BEFORE UPDATE ON hash_verifications FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Hash verification records cannot be edited.';
END$$

CREATE TRIGGER trg_hv_no_delete BEFORE DELETE ON hash_verifications FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Hash verification records cannot be deleted.';
END$$

CREATE TRIGGER trg_rv_no_update BEFORE UPDATE ON report_versions FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Report versions cannot be edited. Save a new version instead.';
END$$

CREATE TRIGGER trg_rv_no_delete BEFORE DELETE ON report_versions FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Report versions cannot be deleted.';
END$$

CREATE TRIGGER trg_audit_no_update BEFORE UPDATE ON audit_logs FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Audit records cannot be edited.';
END$$

CREATE TRIGGER trg_audit_no_delete BEFORE DELETE ON audit_logs FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Audit records cannot be deleted.';
END$$

CREATE TRIGGER trg_la_no_update BEFORE UPDATE ON login_attempts FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Login attempt records cannot be edited.';
END$$

CREATE TRIGGER trg_la_no_delete BEFORE DELETE ON login_attempts FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Login attempt records cannot be deleted.';
END$$

-- ---------------------------------------------------------------------
-- B. Integrity rules that span rows or tables
-- ---------------------------------------------------------------------

-- B1. A verification's result is computed by the database, never trusted
--     from the application, and only the current reference hash may be used.
CREATE TRIGGER trg_hv_set_result BEFORE INSERT ON hash_verifications FOR EACH ROW
BEGIN
  DECLARE v_ref CHAR(64) CHARACTER SET ascii COLLATE ascii_bin DEFAULT NULL;

  SELECT hash_value INTO v_ref
    FROM evidence_hashes
   WHERE hash_id = NEW.hash_id;

  IF v_ref IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Reference hash not found.';
  END IF;

  IF EXISTS (SELECT 1 FROM evidence_hashes WHERE supersedes_hash_id = NEW.hash_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This hash has been superseded. Verify against the current reference hash.';
  END IF;

  SET NEW.result = IF(NEW.computed_hash = v_ref, 'Verified', 'Failed');
END$$

-- B2. A superseding hash must belong to the same evidence item.
CREATE TRIGGER trg_eh_same_evidence BEFORE INSERT ON evidence_hashes FOR EACH ROW
BEGIN
  IF NEW.supersedes_hash_id IS NOT NULL
     AND NOT ((SELECT evidence_id FROM evidence_hashes WHERE hash_id = NEW.supersedes_hash_id) <=> NEW.evidence_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A corrected hash must belong to the same evidence item.';
  END IF;
END$$

-- B3. A custody correction must refer to an entry for the same evidence item.
CREATE TRIGGER trg_coc_same_evidence BEFORE INSERT ON chain_of_custody FOR EACH ROW
BEGIN
  IF NEW.corrects_custody_id IS NOT NULL
     AND NOT ((SELECT evidence_id FROM chain_of_custody WHERE custody_id = NEW.corrects_custody_id) <=> NEW.evidence_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A custody correction must refer to an entry for the same evidence item.';
  END IF;
END$$

-- B4. Examinations may only cover evidence from their own case.
CREATE TRIGGER trg_ee_same_case BEFORE INSERT ON examination_evidence FOR EACH ROW
BEGIN
  IF NOT ((SELECT case_id FROM evidence     WHERE evidence_id    = NEW.evidence_id)
      <=> (SELECT case_id FROM examinations WHERE examination_id = NEW.examination_id)) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Evidence and examination belong to different cases.';
  END IF;
END$$

-- B5. Reports may only cite examinations from their own case.
CREATE TRIGGER trg_re_same_case BEFORE INSERT ON report_examinations FOR EACH ROW
BEGIN
  IF NOT ((SELECT case_id FROM forensic_reports WHERE report_id      = NEW.report_id)
      <=> (SELECT case_id FROM examinations     WHERE examination_id = NEW.examination_id)) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Report and examination belong to different cases.';
  END IF;
END$$

-- B6. New report content is only accepted while the report is a Draft.
CREATE TRIGGER trg_rv_only_draft BEFORE INSERT ON report_versions FOR EACH ROW
BEGIN
  IF NOT ((SELECT status FROM forensic_reports WHERE report_id = NEW.report_id) <=> 'Draft') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'New versions can only be added while the report is a Draft.';
  END IF;
END$$

-- B7. A pending request cannot reuse an existing account's username or email.
--     (Uniqueness across two tables cannot be a UNIQUE constraint.)
CREATE TRIGGER trg_ar_unique_vs_users BEFORE INSERT ON account_requests FOR EACH ROW
BEGIN
  IF NEW.request_status = 'Pending'
     AND EXISTS (SELECT 1 FROM users WHERE username = NEW.username OR email = NEW.email) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'That username or email already belongs to an account.';
  END IF;
END$$

-- B8. Closed cases are read-only (decision D3: closing is final).
CREATE TRIGGER trg_cases_closed_readonly BEFORE UPDATE ON cases FOR EACH ROW
BEGIN
  IF OLD.status = 'Closed' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Closed cases are read-only.';
  END IF;
END$$

-- ---------------------------------------------------------------------
-- C. Role changes are audited by the database (decision D5).
--    Flask does NOT write its own audit row for role changes,
--    so each change is recorded exactly once.
-- ---------------------------------------------------------------------
CREATE TRIGGER trg_ur_audit_insert AFTER INSERT ON user_roles FOR EACH ROW
BEGIN
  INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address)
  SELECT @app_user_id, 'role.assign', 'User', u.username, 'Success',
         CONCAT('Granted role: ', r.role_name), @app_ip
    FROM users u
    JOIN roles r ON r.role_id = NEW.role_id
   WHERE u.user_id = NEW.user_id;
END$$

CREATE TRIGGER trg_ur_audit_delete AFTER DELETE ON user_roles FOR EACH ROW
BEGIN
  INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address)
  SELECT @app_user_id, 'role.revoke', 'User', u.username, 'Success',
         CONCAT('Revoked role: ', r.role_name), @app_ip
    FROM users u
    JOIN roles r ON r.role_id = OLD.role_id
   WHERE u.user_id = OLD.user_id;
END$$

DELIMITER ;
