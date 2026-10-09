-- =====================================================================
-- FORGE-X  |  database/migrations/008_yara.sql
-- FORGE-X 2.0 Phase 7: YARA rule library and evidence scans (YARA-X).
-- Run ONCE, as root, on a database built before this change:
--   mysql -u root -p -e "source database/migrations/008_yara.sql"
--
-- Adds 6 tables:
--   yara_rules           the library (name, scope, enabled); mutable flags
--   yara_rule_versions   immutable rule source versions (append-only)
--   yara_rule_cases      rule-to-case associations for "Selected cases" rules
--   yara_scans           one row per finished scan (append-only)
--   yara_scan_rules      exactly which rule versions a scan used (append-only)
--   yara_matches         what matched (append-only)
-- 8 triggers keep the four history tables append-only; audit_logs gains
-- the entity type 'YARA rule'. Scans never modify evidence; they run in a
-- separate worker process on the stored copy (see app/yara/).
-- =====================================================================
USE forge_x_db;

CREATE TABLE yara_rules (
  rule_id       INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name          VARCHAR(100) NOT NULL,
  description   VARCHAR(500) NULL,
  author        VARCHAR(100) NULL,
  scope         ENUM('All cases','Selected cases') NOT NULL DEFAULT 'All cases',
  is_enabled    BOOLEAN NOT NULL DEFAULT TRUE,
  created_by    INT UNSIGNED NOT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (rule_id),
  UNIQUE KEY uq_yara_rule_name (name),
  CONSTRAINT fk_yr_user FOREIGN KEY (created_by) REFERENCES users (user_id),
  CONSTRAINT chk_yr_name CHECK (name REGEXP '^[A-Za-z0-9 ._-]{2,100}$')
) ENGINE = InnoDB;

