-- =====================================================================
-- FORGE-X  |  database/transactions_demo.sql
-- Calls the workflow procedures successfully, so each one COMMITs.
--
-- NEEDS THE DEMO DATA (install_demo.sql). THIS FILE CHANGES THE DATA.
-- Run it after verify_demo.sql. To return to the
-- original seed state afterwards, run install_demo.sql again.
--
-- New codes use the current year: run in 2026 and the new case is
-- FX-2026-0025; run in 2027 and it is FX-2027-0001 (a new yearly counter).
-- =====================================================================

USE forge_x_db;

-- Flask sets these per request; here we play the part of the app.
SET @app_ip = '127.0.0.1';

-- 1. Return FX-EV-2026-00055 from imaging to storage (Dev -> Priya).
SET @app_user_id = 5;
CALL sp_transfer_evidence(55, 5, 'Returned', 4, 4, NULL, 'Sealed, intact', 'FX-S-1191',
                          'Imaging complete', NULL, 5, @custody_id);
SELECT @custody_id AS new_custody_entry;
SELECT evidence_code, current_status, custodian_name, location_name
  FROM v_current_custodians WHERE evidence_code = 'FX-EV-2026-00055';   -- In Storage, Priya Nair, Locker 4

-- 2. Register a new case (Ishaan Verma as lead).
SET @app_user_id = 1;
CALL sp_register_case('Suspicious login alerts on HR portal',
                      'The HR portal raised repeated alerts for logins outside working hours.',
                      5, 'Medium', 8, 1, @case_id, @case_ref);
SELECT @case_id AS case_id, @case_ref AS case_reference;

-- 3. Register evidence for it, with its original hash, in one transaction.
SET @app_user_id = 3;
CALL sp_register_evidence(@case_id, 8, 'HR portal authentication logs', 'CSV export', 1048576,
                          NOW() - INTERVAL 1 HOUR, 3, 'HR portal server', 'Exported to sealed USB', 'FX-S-1300',
                          'be3ad1ce0bbbce58526ae83027adb07653bdce82673eea6daeb9d34ad43bcc1f', 'Computed', NULL,
                          3, @ev_id, @ev_code);
SELECT @ev_id AS evidence_id, @ev_code AS evidence_code;

-- 4. Receive it into the lab (In Transit -> In Storage).
SET @app_user_id = 4;
CALL sp_transfer_evidence(@ev_id, 3, 'Received', 4, 3, NULL, 'Sealed, intact', 'FX-S-1300',
                          'Transported to the lab', NULL, 4, @custody_id2);
SELECT * FROM v_evidence_overview WHERE evidence_id = @ev_id;            -- In Storage, Pending

-- 5. Add Rohan Iyer to the new case.
SET @app_user_id = 1;
CALL sp_assign_investigator(@case_id, 2, FALSE, 1);
SELECT u.full_name, ci.is_lead FROM case_investigators ci JOIN users u ON u.user_id = ci.user_id
 WHERE ci.case_id = @case_id;                                            -- Ishaan (lead), Rohan

-- 6. Approve Arjun Rao's request as an Investigator (role audit row comes from the trigger).
CALL sp_approve_account_request(45, 2, 1, @new_user_id);
SELECT u.user_id, u.username, ar.request_status, ar.password_hash IS NULL AS hash_cleared_from_request
  FROM users u JOIN account_requests ar ON ar.created_user_id = u.user_id
 WHERE u.user_id = @new_user_id;

-- 7. Save version 2 of the draft report RP-2026-0011.
SET @app_user_id = 2;
CALL sp_create_report_version(11,
     'Disk image examination in progress (EX-2026-0031).',
     'Encrypted files carry a .lockfin extension; a scheduled task created on 17 Sep launched the encryptor.',
     'Encryption started from a scheduled task.',
     'Initial access still under examination.',
     'Examination incomplete.',
     'Added scheduled task observation', 2, @version_no);
SELECT @version_no AS new_version;                                       -- 2

-- 8. Close the new case: its only item is in storage and it has no open examinations.
SET @app_user_id = 8;
CALL sp_close_case(@case_id, 'Alerts traced to a misconfigured monitoring job.', 8);
SELECT case_reference, status, closed_at FROM cases WHERE case_id = @case_id;

-- The audit trail of everything above, newest first.
SELECT audit_id, user_id, action, entity_type, entity_ref, outcome, details
  FROM audit_logs ORDER BY audit_id DESC LIMIT 12;

-- Try these one at a time to see the database refuse them:
--   CALL sp_close_case(22, 'test', 1);
--     -> Complete or cancel all examinations before closing the case.
--   UPDATE cases SET title = 'x' WHERE case_id = @case_id;
--     -> Closed cases are read-only.
--   CALL sp_transfer_evidence(55, 5, 'Checked Out', 2, 7, NULL, 'ok', NULL, 'x', NULL, 4, @x);
--     -> Custodian changed by another user. Reload and try again.   (Priya holds it now)

SET @app_user_id = NULL;
SET @app_ip = NULL;
