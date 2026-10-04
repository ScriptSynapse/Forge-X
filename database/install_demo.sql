-- =====================================================================
-- FORGE-X  |  database/install_demo.sql   (OPTIONAL)
-- Builds the lab WITH the synthetic demonstration data (8 users, 12
-- cases, 20 evidence items...) and runs the full 40-test verify_demo.sql.
--
-- WARNING: drops and recreates forge_x_db. All existing data is lost.
--   mysql -u root -p --default-character-set=utf8mb4 --table -e "source database/install_demo.sql"
-- Demo accounts have no usable password until you run
--   flask --app run set-password <username>
-- =====================================================================

SOURCE database/schema.sql;
SOURCE database/triggers.sql;
SOURCE database/views.sql;
SOURCE database/procedures.sql;
SOURCE database/seed_reference.sql;
SOURCE database/seed_demo.sql;
SOURCE database/verify_demo.sql;
