-- =====================================================================
-- FORGE-X : Forensic Operations, Records, Governance & Evidence Exchange
-- File   : 08_triggers.sql
-- Purpose: MySQL triggers that make the evidence lifecycle self-auditing
--          at the database layer — none of this logic lives in
--          application code; it genuinely happens inside MySQL.
-- Depends: 01_create_database.sql .. 04_indexes.sql (09_seed_data.sql
--          is recommended before testing, so there is real custody
--          history to exercise the triggers against).
--
-- SCHEMA EXTENSIONS REQUIRED FOR THIS PHASE
--   Two small, deliberate schema additions are made below before the
--   triggers themselves, because the trigger brief genuinely needs
--   columns/values that did not exist at the end of Step 3:
--
--   1. evidence.current_custodian_id (new column) — Trigger 1 fires
--      "when the current custodian of evidence changes". Our custody
--      model up to Step 3 was a pure insert-only ledger
--      (chain_of_custody) with no single "who has it right now"
--      pointer to detect a *change* against. Adding this FK column
--      gives evidence a fast "current holder" pointer; the trigger
--      below is what keeps chain_of_custody synchronized with it
--      automatically, so the two can never drift apart.
--
--   2. evidence.integrity_status gains a 4th domain value,
--      'requires_recheck' — Trigger 3 must set this exact status when
--      a reference hash changes. It didn't exist in the ENUM/CHECK
--      domain defined in Step 2/3, so both are extended here.
--
--   IMPORTANT MYSQL LIMITATION (discovered during testing, documented
--   here so it isn't rediscovered the hard way): a trigger cannot
--   modify a table that the *invoking* statement itself already reads
--   from — e.g. `UPDATE evidence_hashes SET ... WHERE evidence_id =
--   (SELECT evidence_id FROM evidence WHERE ...)` fails with
--   ERROR 1442 the moment trg_evidence_hashes_reference_change tries
--   to `UPDATE evidence`, because that top-level statement already
--   touched `evidence` in its own subquery. This is not a flaw in the
--   trigger — real application code looks up a target row's ID first
--   (`SELECT hash_id FROM ... WHERE ...`) and then issues a clean
--   `UPDATE evidence_hashes SET ... WHERE hash_id = ?`, which never
--   references `evidence` at all and triggers correctly. MySQL rolls
--   the whole statement back atomically if this is hit, so it fails
--   safely either way.
--
-- SESSION VARIABLE CONVENTION: @forgex_actor_id
--   audit_logs.user_id and several trigger-written rows need to record
--   *which application user* caused a change. A trigger only sees the
--   MySQL connection's DB user (usually a shared service account), not
--   the individual investigator using the app — so the application is
--   expected to run `SET @forgex_actor_id = <user_id>;` once per
--   session/request before its writes. Every trigger below falls back
--   to a sensible column-derived default (e.g. the row's own
--   collected_by/created_by) if the app forgot to set it, so nothing
--   ever fails purely because this session variable is absent.
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
-- SCHEMA EXTENSION 1 — evidence.current_custodian_id
-- =====================================================================
ALTER TABLE evidence
    ADD COLUMN current_custodian_id BIGINT UNSIGNED NULL
        COMMENT 'FK to users; who currently holds this evidence. Kept in sync with chain_of_custody by trg_evidence_custody_audit.'
        AFTER collected_by;

ALTER TABLE evidence
    ADD CONSTRAINT fk_evidence_current_custodian
        FOREIGN KEY (current_custodian_id) REFERENCES users (user_id)
        ON DELETE RESTRICT ON UPDATE RESTRICT;

-- Backfill: set each evidence item's current custodian to whoever holds
-- it last, according to the custody history already on record (safe
-- no-op / sets nothing if chain_of_custody is empty). Uses a window
-- function (ROW_NUMBER) to pick each evidence item's most recent
-- custody event.
UPDATE evidence e
JOIN (
    SELECT evidence_id, transferred_to,
           ROW_NUMBER() OVER (PARTITION BY evidence_id ORDER BY custody_timestamp DESC, custody_id DESC) AS rn
    FROM chain_of_custody
) latest
    ON latest.evidence_id = e.evidence_id AND latest.rn = 1
SET e.current_custodian_id = latest.transferred_to;

SELECT 'Schema extension 1 complete: evidence.current_custodian_id added and backfilled.' AS status;

-- =====================================================================
-- SCHEMA EXTENSION 2 — evidence.integrity_status gains 'requires_recheck'
-- =====================================================================
ALTER TABLE evidence
    MODIFY COLUMN integrity_status
        ENUM('intact','compromised','under_verification','requires_recheck')
        NOT NULL DEFAULT 'intact';

-- The named CHECK from 03_constraints.sql must be redefined to match
-- the widened domain (MODIFY COLUMN does not update it automatically).
ALTER TABLE evidence DROP CHECK chk_evidence_integrity_status_valid_values;
ALTER TABLE evidence
    ADD CONSTRAINT chk_evidence_integrity_status_valid_values
    CHECK (integrity_status IN ('intact','compromised','under_verification','requires_recheck'));

SELECT 'Schema extension 2 complete: integrity_status domain now includes requires_recheck.' AS status;

-- =====================================================================
-- TRIGGER 1 — EVIDENCE CUSTODY AUDIT
--   Fires whenever evidence.current_custodian_id actually changes to a
--   new, non-NULL value. Automatically appends the authoritative
--   custody-transfer record to chain_of_custody (evidence ID, previous
--   custodian, new custodian, timestamp) AND a matching audit_logs
--   entry — so chain_of_custody can never fall out of sync with the
--   "who has it now" pointer, because the application never writes to
--   chain_of_custody directly for a routine hand-off; it just updates
--   the pointer and MySQL does the rest.
--
--   ENHANCED IN STEP 5 (07_procedures.sql / sp_transfer_evidence):
--   three more optional session variables let a well-behaved caller
--   pass through richer, caller-supplied context instead of the
--   generic auto-note this trigger falls back to on a bare UPDATE:
--     @forgex_custody_location_id — where the hand-off actually happened
--     @forgex_custody_remarks     — a real remarks string
--     @forgex_custody_action      — override the default 'transferred'
--   All three are optional; if unset, behavior is byte-for-byte
--   identical to the original Step 4 version (re-verified below).
-- =====================================================================
DROP TRIGGER IF EXISTS trg_evidence_custody_audit;

DELIMITER $$

CREATE TRIGGER trg_evidence_custody_audit
    AFTER UPDATE ON evidence
    FOR EACH ROW
BEGIN
    IF NEW.current_custodian_id IS NOT NULL
       AND NOT (NEW.current_custodian_id <=> OLD.current_custodian_id) THEN

        INSERT INTO chain_of_custody
            (evidence_id, transferred_from, transferred_to, custody_action,
             location_id, custody_timestamp, remarks)
        VALUES
            (NEW.evidence_id, OLD.current_custodian_id, NEW.current_custodian_id,
             COALESCE(@forgex_custody_action, 'transferred'),
             COALESCE(@forgex_custody_location_id,
                       NEW.storage_location_id,
                       (SELECT jurisdiction_location_id FROM cases WHERE case_id = NEW.case_id),
                       1),
             NOW(),
             COALESCE(@forgex_custody_remarks,
                       CONCAT('Auto-logged by trg_evidence_custody_audit: custodian changed from user ',
                              COALESCE(OLD.current_custodian_id, 0), ' to user ', NEW.current_custodian_id, '.')));

        INSERT INTO audit_logs
            (user_id, table_name, record_id, action_type, old_values, new_values, action_timestamp)
        VALUES
            (COALESCE(@forgex_actor_id, NEW.current_custodian_id),
             'evidence', NEW.evidence_id, 'UPDATE',
             JSON_OBJECT('current_custodian_id', OLD.current_custodian_id),
             JSON_OBJECT('current_custodian_id', NEW.current_custodian_id),
             NOW());
    END IF;
END$$

DELIMITER ;

-- =====================================================================
-- TRIGGER 2 — CASE STATUS CHANGE
--   Fires whenever cases.status changes. Automatically inserts a
--   CASE_STATUS_CHANGED event into case_timeline. (case_timeline's
--   event_type ENUM already has a 'status_change' value from Step 2 —
--   this trigger uses that value and stamps the literal marker
--   "[CASE_STATUS_CHANGED]" into the description text itself, so the
--   event is both correctly typed against the existing schema AND
--   greppable/matchable against the exact tag requested.)
-- =====================================================================
DROP TRIGGER IF EXISTS trg_cases_status_change;

DELIMITER $$

CREATE TRIGGER trg_cases_status_change
    AFTER UPDATE ON cases
    FOR EACH ROW
BEGIN
    IF NOT (NEW.status <=> OLD.status) THEN
        INSERT INTO case_timeline
            (case_id, event_type, event_description, related_table, related_record_id,
             event_timestamp, recorded_by)
        VALUES
            (NEW.case_id, 'status_change',
             CONCAT('[CASE_STATUS_CHANGED] Case status changed from ', UPPER(OLD.status),
                    ' to ', UPPER(NEW.status), '.'),
             'cases', NEW.case_id, NOW(),
             COALESCE(@forgex_actor_id, NEW.created_by));
    END IF;
END$$

DELIMITER ;

-- =====================================================================
-- TRIGGER 3 — EVIDENCE HASH CHANGE
--   Fires when a REFERENCE hash (evidence_hashes.is_original = 1) has
--   its hash_value edited — i.e. the original acquisition-time hash on
--   record for an evidence item no longer matches what was first
--   captured. In forensics this is a serious integrity signal, so the
--   trigger immediately flags the evidence as 'requires_recheck' and
--   writes a full audit_logs entry (old hash, new hash, who, when).
-- =====================================================================
DROP TRIGGER IF EXISTS trg_evidence_hashes_reference_change;

DELIMITER $$

CREATE TRIGGER trg_evidence_hashes_reference_change
    AFTER UPDATE ON evidence_hashes
    FOR EACH ROW
BEGIN
    IF NEW.is_original = 1 AND NOT (NEW.hash_value <=> OLD.hash_value) THEN

        UPDATE evidence
           SET integrity_status = 'requires_recheck'
         WHERE evidence_id = NEW.evidence_id;

        INSERT INTO audit_logs
            (user_id, table_name, record_id, action_type, old_values, new_values, action_timestamp)
        VALUES
            (COALESCE(@forgex_actor_id, NEW.computed_by),
             'evidence_hashes', NEW.hash_id, 'UPDATE',
             JSON_OBJECT('hash_value', OLD.hash_value, 'evidence_id', OLD.evidence_id, 'hash_algorithm', OLD.hash_algorithm),
             JSON_OBJECT('hash_value', NEW.hash_value, 'evidence_id', NEW.evidence_id, 'hash_algorithm', NEW.hash_algorithm,
                          'flag', 'REQUIRES_RECHECK'),
             NOW());
    END IF;
END$$

DELIMITER ;

-- =====================================================================
-- TRIGGER 4 — PROTECT EVIDENCE (BEFORE DELETE)
--   Evidence with any chain-of-custody history must not be deletable,
--   full stop. fk_custody_evidence (ON DELETE RESTRICT, from
--   03_constraints.sql / 02_tables.sql) already makes this physically
--   impossible at the storage-engine level. This trigger adds a
--   second, higher-level guard that fires first and raises a clear,
--   business-meaningful SQLSTATE error instead of a generic FK error —
--   much easier for application code (and a human) to understand than
--   parsing "ERROR 1451 (23000): Cannot delete or update a parent
--   row...". Defense in depth: even if the FK were ever mistakenly
--   dropped, this trigger alone still enforces the rule.
-- =====================================================================
DROP TRIGGER IF EXISTS trg_evidence_protect_delete;

DELIMITER $$

CREATE TRIGGER trg_evidence_protect_delete
    BEFORE DELETE ON evidence
    FOR EACH ROW
BEGIN
    DECLARE custody_row_count INT DEFAULT 0;

    SELECT COUNT(*) INTO custody_row_count
    FROM chain_of_custody
    WHERE evidence_id = OLD.evidence_id;

    IF custody_row_count > 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Evidence cannot be deleted because it has chain-of-custody history.';
    END IF;
END$$

DELIMITER ;

-- =====================================================================
-- TRIGGER 5 — AUDIT IMPORTANT EVIDENCE CHANGES
--   Fires whenever any of the evidentiarily significant, editable
--   evidence fields change (description, integrity_status,
--   storage_location_id, file_path, evidence_type_id) and writes a
--   full old/new snapshot of those fields into audit_logs, along with
--   the acting user and timestamp. Deliberately distinct in scope from
--   Trigger 1 (which only watches current_custodian_id) — MySQL 8.0
--   supports multiple AFTER UPDATE triggers on the same table, each
--   firing independently, so a single UPDATE that changes both the
--   custodian and, say, the description correctly produces one
--   audit_logs row from each trigger.
-- =====================================================================
DROP TRIGGER IF EXISTS trg_evidence_important_changes_audit;

DELIMITER $$

CREATE TRIGGER trg_evidence_important_changes_audit
    AFTER UPDATE ON evidence
    FOR EACH ROW
BEGIN
    IF NOT (NEW.description <=> OLD.description)
       OR NOT (NEW.integrity_status <=> OLD.integrity_status)
       OR NOT (NEW.storage_location_id <=> OLD.storage_location_id)
       OR NOT (NEW.file_path <=> OLD.file_path)
       OR NOT (NEW.evidence_type_id <=> OLD.evidence_type_id) THEN

        INSERT INTO audit_logs
            (user_id, table_name, record_id, action_type, old_values, new_values, action_timestamp)
        VALUES
            (COALESCE(@forgex_actor_id, NEW.collected_by),
             'evidence', NEW.evidence_id, 'UPDATE',
             JSON_OBJECT('description', OLD.description, 'integrity_status', OLD.integrity_status,
                         'storage_location_id', OLD.storage_location_id, 'file_path', OLD.file_path,
                         'evidence_type_id', OLD.evidence_type_id),
             JSON_OBJECT('description', NEW.description, 'integrity_status', NEW.integrity_status,
                         'storage_location_id', NEW.storage_location_id, 'file_path', NEW.file_path,
                         'evidence_type_id', NEW.evidence_type_id),
             NOW());
    END IF;
END$$

DELIMITER ;

SELECT 'All 5 FORGE-X triggers created successfully.' AS status;

-- =====================================================================
-- Verification: list every trigger now installed
-- =====================================================================
SELECT TRIGGER_NAME, EVENT_MANIPULATION AS event, ACTION_TIMING AS timing, EVENT_OBJECT_TABLE AS on_table
FROM information_schema.TRIGGERS
WHERE TRIGGER_SCHEMA = 'forge_x'
ORDER BY EVENT_OBJECT_TABLE, ACTION_TIMING, EVENT_MANIPULATION;
