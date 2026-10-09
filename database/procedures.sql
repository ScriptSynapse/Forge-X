-- =====================================================================
-- FORGE-X  |  database/procedures.sql
-- 2 helper functions and 12 stored procedures.
-- Run after schema.sql, triggers.sql and views.sql.
--
-- Transaction rules used by every workflow procedure:
--   * The procedure owns its transaction: START TRANSACTION ... COMMIT.
--     Call it OUTSIDE any open transaction (START TRANSACTION inside a
--     procedure implicitly commits whatever the caller had open).
--   * DECLARE EXIT HANDLER FOR SQLEXCEPTION -> ROLLBACK; RESIGNAL;
--     Any error (a failed CHECK, a duplicate key, or one of our own
--     SIGNALs) undoes every change and passes the error to Flask.
--   * Rows a decision depends on are read with SELECT ... FOR UPDATE.
--   * Lock order: reference_sequences row -> parent (case/report)
--     -> child (evidence). Keeping one order prevents deadlocks.
--   * Business-code counters (sp_next_reference) run inside the
--     caller's transaction, so a rollback also rolls back the counter:
--     codes are never skipped and never reused.
--
-- SQL SECURITY INVOKER: procedures run with the caller's privileges,
-- so the app account can do nothing through them that its own grants
-- would not allow.
-- =====================================================================

USE forge_x_db;

DROP FUNCTION  IF EXISTS fn_has_role;
DROP FUNCTION  IF EXISTS fn_is_case_lead;
DROP PROCEDURE IF EXISTS sp_next_reference;
DROP PROCEDURE IF EXISTS sp_register_case;
DROP PROCEDURE IF EXISTS sp_assign_investigator;
DROP PROCEDURE IF EXISTS sp_remove_investigator;
DROP PROCEDURE IF EXISTS sp_register_evidence;
DROP PROCEDURE IF EXISTS sp_transfer_evidence;
DROP PROCEDURE IF EXISTS sp_record_custody_correction;
DROP PROCEDURE IF EXISTS sp_approve_account_request;
DROP PROCEDURE IF EXISTS sp_reject_account_request;
DROP PROCEDURE IF EXISTS sp_close_case;
DROP PROCEDURE IF EXISTS sp_create_report;
DROP PROCEDURE IF EXISTS sp_create_report_version;

DELIMITER $$

-- =====================================================================
-- Helper functions
-- =====================================================================

-- TRUE if the user is Active and holds the named role.
CREATE FUNCTION fn_has_role(p_user_id INT UNSIGNED, p_role_name VARCHAR(40))
RETURNS BOOLEAN
READS SQL DATA
SQL SECURITY INVOKER
BEGIN
  RETURN EXISTS (
    SELECT 1
      FROM user_roles ur
      JOIN roles r ON r.role_id = ur.role_id
      JOIN users u ON u.user_id = ur.user_id
     WHERE ur.user_id = p_user_id
       AND r.role_name = p_role_name
       AND u.account_status = 'Active');
END$$

-- TRUE if the user is the lead investigator of the case.
CREATE FUNCTION fn_is_case_lead(p_user_id INT UNSIGNED, p_case_id INT UNSIGNED)
RETURNS BOOLEAN
READS SQL DATA
SQL SECURITY INVOKER
BEGIN
  RETURN EXISTS (
    SELECT 1 FROM case_investigators
     WHERE case_id = p_case_id AND user_id = p_user_id AND is_lead = TRUE);
END$$

-- =====================================================================
-- sp_next_reference: next number for a yearly business code.
-- No transaction of its own: it runs inside the caller's transaction.
-- =====================================================================
CREATE PROCEDURE sp_next_reference(
  IN  p_seq_name VARCHAR(20),
  IN  p_year     SMALLINT UNSIGNED,
  OUT p_value    INT UNSIGNED)
SQL SECURITY INVOKER
BEGIN
  -- Create the counter row for a new year if it does not exist yet.
  INSERT IGNORE INTO reference_sequences (seq_name, seq_year, last_number)
  VALUES (p_seq_name, p_year, 0);

  -- Lock the counter row: concurrent registrations queue here.
  SELECT last_number + 1 INTO p_value
    FROM reference_sequences
   WHERE seq_name = p_seq_name AND seq_year = p_year
   FOR UPDATE;

  UPDATE reference_sequences
     SET last_number = p_value
   WHERE seq_name = p_seq_name AND seq_year = p_year;
