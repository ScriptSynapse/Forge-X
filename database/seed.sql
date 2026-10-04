-- =====================================================================
-- FORGE-X  |  database/seed.sql
-- Synthetic demonstration data. Every person, case, device, hash and
-- IP address here is invented. No real investigative data.
--
-- Run after schema.sql, triggers.sql, views.sql and procedures.sql.
-- Rows are inserted directly (not through procedures) with explicit
-- IDs so that sample_queries.sql has predictable results. The data
-- obeys every constraint and trigger, and verify.sql checks that the
-- denormalized evidence columns match the custody history.
--
-- PASSWORDS: seed accounts get an unusable placeholder hash, so no
-- password is ever stored in this file. In Phase 6 you will set real
-- passwords with a Flask command (flask set-password <username>).
-- =====================================================================

USE forge_x_db;

SET @no_pw = '!no-password-set:run-flask-set-password';

-- Attribute the trigger-generated role audit rows to the administrator.
SET @app_user_id = NULL;
SET @app_ip = '127.0.0.1';

-- ---------------------------------------------------------------------
-- Roles
-- ---------------------------------------------------------------------
INSERT INTO roles (role_id, role_name, description) VALUES
 (1, 'Administrator',      'Manages accounts and roles, approves reports and can see every record.'),
 (2, 'Investigator',       'Works on assigned cases: examinations, reports and evidence check-outs.'),
 (3, 'Evidence Custodian', 'Registers and stores evidence, records transfers and verifies hashes.'),
 (4, 'Read-Only Auditor',  'Reads all records and audit logs without changing anything.');

-- ---------------------------------------------------------------------
-- Users (8). Kabir Shah is deactivated; Ishaan Verma came from AR-0042.
-- ---------------------------------------------------------------------
INSERT INTO users (user_id, full_name, email, username, password_hash, account_status,
                   must_change_password, created_at, last_login_at) VALUES
 (1, 'Ananya Mehta', 'ananya.mehta@example.edu', 'ananya.m',   @no_pw, 'Active',      TRUE, '2026-01-12 09:00:00', '2026-10-03 08:55:02'),
 (2, 'Rohan Iyer',   'rohan.iyer@example.edu',   'rohan.iyer', @no_pw, 'Active',      TRUE, '2026-01-12 09:30:00', '2026-10-03 09:31:10'),
 (3, 'Sara Khan',    'sara.khan@example.edu',    'sara.khan',  @no_pw, 'Active',      TRUE, '2026-01-15 10:00:00', '2026-10-02 18:20:41'),
 (4, 'Priya Nair',   'priya.nair@example.edu',   'priya.nair', @no_pw, 'Active',      TRUE, '2026-01-15 10:15:00', '2026-10-03 10:40:12'),
 (5, 'Dev Kulkarni', 'dev.kulkarni@example.edu', 'dev.k',      @no_pw, 'Active',      TRUE, '2026-02-02 11:00:00', '2026-10-02 17:02:30'),
 (6, 'Meera Joshi',  'meera.joshi@example.edu',  'meera.j',    @no_pw, 'Active',      TRUE, '2026-02-20 12:00:00', '2026-10-02 15:10:05'),
 (7, 'Kabir Shah',   'kabir.shah@example.edu',   'kabir.shah', @no_pw, 'Deactivated', TRUE, '2026-01-20 09:00:00', '2026-06-14 11:20:00'),
 (8, 'Ishaan Verma', 'ishaan.verma@example.edu', 'ishaan.v',   @no_pw, 'Active',      TRUE, '2026-10-03 10:15:02', NULL);

-- First administrator's role has no assigner (bootstrap); every later
-- role is granted by user 1. Trigger trg_ur_audit_insert logs each one.
INSERT INTO user_roles (user_id, role_id, assigned_by, assigned_at) VALUES
 (1, 1, NULL, '2026-01-12 09:00:00');

SET @app_user_id = 1;

INSERT INTO user_roles (user_id, role_id, assigned_by, assigned_at) VALUES
 (2, 2, 1, '2026-01-12 09:30:00'),
 (3, 2, 1, '2026-01-15 10:00:00'),
 (3, 3, 1, '2026-10-02 11:03:26'),
 (4, 3, 1, '2026-01-15 10:15:00'),
 (5, 3, 1, '2026-02-02 11:00:00'),
 (6, 4, 1, '2026-02-20 12:00:00'),
 (7, 2, 1, '2026-01-20 09:00:00'),
 (8, 2, 1, '2026-10-03 10:15:02');

-- ---------------------------------------------------------------------
-- Account requests: 3 pending, 1 approved (-> Ishaan), 1 rejected
-- ---------------------------------------------------------------------
INSERT INTO account_requests (request_id, full_name, email, username, password_hash, reason,
                              request_status, reviewed_by, reviewed_at, review_note,
                              created_user_id, created_at) VALUES
 (41, 'Rahul Sen',     'rahul.sen@example.com',    'rsen',      NULL,   'Testing the signup form',
      'Rejected', 1, '2026-09-20 10:00:00', 'Not a member of the lab', NULL, '2026-09-19 18:30:00'),
 (42, 'Ishaan Verma',  'ishaan.verma@example.edu', 'ishaan.v',  NULL,   'New investigator joining the incident response team.',
      'Approved', 1, '2026-10-03 10:15:02', NULL, 8, '2026-10-01 09:20:00'),
 (43, 'Vikram Pillai', 'vikram.p@example.edu',     'vpillai',   @no_pw, NULL,
      'Pending', NULL, NULL, NULL, NULL, '2026-10-01 19:03:00'),
 (44, 'Neha Desai',    'neha.desai@example.edu',   'neha.d',    @no_pw, 'Evidence intake for the network security lab.',
      'Pending', NULL, NULL, NULL, NULL, '2026-10-02 14:12:00'),
 (45, 'Arjun Rao',     'arjun.rao@example.edu',    'arjun.rao', @no_pw, 'Joining the lab as a trainee examiner.',
      'Pending', NULL, NULL, NULL, NULL, '2026-10-03 09:40:00');

-- ---------------------------------------------------------------------
-- Login attempts (identifiers only; passwords are never stored)
-- ---------------------------------------------------------------------
INSERT INTO login_attempts (attempt_id, username_or_email, user_id, success, failure_reason,
                            ip_address, user_agent, attempted_at) VALUES
 ( 1, 'rohan.iyer',             2, FALSE, 'invalid_credentials', '10.20.1.22', 'Mozilla/5.0 (Windows NT 10.0)', '2026-10-01 09:12:10.000'),
 ( 2, 'rohan.iyer',             2, FALSE, 'invalid_credentials', '10.20.1.22', 'Mozilla/5.0 (Windows NT 10.0)', '2026-10-01 09:12:31.000'),
 ( 3, 'rohan.iyer',             2, TRUE,  NULL,                  '10.20.1.22', 'Mozilla/5.0 (Windows NT 10.0)', '2026-10-01 09:13:05.000'),
 ( 4, 'kabir.shah',             7, FALSE, 'account_inactive',    '10.20.3.5',  'Mozilla/5.0 (Windows NT 10.0)', '2026-10-01 14:20:44.000'),
 ( 5, 'meera.j',                6, TRUE,  NULL,                  '10.20.1.31', 'Mozilla/5.0 (Windows NT 10.0)', '2026-10-02 15:10:05.000'),
 ( 6, 'dev.k',                  5, TRUE,  NULL,                  '10.20.1.18', 'Mozilla/5.0 (Windows NT 10.0)', '2026-10-02 17:02:30.000'),
 ( 7, 'sara.khan',              3, TRUE,  NULL,                  '10.20.1.25', 'Mozilla/5.0 (Windows NT 10.0)', '2026-10-02 18:20:41.000'),
 ( 8, 'ananya.m',               1, TRUE,  NULL,                  '10.20.1.10', 'Mozilla/5.0 (Windows NT 10.0)', '2026-10-03 08:55:02.000'),
 ( 9, 'rohan.iyer',             2, TRUE,  NULL,                  '10.20.1.22', 'Mozilla/5.0 (Windows NT 10.0)', '2026-10-03 09:31:10.000'),
 (10, 'arjun.r',             NULL, FALSE, 'invalid_credentials', '10.20.4.17', 'Mozilla/5.0 (X11; Linux)',      '2026-10-03 09:55:10.000'),
 (11, 'arjun.r',             NULL, FALSE, 'invalid_credentials', '10.20.4.17', 'Mozilla/5.0 (X11; Linux)',      '2026-10-03 09:56:02.000'),
 (12, 'arjun.r',             NULL, FALSE, 'invalid_credentials', '10.20.4.17', 'Mozilla/5.0 (X11; Linux)',      '2026-10-03 09:57:30.000'),
 (13, 'arjun.r',             NULL, FALSE, 'invalid_credentials', '10.20.4.17', 'Mozilla/5.0 (X11; Linux)',      '2026-10-03 09:58:44.000'),
 (14, 'arjun.r',             NULL, FALSE, 'rate_limited',        '10.20.4.17', 'Mozilla/5.0 (X11; Linux)',      '2026-10-03 09:59:20.000'),
 (15, 'priya.nair@example.edu', 4, TRUE,  NULL,                  '10.20.1.14', 'Mozilla/5.0 (Windows NT 10.0)', '2026-10-03 10:40:12.000');

