-- =====================================================================
-- FORGE-X  |  database/schema.sql
-- Creates forge_x_db with all 33 tables, keys, constraints and indexes.
-- Requires MySQL 8.0.16 or newer (CHECK constraints are enforced).
--
-- WARNING: this script DROPS and recreates forge_x_db. Run it as root
-- (or another admin account), never as the application account.
--
-- Run order: schema.sql -> triggers.sql -> views.sql -> procedures.sql
--            -> seed_reference.sql -> verify.sql   (see install_all.sql)
--            then app_user.sql, then: flask --app run create-admin <username>
-- =====================================================================

DROP DATABASE IF EXISTS forge_x_db;
CREATE DATABASE forge_x_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE forge_x_db;

-- Foreign keys below declare no ON DELETE / ON UPDATE clause. In InnoDB
-- the default is NO ACTION, which behaves exactly like RESTRICT:
-- a parent row that is still referenced can never be deleted.

-- ---------------------------------------------------------------------
-- 1. roles: the four fixed application roles
-- ---------------------------------------------------------------------
CREATE TABLE roles (
  role_id      TINYINT UNSIGNED NOT NULL AUTO_INCREMENT,
  role_name    VARCHAR(40)      NOT NULL,
  description  VARCHAR(255)     NOT NULL,
  PRIMARY KEY (role_id),
  UNIQUE KEY uq_roles_name (role_name)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 2. users: active and deactivated accounts (never pending applicants)
-- ---------------------------------------------------------------------
CREATE TABLE users (
  user_id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
  full_name             VARCHAR(100) NOT NULL,
  email                 VARCHAR(254) NOT NULL,
  username              VARCHAR(30)  NOT NULL,
  password_hash         VARCHAR(255) NOT NULL,
  account_status        ENUM('Active','Deactivated') NOT NULL DEFAULT 'Active',
  must_change_password  BOOLEAN      NOT NULL DEFAULT FALSE,
  -- Incremented on logout, password change and deactivation; sessions that
  -- carry an older value are rejected (server-side logout, Phase 6).
  session_version       INT UNSIGNED NOT NULL DEFAULT 0,
  created_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  last_login_at         DATETIME     NULL,
  PRIMARY KEY (user_id),
  UNIQUE KEY uq_users_email (email),
  UNIQUE KEY uq_users_username (username),
  CONSTRAINT chk_users_username CHECK (username REGEXP '^[A-Za-z0-9._]{3,30}$'),
  CONSTRAINT chk_users_email    CHECK (email LIKE '%_@_%._%')
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 3. user_roles: users <-> roles (many-to-many)
-- ---------------------------------------------------------------------
CREATE TABLE user_roles (
  user_role_id  INT UNSIGNED     NOT NULL AUTO_INCREMENT,
  user_id       INT UNSIGNED     NOT NULL,
  role_id       TINYINT UNSIGNED NOT NULL,
  assigned_by   INT UNSIGNED     NULL,   -- NULL only for the seeded first administrator
  assigned_at   DATETIME         NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_role_id),
  UNIQUE KEY uq_user_roles (user_id, role_id),
  CONSTRAINT fk_ur_user     FOREIGN KEY (user_id)     REFERENCES users (user_id),
  CONSTRAINT fk_ur_role     FOREIGN KEY (role_id)     REFERENCES roles (role_id),
  CONSTRAINT fk_ur_assigner FOREIGN KEY (assigned_by) REFERENCES users (user_id),
  -- Nobody can grant a role to themselves (no self-elevation).
  CONSTRAINT chk_ur_not_self CHECK (assigned_by IS NULL OR assigned_by <> user_id)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 4. account_requests: signup requests awaiting review
-- ---------------------------------------------------------------------
CREATE TABLE account_requests (
  request_id        INT UNSIGNED NOT NULL AUTO_INCREMENT,
  full_name         VARCHAR(100) NOT NULL,
  email             VARCHAR(254) NOT NULL,
  username          VARCHAR(30)  NOT NULL,
  password_hash     VARCHAR(255) NULL,      -- cleared once the request is reviewed
  reason            VARCHAR(500) NULL,
  request_status    ENUM('Pending','Approved','Rejected') NOT NULL DEFAULT 'Pending',
  reviewed_by       INT UNSIGNED NULL,
  reviewed_at       DATETIME     NULL,
  review_note       VARCHAR(255) NULL,
  created_user_id   INT UNSIGNED NULL,
  created_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- Helper columns: unique only among *pending* requests (NULL otherwise).
  pending_email     VARCHAR(254) GENERATED ALWAYS AS (IF(request_status = 'Pending', email, NULL)) STORED,
  pending_username  VARCHAR(30)  GENERATED ALWAYS AS (IF(request_status = 'Pending', username, NULL)) STORED,
  PRIMARY KEY (request_id),
  UNIQUE KEY uq_ar_created_user (created_user_id),
  UNIQUE KEY uq_ar_pending_email (pending_email),
  UNIQUE KEY uq_ar_pending_username (pending_username),
  KEY idx_ar_status_created (request_status, created_at),
  CONSTRAINT fk_ar_reviewer FOREIGN KEY (reviewed_by)     REFERENCES users (user_id),
  CONSTRAINT fk_ar_created  FOREIGN KEY (created_user_id) REFERENCES users (user_id),
  CONSTRAINT chk_ar_username CHECK (username REGEXP '^[A-Za-z0-9._]{3,30}$'),
  -- Pending: hash present, no reviewer. Reviewed: reviewer set, hash cleared.
  CONSTRAINT chk_ar_review CHECK (
       (request_status = 'Pending'  AND reviewed_by IS NULL     AND reviewed_at IS NULL     AND password_hash IS NOT NULL)
    OR (request_status <> 'Pending' AND reviewed_by IS NOT NULL AND reviewed_at IS NOT NULL AND password_hash IS NULL)
  ),
  CONSTRAINT chk_ar_created CHECK ((request_status = 'Approved') = (created_user_id IS NOT NULL))
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 5. login_attempts: every authentication attempt (never the password)
-- ---------------------------------------------------------------------
CREATE TABLE login_attempts (
  attempt_id         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  username_or_email  VARCHAR(254)    NOT NULL,
  user_id            INT UNSIGNED    NULL,
  success            BOOLEAN         NOT NULL,
  failure_reason     ENUM('invalid_credentials','account_inactive','rate_limited') NULL,
  ip_address         VARCHAR(45)     NOT NULL,
  user_agent         VARCHAR(255)    NULL,
  attempted_at       DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (attempt_id),
  KEY idx_login_ident_time (username_or_email, attempted_at),
  KEY idx_login_ip_time (ip_address, attempted_at),
  CONSTRAINT fk_la_user FOREIGN KEY (user_id) REFERENCES users (user_id),
  CONSTRAINT chk_la_outcome CHECK (
       (success = TRUE  AND failure_reason IS NULL AND user_id IS NOT NULL)
    OR (success = FALSE AND failure_reason IS NOT NULL)
  )
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 6-8. Lookup tables
-- ---------------------------------------------------------------------
CREATE TABLE case_types (
  case_type_id  SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
  type_name     VARCHAR(60)  NOT NULL,
  description   VARCHAR(255) NULL,
  is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
  PRIMARY KEY (case_type_id),
  UNIQUE KEY uq_case_types_name (type_name)
) ENGINE = InnoDB;

CREATE TABLE evidence_types (
  evidence_type_id  SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
  type_name         VARCHAR(60)  NOT NULL,
  description       VARCHAR(255) NULL,
  is_active         BOOLEAN      NOT NULL DEFAULT TRUE,
  PRIMARY KEY (evidence_type_id),
  UNIQUE KEY uq_evidence_types_name (type_name)
) ENGINE = InnoDB;

CREATE TABLE examination_types (
  examination_type_id  SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
  type_name            VARCHAR(80)  NOT NULL,
  description          VARCHAR(255) NULL,
  is_active            BOOLEAN      NOT NULL DEFAULT TRUE,
  PRIMARY KEY (examination_type_id),
  UNIQUE KEY uq_examination_types_name (type_name)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 9. storage_locations
-- ---------------------------------------------------------------------
CREATE TABLE storage_locations (
  location_id    SMALLINT UNSIGNED NOT NULL AUTO_INCREMENT,
  location_name  VARCHAR(100) NOT NULL,
  location_type  ENUM('Vault','Evidence Room','Examination Lab','Imaging Bench','Other') NOT NULL,
  description    VARCHAR(255) NULL,
  is_active      BOOLEAN      NOT NULL DEFAULT TRUE,
  PRIMARY KEY (location_id),
  UNIQUE KEY uq_locations_name (location_name)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 10. reference_sequences: gap-free yearly counters for business codes
-- ---------------------------------------------------------------------
CREATE TABLE reference_sequences (
  seq_name    ENUM('CASE','EVIDENCE','EXAMINATION','REPORT') NOT NULL,
  seq_year    SMALLINT UNSIGNED NOT NULL,
  last_number  INT UNSIGNED      NOT NULL DEFAULT 0,
  PRIMARY KEY (seq_name, seq_year)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 11. cases
-- ---------------------------------------------------------------------
CREATE TABLE cases (
  case_id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  case_reference   CHAR(12) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  title            VARCHAR(200) NOT NULL,
  description      TEXT         NOT NULL,
  case_type_id     SMALLINT UNSIGNED NOT NULL,
  priority         ENUM('Low','Medium','High','Critical') NOT NULL DEFAULT 'Medium',
  status           ENUM('Open','In Progress','On Hold','Closed') NOT NULL DEFAULT 'Open',
  due_date         DATE         NULL,
  created_by       INT UNSIGNED NOT NULL,
  created_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  closed_at        DATETIME     NULL,
  closure_summary  VARCHAR(1000) NULL,
  PRIMARY KEY (case_id),
  UNIQUE KEY uq_cases_reference (case_reference),
  KEY idx_cases_status_priority (status, priority),
  KEY idx_cases_created_at (created_at),
  KEY idx_cases_due_date (due_date),
  CONSTRAINT fk_cases_type    FOREIGN KEY (case_type_id) REFERENCES case_types (case_type_id),
  CONSTRAINT fk_cases_creator FOREIGN KEY (created_by)   REFERENCES users (user_id),
  CONSTRAINT chk_cases_reference CHECK (case_reference REGEXP '^FX-[0-9]{4}-[0-9]{4}$'),
  CONSTRAINT chk_cases_closed CHECK (
       (status = 'Closed'  AND closed_at IS NOT NULL AND closure_summary IS NOT NULL)
    OR (status <> 'Closed' AND closed_at IS NULL)
  ),
  CONSTRAINT chk_cases_closed_after CHECK (closed_at IS NULL OR closed_at >= created_at),
  CONSTRAINT chk_cases_due_after_created CHECK (due_date IS NULL OR due_date >= DATE(created_at))
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 12. case_investigators: cases <-> investigators (many-to-many)
-- ---------------------------------------------------------------------
CREATE TABLE case_investigators (
  case_investigator_id  INT UNSIGNED NOT NULL AUTO_INCREMENT,
  case_id               INT UNSIGNED NOT NULL,
  user_id               INT UNSIGNED NOT NULL,
  is_lead               BOOLEAN      NOT NULL DEFAULT FALSE,
  assigned_by           INT UNSIGNED NOT NULL,
  assigned_at           DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- Helper column: equals case_id only for the lead row, so UNIQUE => one lead per case.
  lead_case_id          INT UNSIGNED GENERATED ALWAYS AS (IF(is_lead = TRUE, case_id, NULL)) STORED,
  PRIMARY KEY (case_investigator_id),
  UNIQUE KEY uq_ci_case_user (case_id, user_id),
  UNIQUE KEY uq_ci_one_lead (lead_case_id),
  CONSTRAINT fk_ci_case     FOREIGN KEY (case_id)     REFERENCES cases (case_id),
  CONSTRAINT fk_ci_user     FOREIGN KEY (user_id)     REFERENCES users (user_id),
  CONSTRAINT fk_ci_assigner FOREIGN KEY (assigned_by) REFERENCES users (user_id)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- case_notes: notes and references on a case (FORGE-X 2.0, decision U5).
-- Append-only (triggers trg_cn_*); corrections are linked new notes.
-- ---------------------------------------------------------------------
CREATE TABLE case_notes (
  note_id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  case_id           INT UNSIGNED NOT NULL,
  note_text         VARCHAR(4000) NOT NULL,
  reference         VARCHAR(255)  NULL,
  corrects_note_id  INT UNSIGNED  NULL,
  author_id         INT UNSIGNED  NOT NULL,
  created_at        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (note_id),
  KEY idx_case_notes_case_time (case_id, created_at),
  CONSTRAINT fk_cn_case     FOREIGN KEY (case_id)          REFERENCES cases (case_id),
  CONSTRAINT fk_cn_author   FOREIGN KEY (author_id)        REFERENCES users (user_id),
  CONSTRAINT fk_cn_corrects FOREIGN KEY (corrects_note_id) REFERENCES case_notes (note_id),
  CONSTRAINT chk_cn_text CHECK (CHAR_LENGTH(TRIM(note_text)) >= 2)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 13. evidence: metadata only, never the evidence files themselves
-- ---------------------------------------------------------------------
CREATE TABLE evidence (
  evidence_id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  evidence_code         CHAR(16) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  case_id               INT UNSIGNED NOT NULL,
  evidence_type_id      SMALLINT UNSIGNED NOT NULL,
  description           VARCHAR(500) NOT NULL,
  source_details        VARCHAR(255) NULL,
  size_bytes            BIGINT UNSIGNED NULL,
  collected_at          DATETIME     NOT NULL,
  collected_by          INT UNSIGNED NOT NULL,
  collection_site       VARCHAR(200) NOT NULL,
  collection_condition  VARCHAR(200) NOT NULL,
  -- Current state: controlled redundancy, kept in step with chain_of_custody
  -- by the transfer transaction (see sp_transfer_evidence).
  current_status        ENUM('In Transit','In Storage','Checked Out','Under Examination','Released','Archived') NOT NULL DEFAULT 'In Transit',
  current_custodian_id  INT UNSIGNED NOT NULL,
  current_location_id   SMALLINT UNSIGNED NULL,
  registered_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at            DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (evidence_id),
  UNIQUE KEY uq_evidence_code (evidence_code),
  KEY idx_evidence_status (current_status),
  CONSTRAINT fk_ev_case      FOREIGN KEY (case_id)              REFERENCES cases (case_id),
  CONSTRAINT fk_ev_type      FOREIGN KEY (evidence_type_id)     REFERENCES evidence_types (evidence_type_id),
  CONSTRAINT fk_ev_collector FOREIGN KEY (collected_by)         REFERENCES users (user_id),
  CONSTRAINT fk_ev_custodian FOREIGN KEY (current_custodian_id) REFERENCES users (user_id),
  CONSTRAINT fk_ev_location  FOREIGN KEY (current_location_id)  REFERENCES storage_locations (location_id),
  CONSTRAINT chk_ev_code CHECK (evidence_code REGEXP '^FX-EV-[0-9]{4}-[0-9]{5}$'),
  CONSTRAINT chk_ev_dates CHECK (collected_at <= registered_at)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- evidence_files: the stored copy of an evidence item (FORGE-X 2.0, U1).
-- One file per item; the file itself is on disk under a generated object
-- ID. Append-only (triggers trg_ef_*).
-- ---------------------------------------------------------------------
CREATE TABLE evidence_files (
  file_id        INT UNSIGNED NOT NULL AUTO_INCREMENT,
  evidence_id    INT UNSIGNED NOT NULL,
  object_id      CHAR(36) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  original_name  VARCHAR(255) NOT NULL,
  media_type     VARCHAR(100) NOT NULL,
  size_bytes     BIGINT UNSIGNED NOT NULL,
  sha256         CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  stored_by      INT UNSIGNED NOT NULL,
  stored_at      DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (file_id),
  UNIQUE KEY uq_ef_evidence (evidence_id),
  UNIQUE KEY uq_ef_object (object_id),
  CONSTRAINT fk_ef_evidence FOREIGN KEY (evidence_id) REFERENCES evidence (evidence_id),
  CONSTRAINT fk_ef_user     FOREIGN KEY (stored_by)   REFERENCES users (user_id),
  CONSTRAINT chk_ef_object CHECK (object_id REGEXP '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'),
  CONSTRAINT chk_ef_sha256 CHECK (sha256 REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT chk_ef_size   CHECK (size_bytes > 0)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- evidence_file_locations: where each stored file is (FORGE-X 2.0 Phase 9).
-- Latest row = current location; no row = local disk. Append-only.
-- ---------------------------------------------------------------------
CREATE TABLE evidence_file_locations (
  location_id    INT UNSIGNED NOT NULL AUTO_INCREMENT,
  file_id        INT UNSIGNED NOT NULL,
  backend        ENUM('local','s3') NOT NULL,
  container      VARCHAR(255) NULL,
  sha256_before  CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  sha256_after   CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  note           VARCHAR(255) NOT NULL,
  moved_by       INT UNSIGNED NOT NULL,
  moved_at       DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (location_id),
  KEY idx_efl_file (file_id, location_id),
  CONSTRAINT fk_efl_file FOREIGN KEY (file_id)  REFERENCES evidence_files (file_id),
  CONSTRAINT fk_efl_user FOREIGN KEY (moved_by) REFERENCES users (user_id),
  CONSTRAINT chk_efl_before CHECK (sha256_before IS NULL OR sha256_before REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT chk_efl_after  CHECK (sha256_after REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT chk_efl_verified CHECK (sha256_before IS NULL OR sha256_before = sha256_after)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 14. evidence_hashes: recorded reference hashes (append-only)
-- ---------------------------------------------------------------------
CREATE TABLE evidence_hashes (
  hash_id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  evidence_id         INT UNSIGNED NOT NULL,
  algorithm           ENUM('SHA-256') NOT NULL DEFAULT 'SHA-256',
  hash_value          CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  source              ENUM('Computed','Manual') NOT NULL,
  source_notes        VARCHAR(500) NULL,
  recorded_by         INT UNSIGNED NOT NULL,
  recorded_at         DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  supersedes_hash_id  INT UNSIGNED NULL,
  correction_reason   VARCHAR(500) NULL,
  -- Helper column: the first (root) hash of each item; UNIQUE => one root per item,
  -- so every item has a single linear chain of corrections.
  root_evidence_id    INT UNSIGNED GENERATED ALWAYS AS (IF(supersedes_hash_id IS NULL, evidence_id, NULL)) STORED,
  PRIMARY KEY (hash_id),
  UNIQUE KEY uq_eh_supersedes (supersedes_hash_id),
  UNIQUE KEY uq_eh_one_root (root_evidence_id),
  KEY idx_hashes_value (hash_value),
  CONSTRAINT fk_eh_evidence   FOREIGN KEY (evidence_id)        REFERENCES evidence (evidence_id),
  CONSTRAINT fk_eh_recorder   FOREIGN KEY (recorded_by)        REFERENCES users (user_id),
  CONSTRAINT fk_eh_supersedes FOREIGN KEY (supersedes_hash_id) REFERENCES evidence_hashes (hash_id),
  CONSTRAINT chk_eh_format CHECK (hash_value REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT chk_eh_manual_notes CHECK (source = 'Computed' OR source_notes IS NOT NULL),
  CONSTRAINT chk_eh_correction CHECK ((supersedes_hash_id IS NULL) = (correction_reason IS NULL))
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 15. hash_verifications: every comparison (append-only)
-- ---------------------------------------------------------------------
CREATE TABLE hash_verifications (
  verification_id    INT UNSIGNED NOT NULL AUTO_INCREMENT,
  hash_id            INT UNSIGNED NOT NULL,
  computed_hash      CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  result             ENUM('Verified','Failed') NOT NULL DEFAULT 'Failed', -- always set by trigger
  method             ENUM('Sample file','Manual entry','Stored file') NOT NULL,
  sample_file_name   VARCHAR(255) NULL,
  sample_size_bytes  BIGINT UNSIGNED NULL,
  notes              VARCHAR(500) NULL,
  verified_by        INT UNSIGNED NOT NULL,
  verified_at        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (verification_id),
  KEY idx_hv_hash_time (hash_id, verified_at),
  CONSTRAINT fk_hv_hash     FOREIGN KEY (hash_id)     REFERENCES evidence_hashes (hash_id),
  CONSTRAINT fk_hv_verifier FOREIGN KEY (verified_by) REFERENCES users (user_id),
  CONSTRAINT chk_hv_format CHECK (computed_hash REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT chk_hv_method CHECK (
       (method = 'Sample file'  AND sample_file_name IS NOT NULL)
    OR (method = 'Manual entry' AND notes IS NOT NULL)
    OR (method = 'Stored file'  AND sample_file_name IS NOT NULL)
  )
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 16. chain_of_custody: every handling event (append-only)
-- ---------------------------------------------------------------------
CREATE TABLE chain_of_custody (
  custody_id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  evidence_id          INT UNSIGNED NOT NULL,
  action               ENUM('Collected','Received','Transferred','Checked Out','Examined',
                            'Returned','Stored','Released','Archived','Exported') NOT NULL,
  from_custodian_id    INT UNSIGNED NULL,
  to_custodian_id      INT UNSIGNED NOT NULL,
  location_id          SMALLINT UNSIGNED NULL,
  location_note        VARCHAR(200) NULL,
  evidence_condition   VARCHAR(200) NOT NULL,
  seal_number          VARCHAR(30)  NULL,
  reason               VARCHAR(500) NOT NULL,
  occurred_at          DATETIME     NOT NULL,
  recorded_by          INT UNSIGNED NOT NULL,
  recorded_at          DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  corrects_custody_id  INT UNSIGNED NULL,
  PRIMARY KEY (custody_id),
  KEY idx_coc_evidence_time (evidence_id, occurred_at, custody_id),
  KEY idx_coc_occurred (occurred_at),
  CONSTRAINT fk_coc_evidence FOREIGN KEY (evidence_id)         REFERENCES evidence (evidence_id),
  CONSTRAINT fk_coc_from     FOREIGN KEY (from_custodian_id)   REFERENCES users (user_id),
  CONSTRAINT fk_coc_to       FOREIGN KEY (to_custodian_id)     REFERENCES users (user_id),
  CONSTRAINT fk_coc_location FOREIGN KEY (location_id)         REFERENCES storage_locations (location_id),
  CONSTRAINT fk_coc_recorder FOREIGN KEY (recorded_by)         REFERENCES users (user_id),
  CONSTRAINT fk_coc_corrects FOREIGN KEY (corrects_custody_id) REFERENCES chain_of_custody (custody_id),
  CONSTRAINT chk_coc_from     CHECK ((action = 'Collected') = (from_custodian_id IS NULL)),
  CONSTRAINT chk_coc_location CHECK (location_id IS NOT NULL OR location_note IS NOT NULL),
  CONSTRAINT chk_coc_time     CHECK (occurred_at <= recorded_at)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 17. examinations
-- ---------------------------------------------------------------------
CREATE TABLE examinations (
  examination_id       INT UNSIGNED NOT NULL AUTO_INCREMENT,
  examination_code     CHAR(12) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  case_id              INT UNSIGNED NOT NULL,
  examination_type_id  SMALLINT UNSIGNED NOT NULL,
  examiner_id          INT UNSIGNED NOT NULL,
  status               ENUM('Pending','In Progress','Completed','Cancelled','Under Review') NOT NULL DEFAULT 'Pending',
  due_date             DATE     NULL,
  started_at           DATETIME NULL,
  submitted_at         DATETIME NULL,
  completed_at         DATETIME NULL,
  reviewed_by          INT UNSIGNED NULL,
  reviewed_at          DATETIME NULL,
  review_note          VARCHAR(500) NULL,
  tools_methods        TEXT     NULL,
  observations         TEXT     NULL,
  findings             TEXT     NULL,
  conclusion           TEXT     NULL,
  limitations          TEXT     NULL,
  cancel_reason        VARCHAR(500) NULL,
  created_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (examination_id),
  UNIQUE KEY uq_exam_code (examination_code),
  KEY idx_exam_status_due (status, due_date),
  CONSTRAINT fk_exam_case     FOREIGN KEY (case_id)             REFERENCES cases (case_id),
  CONSTRAINT fk_exam_type     FOREIGN KEY (examination_type_id) REFERENCES examination_types (examination_type_id),
  CONSTRAINT fk_exam_examiner FOREIGN KEY (examiner_id)         REFERENCES users (user_id),
  CONSTRAINT fk_exam_reviewer FOREIGN KEY (reviewed_by)         REFERENCES users (user_id),
  CONSTRAINT chk_exam_independent CHECK (reviewed_by IS NULL OR reviewed_by <> examiner_id),
  CONSTRAINT chk_exam_code CHECK (examination_code REGEXP '^EX-[0-9]{4}-[0-9]{4}$'),
  CONSTRAINT chk_exam_state CHECK (
       (status = 'Pending'     AND started_at IS NULL     AND completed_at IS NULL)
    OR (status = 'In Progress' AND started_at IS NOT NULL AND completed_at IS NULL)
    OR (status = 'Under Review' AND started_at IS NOT NULL AND completed_at IS NULL AND submitted_at IS NOT NULL
                               AND tools_methods IS NOT NULL AND findings IS NOT NULL)
    OR (status = 'Completed'   AND started_at IS NOT NULL AND completed_at IS NOT NULL
                               AND completed_at >= started_at
                               AND tools_methods IS NOT NULL AND findings IS NOT NULL)
    OR (status = 'Cancelled'   AND cancel_reason IS NOT NULL)
  )
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 18. examination_evidence: examinations <-> evidence (many-to-many)
-- ---------------------------------------------------------------------
CREATE TABLE examination_evidence (
  examination_id  INT UNSIGNED NOT NULL,
  evidence_id     INT UNSIGNED NOT NULL,
  linked_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (examination_id, evidence_id),
  CONSTRAINT fk_ee_exam     FOREIGN KEY (examination_id) REFERENCES examinations (examination_id),
  CONSTRAINT fk_ee_evidence FOREIGN KEY (evidence_id)    REFERENCES evidence (evidence_id)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- examination_artifacts: artifacts found during an examination
-- (FORGE-X 2.0, U3). Append-only (triggers trg_art_*).
-- ---------------------------------------------------------------------
CREATE TABLE examination_artifacts (
  artifact_id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  examination_id       INT UNSIGNED NOT NULL,
  evidence_id          INT UNSIGNED NULL,
  artifact_type        ENUM('File','Registry entry','Log entry','Network indicator','Email','Other') NOT NULL,
  description          VARCHAR(500) NOT NULL,
  location             VARCHAR(500) NULL,
  sha256               CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NULL,
  corrects_artifact_id INT UNSIGNED NULL,
  recorded_by          INT UNSIGNED NOT NULL,
  recorded_at          DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (artifact_id),
  KEY idx_artifacts_exam (examination_id, recorded_at),
  KEY idx_artifacts_sha256 (sha256),
  CONSTRAINT fk_art_exam     FOREIGN KEY (examination_id)       REFERENCES examinations (examination_id),
  CONSTRAINT fk_art_evidence FOREIGN KEY (evidence_id)          REFERENCES evidence (evidence_id),
  CONSTRAINT fk_art_user     FOREIGN KEY (recorded_by)          REFERENCES users (user_id),
  CONSTRAINT fk_art_corrects FOREIGN KEY (corrects_artifact_id) REFERENCES examination_artifacts (artifact_id),
  CONSTRAINT chk_art_sha256  CHECK (sha256 IS NULL OR sha256 REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT chk_art_text    CHECK (CHAR_LENGTH(TRIM(description)) >= 2)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 19. forensic_reports: report header and review status
-- ---------------------------------------------------------------------
CREATE TABLE forensic_reports (
  report_id     INT UNSIGNED NOT NULL AUTO_INCREMENT,
  report_code   CHAR(12) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  case_id       INT UNSIGNED NOT NULL,
  title         VARCHAR(200) NOT NULL,
  author_id     INT UNSIGNED NOT NULL,
  status        ENUM('Draft','Under Review','Approved') NOT NULL DEFAULT 'Draft',
  submitted_at  DATETIME NULL,
  approved_by   INT UNSIGNED NULL,
  approved_at   DATETIME NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (report_id),
  UNIQUE KEY uq_report_code (report_code),
  KEY idx_reports_status (status),
  CONSTRAINT fk_rep_case     FOREIGN KEY (case_id)     REFERENCES cases (case_id),
  CONSTRAINT fk_rep_author   FOREIGN KEY (author_id)   REFERENCES users (user_id),
  CONSTRAINT fk_rep_approver FOREIGN KEY (approved_by) REFERENCES users (user_id),
  CONSTRAINT chk_rep_code CHECK (report_code REGEXP '^RP-[0-9]{4}-[0-9]{4}$'),
  CONSTRAINT chk_rep_approval CHECK (
       (status = 'Approved'  AND approved_by IS NOT NULL AND approved_at IS NOT NULL)
    OR (status <> 'Approved' AND approved_by IS NULL     AND approved_at IS NULL)
  ),
  CONSTRAINT chk_rep_submitted CHECK (status = 'Draft' OR submitted_at IS NOT NULL),
  -- Independent review: nobody approves their own report.
  CONSTRAINT chk_rep_independent CHECK (approved_by IS NULL OR approved_by <> author_id)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 20. report_versions: immutable content snapshots (append-only)
-- ---------------------------------------------------------------------
CREATE TABLE report_versions (
  version_id    INT UNSIGNED      NOT NULL AUTO_INCREMENT,
  report_id     INT UNSIGNED      NOT NULL,
  version_no    SMALLINT UNSIGNED NOT NULL,
  methodology   TEXT NULL,
  observations  TEXT NULL,
  findings      TEXT NULL,
  conclusions   TEXT NULL,
  limitations   TEXT NULL,
  change_note   VARCHAR(255)      NOT NULL,
  created_by    INT UNSIGNED      NOT NULL,
  created_at    DATETIME          NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (version_id),
  UNIQUE KEY uq_rv_report_version (report_id, version_no),
  CONSTRAINT fk_rv_report  FOREIGN KEY (report_id)  REFERENCES forensic_reports (report_id),
  CONSTRAINT fk_rv_creator FOREIGN KEY (created_by) REFERENCES users (user_id),
  CONSTRAINT chk_rv_version CHECK (version_no >= 1)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- 21. report_examinations: reports <-> examinations (many-to-many)
-- ---------------------------------------------------------------------
CREATE TABLE report_examinations (
  report_id       INT UNSIGNED NOT NULL,
  examination_id  INT UNSIGNED NOT NULL,
  linked_at       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (report_id, examination_id),
  CONSTRAINT fk_re_report FOREIGN KEY (report_id)      REFERENCES forensic_reports (report_id),
  CONSTRAINT fk_re_exam   FOREIGN KEY (examination_id) REFERENCES examinations (examination_id)
) ENGINE = InnoDB;

-- ---------------------------------------------------------------------
-- YARA rule library and scans (FORGE-X 2.0 Phase 7). History tables are
-- append-only (triggers trg_yrv_*, trg_ys_*, trg_ysr_*, trg_ym_*).
-- ---------------------------------------------------------------------
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


-- ---------------------------------------------------------------------
-- api_tokens: personal tokens for the read-only REST API (FORGE-X 2.0
-- Phase 10). Only the SHA-256 is stored; expiry at most 90 days.
-- ---------------------------------------------------------------------
CREATE TABLE api_tokens (
  token_id      INT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id       INT UNSIGNED NOT NULL,
  name          VARCHAR(60)  NOT NULL,
  token_prefix  CHAR(8) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  token_hash    CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
  created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  expires_at    DATETIME NOT NULL,
  last_used_at  DATETIME NULL,
  revoked_at    DATETIME NULL,
  PRIMARY KEY (token_id),
  UNIQUE KEY uq_api_token_hash (token_hash),
  KEY idx_api_tokens_user (user_id),
  CONSTRAINT fk_api_tokens_user FOREIGN KEY (user_id) REFERENCES users (user_id),
  CONSTRAINT chk_api_token_hash CHECK (token_hash REGEXP '^[0-9a-f]{64}$'),
  CONSTRAINT chk_api_token_expiry CHECK (expires_at > created_at AND expires_at <= created_at + INTERVAL 90 DAY),
  CONSTRAINT chk_api_token_name CHECK (CHAR_LENGTH(TRIM(name)) >= 2)
) ENGINE = InnoDB;


-- ---------------------------------------------------------------------
-- 22. audit_logs: append-only activity record (no secrets, ever)
-- ---------------------------------------------------------------------
CREATE TABLE audit_logs (
  audit_id     BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id      INT UNSIGNED    NULL,
  action       VARCHAR(50)     NOT NULL,
  entity_type  ENUM('User','Role','Account request','Case','Evidence','Evidence hash',
                    'Custody entry','Examination','Report','Storage location','YARA rule','API token') NOT NULL,
  entity_ref   VARCHAR(40)     NULL,
  outcome      ENUM('Success','Failure','Denied') NOT NULL,
  details      VARCHAR(500)    NULL,
  ip_address   VARCHAR(45)     NULL,
  created_at   DATETIME(3)     NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (audit_id),
  KEY idx_audit_created (created_at),
  KEY idx_audit_user_time (user_id, created_at),
  KEY idx_audit_entity (entity_type, entity_ref),
  CONSTRAINT fk_audit_user FOREIGN KEY (user_id) REFERENCES users (user_id)
) ENGINE = InnoDB;