END$$

-- =====================================================================
-- sp_register_case: create a case and its lead assignment atomically.
-- =====================================================================
CREATE PROCEDURE sp_register_case(
  IN  p_title          VARCHAR(200),
  IN  p_description    TEXT,
  IN  p_case_type_id   SMALLINT UNSIGNED,
  IN  p_priority       VARCHAR(10),
  IN  p_lead_user_id   INT UNSIGNED,
  IN  p_created_by     INT UNSIGNED,
  OUT p_case_id        INT UNSIGNED,
  OUT p_case_reference CHAR(12))
SQL SECURITY INVOKER
BEGIN
  DECLARE v_year SMALLINT UNSIGNED DEFAULT YEAR(CURDATE());
  DECLARE v_seq  INT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;

  IF NOT (fn_has_role(p_created_by, 'Administrator') OR fn_has_role(p_created_by, 'Investigator')) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only administrators and investigators can register cases.';
  END IF;

  IF NOT fn_has_role(p_lead_user_id, 'Investigator') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'The lead must be an active investigator.';
  END IF;

  IF NOT EXISTS (SELECT 1 FROM case_types WHERE case_type_id = p_case_type_id AND is_active = TRUE) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Choose an active case type.';
  END IF;

  CALL sp_next_reference('CASE', v_year, v_seq);
  SET p_case_reference = CONCAT('FX-', v_year, '-', LPAD(v_seq, 4, '0'));

  INSERT INTO cases (case_reference, title, description, case_type_id, priority, status, created_by)
  VALUES (p_case_reference, p_title, p_description, p_case_type_id, p_priority, 'Open', p_created_by);
  SET p_case_id = LAST_INSERT_ID();

  INSERT INTO case_investigators (case_id, user_id, is_lead, assigned_by)
  VALUES (p_case_id, p_lead_user_id, TRUE, p_created_by);

  INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address)
  VALUES (p_created_by, 'case.create', 'Case', p_case_reference, 'Success',
          CONCAT('Priority ', p_priority, ', lead user ', p_lead_user_id), @app_ip);

  COMMIT;
END$$

-- =====================================================================
-- sp_assign_investigator: add an investigator, or make one the lead.
-- =====================================================================
CREATE PROCEDURE sp_assign_investigator(
  IN p_case_id     INT UNSIGNED,
  IN p_user_id     INT UNSIGNED,
  IN p_make_lead   BOOLEAN,
  IN p_assigned_by INT UNSIGNED)
SQL SECURITY INVOKER
BEGIN
  DECLARE v_status    VARCHAR(20) DEFAULT NULL;
  DECLARE v_reference CHAR(12);
  DECLARE v_is_lead   BOOLEAN DEFAULT NULL;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;

  SELECT status, case_reference INTO v_status, v_reference
    FROM cases WHERE case_id = p_case_id
     FOR UPDATE;

  IF v_status IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Case not found.';
  END IF;
  IF v_status = 'Closed' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Investigators cannot be changed on a closed case.';
  END IF;
  IF NOT (fn_has_role(p_assigned_by, 'Administrator') OR fn_is_case_lead(p_assigned_by, p_case_id)) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only an administrator or the lead investigator can assign investigators.';
  END IF;
  IF NOT fn_has_role(p_user_id, 'Investigator') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only active investigators can be assigned to cases.';
  END IF;

  SELECT is_lead INTO v_is_lead
    FROM case_investigators
   WHERE case_id = p_case_id AND user_id = p_user_id;

  IF v_is_lead IS NOT NULL AND NOT p_make_lead THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This investigator is already assigned to the case.';
  END IF;
  IF v_is_lead = TRUE AND p_make_lead THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This investigator is already the lead.';
  END IF;

  IF p_make_lead THEN
    -- Clear the old lead first, so the one-lead-per-case unique key holds.
    UPDATE case_investigators SET is_lead = FALSE
     WHERE case_id = p_case_id AND is_lead = TRUE;
  END IF;

  IF v_is_lead IS NULL THEN
    INSERT INTO case_investigators (case_id, user_id, is_lead, assigned_by)
    VALUES (p_case_id, p_user_id, p_make_lead, p_assigned_by);
  ELSE
    UPDATE case_investigators SET is_lead = TRUE
     WHERE case_id = p_case_id AND user_id = p_user_id;
  END IF;

  INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address)
  VALUES (p_assigned_by, IF(p_make_lead, 'case.set_lead', 'case.assign_investigator'), 'Case',
          v_reference, 'Success', CONCAT('Investigator user ', p_user_id), @app_ip);

  COMMIT;
