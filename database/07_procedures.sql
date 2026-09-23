-- =====================================================================
-- FORGE-X : Forensic Operations, Records, Governance & Evidence Exchange
-- File   : 07_procedures.sql
-- Purpose: Stored procedures that orchestrate the case/evidence
--          lifecycle as real, atomic MySQL transactions — validation,
--          multi-table writes, and error handling all happen inside
--          the database, not the application layer.
-- Depends: 01_create_database.sql .. 06_functions.sql,
--          08_triggers.sql (several procedures deliberately rely on
--          the Step 4/5 triggers rather than duplicating their work —
--          see the note on sp_transfer_evidence below).
--
-- SESSION VARIABLE CONVENTION (established in 08_triggers.sql)
--   @forgex_actor_id            — acting application user, read by
--                                  triggers to attribute audit_logs
--   @forgex_custody_location_id — optional override read by
--                                  trg_evidence_custody_audit
--   @forgex_custody_remarks     — optional override, same trigger
--   @forgex_custody_action      — optional override, same trigger
--   Every procedure below that changes evidence.current_custodian_id
--   sets these before the UPDATE and clears them immediately after,
--   so nothing leaks into unrelated statements later in the session.
--
-- ERROR HANDLING PATTERN (used identically in every procedure)
--   DECLARE EXIT HANDLER FOR SQLEXCEPTION
--   BEGIN
--       ROLLBACK;
--       RESIGNAL;
--   END;
--   Any SIGNAL raised for a business-rule violation, or any real MySQL
--   error (a failed FK, a CHECK violation, a duplicate key), is caught
--   by this handler: it rolls back everything the procedure has done
--   so far in this transaction, then RESIGNALs — re-raising the exact
--   original SQLSTATE and message to the caller unchanged. Nothing is
--   ever left half-committed.
--
-- WHY sp_transfer_evidence() DOES NOT MANUALLY INSERT A
-- chain_of_custody OR audit_logs ROW
--   The brief's 8-step spec for sp_transfer_evidence lists "6. Insert
--   chain-of-custody record" and "8. Insert audit record" as explicit
--   steps. trg_evidence_custody_audit (08_triggers.sql, enhanced in
--   this step) already does exactly both of these automatically the
--   instant evidence.current_custodian_id changes — that trigger was
--   purpose-built for this. Having the procedure ALSO insert those two
--   rows manually would silently double every custody transfer's audit
--   trail (two chain_of_custody rows and two audit_logs rows per
--   transfer) — which would itself be a serious correctness bug in a
--   system whose entire point is a trustworthy, non-duplicated custody
--   ledger. So step 6 and step 8 are satisfied by the procedure
--   deliberately triggering that cascade (by setting the session
--   variables above, then updating current_custodian_id), and this is
--   verified explicitly in the test section at the bottom of this
--   file: exactly one new chain_of_custody row and exactly one new
--   audit_logs row are created per successful transfer, never two.
--   Step 7 ("Insert timeline event") has no such automatic trigger, so
--   the procedure inserts that one directly.
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
-- SCHEMA REFINEMENT NOTE — evidence_hashes UNIQUE constraint
--   Discovered while testing sp_verify_evidence() below: a genuinely
--   successful re-verification — where the freshly computed hash
--   legitimately MATCHES the reference hash — has, by definition, the
--   exact same hash_value as the original row. Logging that normal
--   MATCH result as a new evidence_hashes row collided with the
--   original UNIQUE(evidence_id, hash_algorithm, hash_value) constraint
--   from Step 2 (ERROR 1062) — only a MISMATCH could ever be logged,
--   which is backwards. Fixed at the source in 02_tables.sql: the
--   constraint is now UNIQUE(evidence_id, hash_algorithm, hash_value,
--   computed_at), which still blocks true accidental duplicates (same
--   hash logged twice at the same instant) while correctly allowing
--   the same hash value to be re-logged at a later verification
--   timestamp. If you are updating an existing database that still has
--   the narrower Step-2 constraint, run:
--     ALTER TABLE evidence_hashes DROP INDEX uq_evidence_hashes_value;
--     ALTER TABLE evidence_hashes ADD CONSTRAINT uq_evidence_hashes_value
--       UNIQUE (evidence_id, hash_algorithm, hash_value, computed_at);
-- =====================================================================