-- ---------------------------------------------------------------------
-- Lookup tables
-- ---------------------------------------------------------------------
INSERT INTO case_types (case_type_id, type_name, description) VALUES
 (1, 'Data Breach',                 'Unauthorized disclosure or exposure of data'),
 (2, 'Financial Fraud',             'Manipulation of financial records or payments'),
 (3, 'Insider Threat',              'Misuse of access by a current or former insider'),
 (4, 'Malware Incident',            'Ransomware, cryptominers and other malicious code'),
 (5, 'Unauthorized Access',         'Use of accounts or systems without permission'),
 (6, 'Intellectual Property Theft', 'Leak or theft of designs, code or documents'),
 (7, 'Harassment and Cyberstalking','Abusive or threatening electronic communication');

INSERT INTO evidence_types (evidence_type_id, type_name, description) VALUES
 ( 1, 'Hard Disk',           'Magnetic hard disk drive'),
 ( 2, 'SSD',                 'Solid-state drive'),
 ( 3, 'USB Drive',           'USB flash storage'),
 ( 4, 'Mobile Device',       'Phone or tablet'),
 ( 5, 'Memory Card',         'SD or microSD card'),
 ( 6, 'Disk Image',          'Forensic image of a volume or device'),
 ( 7, 'Network Capture',     'Packet capture or flow export'),
 ( 8, 'Log File',            'System, application or security log export'),
 ( 9, 'Digital Document',    'Individual files such as emails, PDFs or spreadsheets'),
 (10, 'Other Digital Media', 'Any other digital storage medium');

INSERT INTO examination_types (examination_type_id, type_name, description) VALUES
 (1, 'Disk Image Examination',               'Examination of a forensic disk image'),
 (2, 'File System Analysis',                 'Recovery and analysis of file system artefacts'),
 (3, 'Log Analysis',                         'Review of system, security and application logs'),
 (4, 'Mobile Device Examination',            'Logical or physical examination of a mobile device'),
 (5, 'Network Traffic Analysis',             'Analysis of captured network traffic'),
 (6, 'Malware Analysis in a Controlled Lab', 'Static and dynamic analysis in an isolated lab'),
 (7, 'Metadata Analysis',                    'Analysis of document and file metadata');

INSERT INTO storage_locations (location_id, location_name, location_type, description) VALUES
 ( 1, 'Vault B, Shelf 3',          'Vault',           'Long-term secure storage'),
 ( 2, 'Vault B, Shelf 5',          'Vault',           'Long-term secure storage'),
 ( 3, 'Evidence Room A, Locker 2', 'Evidence Room',   'Intake locker'),
 ( 4, 'Evidence Room A, Locker 4', 'Evidence Room',   'Intake locker'),
 ( 5, 'Evidence Room A, Locker 9', 'Evidence Room',   'Intake locker'),
 ( 6, 'Evidence Room A, Locker 12','Evidence Room',   'Intake locker'),
 ( 7, 'Examination Lab 1',         'Examination Lab', 'Main examination lab'),
 ( 8, 'Examination Lab 2',         'Examination Lab', 'Mobile and network lab'),
 ( 9, 'Imaging bench 1',           'Imaging Bench',   'Write-blocked imaging station'),
 (10, 'Archive Room',              'Other',           'Archive for closed cases');

-- ---------------------------------------------------------------------
-- Cases (12): 5 closed, 7 active. FX-2026-0013 is closed without a report;
-- FX-2026-0019 and FX-2026-0024 have no evidence yet.
-- ---------------------------------------------------------------------
INSERT INTO cases (case_id, case_reference, title, description, case_type_id, priority, status,
                   created_by, created_at, closed_at, closure_summary) VALUES
 (13, 'FX-2026-0013', 'Unauthorized cloud storage sync',
      'An employee laptop synced internal folders to a personal cloud account.', 3, 'Low', 'Closed',
      1, '2026-04-06 11:00:00', '2026-05-02 16:00:00', 'Sync confirmed as accidental; data removed from the personal account.'),
 (14, 'FX-2026-0014', 'Lost laptop data exposure check',
      'A laptop found at reception was checked for signs of access while it was lost.', 1, 'Medium', 'Closed',
      1, '2026-04-20 10:00:00', '2026-05-15 12:00:00', 'No evidence of access while the laptop was lost.'),
 (15, 'FX-2026-0015', 'Fake vendor invoices',
      'Invoices from an unknown vendor were paid through the ERP system.', 2, 'Medium', 'Closed',
      1, '2026-07-18 09:30:00', '2026-08-05 15:00:00', 'Invoices traced to a compromised vendor-onboarding account.'),
 (16, 'FX-2026-0016', 'Cryptominer on lab workstations',
      'Lab workstations showed sustained high CPU use outside working hours.', 4, 'Low', 'Closed',
      2, '2026-08-02 14:00:00', '2026-08-16 11:00:00', 'Cryptominer removed; installed through a shared lab account.'),
 (17, 'FX-2026-0017', 'Compromised administrator credentials',
      'An administrator account logged in from an unfamiliar location.', 5, 'High', 'Closed',
      1, '2026-08-10 08:45:00', '2026-08-24 17:00:00', 'Credentials reused from an external breach; account reset.'),
 (18, 'FX-2026-0018', 'Former employee data exfiltration',
      'A departing employee may have copied customer data before leaving.', 3, 'High', 'In Progress',
      1, '2026-08-21 10:00:00', NULL, NULL),
 (19, 'FX-2026-0019', 'Abusive messages sent to an employee',
      'An employee received repeated abusive messages from an unknown account.', 7, 'Medium', 'Open',
      3, '2026-08-29 15:30:00', NULL, NULL),
 (20, 'FX-2026-0020', 'Expense report manipulation',
      'Several expense claims appear to have been altered after approval.', 2, 'Medium', 'In Progress',
      1, '2026-09-05 11:20:00', NULL, NULL),
 (21, 'FX-2026-0021', 'Leaked product design documents',
      'Unreleased product designs appeared on a public forum.', 6, 'High', 'On Hold',
      1, '2026-09-12 09:00:00', NULL, NULL),
 (22, 'FX-2026-0022', 'Ransomware on finance file server',
      'Finance staff reported encrypted files and a ransom note on file server FS-FIN-02.', 4, 'Critical', 'In Progress',
      1, '2026-09-18 21:40:00', NULL, NULL),
 (23, 'FX-2026-0023', 'Phishing campaign targeting payroll staff',
      'Payroll staff received emails impersonating the internal payroll service.', 1, 'Critical', 'In Progress',
      3, '2026-09-24 13:10:00', NULL, NULL),
 (24, 'FX-2026-0024', 'Unauthorized VPN access at branch office',
      'VPN logins from a branch office occurred while the office was closed.', 5, 'High', 'Open',
      2, '2026-09-28 16:45:00', NULL, NULL);

INSERT INTO case_investigators (case_id, user_id, is_lead, assigned_by, assigned_at) VALUES
 (13, 2, TRUE,  1, '2026-04-06 11:00:00'),
 (13, 7, FALSE, 1, '2026-04-07 09:00:00'),
 (14, 3, TRUE,  1, '2026-04-20 10:00:00'),
 (15, 3, TRUE,  1, '2026-07-18 09:30:00'),
 (16, 2, TRUE,  2, '2026-08-02 14:00:00'),
 (17, 3, TRUE,  1, '2026-08-10 08:45:00'),
 (18, 2, TRUE,  1, '2026-08-21 10:00:00'),
 (18, 8, FALSE, 1, '2026-10-03 10:30:00'),
 (19, 3, TRUE,  3, '2026-08-29 15:30:00'),
 (20, 2, TRUE,  1, '2026-09-05 11:20:00'),
 (21, 3, TRUE,  1, '2026-09-12 09:00:00'),
 (21, 2, FALSE, 1, '2026-09-13 10:00:00'),
 (22, 2, TRUE,  1, '2026-09-18 21:40:00'),
 (22, 3, FALSE, 1, '2026-09-25 10:12:00'),
 (23, 3, TRUE,  3, '2026-09-24 13:10:00'),
 (23, 2, FALSE, 3, '2026-09-26 09:00:00'),
 (24, 2, TRUE,  2, '2026-09-28 16:45:00');

