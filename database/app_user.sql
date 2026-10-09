-- =====================================================================
-- FORGE-X  |  database/app_user.sql
-- Creates the least-privilege account Flask uses. Run as root AFTER
-- schema/triggers/views/procedures/seed.
--
-- BEFORE RUNNING: replace CHANGE_ME_App#Passw0rd_2026 (twice) with
-- your own strong password, and put the same value in your .env file
-- as MYSQL_PASSWORD. Never commit the real password to Git.
--
-- Design (database-level permissions):
--   * Privileges are granted to a MySQL ROLE, and the role is granted to
--     the login account(s). Two hosts are created because, depending on
--     server settings, a local TCP connection may arrive as 'localhost'
--     or as '127.0.0.1'.
--   * No DDL (CREATE/ALTER/DROP), no TRUNCATE, no GRANT, no FILE.
--   * Append-only tables get SELECT + INSERT only: even if a trigger
--     were dropped, the app account still could not UPDATE or DELETE
--     custody, hash, verification, report-version, audit or login rows.
--   * DELETE only where unassigning is a normal operation.
--
-- Application roles (Administrator, Investigator, ...) are different:
-- they are rows in the roles table, checked by Flask and by the stored
-- procedures for each PERSON. Every person shares this one database
-- account, so MySQL itself cannot tell lab members apart.
-- =====================================================================

DROP USER IF EXISTS 'forge_x_app'@'localhost';
DROP USER IF EXISTS 'forge_x_app'@'127.0.0.1';
DROP ROLE IF EXISTS 'forge_x_app_role';

CREATE ROLE 'forge_x_app_role';

-- Read everything (tables and views).
GRANT SELECT ON forge_x_db.* TO 'forge_x_app_role';

-- Call stored procedures and functions.
GRANT EXECUTE ON forge_x_db.* TO 'forge_x_app_role';

-- Append-only tables: INSERT only (plus SELECT above).
GRANT INSERT ON forge_x_db.chain_of_custody   TO 'forge_x_app_role';
GRANT INSERT ON forge_x_db.evidence_hashes    TO 'forge_x_app_role';
GRANT INSERT ON forge_x_db.hash_verifications TO 'forge_x_app_role';
GRANT INSERT ON forge_x_db.report_versions    TO 'forge_x_app_role';
GRANT INSERT ON forge_x_db.audit_logs         TO 'forge_x_app_role';
GRANT INSERT ON forge_x_db.login_attempts     TO 'forge_x_app_role';

-- Junction tables that are only ever added to.
GRANT INSERT ON forge_x_db.examination_evidence TO 'forge_x_app_role';
GRANT INSERT ON forge_x_db.report_examinations  TO 'forge_x_app_role';

-- Mutable tables: INSERT + UPDATE (no DELETE: records are archived, not deleted).
GRANT INSERT, UPDATE ON forge_x_db.users               TO 'forge_x_app_role';
GRANT INSERT, UPDATE ON forge_x_db.account_requests    TO 'forge_x_app_role';
GRANT INSERT, UPDATE ON forge_x_db.case_types          TO 'forge_x_app_role';
GRANT INSERT, UPDATE ON forge_x_db.evidence_types      TO 'forge_x_app_role';
GRANT INSERT, UPDATE ON forge_x_db.examination_types   TO 'forge_x_app_role';
GRANT INSERT, UPDATE ON forge_x_db.storage_locations   TO 'forge_x_app_role';
GRANT INSERT, UPDATE ON forge_x_db.reference_sequences TO 'forge_x_app_role';
GRANT INSERT, UPDATE ON forge_x_db.cases               TO 'forge_x_app_role';
GRANT INSERT, UPDATE ON forge_x_db.evidence            TO 'forge_x_app_role';
GRANT INSERT, UPDATE ON forge_x_db.examinations        TO 'forge_x_app_role';
GRANT INSERT, UPDATE ON forge_x_db.forensic_reports    TO 'forge_x_app_role';

-- Unassigning is a normal operation here (decision D4).
GRANT INSERT, UPDATE, DELETE ON forge_x_db.user_roles         TO 'forge_x_app_role';
GRANT INSERT, UPDATE, DELETE ON forge_x_db.case_investigators TO 'forge_x_app_role';

-- Deleting a case registered by mistake (only when it has no evidence,
-- examinations or reports: the RESTRICT foreign keys refuse otherwise).
GRANT DELETE ON forge_x_db.cases TO 'forge_x_app_role';

-- Case notes are append-only (FORGE-X 2.0): INSERT only, no UPDATE or DELETE.
GRANT INSERT ON forge_x_db.case_notes TO 'forge_x_app_role';

-- Stored evidence file records are append-only (FORGE-X 2.0): INSERT only.
GRANT INSERT ON forge_x_db.evidence_files TO 'forge_x_app_role';

-- Examination artifacts are append-only (FORGE-X 2.0): INSERT only.
GRANT INSERT ON forge_x_db.examination_artifacts TO 'forge_x_app_role';

-- YARA (FORGE-X 2.0 Phase 7): rules are mutable (flags); versions, scans and matches append-only.
GRANT INSERT, UPDATE ON forge_x_db.yara_rules         TO 'forge_x_app_role';
GRANT INSERT         ON forge_x_db.yara_rule_versions TO 'forge_x_app_role';
GRANT INSERT, DELETE ON forge_x_db.yara_rule_cases    TO 'forge_x_app_role';
GRANT INSERT         ON forge_x_db.yara_scans         TO 'forge_x_app_role';
GRANT INSERT         ON forge_x_db.yara_scan_rules    TO 'forge_x_app_role';
GRANT INSERT         ON forge_x_db.yara_matches       TO 'forge_x_app_role';

-- Evidence file location history (FORGE-X 2.0 Phase 9): append-only, INSERT only.
GRANT INSERT ON forge_x_db.evidence_file_locations TO 'forge_x_app_role';

-- API tokens (FORGE-X 2.0 Phase 10): created, marked used, revoked. Never deleted.
GRANT INSERT, UPDATE ON forge_x_db.api_tokens TO 'forge_x_app_role';

-- The roles table is fixed reference data: SELECT only (granted above).

CREATE USER 'forge_x_app'@'localhost' IDENTIFIED BY 'CHANGE_ME_App#Passw0rd_2026';
CREATE USER 'forge_x_app'@'127.0.0.1' IDENTIFIED BY 'CHANGE_ME_App#Passw0rd_2026';

GRANT 'forge_x_app_role' TO 'forge_x_app'@'localhost', 'forge_x_app'@'127.0.0.1';
SET DEFAULT ROLE 'forge_x_app_role' TO 'forge_x_app'@'localhost', 'forge_x_app'@'127.0.0.1';

-- Check what the account can do:
SHOW GRANTS FOR 'forge_x_app'@'localhost' USING 'forge_x_app_role';
