-- =====================================================================
-- FORGE-X  |  database/seed_reference.sql
-- Reference data the application needs on every installation:
-- the four roles, case / evidence / examination types and storage
-- locations. No users, cases or evidence.
--
-- The first administrator is created afterwards with:
--   flask --app run create-admin <username>
-- =====================================================================

USE forge_x_db;
-- ---------------------------------------------------------------------
-- Roles
-- ---------------------------------------------------------------------
INSERT INTO roles (role_id, role_name, description) VALUES
 (1, 'Administrator',      'Manages accounts and roles, approves reports and can see every record.'),
 (2, 'Investigator',       'Works on assigned cases: examinations, reports and evidence check-outs.'),
 (3, 'Evidence Custodian', 'Registers and stores evidence, records transfers and verifies hashes.'),
 (4, 'Read-Only Auditor',  'Reads all records and audit logs without changing anything.');

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