-- ---------------------------------------------------------------------
-- Evidence (20). current_* columns equal the latest custody entry.
-- ---------------------------------------------------------------------
INSERT INTO evidence (evidence_id, evidence_code, case_id, evidence_type_id, description, source_details,
                      size_bytes, collected_at, collected_by, collection_site, collection_condition,
                      current_status, current_custodian_id, current_location_id, registered_at) VALUES
 (40, 'FX-EV-2026-00040', 13,  2, 'Employee laptop SSD',                         'Laptop LT-0412 internal SSD, serial SYN-SSD-4412', 512110190592,  '2026-04-07 10:00:00', 5, 'Employee desk, 2nd floor', 'Powered off, bagged', 'Archived',          4, 10, '2026-04-07 10:15:00'),
 (41, 'FX-EV-2026-00041', 14,  1, 'Recovered laptop drive',                      'Laptop LT-0388 HDD, serial SYN-HDD-0388',          1000204886016, '2026-04-21 09:30:00', 5, 'Reception lost-and-found', 'Bagged',              'Released',          4, NULL, '2026-04-21 09:45:00'),
 (42, 'FX-EV-2026-00042', 15,  9, 'Vendor invoice PDFs exported from ERP',       NULL,                                               48234496,      '2026-07-19 11:00:00', 3, 'Finance ERP export',       'Exported to sealed USB', 'Archived',       4, 10, '2026-07-19 11:15:00'),
 (43, 'FX-EV-2026-00043', 15,  8, 'ERP access logs, June to July',               NULL,                                               9437184,       '2026-07-19 11:05:00', 3, 'ERP application server',   'Exported to sealed USB', 'Archived',       4, 10, '2026-07-19 11:20:00'),
 (44, 'FX-EV-2026-00044', 16,  6, 'Forensic image of LAB-WS-07',                 'E01, 3 segments',                                  256060514304,  '2026-08-03 13:00:00', 5, 'Lab workstation LAB-WS-07','Sealed, intact',      'Archived',          4, 10, '2026-08-03 13:15:00'),
 (45, 'FX-EV-2026-00045', 17,  8, 'Domain controller security logs',             'Export from DC-01',                                 734003200,     '2026-08-11 10:00:00', 3, 'Domain controller DC-01',  'Exported to sealed USB', 'Archived',       4, 10, '2026-08-11 10:15:00'),
 (46, 'FX-EV-2026-00046', 18,  3, 'USB drive returned by former employee',       '64 GB USB drive, serial SYN-USB-7781',              64023257088,   '2026-08-22 10:30:00', 5, 'HR office',                'Bagged',              'In Storage',        4,  2, '2026-08-22 10:45:00'),
 (47, 'FX-EV-2026-00047', 21,  4, 'Engineer''s personal phone, provided with consent', 'Android phone, IMEI withheld (synthetic)',  NULL,          '2026-09-12 16:00:00', 5, 'Engineer''s desk, R&D wing', 'Powered off, Faraday bag', 'In Storage', 5,  5, '2026-09-12 16:15:00'),
 (48, 'FX-EV-2026-00048', 20,  9, 'Expense claim spreadsheets',                  NULL,                                               15728640,      '2026-09-06 11:00:00', 3, 'Finance shared drive',     'Exported to sealed USB', 'In Storage',     4,  1, '2026-09-06 11:15:00'),
 (49, 'FX-EV-2026-00049', 18,  7, 'Outbound proxy capture, 15 to 20 Aug',        'PCAPNG export',                                    2147483648,    '2026-08-23 12:00:00', 3, 'Outbound proxy appliance', 'Exported to sealed USB', 'In Storage',     4,  2, '2026-08-23 12:15:00'),
 (50, 'FX-EV-2026-00050', 21,  5, 'SD card from desk camera',                    '32 GB microSD',                                    31914983424,   '2026-09-13 10:00:00', 5, 'Desk camera, R&D wing',    'Bagged',              'In Storage',        5,  5, '2026-09-13 10:15:00'),
 (51, 'FX-EV-2026-00051', 22,  6, 'Forensic image of FS-FIN-02 system volume',   'E01, 5 segments; source SSD serial SYN-SN-2207',    512110190592,  '2026-09-18 22:10:00', 5, 'Finance server room, 3rd floor', 'Sealed, intact', 'Under Examination', 2,  7, '2026-09-18 22:25:00'),
 (52, 'FX-EV-2026-00052', 22,  1, 'FS-FIN-02 data drive, 4 TB',                  'Serial SYN-HDD-9921',                              4000787030016, '2026-09-18 22:40:00', 5, 'Finance server room, 3rd floor', 'Sealed, intact', 'In Storage',        4,  1, '2026-09-18 22:55:00'),
 (53, 'FX-EV-2026-00053', 22,  7, 'Perimeter firewall capture, 14 to 16 Sep',    'PCAPNG export',                                    5368709120,    '2026-09-18 23:30:00', 3, 'Perimeter firewall',       'Exported to sealed USB', 'Under Examination', 3, 7, '2026-09-18 23:45:00'),
 (54, 'FX-EV-2026-00054', 22,  8, 'Windows event log export, FS-FIN-02',         'EVTX files',                                       1073741824,    '2026-09-19 08:00:00', 3, 'FS-FIN-02 live log export','Exported to sealed USB', 'In Storage',     4,  1, '2026-09-19 08:15:00'),
 (55, 'FX-EV-2026-00055', 22,  3, 'USB drive found at finance desk 3',           '16 GB USB drive, serial SYN-USB-3310',              16008609792,   '2026-09-19 11:00:00', 5, 'Finance desk 3',           'Bagged',              'Checked Out',       5,  9, '2026-09-19 11:15:00'),
 (56, 'FX-EV-2026-00056', 22,  9, 'Ransom note text file recovered from share',  NULL,                                               4096,          '2026-09-19 11:30:00', 3, 'Finance shared drive',     'Exported to sealed USB', 'In Storage',     4,  1, '2026-09-19 11:45:00'),
 (57, 'FX-EV-2026-00057', 23,  4, 'Payroll officer''s work phone',               'iOS phone, asset tag SYN-PH-0217',                 NULL,          '2026-09-24 15:00:00', 5, 'Payroll office',           'Powered off, Faraday bag', 'Under Examination', 3, 8, '2026-09-24 15:15:00'),
 (58, 'FX-EV-2026-00058', 23,  9, 'Phishing email samples (.eml)',               '12 messages',                                      1048576,       '2026-09-24 15:30:00', 3, 'Mail gateway quarantine',  'Exported to sealed USB', 'In Storage',     4,  2, '2026-09-24 15:45:00'),
 (59, 'FX-EV-2026-00059', 23,  8, 'Mail gateway logs, 20 to 24 Sep',             'CSV export',                                       20971520,      '2026-09-24 15:45:00', 3, 'Mail gateway',             'Exported to sealed USB', 'In Storage',     4,  2, '2026-09-24 16:00:00');