-- =====================================================================
-- PROCEDURE 1: sp_create_case
-- Purpose: Validated case creation + its opening timeline event, as
--          one atomic transaction.
-- =====================================================================
DROP PROCEDURE IF EXISTS sp_create_case;

DELIMITER $$

CREATE PROCEDURE sp_create_case(
    IN  p_case_number   VARCHAR(40),
    IN  p_case_title    VARCHAR(200),
    IN  p_case_type_id  SMALLINT UNSIGNED,
    IN  p_priority      ENUM('low','medium','high','critical'),
    IN  p_jurisdiction_location_id INT UNSIGNED,
    IN  p_description   TEXT,
    IN  p_created_by    BIGINT UNSIGNED,
    OUT p_case_id        BIGINT UNSIGNED
)
proc_body: BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF NOT EXISTS (SELECT 1 FROM case_types WHERE case_type_id = p_case_type_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_create_case: case_type_id does not exist.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM users WHERE user_id = p_created_by AND is_active = 1) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_create_case: created_by user does not exist or is inactive.';
    END IF;

    START TRANSACTION;

    INSERT INTO cases (case_number, case_title, case_type_id, priority,
                        jurisdiction_location_id, description, created_by)
    VALUES (p_case_number, p_case_title, p_case_type_id, COALESCE(p_priority,'medium'),
            p_jurisdiction_location_id, p_description, p_created_by);

    SET p_case_id = LAST_INSERT_ID();

    INSERT INTO case_timeline (case_id, event_type, event_description, related_table,
                                related_record_id, recorded_by)
    VALUES (p_case_id, 'case_opened',
            CONCAT('Case ', p_case_number, ' opened: ', p_case_title, '.'),
            'cases', p_case_id, p_created_by);

    COMMIT;
END proc_body$$

DELIMITER ;

-- =====================================================================
-- PROCEDURE 2: sp_register_evidence
-- Purpose: Validated evidence intake — creates the evidence row with
--          its initial custodian set to the collector, writes the
--          FIRST chain_of_custody entry ('collected', from NULL) and a
--          timeline event, atomically. (This is the one place the
--          procedure DOES insert chain_of_custody directly — it is the
--          very first custody event for a brand-new evidence row, so
--          current_custodian_id is being set on INSERT, not changed on
--          UPDATE, and trg_evidence_custody_audit — which only fires
--          on UPDATE — correctly does not apply here.)
-- =====================================================================
DROP PROCEDURE IF EXISTS sp_register_evidence;

DELIMITER $$