END$$

-- =====================================================================
-- sp_remove_investigator: unassign a non-lead investigator (decision D4).
-- =====================================================================
CREATE PROCEDURE sp_remove_investigator(
  IN p_case_id    INT UNSIGNED,
  IN p_user_id    INT UNSIGNED,
  IN p_removed_by INT UNSIGNED)
SQL SECURITY INVOKER
BEGIN
  DECLARE v_status    VARCHAR(20) DEFAULT NULL;
  DECLARE v_reference CHAR(12);
  DECLARE v_is_lead   BOOLEAN DEFAULT NULL;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;

  SELECT status, case_reference INTO v_status, v_reference
    FROM cases WHERE case_id = p_case_id
     FOR UPDATE;

  IF v_status IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Case not found.';
  END IF;
  IF v_status = 'Closed' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Investigators cannot be changed on a closed case.';
  END IF;
  IF NOT (fn_has_role(p_removed_by, 'Administrator') OR fn_is_case_lead(p_removed_by, p_case_id)) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only an administrator or the lead investigator can remove investigators.';
  END IF;

  SELECT is_lead INTO v_is_lead
    FROM case_investigators WHERE case_id = p_case_id AND user_id = p_user_id;

  IF v_is_lead IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This investigator is not assigned to the case.';
  END IF;
  IF v_is_lead = TRUE THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Assign a new lead before removing the current one.';
  END IF;

  DELETE FROM case_investigators WHERE case_id = p_case_id AND user_id = p_user_id;

  INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address)
  VALUES (p_removed_by, 'case.remove_investigator', 'Case', v_reference, 'Success',
          CONCAT('Investigator user ', p_user_id), @app_ip);

  COMMIT;
END$$

-- =====================================================================
-- sp_register_evidence: evidence row + first custody entry (Collected)
-- + optional original hash, all in one transaction.
-- =====================================================================
CREATE PROCEDURE sp_register_evidence(
  IN  p_case_id          INT UNSIGNED,
  IN  p_evidence_type_id SMALLINT UNSIGNED,
  IN  p_description      VARCHAR(500),
  IN  p_source_details   VARCHAR(255),
  IN  p_size_bytes       BIGINT UNSIGNED,
  IN  p_collected_at     DATETIME,
  IN  p_collected_by     INT UNSIGNED,
  IN  p_collection_site  VARCHAR(200),
  IN  p_condition        VARCHAR(200),
  IN  p_seal_number      VARCHAR(30),
  IN  p_hash_value       CHAR(64),
  IN  p_hash_source      VARCHAR(10),
  IN  p_hash_notes       VARCHAR(500),
  IN  p_registered_by    INT UNSIGNED,
  OUT p_evidence_id      INT UNSIGNED,
  OUT p_evidence_code    CHAR(16))
