-- =====================================================================
-- FORGE-X  |  database/migrations/006_custody_exported.sql
-- FORGE-X 2.0 Phase 4. Run ONCE, as root, on a database built before this
-- change (fresh installs include it):
--   mysql -u root -p -e "source database/migrations/006_custody_exported.sql"
--
-- Adds the custody action 'Exported': a copy of the stored evidence file was
-- downloaded. The original's custodian, location and status don't change,
-- so an Exported entry repeats the current custodian and location (which
-- keeps the "latest entry matches the item" consistency check true).
-- The value is appended to the ENUM, so every existing row stays valid.
-- =====================================================================
USE forge_x_db;

ALTER TABLE chain_of_custody
  MODIFY action ENUM('Collected','Received','Transferred','Checked Out','Examined',
                     'Returned','Stored','Released','Archived','Exported') NOT NULL;
