-- =====================================================================
-- FORGE-X : Forensic Operations, Records, Governance & Evidence Exchange
-- File   : 06_functions.sql
-- Purpose: Stored SQL functions — small, reusable, single-value
--          computations that both ad-hoc queries and the stored
--          procedures in 07_procedures.sql call directly.
-- Depends: 01_create_database.sql .. 04_indexes.sql
--          (09_seed_data.sql recommended so the test queries below
--          return non-trivial results).
--
-- DETERMINISM NOTE
--   fn_compare_hash() is a pure computation (no table access) and is
--   genuinely DETERMINISTIC/NO SQL. The other four read table data
--   that changes over time (e.g. today's evidence count for a case
--   will differ from next week's), so they are declared
--   READS SQL DATA. MySQL still requires *some* determinism
--   declaration for binary logging; per common convention (and because
--   these functions have no side effects and are safe to log
--   statement-based or row-based), they are declared DETERMINISTIC in
--   the narrower sense the flag actually controls: "given the current
--   table contents, calling this twice with the same input in the same
--   statement returns the same result" — it is not a claim that the
--   result never changes over time.
-- =====================================================================

USE forge_x;

-- Defensive: ensures THIS session sends/receives utf8mb4 regardless of
-- how the client was invoked (protects against a classic gotcha: running
-- `mysql -u root < this_file.sql` without --default-character-set=utf8mb4
-- silently corrupts any non-ASCII literal in this file via latin1
-- misinterpretation at write time -- discovered and fixed during Step 6
-- backend integration testing).
SET NAMES utf8mb4;

-- =====================================================================
-- FUNCTION 1: fn_get_case_evidence_count
-- Purpose: Total evidence items logged against a case. Used by
--          vw_case_summary and by application dashboards.
-- =====================================================================
DROP FUNCTION IF EXISTS fn_get_case_evidence_count;

DELIMITER $$

CREATE FUNCTION fn_get_case_evidence_count(p_case_id BIGINT UNSIGNED)
    RETURNS INT UNSIGNED
    DETERMINISTIC
    READS SQL DATA
BEGIN
    DECLARE v_count INT UNSIGNED;
    SELECT COUNT(*) INTO v_count FROM evidence WHERE case_id = p_case_id;
    RETURN v_count;
END$$

DELIMITER ;

-- =====================================================================
-- FUNCTION 2: fn_get_case_device_count
-- Purpose: Total devices seized under a case.
-- =====================================================================
DROP FUNCTION IF EXISTS fn_get_case_device_count;

DELIMITER $$

CREATE FUNCTION fn_get_case_device_count(p_case_id BIGINT UNSIGNED)
    RETURNS INT UNSIGNED
    DETERMINISTIC
    READS SQL DATA
BEGIN
    DECLARE v_count INT UNSIGNED;
    SELECT COUNT(*) INTO v_count FROM devices WHERE case_id = p_case_id;
    RETURN v_count;
END$$

DELIMITER ;

-- =====================================================================
-- FUNCTION 3: fn_get_case_open_examinations_count
-- Purpose: Count of examinations for a case's evidence that are NOT
--          yet completed/peer_reviewed (i.e. 'scheduled' or
--          'in_progress'). A small helper reused by sp_close_case()
--          in 07_procedures.sql to enforce "don't close a case with
--          examinations still in flight" — demonstrates a function
--          being composed inside a procedure's own validation logic.
-- =====================================================================
DROP FUNCTION IF EXISTS fn_get_case_open_examinations_count;

DELIMITER $$

CREATE FUNCTION fn_get_case_open_examinations_count(p_case_id BIGINT UNSIGNED)
    RETURNS INT UNSIGNED
    DETERMINISTIC
    READS SQL DATA
BEGIN
    DECLARE v_count INT UNSIGNED;
    SELECT COUNT(*) INTO v_count
      FROM evidence_examinations x
      JOIN evidence e ON x.evidence_id = e.evidence_id
     WHERE e.case_id = p_case_id
       AND x.examination_status IN ('scheduled','in_progress');
    RETURN v_count;
END$$

DELIMITER ;

-- =====================================================================
-- FUNCTION 4: fn_get_case_progress
-- Purpose: A single 0.00-100.00 progress percentage for a case, defined
--          as the share of that case's examinations which have reached
--          'completed' or 'peer_reviewed'. A case with zero
--          examinations logged yet returns 0.00 (progress is not yet
--          measurable), not NULL or a divide-by-zero error.
-- =====================================================================
DROP FUNCTION IF EXISTS fn_get_case_progress;

DELIMITER $$

CREATE FUNCTION fn_get_case_progress(p_case_id BIGINT UNSIGNED)
    RETURNS DECIMAL(5,2)
    DETERMINISTIC
    READS SQL DATA
BEGIN
    DECLARE v_total INT UNSIGNED;
    DECLARE v_done INT UNSIGNED;
    DECLARE v_progress DECIMAL(5,2);

    SELECT COUNT(*),
           SUM(CASE WHEN x.examination_status IN ('completed','peer_reviewed') THEN 1 ELSE 0 END)
      INTO v_total, v_done
      FROM evidence_examinations x
      JOIN evidence e ON x.evidence_id = e.evidence_id
     WHERE e.case_id = p_case_id;

    IF v_total IS NULL OR v_total = 0 THEN
        SET v_progress = 0.00;
    ELSE
        SET v_progress = ROUND((v_done / v_total) * 100, 2);
    END IF;

    RETURN v_progress;
END$$

DELIMITER ;

-- =====================================================================
-- FUNCTION 5: fn_compare_hash
-- Purpose: Case-insensitive, whitespace-tolerant comparison of two hash
--          strings. Pure computation — no table access — so this is a
--          genuinely deterministic NO SQL function. Used directly by
--          sp_verify_evidence() in 07_procedures.sql, and safe to call
--          standalone from any query.
-- =====================================================================
DROP FUNCTION IF EXISTS fn_compare_hash;

DELIMITER $$

CREATE FUNCTION fn_compare_hash(p_hash1 VARCHAR(128), p_hash2 VARCHAR(128))
    RETURNS VARCHAR(20)
    DETERMINISTIC
    NO SQL
BEGIN
    IF p_hash1 IS NULL OR p_hash2 IS NULL THEN
        RETURN 'UNKNOWN';
    ELSEIF LOWER(TRIM(p_hash1)) = LOWER(TRIM(p_hash2)) THEN
        RETURN 'MATCH';
    ELSE
        RETURN 'MISMATCH';
    END IF;
END$$

DELIMITER ;

SELECT 'All 5 FORGE-X stored functions created successfully.' AS status;

-- =====================================================================
-- Quick smoke test (uses the flagship case and real seed data)
-- =====================================================================
SELECT
    c.case_number,
    fn_get_case_evidence_count(c.case_id)          AS evidence_count,
    fn_get_case_device_count(c.case_id)             AS device_count,
    fn_get_case_open_examinations_count(c.case_id)  AS open_examinations,
    fn_get_case_progress(c.case_id)                 AS progress_percent
FROM cases c
ORDER BY c.case_id;

SELECT
    fn_compare_hash('ABCDEF1234', 'abcdef1234')       AS should_be_match,
    fn_compare_hash('ABCDEF1234', 'ABCDEF9999')       AS should_be_mismatch,
    fn_compare_hash(NULL, 'ABCDEF1234')               AS should_be_unknown;