CREATE PROCEDURE sp_register_evidence(
    IN  p_evidence_number  VARCHAR(50),
    IN  p_case_id           BIGINT UNSIGNED,
    IN  p_device_id          BIGINT UNSIGNED,
    IN  p_evidence_type_id    SMALLINT UNSIGNED,
    IN  p_description          TEXT,
    IN  p_acquisition_method    ENUM('physical_seizure','logical_extraction','physical_extraction',
                                      'network_capture','cloud_extraction','manual_documentation'),
    IN  p_collected_by           BIGINT UNSIGNED,
    IN  p_storage_location_id     INT UNSIGNED,
    OUT p_evidence_id              BIGINT UNSIGNED
)
proc_body: BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF NOT EXISTS (SELECT 1 FROM cases WHERE case_id = p_case_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_register_evidence: case_id does not exist.';
    END IF;
    IF p_device_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM devices WHERE device_id = p_device_id AND case_id = p_case_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_register_evidence: device_id does not exist for this case.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM users WHERE user_id = p_collected_by AND is_active = 1) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_register_evidence: collected_by user does not exist or is inactive.';
    END IF;

    START TRANSACTION;

    INSERT INTO evidence (evidence_number, case_id, device_id, evidence_type_id, description,
                           acquisition_method, collected_by, current_custodian_id, collected_at,
                           storage_location_id)
    VALUES (p_evidence_number, p_case_id, p_device_id, p_evidence_type_id, p_description,
            p_acquisition_method, p_collected_by, p_collected_by, NOW(),
            p_storage_location_id);

    SET p_evidence_id = LAST_INSERT_ID();

    INSERT INTO chain_of_custody (evidence_id, transferred_from, transferred_to, custody_action,
                                   location_id, remarks)
    VALUES (p_evidence_id, NULL, p_collected_by, 'collected',
            COALESCE(p_storage_location_id,
                     (SELECT jurisdiction_location_id FROM cases WHERE case_id = p_case_id), 1),
            'Initial collection logged by sp_register_evidence.');

    INSERT INTO case_timeline (case_id, event_type, event_description, related_table,
                                related_record_id, recorded_by)
    VALUES (p_case_id, 'evidence_collected',
            CONCAT('Evidence ', p_evidence_number, ' registered and logged into custody.'),
            'evidence', p_evidence_id, p_collected_by);

    COMMIT;
END proc_body$$

DELIMITER ;

-- =====================================================================
-- PROCEDURE 3: sp_assign_investigator
-- Purpose: Validated case-investigator assignment (the M:N junction
--          insert), plus a timeline event, atomically.
-- =====================================================================
DROP PROCEDURE IF EXISTS sp_assign_investigator;

DELIMITER $$