-- ---------------------------------------------------------------------
-- Chain of custody (59 entries, chronological). Entry 55 corrects 54.
-- ---------------------------------------------------------------------
INSERT INTO chain_of_custody (custody_id, evidence_id, action, from_custodian_id, to_custodian_id, location_id,
                              location_note, evidence_condition, seal_number, reason, occurred_at,
                              recorded_by, recorded_at, corrects_custody_id) VALUES
 ( 1, 40, 'Collected',   NULL, 5, NULL, 'Employee desk, 2nd floor',   'Powered off, bagged',    'FX-S-0941', 'Collected at site',                          '2026-04-07 10:00:00', 5, '2026-04-07 10:20:00', NULL),
 ( 2, 40, 'Received',       5, 4,    3, NULL,                         'Sealed, intact',         'FX-S-0941', 'Transported to the lab',                     '2026-04-07 15:00:00', 4, '2026-04-07 15:05:00', NULL),
 ( 3, 41, 'Collected',   NULL, 5, NULL, 'Reception lost-and-found',   'Bagged',                 'FX-S-0977', 'Collected at site',                          '2026-04-21 09:30:00', 5, '2026-04-21 09:45:00', NULL),
 ( 4, 41, 'Received',       5, 4,    4, NULL,                         'Sealed, intact',         'FX-S-0977', 'Transported to the lab',                     '2026-04-21 14:00:00', 4, '2026-04-21 14:05:00', NULL),
 ( 5, 40, 'Archived',       4, 4,   10, NULL,                         'Sealed, intact',         'FX-S-0941', 'Case FX-2026-0013 closed',                   '2026-05-04 11:00:00', 4, '2026-05-04 11:05:00', NULL),
 ( 6, 41, 'Released',       4, 4, NULL, 'Released to IT department',  'Sealed, intact',         'FX-S-0977', 'Returned to owning department after closure','2026-05-16 10:00:00', 4, '2026-05-16 10:10:00', NULL),
 ( 7, 42, 'Collected',   NULL, 3, NULL, 'Finance ERP export',         'Exported to sealed USB', 'FX-S-1052', 'Collected at site',                          '2026-07-19 11:00:00', 3, '2026-07-19 11:10:00', NULL),
 ( 8, 43, 'Collected',   NULL, 3, NULL, 'ERP application server',     'Exported to sealed USB', 'FX-S-1053', 'Collected at site',                          '2026-07-19 11:05:00', 3, '2026-07-19 11:15:00', NULL),
 ( 9, 42, 'Received',       3, 4,    1, NULL,                         'Sealed, intact',         'FX-S-1052', 'Transported to the lab',                     '2026-07-19 16:00:00', 4, '2026-07-19 16:05:00', NULL),
 (10, 43, 'Received',       3, 4,    1, NULL,                         'Sealed, intact',         'FX-S-1053', 'Transported to the lab',                     '2026-07-19 16:02:00', 4, '2026-07-19 16:07:00', NULL),
 (11, 44, 'Collected',   NULL, 5, NULL, 'Lab workstation LAB-WS-07',  'Sealed, intact',         'FX-S-1090', 'Collected at site',                          '2026-08-03 13:00:00', 5, '2026-08-03 13:10:00', NULL),
 (12, 44, 'Received',       5, 4,    1, NULL,                         'Sealed, intact',         'FX-S-1090', 'Transported to the lab',                     '2026-08-03 17:00:00', 4, '2026-08-03 17:05:00', NULL),
 (13, 42, 'Archived',       4, 4,   10, NULL,                         'Sealed, intact',         'FX-S-1052', 'Case FX-2026-0015 closed',                   '2026-08-06 10:00:00', 4, '2026-08-06 10:05:00', NULL),
 (14, 43, 'Archived',       4, 4,   10, NULL,                         'Sealed, intact',         'FX-S-1053', 'Case FX-2026-0015 closed',                   '2026-08-06 10:02:00', 4, '2026-08-06 10:07:00', NULL),
 (15, 45, 'Collected',   NULL, 3, NULL, 'Domain controller DC-01',    'Exported to sealed USB', 'FX-S-1102', 'Collected at site',                          '2026-08-11 10:00:00', 3, '2026-08-11 10:10:00', NULL),
 (16, 45, 'Received',       3, 4,    1, NULL,                         'Sealed, intact',         'FX-S-1102', 'Transported to the lab',                     '2026-08-11 15:00:00', 4, '2026-08-11 15:05:00', NULL),
 (17, 44, 'Archived',       4, 4,   10, NULL,                         'Sealed, intact',         'FX-S-1090', 'Case FX-2026-0016 closed',                   '2026-08-17 10:00:00', 4, '2026-08-17 10:05:00', NULL),
 (18, 46, 'Collected',   NULL, 5, NULL, 'HR office',                  'Bagged',                 'FX-S-1120', 'Collected at site',                          '2026-08-22 10:30:00', 5, '2026-08-22 10:40:00', NULL),
 (19, 46, 'Received',       5, 4,    2, NULL,                         'Sealed, intact',         'FX-S-1120', 'Transported to the lab',                     '2026-08-22 14:00:00', 4, '2026-08-22 14:05:00', NULL),
 (20, 49, 'Collected',   NULL, 3, NULL, 'Outbound proxy appliance',   'Exported to sealed USB', 'FX-S-1124', 'Collected at site',                          '2026-08-23 12:00:00', 3, '2026-08-23 12:10:00', NULL),
 (21, 49, 'Received',       3, 4,    2, NULL,                         'Sealed, intact',         'FX-S-1124', 'Transported to the lab',                     '2026-08-23 16:00:00', 4, '2026-08-23 16:05:00', NULL),
 (22, 45, 'Archived',       4, 4,   10, NULL,                         'Sealed, intact',         'FX-S-1102', 'Case FX-2026-0017 closed',                   '2026-08-25 10:00:00', 4, '2026-08-25 10:05:00', NULL),
 (23, 48, 'Collected',   NULL, 3, NULL, 'Finance shared drive',       'Exported to sealed USB', 'FX-S-1150', 'Collected at site',                          '2026-09-06 11:00:00', 3, '2026-09-06 11:10:00', NULL),
 (24, 48, 'Received',       3, 4,    1, NULL,                         'Sealed, intact',         'FX-S-1150', 'Transported to the lab',                     '2026-09-06 15:00:00', 4, '2026-09-06 15:05:00', NULL),
 (25, 47, 'Collected',   NULL, 5, NULL, 'Engineer''s desk, R&D wing', 'Powered off, Faraday bag','FX-S-1161','Collected at site with the owner''s consent', '2026-09-12 16:00:00', 5, '2026-09-12 16:10:00', NULL),
 (26, 47, 'Stored',         5, 5,    5, NULL,                         'Powered off, Faraday bag','FX-S-1161','Intake complete',                            '2026-09-12 18:00:00', 5, '2026-09-12 18:05:00', NULL),
 (27, 50, 'Collected',   NULL, 5, NULL, 'Desk camera, R&D wing',      'Bagged',                 'FX-S-1163', 'Collected at site',                          '2026-09-13 10:00:00', 5, '2026-09-13 10:10:00', NULL),
 (28, 50, 'Stored',         5, 5,    5, NULL,                         'Sealed, intact',         'FX-S-1163', 'Intake complete',                            '2026-09-13 13:00:00', 5, '2026-09-13 13:05:00', NULL),
 (29, 51, 'Collected',   NULL, 5, NULL, 'Finance server room, on site','Sealed, intact',        'FX-S-1187', 'Acquired on site through a hardware write blocker', '2026-09-18 22:10:00', 5, '2026-09-18 22:30:00', NULL),
 (30, 52, 'Collected',   NULL, 5, NULL, 'Finance server room, on site','Sealed, intact',        'FX-S-1188', 'Drive removed from FS-FIN-02 after imaging', '2026-09-18 22:40:00', 5, '2026-09-18 22:50:00', NULL),
 (31, 53, 'Collected',   NULL, 3, NULL, 'Perimeter firewall',         'Exported to sealed USB', 'FX-S-1189', 'Collected at site',                          '2026-09-18 23:30:00', 3, '2026-09-18 23:40:00', NULL),
 (32, 54, 'Collected',   NULL, 3, NULL, 'FS-FIN-02 live log export',  'Exported to sealed USB', 'FX-S-1190', 'Collected at site',                          '2026-09-19 08:00:00', 3, '2026-09-19 08:10:00', NULL),
 (33, 51, 'Received',       5, 4,    6, NULL,                         'Sealed, intact',         'FX-S-1187', 'Transported from site in sealed evidence bag FX-S-1187', '2026-09-19 09:35:00', 4, '2026-09-19 09:40:00', NULL),
 (34, 52, 'Received',       5, 4,    6, NULL,                         'Sealed, intact',         'FX-S-1188', 'Transported to the lab',                     '2026-09-19 09:40:00', 4, '2026-09-19 09:45:00', NULL),
 (35, 53, 'Received',       3, 4,    6, NULL,                         'Sealed, intact',         'FX-S-1189', 'Transported to the lab',                     '2026-09-19 10:00:00', 4, '2026-09-19 10:05:00', NULL),
 (36, 54, 'Received',       3, 4,    6, NULL,                         'Sealed, intact',         'FX-S-1190', 'Transported to the lab',                     '2026-09-19 10:05:00', 4, '2026-09-19 10:10:00', NULL),
 (37, 55, 'Collected',   NULL, 5, NULL, 'Finance desk 3',             'Bagged',                 'FX-S-1191', 'Collected at site',                          '2026-09-19 11:00:00', 5, '2026-09-19 11:10:00', NULL),
 (38, 56, 'Collected',   NULL, 3, NULL, 'Finance shared drive',       'Exported to sealed USB', 'FX-S-1192', 'Collected at site',                          '2026-09-19 11:30:00', 3, '2026-09-19 11:40:00', NULL),
 (39, 55, 'Received',       5, 4,    4, NULL,                         'Sealed, intact',         'FX-S-1191', 'Transported to the lab',                     '2026-09-19 12:00:00', 4, '2026-09-19 12:05:00', NULL),
 (40, 56, 'Received',       3, 4,    6, NULL,                         'Sealed, intact',         'FX-S-1192', 'Transported to the lab',                     '2026-09-19 12:10:00', 4, '2026-09-19 12:15:00', NULL),
 (41, 51, 'Stored',         4, 4,    1, NULL,                         'Sealed, intact',         'FX-S-1187', 'Intake checks and hash verification complete','2026-09-19 14:30:00', 4, '2026-09-19 14:35:00', NULL),
 (42, 52, 'Stored',         4, 4,    1, NULL,                         'Sealed, intact',         'FX-S-1188', 'Intake complete',                            '2026-09-19 14:35:00', 4, '2026-09-19 14:40:00', NULL),
 (43, 53, 'Stored',         4, 4,    1, NULL,                         'Sealed, intact',         'FX-S-1189', 'Intake complete',                            '2026-09-19 14:40:00', 4, '2026-09-19 14:45:00', NULL),
 (44, 54, 'Stored',         4, 4,    1, NULL,                         'Sealed, intact',         'FX-S-1190', 'Intake complete',                            '2026-09-19 14:45:00', 4, '2026-09-19 14:50:00', NULL),
 (45, 56, 'Stored',         4, 4,    1, NULL,                         'Sealed, intact',         'FX-S-1192', 'Intake complete',                            '2026-09-19 14:50:00', 4, '2026-09-19 14:55:00', NULL),
 (46, 57, 'Collected',   NULL, 5, NULL, 'Payroll office',             'Powered off, Faraday bag','FX-S-1201','Collected at site',                          '2026-09-24 15:00:00', 5, '2026-09-24 15:10:00', NULL),
 (47, 58, 'Collected',   NULL, 3, NULL, 'Mail gateway quarantine',    'Exported to sealed USB', 'FX-S-1202', 'Collected at site',                          '2026-09-24 15:30:00', 3, '2026-09-24 15:40:00', NULL),
 (48, 59, 'Collected',   NULL, 3, NULL, 'Mail gateway',               'Exported to sealed USB', 'FX-S-1203', 'Collected at site',                          '2026-09-24 15:45:00', 3, '2026-09-24 15:55:00', NULL),
 (49, 57, 'Received',       5, 4,    3, NULL,                         'Powered off, Faraday bag','FX-S-1201','Transported to the lab',                     '2026-09-24 16:15:00', 4, '2026-09-24 16:20:00', NULL),
 (50, 58, 'Received',       3, 4,    2, NULL,                         'Sealed, intact',         'FX-S-1202', 'Transported to the lab',                     '2026-09-24 18:30:00', 4, '2026-09-24 18:35:00', NULL),
 (51, 59, 'Received',       3, 4,    2, NULL,                         'Sealed, intact',         'FX-S-1203', 'Transported to the lab',                     '2026-09-24 18:40:00', 4, '2026-09-24 18:45:00', NULL),
 (52, 53, 'Checked Out',    4, 3,    7, NULL,                         'Sealed, intact',         'FX-S-1189', 'For network traffic analysis EX-2026-0030',  '2026-09-25 11:30:00', 4, '2026-09-25 11:35:00', NULL),
 (53, 53, 'Examined',       3, 3,    7, NULL,                         'Seal opened, resealed as FX-S-1210', 'FX-S-1210', 'EX-2026-0030 started on a verified working copy', '2026-09-25 12:00:00', 3, '2026-09-25 12:05:00', NULL),
 (54, 51, 'Checked Out',    4, 2,    8, NULL,                         'Sealed, intact',         'FX-S-1187', 'For disk image examination EX-2026-0031',    '2026-09-26 15:50:00', 4, '2026-09-26 15:55:00', NULL),
 (55, 51, 'Checked Out',    4, 2,    7, NULL,                         'Sealed, intact',         'FX-S-1187', 'The item went to Examination Lab 1, not Lab 2. Entry #54 is kept unchanged.', '2026-09-26 15:50:00', 4, '2026-09-26 17:12:00', 54),
 (56, 51, 'Examined',       2, 2,    7, NULL,                         'Seal opened, resealed as FX-S-1241', 'FX-S-1241', 'EX-2026-0031 started on a verified working copy', '2026-09-27 10:05:00', 2, '2026-09-27 10:10:00', NULL),
 (57, 57, 'Checked Out',    4, 3,    8, NULL,                         'Powered off, Faraday bag','FX-S-1201','For mobile device examination EX-2026-0028', '2026-09-29 10:00:00', 4, '2026-09-29 10:05:00', NULL),
 (58, 57, 'Examined',       3, 3,    8, NULL,                         'Removed from Faraday bag inside shielded enclosure', NULL, 'EX-2026-0028 started', '2026-09-29 10:30:00', 3, '2026-09-29 10:35:00', NULL),
 (59, 55, 'Checked Out',    4, 5,    9, NULL,                         'Sealed, intact',         'FX-S-1191', 'Write-blocked imaging',                      '2026-10-02 17:05:00', 5, '2026-10-02 17:08:00', NULL);