SQL SECURITY INVOKER
BEGIN
  DECLARE v_year   SMALLINT UNSIGNED DEFAULT YEAR(CURDATE());
  DECLARE v_seq    INT UNSIGNED;
  DECLARE v_status VARCHAR(20) DEFAULT NULL;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;

  -- Lock order: sequence row first, then the parent case.
  CALL sp_next_reference('EVIDENCE', v_year, v_seq);

  SELECT status INTO v_status FROM cases WHERE case_id = p_case_id FOR UPDATE;

  IF v_status IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Case not found.';
  END IF;
  IF v_status = 'Closed' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Evidence cannot be added to a closed case.';
  END IF;
  IF NOT (fn_has_role(p_registered_by, 'Administrator')
          OR fn_has_role(p_registered_by, 'Evidence Custodian')
          OR EXISTS (SELECT 1 FROM case_investigators
                      WHERE case_id = p_case_id AND user_id = p_registered_by)) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'You are not allowed to register evidence for this case.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM users WHERE user_id = p_collected_by AND account_status = 'Active') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'The collector must be an active user.';
  END IF;

  SET p_evidence_code = CONCAT('FX-EV-', v_year, '-', LPAD(v_seq, 5, '0'));

  INSERT INTO evidence (evidence_code, case_id, evidence_type_id, description, source_details, size_bytes,
                        collected_at, collected_by, collection_site, collection_condition,
                        current_status, current_custodian_id, current_location_id)
  VALUES (p_evidence_code, p_case_id, p_evidence_type_id, p_description, p_source_details, p_size_bytes,
          p_collected_at, p_collected_by, p_collection_site, p_condition,
          'In Transit', p_collected_by, NULL);
  SET p_evidence_id = LAST_INSERT_ID();

  INSERT INTO chain_of_custody (evidence_id, action, from_custodian_id, to_custodian_id, location_id,
                                location_note, evidence_condition, seal_number, reason, occurred_at, recorded_by)
  VALUES (p_evidence_id, 'Collected', NULL, p_collected_by, NULL,
          p_collection_site, p_condition, p_seal_number, 'Collected at site', p_collected_at, p_registered_by);

  IF p_hash_value IS NOT NULL THEN
    INSERT INTO evidence_hashes (evidence_id, hash_value, source, source_notes, recorded_by)
    VALUES (p_evidence_id, LOWER(p_hash_value), p_hash_source, p_hash_notes, p_registered_by);
  END IF;

  INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address)
  VALUES (p_registered_by, 'evidence.register', 'Evidence', p_evidence_code, 'Success',
          IF(p_hash_value IS NULL, 'No hash recorded yet', 'Original SHA-256 recorded'), @app_ip);

  COMMIT;
END$$

-- =====================================================================
-- sp_transfer_evidence: the core chain-of-custody transaction.
-- =====================================================================
CREATE PROCEDURE sp_transfer_evidence(
  IN  p_evidence_id           INT UNSIGNED,
  IN  p_expected_custodian_id INT UNSIGNED,
  IN  p_action                VARCHAR(20),
  IN  p_to_custodian_id       INT UNSIGNED,
  IN  p_location_id           SMALLINT UNSIGNED,
  IN  p_location_note         VARCHAR(200),
  IN  p_condition             VARCHAR(200),
  IN  p_seal_number           VARCHAR(30),
  IN  p_reason                VARCHAR(500),
  IN  p_occurred_at           DATETIME,
  IN  p_recorded_by           INT UNSIGNED,
  OUT p_custody_id            INT UNSIGNED)
