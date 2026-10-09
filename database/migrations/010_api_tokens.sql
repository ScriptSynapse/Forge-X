-- =====================================================================
-- FORGE-X  |  database/migrations/010_api_tokens.sql
-- FORGE-X 2.0 Phase 10: personal API tokens for the read-only REST API.
-- Run ONCE, as root, on a database built before this change:
--   mysql -u root -p -e "source database/migrations/010_api_tokens.sql"
--
-- Only the SHA-256 of a token is stored (the token itself is shown once).
-- Tokens always expire (at most 90 days), can be revoked, and are refused
-- as soon as the account is deactivated. No DELETE: a revoked token stays
-- as a record of who could access the API and when.
-- =====================================================================
USE forge_x_db;

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

ALTER TABLE audit_logs
  MODIFY entity_type ENUM('User','Role','Account request','Case','Evidence','Evidence hash',
                          'Custody entry','Examination','Report','Storage location','YARA rule','API token') NOT NULL;

GRANT INSERT, UPDATE ON forge_x_db.api_tokens TO 'forge_x_app_role';