-- ---------------------------------------------------------------------
-- Evidence hashes. Hash 13 corrects a mistyped manual entry (12).
-- No hash yet: FX-EV-2026-00048 and FX-EV-2026-00055 (Not Verified).
-- ---------------------------------------------------------------------
INSERT INTO evidence_hashes (hash_id, evidence_id, hash_value, source, source_notes, recorded_by,
                             recorded_at, supersedes_hash_id, correction_reason) VALUES
 ( 1, 40, 'f7f59e8326fd296bee51c31c0b014531249d1850687cc307aa8b866a5cf6e3cf', 'Computed', NULL, 4, '2026-04-07 15:10:00', NULL, NULL),
 ( 2, 41, '5fd9f628b8642265e14b0c4aaaaee08cdd79060ff90398c00f9ffd6d9caab299', 'Computed', NULL, 4, '2026-04-21 14:10:00', NULL, NULL),
 ( 3, 42, '032488ff3390360db09c4ba92f0a4a754a753616b54e39d702b2c988f6a7e3b9', 'Computed', NULL, 4, '2026-07-19 16:10:00', NULL, NULL),
 ( 4, 43, 'cd7b6d21092196e9ee0134d78f47f9ceca1fb7806aa2ff44e8b3e5c2e08fc4bc', 'Computed', NULL, 4, '2026-07-19 16:12:00', NULL, NULL),
 ( 5, 44, 'f3192c21701f9aee8df367ae409c0027c5001970ef41a61e4090d81eff242d88', 'Computed', NULL, 4, '2026-08-03 17:10:00', NULL, NULL),
 ( 6, 45, '72d04c551918872a9528912b8c3cd652b77edd02bf84df67d66d6041df59d29c', 'Computed', NULL, 4, '2026-08-11 15:10:00', NULL, NULL),
 ( 7, 46, '3a72f1a1c36688a934769b17012a24b845b94e250aa773828feafb307cfcbf37', 'Computed', NULL, 4, '2026-08-22 14:10:00', NULL, NULL),
 ( 8, 47, 'c5b81fb0ddc15ca91b36ba28d4a5a49de90b12778eb0451101c4f5e1f5c984b6', 'Manual',   'Copied from the extraction tool''s acquisition report', 5, '2026-09-12 18:10:00', NULL, NULL),
 ( 9, 49, 'b79f13c915ed9d4030876281f0ff949a83a3699e2f0328a2243b2fed9d8a243c', 'Computed', NULL, 4, '2026-08-23 16:10:00', NULL, NULL),
 (10, 50, 'c219f7a912e78dca4e4f7b093478269b807911f97aab1d5ed0fd2bdba338f2d5', 'Computed', NULL, 5, '2026-09-13 13:10:00', NULL, NULL),
 (11, 51, '3b7f1c9e04a2d58e6f91c2a7b34d0e85f1c6a9d2e7b40f38c5a1d9e62b7f0c4a', 'Manual',   'From the on-site acquisition log', 4, '2026-09-19 14:00:00', NULL, NULL),
 (12, 52, 'bc95bf0a5d904dbfdf1a5055c093cb4c2921136336bcfd7356450f3fd1a8ebbb', 'Manual',   'Typed from the on-site acquisition log', 4, '2026-09-19 14:01:00', NULL, NULL),
 (13, 52, '1898812520614cea8a1f0382d58e3273350dc09efe1d5d36022c53a67e59ea18', 'Manual',   'Re-entered from the on-site acquisition log', 4, '2026-09-20 09:30:00', 12,
      'Hash #12 was mistyped from the acquisition log. Re-entered after checking the log.'),
 (14, 53, 'bf608cbd4d4bb83c9c4ad6981a567058ee29d585c50176149c0d30f6e4579664', 'Computed', NULL, 4, '2026-09-19 14:02:00', NULL, NULL),
 (15, 54, '23861c9c0500cc4781df12e1b07fd29d4e2fa41e62a7c670e88412227827bf62', 'Computed', NULL, 4, '2026-09-19 14:03:00', NULL, NULL),
 (16, 56, 'db972a638eef1e6643a76539002df302a1b4f5b16934522cf031392d447cd1ca', 'Computed', NULL, 4, '2026-09-19 14:04:00', NULL, NULL),
 (17, 57, '202f0e564156ef78577c700f1c3955415b5e80bce0c8cec67c731aea184bb01f', 'Computed', NULL, 4, '2026-09-24 16:30:00', NULL, NULL),
 (18, 58, 'e1b9d77e82f1c0956bfbf68c7de83ba7ae9ea045e2935d517093c4a15bc8017d', 'Computed', NULL, 4, '2026-09-24 18:50:00', NULL, NULL),
 (19, 59, '4b7879ef34523e5d20e9fbec71440bab1a0e6fa4d556b3c6a44e5eb85832a581', 'Computed', NULL, 4, '2026-09-24 18:52:00', NULL, NULL);