SQL SECURITY INVOKER
BEGIN
  DECLARE v_code       CHAR(16) DEFAULT NULL;
  DECLARE v_status     VARCHAR(20);
  DECLARE v_custodian  INT UNSIGNED;
  DECLARE v_new_status VARCHAR(20);
  DECLARE v_allowed    BOOLEAN DEFAULT FALSE;
  DECLARE v_msg        VARCHAR(128);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;

  -- 1. Lock the evidence row. A concurrent transfer of the same item
  --    waits here until this transaction commits or rolls back.
  SELECT evidence_code, current_status, current_custodian_id
    INTO v_code, v_status, v_custodian
    FROM evidence
   WHERE evidence_id = p_evidence_id
     FOR UPDATE;

  IF v_code IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Evidence item not found.';
  END IF;

  -- 2. Confirm the custodian the user saw is still the custodian.
  IF v_custodian <> p_expected_custodian_id THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Custodian changed by another user. Reload and try again.';
  END IF;

  -- 3. Permission: custodians and administrators record any transfer;
  --    investigators may check out, return or record examination of
  --    items from cases they are assigned to.
  IF NOT (fn_has_role(p_recorded_by, 'Administrator')
          OR fn_has_role(p_recorded_by, 'Evidence Custodian')
          OR (p_action IN ('Checked Out','Examined','Returned')
              AND EXISTS (SELECT 1 FROM case_investigators ci
                            JOIN evidence e ON e.case_id = ci.case_id
                           WHERE e.evidence_id = p_evidence_id
                             AND ci.user_id = p_recorded_by))) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'You are not allowed to record this custody action.';
  END IF;

  -- 4. Is this action allowed from the current status?
  SET v_allowed = CASE p_action
    WHEN 'Received'    THEN v_status IN ('In Transit','Checked Out')
    WHEN 'Transferred' THEN v_status IN ('In Transit','In Storage','Checked Out','Under Examination')
    WHEN 'Checked Out' THEN v_status = 'In Storage'
    WHEN 'Examined'    THEN v_status IN ('Checked Out','Under Examination')
    WHEN 'Returned'    THEN v_status IN ('Checked Out','Under Examination')
    WHEN 'Stored'      THEN v_status IN ('In Transit','In Storage','Checked Out')
    WHEN 'Released'    THEN v_status = 'In Storage'
    WHEN 'Archived'    THEN v_status IN ('In Storage','Released')
    ELSE FALSE
  END;

  IF NOT v_allowed THEN
    SET v_msg = CONCAT('Action "', p_action, '" is not allowed while the item is ', v_status, '.');
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = v_msg;
  END IF;

  SET v_new_status = CASE p_action
    WHEN 'Received'    THEN 'In Storage'
    WHEN 'Stored'      THEN 'In Storage'
    WHEN 'Returned'    THEN 'In Storage'
    WHEN 'Checked Out' THEN 'Checked Out'
    WHEN 'Examined'    THEN 'Under Examination'
    WHEN 'Released'    THEN 'Released'
    WHEN 'Archived'    THEN 'Archived'
    ELSE v_status                       -- Transferred: custodian changes, status does not
  END;

  -- 5. Validate destination custodian and location.
  IF v_new_status = 'In Storage' AND p_location_id IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Choose the storage location the item is going to.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM users WHERE user_id = p_to_custodian_id AND account_status = 'Active') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'The new custodian must be an active user.';
  END IF;
  IF p_location_id IS NOT NULL
     AND NOT EXISTS (SELECT 1 FROM storage_locations WHERE location_id = p_location_id AND is_active = TRUE) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Choose an active storage location.';
  END IF;

  -- 6. Append the custody entry.
  INSERT INTO chain_of_custody (evidence_id, action, from_custodian_id, to_custodian_id, location_id,
                                location_note, evidence_condition, seal_number, reason, occurred_at, recorded_by)
  VALUES (p_evidence_id, p_action, v_custodian, p_to_custodian_id, p_location_id,
          p_location_note, p_condition, p_seal_number, p_reason, COALESCE(p_occurred_at, NOW()), p_recorded_by);
  SET p_custody_id = LAST_INSERT_ID();

  -- 7. Move the evidence's current state in the same transaction.
  UPDATE evidence
     SET current_status       = v_new_status,
         current_custodian_id = p_to_custodian_id,
         current_location_id  = p_location_id
   WHERE evidence_id = p_evidence_id;

  -- 8. Audit, then commit everything together.
  INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address)
  VALUES (p_recorded_by, 'custody.transfer', 'Evidence', v_code, 'Success',
          CONCAT(p_action, ', custody entry #', p_custody_id), @app_ip);

  COMMIT;
END$$

-- =====================================================================
-- sp_record_custody_correction: add a linked correction; the original
-- entry is never changed. If the corrected entry is the item's most
-- recent one, the evidence's current custodian/location follow it.
-- =====================================================================
CREATE PROCEDURE sp_record_custody_correction(
  IN  p_corrects_custody_id INT UNSIGNED,
  IN  p_to_custodian_id     INT UNSIGNED,
  IN  p_location_id         SMALLINT UNSIGNED,
  IN  p_location_note       VARCHAR(200),
  IN  p_condition           VARCHAR(200),
  IN  p_seal_number         VARCHAR(30),
  IN  p_reason              VARCHAR(500),
  IN  p_recorded_by         INT UNSIGNED,
  OUT p_custody_id          INT UNSIGNED)
