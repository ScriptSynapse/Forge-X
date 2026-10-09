-- =====================================================================
-- FORGE-X  |  database/migrations/005_evidence_files.sql
-- FORGE-X 2.0 Phase 3 (decision U1: store evidence files). Run ONCE, as
-- root, on a database built before this change (fresh installs include it):
--   mysql -u root -p -e "source database/migrations/005_evidence_files.sql"
--
-- Adds:
--   * evidence_files     one stored file per evidence item: generated object
--                        ID, original name (display only), type, size and the
--                        SHA-256 computed while the file was written.
--                        Append-only (2 triggers + INSERT-only grant).
--   * 'Stored file'      a new hash_verifications.method: re-hashing the
--                        stored copy. chk_hv_method is replaced by a version
--                        that also accepts it (every existing row still passes).
-- The files themselves live on disk (EVIDENCE_STORAGE_DIR), never in MySQL.
-- =====================================================================
USE forge_x_db;

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

DELIMITER $$
CREATE TRIGGER trg_ef_no_update BEFORE UPDATE ON evidence_files FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Stored evidence file records cannot be edited.';
END$$
CREATE TRIGGER trg_ef_no_delete BEFORE DELETE ON evidence_files FOR EACH ROW
BEGIN
  SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Stored evidence file records cannot be deleted.';
END$$
DELIMITER ;

ALTER TABLE hash_verifications
  MODIFY method ENUM('Sample file','Manual entry','Stored file') NOT NULL,
  DROP CHECK chk_hv_method,
  ADD CONSTRAINT chk_hv_method CHECK (
       (method = 'Sample file'  AND sample_file_name IS NOT NULL)
    OR (method = 'Manual entry' AND notes IS NOT NULL)
    OR (method = 'Stored file'  AND sample_file_name IS NOT NULL));

GRANT INSERT ON forge_x_db.evidence_files TO 'forge_x_app_role';