-- ---------------------------------------------------------------------
-- Hash verifications. The trigger computes `result`; the values given
-- here are what it will produce. Hash 8 (FX-EV-2026-00047) passes once,
-- then fails on 30 Sep. Items 50, 54, 57 have hashes but no checks yet.
-- ---------------------------------------------------------------------
INSERT INTO hash_verifications (verification_id, hash_id, computed_hash, method, sample_file_name,
                                sample_size_bytes, notes, verified_by, verified_at) VALUES
 ( 1,  1, 'f7f59e8326fd296bee51c31c0b014531249d1850687cc307aa8b866a5cf6e3cf', 'Sample file', 'ev00040-sample.bin', 1048576, NULL, 4, '2026-04-07 15:15:00'),
 ( 2,  2, '5fd9f628b8642265e14b0c4aaaaee08cdd79060ff90398c00f9ffd6d9caab299', 'Sample file', 'ev00041-sample.bin', 1048576, NULL, 4, '2026-04-21 14:15:00'),
 ( 3,  3, '032488ff3390360db09c4ba92f0a4a754a753616b54e39d702b2c988f6a7e3b9', 'Sample file', 'ev00042-sample.bin', 1048576, NULL, 4, '2026-07-19 16:15:00'),
 ( 4,  4, 'cd7b6d21092196e9ee0134d78f47f9ceca1fb7806aa2ff44e8b3e5c2e08fc4bc', 'Sample file', 'ev00043-sample.bin', 1048576, NULL, 4, '2026-07-19 16:16:00'),
 ( 5,  5, 'f3192c21701f9aee8df367ae409c0027c5001970ef41a61e4090d81eff242d88', 'Sample file', 'ev00044-sample.bin', 1048576, NULL, 4, '2026-08-03 17:15:00'),
 ( 6,  6, '72d04c551918872a9528912b8c3cd652b77edd02bf84df67d66d6041df59d29c', 'Sample file', 'ev00045-sample.bin', 1048576, NULL, 4, '2026-08-11 15:15:00'),
 ( 7,  7, '3a72f1a1c36688a934769b17012a24b845b94e250aa773828feafb307cfcbf37', 'Sample file', 'ev00046-sample.bin', 1048576, NULL, 4, '2026-08-22 14:15:00'),
 ( 8,  8, 'c5b81fb0ddc15ca91b36ba28d4a5a49de90b12778eb0451101c4f5e1f5c984b6', 'Manual entry', NULL, NULL, 'Checked against the acquisition report at intake', 5, '2026-09-12 18:15:00'),
 ( 9,  9, 'b79f13c915ed9d4030876281f0ff949a83a3699e2f0328a2243b2fed9d8a243c', 'Sample file', 'ev00049-sample.bin', 1048576, NULL, 4, '2026-08-23 16:15:00'),
 (10, 11, '3b7f1c9e04a2d58e6f91c2a7b34d0e85f1c6a9d2e7b40f38c5a1d9e62b7f0c4a', 'Sample file', 'ev00051-sample.bin', 1048576, NULL, 4, '2026-09-19 14:05:00'),
 (11, 13, '1898812520614cea8a1f0382d58e3273350dc09efe1d5d36022c53a67e59ea18', 'Sample file', 'ev00052-sample.bin', 1048576, NULL, 4, '2026-09-20 09:35:00'),
 (12, 14, 'bf608cbd4d4bb83c9c4ad6981a567058ee29d585c50176149c0d30f6e4579664', 'Sample file', 'ev00053-sample.bin', 1048576, NULL, 4, '2026-09-19 14:06:00'),
 (13, 16, 'db972a638eef1e6643a76539002df302a1b4f5b16934522cf031392d447cd1ca', 'Sample file', 'ev00056-sample.bin', 4096,    NULL, 4, '2026-09-19 14:07:00'),
 (14, 18, 'e1b9d77e82f1c0956bfbf68c7de83ba7ae9ea045e2935d517093c4a15bc8017d', 'Sample file', 'ev00058-sample.bin', 1048576, NULL, 4, '2026-09-24 18:55:00'),
 (15, 19, '4b7879ef34523e5d20e9fbec71440bab1a0e6fa4d556b3c6a44e5eb85832a581', 'Sample file', 'ev00059-sample.bin', 1048576, NULL, 4, '2026-09-24 18:56:00'),
 (16, 11, '3b7f1c9e04a2d58e6f91c2a7b34d0e85f1c6a9d2e7b40f38c5a1d9e62b7f0c4a', 'Sample file', 'ev00051-sample.bin', 1048576, NULL, 4, '2026-09-26 15:40:00'),
 (17,  8, 'f478f027dd2d31d3816e5b86a988cfb1658f648c38a67cd3f46415635e56bf76', 'Sample file', 'ev00047-extraction.bin', 2097152, 'Recomputed before metadata review', 5, '2026-09-30 11:00:00'),
 (18, 11, '3b7f1c9e04a2d58e6f91c2a7b34d0e85f1c6a9d2e7b40f38c5a1d9e62b7f0c4a', 'Sample file', 'ev00051-verification-sample.bin', 1048576, NULL, 4, '2026-10-03 10:42:18');