SQL SECURITY INVOKER
BEGIN
  DECLARE v_evidence_id INT UNSIGNED DEFAULT NULL;
  DECLARE v_action      VARCHAR(20);
  DECLARE v_from        INT UNSIGNED;
  DECLARE v_occurred    DATETIME;
  DECLARE v_code        CHAR(16);
  DECLARE v_latest      INT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;

  SELECT evidence_id, action, from_custodian_id, occurred_at
    INTO v_evidence_id, v_action, v_from, v_occurred
    FROM chain_of_custody WHERE custody_id = p_corrects_custody_id;

  IF v_evidence_id IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Custody entry not found.';
  END IF;

  SELECT evidence_code INTO v_code FROM evidence WHERE evidence_id = v_evidence_id FOR UPDATE;

  IF NOT (fn_has_role(p_recorded_by, 'Administrator') OR fn_has_role(p_recorded_by, 'Evidence Custodian')) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only custodians and administrators can record corrections.';
  END IF;

  -- The correction describes the same event, so it keeps the original
  -- action and occurred_at; recorded_at shows when it was corrected.
  INSERT INTO chain_of_custody (evidence_id, action, from_custodian_id, to_custodian_id, location_id,
                                location_note, evidence_condition, seal_number, reason, occurred_at,
                                recorded_by, corrects_custody_id)
  VALUES (v_evidence_id, v_action, v_from, p_to_custodian_id, p_location_id,
          p_location_note, p_condition, p_seal_number, p_reason, v_occurred,
          p_recorded_by, p_corrects_custody_id);
  SET p_custody_id = LAST_INSERT_ID();

  SELECT custody_id INTO v_latest
    FROM chain_of_custody
   WHERE evidence_id = v_evidence_id
   ORDER BY occurred_at DESC, custody_id DESC
   LIMIT 1;

  IF v_latest = p_custody_id THEN
    UPDATE evidence
       SET current_custodian_id = p_to_custodian_id,
           current_location_id  = p_location_id
     WHERE evidence_id = v_evidence_id;
  END IF;

  INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address)
  VALUES (p_recorded_by, 'custody.correct', 'Evidence', v_code, 'Success',
          CONCAT('Entry #', p_custody_id, ' corrects #', p_corrects_custody_id), @app_ip);

  COMMIT;
END$$

-- =====================================================================
-- sp_approve_account_request: request -> user + role, atomically.
-- =====================================================================
CREATE PROCEDURE sp_approve_account_request(
  IN  p_request_id  INT UNSIGNED,
  IN  p_role_id     TINYINT UNSIGNED,
  IN  p_reviewer_id INT UNSIGNED,
  OUT p_user_id     INT UNSIGNED)
SQL SECURITY INVOKER
BEGIN
  DECLARE v_status   VARCHAR(10) DEFAULT NULL;
  DECLARE v_name     VARCHAR(100);
  DECLARE v_email    VARCHAR(254);
  DECLARE v_username VARCHAR(30);
  DECLARE v_hash     VARCHAR(255);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;

  IF NOT fn_has_role(p_reviewer_id, 'Administrator') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only administrators can approve account requests.';
  END IF;

  SELECT request_status, full_name, email, username, password_hash
    INTO v_status, v_name, v_email, v_username, v_hash
    FROM account_requests
   WHERE request_id = p_request_id
     FOR UPDATE;

  IF v_status IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Account request not found.';
  END IF;
  IF v_status <> 'Pending' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This request has already been reviewed.';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM roles WHERE role_id = p_role_id) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Choose a valid role.';
  END IF;

  -- A duplicate username/email here raises error 1062 -> full rollback.
  INSERT INTO users (full_name, email, username, password_hash)
  VALUES (v_name, v_email, v_username, v_hash);
  SET p_user_id = LAST_INSERT_ID();

  -- The role-change audit row is written by trigger trg_ur_audit_insert.
  SET @app_user_id = p_reviewer_id;
  INSERT INTO user_roles (user_id, role_id, assigned_by)
  VALUES (p_user_id, p_role_id, p_reviewer_id);

  -- The hash now lives only in users (it is never kept in two tables).
  UPDATE account_requests
     SET request_status  = 'Approved',
         reviewed_by     = p_reviewer_id,
         reviewed_at     = NOW(),
         password_hash   = NULL,
         created_user_id = p_user_id
   WHERE request_id = p_request_id;

  INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address)
  VALUES (p_reviewer_id, 'account.approve', 'Account request', CONCAT('AR-', LPAD(p_request_id, 4, '0')),
          'Success', CONCAT('Created user ', v_username), @app_ip);

  COMMIT;
