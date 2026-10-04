-- =====================================================================
-- FORGE-X  |  database/migrations/002_audit_storage_location.sql  (Phase 9)
--
-- Only needed if you built the database BEFORE Phase 9. A fresh
-- install_all.sql already includes this change. Run ONCE, as root:
--   mysql -u root -p -e "source database/migrations/002_audit_storage_location.sql"
--
-- Why: Phase 9 adds a storage-locations administration page, and its
-- changes are audited. audit_logs.entity_type needs a matching value.
-- Adding a value at the END of an ENUM keeps every existing row valid.
-- =====================================================================
USE forge_x_db;

ALTER TABLE audit_logs
  MODIFY entity_type ENUM('User','Role','Account request','Case','Evidence','Evidence hash',
                          'Custody entry','Examination','Report','Storage location') NOT NULL;