-- ---------------------------------------------------------------------
-- Examinations (12): 7 Completed, 3 In Progress, 1 Pending, 1 Cancelled.
-- EX-2026-0026 (due 30 Sep) and EX-2026-0030 (due 1 Oct) are overdue.
-- ---------------------------------------------------------------------
INSERT INTO examinations (examination_id, examination_code, case_id, examination_type_id, examiner_id, status,
                          due_date, started_at, completed_at, tools_methods, observations, findings,
                          limitations, cancel_reason, created_at) VALUES
 (20, 'EX-2026-0020', 16, 1, 2, 'Completed', '2026-08-12', '2026-08-04 09:00:00', '2026-08-08 17:00:00',
      'Image mounted read-only; scheduled tasks and startup entries reviewed.',
      'A scheduled task launched an unsigned binary every night at 01:00.',
      'The binary matches known cryptomining behaviour; it was installed from the shared lab account.',
      'Only one of the affected workstations was imaged.', NULL, '2026-08-03 18:00:00'),
 (21, 'EX-2026-0021', 14, 2, 3, 'Completed', '2026-05-01', '2026-04-23 10:00:00', '2026-04-30 16:00:00',
      'File system timeline built from the verified image.',
      'No files were opened or modified between the loss date and recovery.',
      'No evidence of access while the laptop was lost.',
      'Timestamps can be altered by a skilled attacker.', NULL, '2026-04-22 09:00:00'),
 (22, 'EX-2026-0022', 17, 3, 3, 'Completed', '2026-08-20', '2026-08-12 10:00:00', '2026-08-18 15:00:00',
      'Security log export filtered for logon events of the affected account.',
      'Successful logons from two external IP ranges on 9 Aug.',
      'Consistent with credential reuse from an external breach.',
      'Logs older than 30 days had been rotated.', NULL, '2026-08-11 16:00:00'),
 (23, 'EX-2026-0023', 15, 7, 3, 'Completed', '2026-07-31', '2026-07-21 10:00:00', '2026-07-28 16:00:00',
      'Invoice PDF metadata extracted and compared with ERP access logs.',
      'All suspicious invoices were created by the same software and uploaded by one account.',
      'The invoices were produced and uploaded through a single compromised onboarding account.',
      'PDF metadata can be edited and was treated as supporting evidence only.', NULL, '2026-07-20 09:00:00'),
 (24, 'EX-2026-0024', 16, 1, 2, 'Cancelled', '2026-08-12', NULL, NULL, NULL, NULL, NULL, NULL,
      'Duplicate request: the image was examined under EX-2026-0020.', '2026-08-03 18:05:00'),
 (25, 'EX-2026-0025', 18, 2, 2, 'Completed', '2026-09-05', '2026-08-26 10:00:00', '2026-09-02 17:00:00',
      'USB file system examined on a verified working copy; deleted entries recovered.',
      '214 customer files were copied to the drive on 18 Aug and deleted on 20 Aug.',
      'Customer data was copied to the drive shortly before the employee left.',
      'Copy time is inferred from file system timestamps.', NULL, '2026-08-25 09:00:00'),
 (26, 'EX-2026-0026', 22, 6, 2, 'Pending', '2026-09-30', NULL, NULL, NULL, NULL, NULL, NULL, NULL, '2026-09-20 10:00:00'),
 (27, 'EX-2026-0027', 21, 7, 2, 'Completed', '2026-09-18', '2026-09-14 10:00:00', '2026-09-17 16:00:00',
      'Photo and document metadata extracted from the phone and SD card.',
      'Three photos of design boards were taken on 10 Sep.',
      'The phone photographed the design boards two days before the leak.',
      'The phone''s reference hash later failed re-verification; findings rest on the 12 Sep extraction.', NULL, '2026-09-13 15:00:00'),
 (28, 'EX-2026-0028', 23, 4, 3, 'In Progress', '2026-10-10', '2026-09-29 10:30:00', NULL, NULL, NULL, NULL, NULL, NULL, '2026-09-26 09:30:00'),
 (29, 'EX-2026-0029', 23, 3, 3, 'Completed', '2026-09-30', '2026-09-25 11:00:00', '2026-09-28 16:30:00',
      'Gateway log export filtered by sender domain and date. Email samples parsed for headers and embedded links. All work done on verified copies.',
      'Gateway logs show 47 messages from the domain payro11-update.example delivered to 31 payroll mailboxes on 22 Sep 2026 between 09:02 and 09:19. Each sample links to a login form hosted outside the organization.',
      'The messages are consistent with a targeted credential-phishing campaign. The look-alike domain suggests deliberate impersonation of the internal payroll service.',
      'Gateway logs do not show whether recipients opened the link. Click activity was outside the scope of this examination.',
      NULL, '2026-09-24 19:00:00'),
 (30, 'EX-2026-0030', 22, 5, 3, 'In Progress', '2026-10-01', '2026-09-25 12:00:00', NULL, NULL, NULL, NULL, NULL, NULL, '2026-09-24 10:00:00'),
 (31, 'EX-2026-0031', 22, 1, 2, 'In Progress', '2026-10-06', '2026-09-27 10:05:00', NULL, NULL, NULL, NULL, NULL, NULL, '2026-09-25 09:00:00');

INSERT INTO examination_evidence (examination_id, evidence_id, linked_at) VALUES
 (20, 44, '2026-08-03 18:00:00'),
 (21, 41, '2026-04-22 09:00:00'),
 (22, 45, '2026-08-11 16:00:00'),
 (23, 42, '2026-07-20 09:00:00'),
 (23, 43, '2026-07-20 09:00:00'),
 (24, 44, '2026-08-03 18:05:00'),
 (25, 46, '2026-08-25 09:00:00'),
 (26, 56, '2026-09-20 10:00:00'),
 (27, 47, '2026-09-13 15:00:00'),
 (27, 50, '2026-09-13 15:00:00'),
 (28, 57, '2026-09-26 09:30:00'),
 (29, 58, '2026-09-24 19:00:00'),
 (29, 59, '2026-09-24 19:00:00'),
 (30, 53, '2026-09-24 10:00:00'),
 (31, 51, '2026-09-25 09:00:00');

-- ---------------------------------------------------------------------
-- Reports. Created as Draft (the trigger only accepts versions for
-- drafts), versions added, then moved to their final status.
-- ---------------------------------------------------------------------
INSERT INTO forensic_reports (report_id, report_code, case_id, title, author_id, status, created_at, updated_at) VALUES
 ( 7, 'RP-2026-0007', 14, 'Lost laptop data exposure assessment',            3, 'Draft', '2026-05-02 10:00:00', '2026-05-08 15:00:00'),
 ( 8, 'RP-2026-0008', 15, 'Fake vendor invoices',                            3, 'Draft', '2026-07-29 10:00:00', '2026-08-02 12:00:00'),
 ( 9, 'RP-2026-0009', 16, 'Cryptominer on lab workstations',                 2, 'Draft', '2026-08-10 10:00:00', '2026-08-13 11:00:00'),
 (10, 'RP-2026-0010', 17, 'Compromised administrator credentials',           3, 'Draft', '2026-08-19 10:00:00', '2026-08-21 14:00:00'),
 (11, 'RP-2026-0011', 22, 'Preliminary findings, finance server ransomware', 2, 'Draft', '2026-09-30 16:00:00', '2026-09-30 16:00:00'),
 (12, 'RP-2026-0012', 23, 'Phishing campaign against payroll staff',         3, 'Draft', '2026-09-26 17:45:00', '2026-10-02 18:22:51');

INSERT INTO report_versions (report_id, version_no, methodology, observations, findings, conclusions,
                             limitations, change_note, created_by, created_at) VALUES
 ( 7, 1, 'File system timeline from a verified image (EX-2026-0021).', 'No file activity between loss and recovery.', 'No sign of access.', 'Data was not exposed.', 'Timestamps can be altered.', 'First draft', 3, '2026-05-02 10:00:00'),
 ( 7, 2, 'File system timeline from a verified image (EX-2026-0021).', 'No file activity between 14 Apr and 21 Apr.', 'No sign of access while lost.', 'No evidence that data was exposed.', 'Timestamps can be altered by a skilled attacker.', 'Clarified dates after review', 3, '2026-05-08 15:00:00'),
 ( 8, 1, 'Invoice metadata compared with ERP logs (EX-2026-0023).', 'Invoices share creation software.', 'Single source.', 'Fraud through one account.', 'Metadata can be edited.', 'First draft', 3, '2026-07-29 10:00:00'),
 ( 8, 2, 'Invoice metadata compared with ERP logs (EX-2026-0023).', 'All 9 suspicious invoices share creation software and uploader.', 'Single compromised onboarding account.', 'Fraud carried out through one compromised account.', 'Metadata treated as supporting evidence only.', 'Added invoice count', 3, '2026-07-31 11:00:00'),
 ( 8, 3, 'Invoice metadata compared with ERP logs (EX-2026-0023).', 'All 9 suspicious invoices share creation software and uploader.', 'Single compromised onboarding account.', 'Fraud carried out through one compromised account; vendor onboarding needs review.', 'Metadata treated as supporting evidence only.', 'Added recommendation', 3, '2026-08-02 12:00:00'),
 ( 9, 1, 'Image examination (EX-2026-0020).', 'Nightly scheduled task launched an unsigned binary.', 'Cryptominer present.', 'Installed through shared lab account.', 'One workstation imaged.', 'First draft', 2, '2026-08-10 10:00:00'),
 ( 9, 2, 'Image examination (EX-2026-0020).', 'Nightly scheduled task at 01:00 launched an unsigned binary.', 'Cryptominer present on LAB-WS-07.', 'Installed through the shared lab account; shared account disabled.', 'Only one of the affected workstations was imaged.', 'Added remediation note', 2, '2026-08-13 11:00:00'),
 (10, 1, 'Security log review (EX-2026-0022).', 'Logons from two external IP ranges on 9 Aug.', 'Credential reuse.', 'Account compromised through reuse.', 'Older logs rotated.', 'First draft', 3, '2026-08-19 10:00:00'),
 (10, 2, 'Security log review (EX-2026-0022).', 'Successful logons from two external IP ranges on 9 Aug.', 'Consistent with credential reuse from an external breach.', 'Account compromised through password reuse; credentials reset.', 'Logs older than 30 days had been rotated.', 'Final wording after review', 3, '2026-08-21 14:00:00'),
 (11, 1, 'Disk image examination in progress (EX-2026-0031).', 'Encrypted files carry a .lockfin extension.', 'Initial access not yet established.', 'Too early for conclusions.', 'Examination incomplete.', 'First draft', 2, '2026-09-30 16:00:00'),
 (12, 1, 'Mail gateway logs and samples hash-verified.', 'Phishing messages reached payroll mailboxes.', 'Likely phishing campaign.', 'Pending log analysis.', 'Log analysis not yet complete.', 'First draft', 3, '2026-09-26 17:45:00'),
 (12, 2, 'Mail gateway logs and email samples were hash-verified, then examined on working copies (EX-2026-0029).', '47 messages from payro11-update.example reached 31 payroll mailboxes on 22 Sep 2026 between 09:02 and 09:19. Each message links to an external login form.', 'Consistent with a targeted credential-phishing campaign impersonating the payroll service.', 'No evidence examined so far shows that credentials were submitted.', 'Gateway logs do not record link clicks.', 'Added EX-2026-0029 results', 3, '2026-09-29 12:10:00'),
 (12, 3, 'Mail gateway logs and email samples were hash-verified, then examined on working copies (EX-2026-0029). Logs were filtered by sender domain and date; headers and embedded links were extracted from each sample.', '47 messages from payro11-update.example reached 31 payroll mailboxes on 22 Sep 2026 between 09:02 and 09:19. Each message links to an external login form.', 'The evidence is consistent with a targeted credential-phishing campaign impersonating the payroll service.', 'No evidence examined so far shows that credentials were submitted.', 'Gateway logs do not record link clicks. The payroll officer''s phone (EX-2026-0028) has not been examined yet.', 'Submitted for review', 3, '2026-10-02 18:22:51');