CREATE TABLE yara_rule_versions (
  version_id     INT UNSIGNED NOT NULL AUTO_INCREMENT,
  rule_id        INT UNSIGNED NOT NULL,
  version_no     SMALLINT UNSIGNED NOT NULL,
  source         MEDIUMTEXT NOT NULL,
  source_sha256  CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  change_note    VARCHAR(255) NOT NULL,
  created_by     INT UNSIGNED NOT NULL,
  created_at     DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (version_id),
  UNIQUE KEY uq_yrv_rule_version (rule_id, version_no),
  CONSTRAINT fk_yrv_rule FOREIGN KEY (rule_id)    REFERENCES yara_rules (rule_id),
  CONSTRAINT fk_yrv_user FOREIGN KEY (created_by) REFERENCES users (user_id),
  CONSTRAINT chk_yrv_sha256 CHECK (source_sha256 REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT chk_yrv_version CHECK (version_no >= 1)
) ENGINE = InnoDB;

CREATE TABLE yara_rule_cases (
  rule_id   INT UNSIGNED NOT NULL,
  case_id   INT UNSIGNED NOT NULL,
  added_by  INT UNSIGNED NOT NULL,
  added_at  DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (rule_id, case_id),
  KEY idx_yrc_case (case_id),
  CONSTRAINT fk_yrc_rule FOREIGN KEY (rule_id)  REFERENCES yara_rules (rule_id),
  CONSTRAINT fk_yrc_case FOREIGN KEY (case_id)  REFERENCES cases (case_id),
  CONSTRAINT fk_yrc_user FOREIGN KEY (added_by) REFERENCES users (user_id)
) ENGINE = InnoDB;

CREATE TABLE yara_scans (
  scan_id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  evidence_id      INT UNSIGNED NOT NULL,
  file_id          INT UNSIGNED NOT NULL,
  status           ENUM('Completed','Failed','Timed out','Memory limit') NOT NULL,
  scanner_version  VARCHAR(40) NULL,
  file_sha256      CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  hash_matches     BOOLEAN NULL,
  rules_count      SMALLINT UNSIGNED NOT NULL,
  matched_count    SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  duration_ms      INT UNSIGNED NULL,
  limits_note      VARCHAR(255) NULL,
  error_message    VARCHAR(500) NULL,
  requested_by     INT UNSIGNED NOT NULL,
  started_at       DATETIME NOT NULL,
  finished_at      DATETIME NOT NULL,
  PRIMARY KEY (scan_id),
  KEY idx_ys_evidence (evidence_id, started_at),
  CONSTRAINT fk_ys_evidence FOREIGN KEY (evidence_id)  REFERENCES evidence (evidence_id),
  CONSTRAINT fk_ys_file     FOREIGN KEY (file_id)      REFERENCES evidence_files (file_id),
  CONSTRAINT fk_ys_user     FOREIGN KEY (requested_by) REFERENCES users (user_id),
  CONSTRAINT chk_ys_sha256  CHECK (file_sha256 IS NULL OR file_sha256 REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT chk_ys_times   CHECK (finished_at >= started_at),
  CONSTRAINT chk_ys_result  CHECK ((status = 'Completed' AND error_message IS NULL AND file_sha256 IS NOT NULL)
                                 OR (status <> 'Completed' AND error_message IS NOT NULL AND matched_count = 0))
) ENGINE = InnoDB;

CREATE TABLE yara_scan_rules (
  scan_id     INT UNSIGNED NOT NULL,
  version_id  INT UNSIGNED NOT NULL,
  PRIMARY KEY (scan_id, version_id),
  CONSTRAINT fk_ysr_scan    FOREIGN KEY (scan_id)    REFERENCES yara_scans (scan_id),
  CONSTRAINT fk_ysr_version FOREIGN KEY (version_id) REFERENCES yara_rule_versions (version_id)
) ENGINE = InnoDB;

CREATE TABLE yara_matches (
  match_id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  scan_id           INT UNSIGNED NOT NULL,
  version_id        INT UNSIGNED NOT NULL,
  rule_identifier   VARCHAR(128) NOT NULL,
  tags              VARCHAR(500) NULL,
  metadata_json     TEXT NULL,
  patterns_json     MEDIUMTEXT NULL,
  PRIMARY KEY (match_id),
  KEY idx_ym_scan (scan_id),
  CONSTRAINT fk_ym_scan    FOREIGN KEY (scan_id)    REFERENCES yara_scans (scan_id),
  CONSTRAINT fk_ym_version FOREIGN KEY (version_id) REFERENCES yara_rule_versions (version_id)
) ENGINE = InnoDB;

DELIMITER $$
CREATE TRIGGER trg_yrv_no_update BEFORE UPDATE ON yara_rule_versions FOR EACH ROW
BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'YARA rule versions cannot be edited. Save a new version.'; END$$
CREATE TRIGGER trg_yrv_no_delete BEFORE DELETE ON yara_rule_versions FOR EACH ROW
BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'YARA rule versions cannot be deleted.'; END$$
CREATE TRIGGER trg_ys_no_update BEFORE UPDATE ON yara_scans FOR EACH ROW
BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'YARA scan records cannot be edited.'; END$$
CREATE TRIGGER trg_ys_no_delete BEFORE DELETE ON yara_scans FOR EACH ROW
BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'YARA scan records cannot be deleted.'; END$$
CREATE TRIGGER trg_ysr_no_update BEFORE UPDATE ON yara_scan_rules FOR EACH ROW
BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'YARA scan records cannot be edited.'; END$$
CREATE TRIGGER trg_ysr_no_delete BEFORE DELETE ON yara_scan_rules FOR EACH ROW
BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'YARA scan records cannot be deleted.'; END$$
CREATE TRIGGER trg_ym_no_update BEFORE UPDATE ON yara_matches FOR EACH ROW
BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'YARA match records cannot be edited.'; END$$
CREATE TRIGGER trg_ym_no_delete BEFORE DELETE ON yara_matches FOR EACH ROW
BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'YARA match records cannot be deleted.'; END$$
DELIMITER ;

ALTER TABLE audit_logs
  MODIFY entity_type ENUM('User','Role','Account request','Case','Evidence','Evidence hash',
                          'Custody entry','Examination','Report','Storage location','YARA rule') NOT NULL;

GRANT INSERT, UPDATE ON forge_x_db.yara_rules         TO 'forge_x_app_role';
GRANT INSERT         ON forge_x_db.yara_rule_versions TO 'forge_x_app_role';
GRANT INSERT, DELETE ON forge_x_db.yara_rule_cases    TO 'forge_x_app_role';
GRANT INSERT         ON forge_x_db.yara_scans         TO 'forge_x_app_role';
GRANT INSERT         ON forge_x_db.yara_scan_rules    TO 'forge_x_app_role';
GRANT INSERT         ON forge_x_db.yara_matches       TO 'forge_x_app_role';