END$$

-- =====================================================================
-- sp_reject_account_request
-- =====================================================================
CREATE PROCEDURE sp_reject_account_request(
  IN p_request_id  INT UNSIGNED,
  IN p_reviewer_id INT UNSIGNED,
  IN p_note        VARCHAR(255))
SQL SECURITY INVOKER
BEGIN
  DECLARE v_status VARCHAR(10) DEFAULT NULL;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;

  IF NOT fn_has_role(p_reviewer_id, 'Administrator') THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only administrators can reject account requests.';
  END IF;

  SELECT request_status INTO v_status
    FROM account_requests WHERE request_id = p_request_id FOR UPDATE;

  IF v_status IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Account request not found.';
  END IF;
  IF v_status <> 'Pending' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'This request has already been reviewed.';
  END IF;

  UPDATE account_requests
     SET request_status = 'Rejected',
         reviewed_by    = p_reviewer_id,
         reviewed_at    = NOW(),
         review_note    = p_note,
         password_hash  = NULL
   WHERE request_id = p_request_id;

  INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address)
  VALUES (p_reviewer_id, 'account.reject', 'Account request', CONCAT('AR-', LPAD(p_request_id, 4, '0')),
          'Success', p_note, @app_ip);

  COMMIT;
END$$

-- =====================================================================
-- sp_close_case: close only when no work or evidence is outstanding.
-- =====================================================================
CREATE PROCEDURE sp_close_case(
  IN p_case_id   INT UNSIGNED,
  IN p_summary   VARCHAR(1000),
  IN p_closed_by INT UNSIGNED)
SQL SECURITY INVOKER
BEGIN
  DECLARE v_status    VARCHAR(20) DEFAULT NULL;
  DECLARE v_reference CHAR(12);
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;

  SELECT status, case_reference INTO v_status, v_reference
    FROM cases WHERE case_id = p_case_id FOR UPDATE;

  IF v_status IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Case not found.';
  END IF;
  IF v_status = 'Closed' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'The case is already closed.';
  END IF;
  IF NOT (fn_has_role(p_closed_by, 'Administrator') OR fn_is_case_lead(p_closed_by, p_case_id)) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only an administrator or the lead investigator can close a case.';
  END IF;
  IF p_summary IS NULL OR CHAR_LENGTH(TRIM(p_summary)) = 0 THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'A closure summary is required.';
  END IF;
  IF EXISTS (SELECT 1 FROM examinations
              WHERE case_id = p_case_id AND status IN ('Pending','In Progress','Under Review')) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Complete or cancel all examinations (including those under review) before closing the case.';
  END IF;
  IF EXISTS (SELECT 1 FROM evidence
              WHERE case_id = p_case_id
                AND current_status IN ('In Transit','Checked Out','Under Examination')) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Return all evidence to storage before closing the case.';
  END IF;

  UPDATE cases
     SET status = 'Closed', closed_at = NOW(), closure_summary = p_summary
   WHERE case_id = p_case_id;

  INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address)
  VALUES (p_closed_by, 'case.close', 'Case', v_reference, 'Success', 'Case closed', @app_ip);

  COMMIT;
END$$

-- =====================================================================
-- sp_create_report: report header + version 1 in one transaction.
-- =====================================================================
CREATE PROCEDURE sp_create_report(
  IN  p_case_id      INT UNSIGNED,
  IN  p_title        VARCHAR(200),
  IN  p_author_id    INT UNSIGNED,
  IN  p_methodology  TEXT,
  IN  p_observations TEXT,
  IN  p_findings     TEXT,
  IN  p_conclusions  TEXT,
  IN  p_limitations  TEXT,
  OUT p_report_id    INT UNSIGNED,
  OUT p_report_code  CHAR(12))