INSERT INTO report_examinations (report_id, examination_id, linked_at) VALUES
 ( 7, 21, '2026-05-02 10:00:00'),
 ( 8, 23, '2026-07-29 10:00:00'),
 ( 9, 20, '2026-08-10 10:00:00'),
 (10, 22, '2026-08-19 10:00:00'),
 (11, 31, '2026-09-30 16:00:00'),
 (12, 29, '2026-09-29 12:10:00');

-- Move reports to their final review status (updated_at set explicitly).
UPDATE forensic_reports SET status = 'Approved', submitted_at = '2026-05-12 09:00:00', approved_by = 1, approved_at = '2026-05-14 10:00:00', updated_at = '2026-05-14 10:00:00' WHERE report_id = 7;
UPDATE forensic_reports SET status = 'Approved', submitted_at = '2026-08-03 09:00:00', approved_by = 1, approved_at = '2026-08-04 10:00:00', updated_at = '2026-08-04 10:00:00' WHERE report_id = 8;
UPDATE forensic_reports SET status = 'Approved', submitted_at = '2026-08-13 12:00:00', approved_by = 1, approved_at = '2026-08-14 10:00:00', updated_at = '2026-08-14 10:00:00' WHERE report_id = 9;
UPDATE forensic_reports SET status = 'Approved', submitted_at = '2026-08-21 15:00:00', approved_by = 1, approved_at = '2026-08-22 10:00:00', updated_at = '2026-08-22 10:00:00' WHERE report_id = 10;
UPDATE forensic_reports SET status = 'Under Review', submitted_at = '2026-10-02 18:22:51', updated_at = '2026-10-02 18:22:51' WHERE report_id = 12;

-- ---------------------------------------------------------------------
-- Historical audit records (role-change rows were added by the trigger)
-- ---------------------------------------------------------------------
INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address, created_at) VALUES
 (1, 'case.close',          'Case',            'FX-2026-0013',     'Success', 'Case closed',                                   '10.20.1.10', '2026-05-02 16:00:00.000'),
 (1, 'report.approve',      'Report',          'RP-2026-0007',     'Success', 'Version 2 approved',                            '10.20.1.10', '2026-05-14 10:00:00.000'),
 (1, 'case.close',          'Case',            'FX-2026-0014',     'Success', 'Case closed',                                   '10.20.1.10', '2026-05-15 12:00:00.000'),
 (1, 'report.approve',      'Report',          'RP-2026-0008',     'Success', 'Version 3 approved',                            '10.20.1.10', '2026-08-04 10:00:00.000'),
 (1, 'case.close',          'Case',            'FX-2026-0015',     'Success', 'Case closed',                                   '10.20.1.10', '2026-08-05 15:00:00.000'),
 (1, 'report.approve',      'Report',          'RP-2026-0009',     'Success', 'Version 2 approved',                            '10.20.1.10', '2026-08-14 10:00:00.000'),
 (2, 'case.close',          'Case',            'FX-2026-0016',     'Success', 'Case closed',                                   '10.20.1.22', '2026-08-16 11:00:00.000'),
 (1, 'report.approve',      'Report',          'RP-2026-0010',     'Success', 'Version 2 approved',                            '10.20.1.10', '2026-08-22 10:00:00.000'),
 (1, 'case.close',          'Case',            'FX-2026-0017',     'Success', 'Case closed',                                   '10.20.1.10', '2026-08-24 17:00:00.000'),
 (1, 'case.create',         'Case',            'FX-2026-0022',     'Success', 'Priority Critical, lead user 2',                '10.20.1.10', '2026-09-18 21:40:00.000'),
 (4, 'evidence.register',   'Evidence',        'FX-EV-2026-00051', 'Success', 'Original SHA-256 recorded',                     '10.20.1.14', '2026-09-19 14:00:00.000'),
 (4, 'custody.transfer',    'Evidence',        'FX-EV-2026-00051', 'Success', 'Checked Out, custody entry #54',                '10.20.1.14', '2026-09-26 15:55:00.000'),
 (4, 'custody.correct',     'Evidence',        'FX-EV-2026-00051', 'Success', 'Entry #55 corrects #54',                        '10.20.1.14', '2026-09-26 17:12:00.000'),
 (5, 'hash.verify',         'Evidence',        'FX-EV-2026-00047', 'Success', 'Result Failed',                                 '10.20.1.18', '2026-09-30 11:00:00.000'),
 (2, 'report.create',       'Report',          'RP-2026-0011',     'Success', 'Version 1 created',                             '10.20.1.22', '2026-09-30 16:00:00.000'),
 (4, 'custody.transfer',    'Evidence',        'FX-EV-2026-00047', 'Failure', 'Custodian changed by another user. Rolled back', '10.20.1.14', '2026-10-01 19:44:05.000'),
 (6, 'case.close',          'Case',            'FX-2026-0019',     'Denied',  'Role Read-Only Auditor lacks permission',       '10.20.1.31', '2026-10-02 15:12:47.000'),
 (2, 'case.update',         'Case',            'FX-2026-0022',     'Success', 'Changed field: description',                    '10.20.1.22', '2026-10-02 16:40:09.000'),
 (5, 'custody.transfer',    'Evidence',        'FX-EV-2026-00055', 'Success', 'Checked Out, custody entry #59',                '10.20.1.18', '2026-10-02 17:05:33.000'),
 (3, 'report.submit',       'Report',          'RP-2026-0012',     'Success', 'Version 3 sent for review',                     '10.20.1.25', '2026-10-02 18:22:51.000'),
 (1, 'account.approve',     'Account request', 'AR-0042',          'Success', 'Created user ishaan.v',                         '10.20.1.10', '2026-10-03 10:15:02.000'),
 (4, 'hash.verify',         'Evidence',        'FX-EV-2026-00051', 'Success', 'Result Verified',                               '10.20.1.14', '2026-10-03 10:42:18.000');

-- ---------------------------------------------------------------------
-- Counters continue after the seeded codes.
-- ---------------------------------------------------------------------
INSERT INTO reference_sequences (seq_name, seq_year, last_number) VALUES
 ('CASE',        2026, 24),
 ('EVIDENCE',    2026, 59),
 ('EXAMINATION', 2026, 31),
 ('REPORT',      2026, 12);

SET @app_user_id = NULL;
SET @app_ip = NULL;
