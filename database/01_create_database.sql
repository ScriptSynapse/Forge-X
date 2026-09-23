-- =====================================================================
-- FORGE-X : Forensic Operations, Records, Governance & Evidence Exchange
-- File   : 01_create_database.sql
-- Purpose: Database creation, character set, collation, and session
--          configuration for the FORGE-X forensic case management schema.
-- Engine : MySQL 8.0+
-- =====================================================================
-- WHY utf8mb4:
--   utf8mb4 (not utf8) is required to correctly store the full Unicode
--   range (emoji, non-Latin names/addresses, special symbols that may
--   appear in seized-device metadata, file names, examiner notes, etc.)
--   utf8mb4_0900_ai_ci is the MySQL 8.0 default accent/case-insensitive
--   collation and is used consistently across the schema.
-- =====================================================================

CREATE DATABASE IF NOT EXISTS forge_x
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_0900_ai_ci;

USE forge_x;

-- Defensive: ensures THIS session sends/receives utf8mb4 regardless of
-- how the client was invoked (protects against a classic gotcha: running
-- `mysql -u root < this_file.sql` without --default-character-set=utf8mb4
-- silently corrupts any non-ASCII literal in this file via latin1
-- misinterpretation at write time -- discovered and fixed during Step 6
-- backend integration testing).
SET NAMES utf8mb4;

-- ---------------------------------------------------------------------
-- Session-level safety settings (recommended for forensic-grade data
-- integrity; also documents ACID-relevant defaults for the viva).
-- ---------------------------------------------------------------------

-- InnoDB is the only engine used in this project (transactions, FK
-- enforcement, row-level locking, crash recovery via redo/undo logs —
-- all required for ACID compliance). This is set explicitly on every
-- CREATE TABLE statement in 02_tables.sql rather than relied on as a
-- server default.

-- Enforce strict SQL mode so invalid/truncated data is rejected rather
-- than silently coerced — this protects evidentiary data integrity.
SET SESSION sql_mode = 'STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION';

-- Ensure foreign key checks are ON for this session (they are ON by
-- default; this is explicit for clarity when this script is run
-- standalone, e.g. after a bulk import script has turned them off).
SET SESSION foreign_key_checks = 1;

-- Use UTC internally for all forensic timestamps to avoid ambiguity
-- across investigators/labs in different time zones. Application layer
-- is responsible for converting to local display time.
SET time_zone = '+00:00';

SELECT 'forge_x database created / verified successfully.' AS status;
