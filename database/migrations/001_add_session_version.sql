-- =====================================================================
-- FORGE-X  |  database/migrations/001_add_session_version.sql  (Phase 6)
--
-- Only needed if you built the database BEFORE Phase 6. A fresh
-- install_all.sql already includes this column. Run ONCE, as root:
--   mysql -u root -p -e "source database/migrations/001_add_session_version.sql"
--
-- Why: Flask stores the session in a signed cookie. Clearing the cookie
-- on logout does not stop a copied cookie from working. Each session now
-- records the user's session_version; logout, password changes and
-- deactivation increment it, so every older session is rejected.
-- =====================================================================
USE forge_x_db;

ALTER TABLE users
  ADD COLUMN session_version INT UNSIGNED NOT NULL DEFAULT 0 AFTER must_change_password;