SQL SECURITY INVOKER
BEGIN
  DECLARE v_year   SMALLINT UNSIGNED DEFAULT YEAR(CURDATE());
  DECLARE v_seq    INT UNSIGNED;
  DECLARE v_status VARCHAR(20) DEFAULT NULL;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;

  CALL sp_next_reference('REPORT', v_year, v_seq);

  SELECT status INTO v_status FROM cases WHERE case_id = p_case_id FOR UPDATE;
  IF v_status IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Case not found.';
  END IF;
  IF NOT (fn_has_role(p_author_id, 'Administrator')
          OR EXISTS (SELECT 1 FROM case_investigators WHERE case_id = p_case_id AND user_id = p_author_id)) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only investigators on this case can write its reports.';
  END IF;

  SET p_report_code = CONCAT('RP-', v_year, '-', LPAD(v_seq, 4, '0'));

  INSERT INTO forensic_reports (report_code, case_id, title, author_id, status)
  VALUES (p_report_code, p_case_id, p_title, p_author_id, 'Draft');
  SET p_report_id = LAST_INSERT_ID();

  INSERT INTO report_versions (report_id, version_no, methodology, observations, findings,
                               conclusions, limitations, change_note, created_by)
  VALUES (p_report_id, 1, p_methodology, p_observations, p_findings,
          p_conclusions, p_limitations, 'First draft', p_author_id);

  INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address)
  VALUES (p_author_id, 'report.create', 'Report', p_report_code, 'Success', 'Version 1 created', @app_ip);

  COMMIT;
END$$

-- =====================================================================
-- sp_create_report_version: next immutable version of a Draft report.
-- =====================================================================
CREATE PROCEDURE sp_create_report_version(
  IN  p_report_id    INT UNSIGNED,
  IN  p_methodology  TEXT,
  IN  p_observations TEXT,
  IN  p_findings     TEXT,
  IN  p_conclusions  TEXT,
  IN  p_limitations  TEXT,
  IN  p_change_note  VARCHAR(255),
  IN  p_created_by   INT UNSIGNED,
  OUT p_version_no   SMALLINT UNSIGNED)
SQL SECURITY INVOKER
BEGIN
  DECLARE v_status VARCHAR(20) DEFAULT NULL;
  DECLARE v_code   CHAR(12);
  DECLARE v_author INT UNSIGNED;
  DECLARE EXIT HANDLER FOR SQLEXCEPTION
  BEGIN
    ROLLBACK;
    RESIGNAL;
  END;

  START TRANSACTION;

  -- Lock the report so two editors cannot both create "version N+1".
  SELECT status, report_code, author_id INTO v_status, v_code, v_author
    FROM forensic_reports WHERE report_id = p_report_id FOR UPDATE;

  IF v_status IS NULL THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Report not found.';
  END IF;
  IF v_status <> 'Draft' THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Return the report to Draft before editing it.';
  END IF;
  IF NOT (p_created_by = v_author OR fn_has_role(p_created_by, 'Administrator')) THEN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only the author or an administrator can revise this report.';
  END IF;

  SELECT COALESCE(MAX(version_no), 0) + 1 INTO p_version_no
    FROM report_versions WHERE report_id = p_report_id;

  INSERT INTO report_versions (report_id, version_no, methodology, observations, findings,
                               conclusions, limitations, change_note, created_by)
  VALUES (p_report_id, p_version_no, p_methodology, p_observations, p_findings,
          p_conclusions, p_limitations, p_change_note, p_created_by);

  UPDATE forensic_reports SET updated_at = NOW() WHERE report_id = p_report_id;

  INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address)
  VALUES (p_created_by, 'report.revise', 'Report', v_code, 'Success',
          CONCAT('Version ', p_version_no, ': ', p_change_note), @app_ip);

  COMMIT;
END$$

DELIMITER ;