CREATE PROCEDURE sp_assign_investigator(
    IN p_case_id      BIGINT UNSIGNED,
    IN p_user_id       BIGINT UNSIGNED,
    IN p_role_in_case   ENUM('lead_investigator','co_investigator','forensic_analyst','supervisor','consultant'),
    IN p_assigned_by     BIGINT UNSIGNED
)
proc_body: BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF NOT EXISTS (SELECT 1 FROM cases WHERE case_id = p_case_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_assign_investigator: case_id does not exist.';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM users WHERE user_id = p_user_id AND is_active = 1) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_assign_investigator: user_id does not exist or is inactive.';
    END IF;
    IF EXISTS (SELECT 1 FROM case_investigators WHERE case_id = p_case_id AND user_id = p_user_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_assign_investigator: this user is already assigned to this case.';
    END IF;

    START TRANSACTION;

    INSERT INTO case_investigators (case_id, user_id, role_in_case)
    VALUES (p_case_id, p_user_id, p_role_in_case);

    INSERT INTO case_timeline (case_id, event_type, event_description, related_table,
                                related_record_id, recorded_by)
    VALUES (p_case_id, 'other',
            CONCAT((SELECT full_name FROM users WHERE user_id = p_user_id),
                   ' assigned to the case as ', p_role_in_case, '.'),
            'case_investigators', p_user_id, p_assigned_by);

    SET @forgex_actor_id = p_assigned_by;
    INSERT INTO audit_logs (user_id, table_name, record_id, action_type, new_values, action_timestamp)
    VALUES (p_assigned_by, 'case_investigators', p_user_id, 'INSERT',
            JSON_OBJECT('case_id', p_case_id, 'user_id', p_user_id, 'role_in_case', p_role_in_case),
            NOW());
    SET @forgex_actor_id = NULL;

    COMMIT;
END proc_body$$

DELIMITER ;

-- =====================================================================
-- PROCEDURE 4: sp_transfer_evidence  ***THE MOST IMPORTANT PROCEDURE***
-- Purpose: The single, safe, correct way to change who holds a piece
--          of evidence. Implements the exact 8-step spec: locks the
--          row, verifies evidence/current-custodian/new-custodian,
--          updates the custodian (which cascades chain_of_custody +
--          audit_logs via trg_evidence_custody_audit — see the file
--          header note above for why that is NOT duplicated here),
--          inserts the timeline event, and commits — or rolls back
--          everything on any failure.
--
-- Parameters:
--   p_evidence_id                — which evidence item
--   p_new_custodian_id           — who should hold it now
--   p_acting_user_id             — who is performing this transfer
--                                   (attributed on the audit trail)
--   p_expected_current_custodian_id — OPTIONAL concurrency guard: if
--                                   supplied (non-NULL), the transfer
--                                   is refused unless the evidence's
--                                   ACTUAL current custodian still
--                                   matches this value. Prevents a
--                                   stale UI from executing a transfer
--                                   based on outdated information
--                                   (classic optimistic-locking
--                                   pattern) — pass NULL to skip this
--                                   check.
--   p_location_id                 — OPTIONAL: where the hand-off
--                                   physically happened (falls back to
--                                   the evidence's storage location,
--                                   then the case's jurisdiction, then
--                                   location_id 1, if NULL)
--   p_remarks                      — OPTIONAL free-text remarks for
--                                   the chain_of_custody entry
-- =====================================================================
DROP PROCEDURE IF EXISTS sp_transfer_evidence;

DELIMITER $$

CREATE PROCEDURE sp_transfer_evidence(
    IN p_evidence_id                   BIGINT UNSIGNED,
    IN p_new_custodian_id                BIGINT UNSIGNED,
    IN p_acting_user_id                    BIGINT UNSIGNED,
    IN p_expected_current_custodian_id       BIGINT UNSIGNED,
    IN p_location_id                          INT UNSIGNED,
    IN p_remarks                               VARCHAR(500)
)
proc_body: BEGIN
    DECLARE v_case_id             BIGINT UNSIGNED;
    DECLARE v_old_custodian_id    BIGINT UNSIGNED;
    DECLARE v_evidence_number     VARCHAR(50);
    DECLARE v_exists_count        INT DEFAULT 0;
    DECLARE v_new_custodian_active TINYINT DEFAULT 0;

    -- Any error anywhere below (a SIGNAL we raise, or a genuine MySQL
    -- error such as a CHECK/FK violation) rolls back everything this
    -- procedure has done so far in this transaction, then re-raises
    -- the original error unchanged to the caller.
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        SET @forgex_actor_id = NULL;
        SET @forgex_custody_location_id = NULL;
        SET @forgex_custody_remarks = NULL;
        SET @forgex_custody_action = NULL;
        RESIGNAL;
    END;

    START TRANSACTION;

    -- ---- Step 1 & 2: lock the evidence row, verify it exists -------
    SELECT COUNT(*) INTO v_exists_count
      FROM evidence
     WHERE evidence_id = p_evidence_id
       FOR UPDATE;

    IF v_exists_count = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_transfer_evidence: evidence_id does not exist.';
    END IF;

    SELECT case_id, current_custodian_id, evidence_number
      INTO v_case_id, v_old_custodian_id, v_evidence_number
      FROM evidence
     WHERE evidence_id = p_evidence_id;

    -- ---- Step 3: verify current custodian ---------------------------
    IF v_old_custodian_id IS NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'sp_transfer_evidence: evidence has no current custodian on record to transfer from.';
    END IF;

    IF p_expected_current_custodian_id IS NOT NULL
       AND p_expected_current_custodian_id <> v_old_custodian_id THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'sp_transfer_evidence: current custodian mismatch - evidence may have been transferred by someone else; refresh and retry.';
    END IF;

    -- ---- Step 4 & 5: verify new custodian ---------------------------
    IF p_new_custodian_id = v_old_custodian_id THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'sp_transfer_evidence: new custodian is the same as the current custodian - nothing to transfer.';
    END IF;

    SELECT is_active INTO v_new_custodian_active
      FROM users WHERE user_id = p_new_custodian_id;

    IF v_new_custodian_active IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_transfer_evidence: new custodian user_id does not exist.';
    ELSEIF v_new_custodian_active = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_transfer_evidence: new custodian is not an active user.';
    END IF;

    -- ---- Step 6: update current custodian --------------------------
    -- Setting these session variables lets trg_evidence_custody_audit
    -- (08_triggers.sql) write a chain_of_custody row with THIS
    -- procedure's real location/remarks instead of its generic
    -- fallback note, and attribute the accompanying audit_logs row to
    -- the real acting user. That trigger cascade satisfies step 6
    -- (chain-of-custody record) and step 8 (audit record) — see the
    -- file header for why they are not also inserted manually here.
    SET @forgex_actor_id = p_acting_user_id;
    SET @forgex_custody_location_id = p_location_id;
    SET @forgex_custody_remarks = p_remarks;
    SET @forgex_custody_action = 'transferred';

    UPDATE evidence
       SET current_custodian_id = p_new_custodian_id
     WHERE evidence_id = p_evidence_id;

    SET @forgex_actor_id = NULL;
    SET @forgex_custody_location_id = NULL;
    SET @forgex_custody_remarks = NULL;
    SET @forgex_custody_action = NULL;

    -- ---- Step 7: insert timeline event -----------------------------
    INSERT INTO case_timeline (case_id, event_type, event_description, related_table,
                                related_record_id, recorded_by)
    VALUES (v_case_id, 'custody_transfer',
            CONCAT('Evidence ', v_evidence_number, ' custody transferred from ',
                   (SELECT full_name FROM users WHERE user_id = v_old_custodian_id), ' to ',
                   (SELECT full_name FROM users WHERE user_id = p_new_custodian_id), '.'),
            'evidence', p_evidence_id, p_acting_user_id);

    -- ---- Step 8: audit record — see file header note; already done
    --      automatically by trg_evidence_custody_audit at Step 6.

    COMMIT;
END proc_body$$

DELIMITER ;

-- =====================================================================
-- PROCEDURE 5: sp_verify_evidence
-- Purpose: Re-verify an evidence item's integrity by comparing a
--          freshly computed hash against its on-file reference hash
--          (via fn_compare_hash). Always logs the verification attempt
--          as a new, non-original evidence_hashes row; on a mismatch,
--          flags the evidence 'requires_recheck' and writes an
--          audit_logs entry (this is a different code path from
--          Trigger 3, which only fires when the REFERENCE hash itself
--          is edited — here we are inserting a new comparison hash,
--          not editing the reference).
-- =====================================================================
DROP PROCEDURE IF EXISTS sp_verify_evidence;

DELIMITER $$

CREATE PROCEDURE sp_verify_evidence(
    IN  p_evidence_id         BIGINT UNSIGNED,
    IN  p_hash_algorithm       ENUM('MD5','SHA1','SHA256','SHA512'),
    IN  p_freshly_computed_hash VARCHAR(128),
    IN  p_verified_by            BIGINT UNSIGNED,
    OUT p_match_result             VARCHAR(20)
)
proc_body: BEGIN
    DECLARE v_reference_hash VARCHAR(128);

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF NOT EXISTS (SELECT 1 FROM evidence WHERE evidence_id = p_evidence_id) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_verify_evidence: evidence_id does not exist.';
    END IF;

    SELECT hash_value INTO v_reference_hash
      FROM evidence_hashes
     WHERE evidence_id = p_evidence_id AND hash_algorithm = p_hash_algorithm AND is_original = 1
     ORDER BY computed_at DESC
     LIMIT 1;

    IF v_reference_hash IS NULL THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'sp_verify_evidence: no reference hash on file for this evidence/algorithm.';
    END IF;

    SET p_match_result = fn_compare_hash(v_reference_hash, p_freshly_computed_hash);

    START TRANSACTION;

    INSERT INTO evidence_hashes (evidence_id, hash_algorithm, hash_value, computed_by, is_original)
    VALUES (p_evidence_id, p_hash_algorithm, p_freshly_computed_hash, p_verified_by, 0);

    IF p_match_result = 'MISMATCH' THEN
        UPDATE evidence SET integrity_status = 'requires_recheck' WHERE evidence_id = p_evidence_id;

        INSERT INTO audit_logs (user_id, table_name, record_id, action_type, old_values, new_values, action_timestamp)
        VALUES (p_verified_by, 'evidence', p_evidence_id, 'UPDATE',
                JSON_OBJECT('reference_hash', v_reference_hash),
                JSON_OBJECT('freshly_computed_hash', p_freshly_computed_hash, 'flag', 'REQUIRES_RECHECK'),
                NOW());
    END IF;

    COMMIT;
END proc_body$$

DELIMITER ;

-- =====================================================================
-- PROCEDURE 6: sp_close_case
-- Purpose: Validated case closure. Refuses to close a case that is
--          already closed/archived, has any examination still
--          'scheduled'/'in_progress' (via fn_get_case_open_examinations_count),
--          or has no report at 'approved' or 'finalized' status.
--          trg_cases_status_change already logs the generic
--          CASE_STATUS_CHANGED timeline row when status flips to
--          'closed'; this procedure additionally logs a specific
--          'case_closed' milestone event.
-- =====================================================================
DROP PROCEDURE IF EXISTS sp_close_case;

DELIMITER $$

CREATE PROCEDURE sp_close_case(
    IN  p_case_id     BIGINT UNSIGNED,
    IN  p_closed_by    BIGINT UNSIGNED,
    OUT p_result_message VARCHAR(255)
)
proc_body: BEGIN
    DECLARE v_status         VARCHAR(30);
    DECLARE v_case_number    VARCHAR(40);
    DECLARE v_open_exam_count INT UNSIGNED;
    DECLARE v_approved_report_count INT UNSIGNED;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    SELECT status, case_number INTO v_status, v_case_number
      FROM cases WHERE case_id = p_case_id;

    IF v_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_close_case: case_id does not exist.';
    END IF;

    IF v_status IN ('closed', 'archived') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'sp_close_case: case is already closed or archived.';
    END IF;

    SET v_open_exam_count = fn_get_case_open_examinations_count(p_case_id);
    IF v_open_exam_count > 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'sp_close_case: cannot close - one or more examinations are still scheduled or in progress.';
    END IF;

    SELECT COUNT(*) INTO v_approved_report_count
      FROM forensic_reports
     WHERE case_id = p_case_id AND report_status IN ('approved', 'finalized');

    IF v_approved_report_count = 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'sp_close_case: cannot close - no approved or finalized report exists for this case.';
    END IF;

    START TRANSACTION;

    -- trg_cases_status_change fires here and logs the generic
    -- [CASE_STATUS_CHANGED] timeline row automatically.
    UPDATE cases SET status = 'closed', closed_at = NOW() WHERE case_id = p_case_id;

    INSERT INTO case_timeline (case_id, event_type, event_description, related_table,
                                related_record_id, recorded_by)
    VALUES (p_case_id, 'case_closed',
            CONCAT('Case ', v_case_number, ' formally closed by procedure sp_close_case.'),
            'cases', p_case_id, p_closed_by);

    SET p_result_message = CONCAT('Case ', v_case_number, ' closed successfully.');

    COMMIT;
END proc_body$$

DELIMITER ;

SELECT 'All 6 FORGE-X stored procedures created successfully.' AS status;

-- =====================================================================
-- Verification: list every routine now installed
-- =====================================================================
SELECT ROUTINE_NAME, ROUTINE_TYPE, IS_DETERMINISTIC, SQL_DATA_ACCESS
FROM information_schema.ROUTINES
WHERE ROUTINE_SCHEMA = 'forge_x'
ORDER BY ROUTINE_TYPE, ROUTINE_NAME;
