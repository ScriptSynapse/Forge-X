-- =====================================================================
-- FORGE-X  |  database/install_all.sql
-- Builds an EMPTY lab: schema, triggers, views, procedures and the
-- reference data (roles, types, storage locations). No users, cases or
-- evidence. Then verifies the installation.
--
-- WARNING: drops and recreates forge_x_db. All existing data is lost.
--
-- Run from the FORGE-X project folder as root:
--   mysql -u root -p --default-character-set=utf8mb4 --table -e "source database/install_all.sql"
-- Then create the first administrator:
--   flask --app run create-admin <username>
--
-- For the demonstration data instead, use install_demo.sql.
-- =====================================================================

SOURCE database/schema.sql;
SOURCE database/triggers.sql;
SOURCE database/views.sql;
SOURCE database/procedures.sql;
SOURCE database/seed_reference.sql;
SOURCE database/verify.sql;
