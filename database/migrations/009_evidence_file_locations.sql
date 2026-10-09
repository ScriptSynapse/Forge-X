-- =====================================================================
-- FORGE-X  |  database/migrations/009_evidence_file_locations.sql
-- FORGE-X 2.0 Phase 9: optional object storage (S3 / MinIO).
-- Run ONCE, as root, on a database built before this change:
--   mysql -u root -p -e "source database/migrations/009_evidence_file_locations.sql"
--
-- evidence_files is append-only, so a file's storage location can't be
-- updated in place. Instead, every placement is a new row here:
--   * at registration: where the file was first stored
--   * after a migration (flask storage-migrate): the new backend, with the
--     SHA-256 measured on the source BEFORE the copy and on the target AFTER it
-- A file's current location is its latest row; files with no row (stored
-- before this migration) are on local disk. Append-only (2 triggers).
-- =====================================================================
USE forge_x_db;

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

DELIMITER $$
CREATE TRIGGER trg_efl_no_update BEFORE UPDATE ON evidence_file_locations FOR EACH ROW
BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Evidence file location records cannot be edited.'; END$$
CREATE TRIGGER trg_efl_no_delete BEFORE DELETE ON evidence_file_locations FOR EACH ROW
BEGIN SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Evidence file location records cannot be deleted.'; END$$
DELIMITER ;

GRANT INSERT ON forge_x_db.evidence_file_locations TO 'forge_x_app_role';
