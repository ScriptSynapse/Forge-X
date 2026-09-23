-- =====================================================================
-- FORGE-X : Forensic Operations, Records, Governance & Evidence Exchange
-- File   : 05_views.sql
-- Purpose: Reporting/dashboard views built from real multi-table JOINs
--          and aggregate functions — no view here is a thin single-
--          table wrapper.
-- Depends: 01_create_database.sql .. 04_indexes.sql
--          (06_functions.sql not required by these views, but
--          09_seed_data.sql is recommended so they return real rows).
--
-- FAN-OUT NOTE (read before modifying any view below)
--   Several views here JOIN a case (or evidence) row out to more than
--   one child table at once (e.g. vw_case_summary joins to
--   investigators, persons, devices, evidence, AND reports in a single
--   query). Joining to several one-to-many child tables simultaneously
--   multiplies rows combinatorially ("fan-out") — a case with 3
--   investigators and 4 devices would appear 12 times before
--   aggregation, and a naive COUNT(*) would then overcount every
--   metric. Every aggregate below is COUNT(DISTINCT <child PK>)
--   specifically to stay correct despite that fan-out — COUNT(DISTINCT
--   column) counts distinct values of that one column regardless of
--   how many times the row was duplicated by unrelated joins, which is
--   the standard, correct way to aggregate multiple one-to-many
--   relationships in a single query.
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
-- VIEW 1: vw_active_cases
-- Purpose: The primary case-list dashboard — every case NOT yet
--          closed/archived/cold, with its lead investigator, live
--          evidence count, and days-open, in one query.
-- =====================================================================
DROP VIEW IF EXISTS vw_active_cases;

CREATE VIEW vw_active_cases AS
SELECT
    c.case_id,
    c.case_number,
    c.case_title,
    ct.type_name                                   AS case_type,
    c.status,
    c.priority,
    u.full_name                                     AS created_by_name,
    (SELECT iu.full_name
       FROM case_investigators ci
       JOIN users iu ON ci.user_id = iu.user_id
      WHERE ci.case_id = c.case_id AND ci.role_in_case = 'lead_investigator'
      ORDER BY ci.assigned_at ASC
      LIMIT 1)                                      AS lead_investigator,
    COUNT(DISTINCT e.evidence_id)                    AS evidence_count,
    DATEDIFF(CURDATE(), c.opened_at)                 AS days_open
FROM cases c
JOIN case_types ct ON c.case_type_id = ct.case_type_id
JOIN users u ON c.created_by = u.user_id
LEFT JOIN evidence e ON e.case_id = c.case_id
WHERE c.status NOT IN ('closed', 'archived', 'cold')
GROUP BY c.case_id, c.case_number, c.case_title, ct.type_name, c.status, c.priority,
         u.full_name, c.opened_at;

-- =====================================================================
-- VIEW 2: vw_evidence_custody
-- Purpose: One row per evidence item showing who currently holds it,
--          where it currently sits, and its most recent custody event
--          — the day-to-day "where is this evidence right now" view.
--          Uses a window function (ROW_NUMBER) to pick each evidence
--          item's single latest chain_of_custody row.
-- =====================================================================
DROP VIEW IF EXISTS vw_evidence_custody;

CREATE VIEW vw_evidence_custody AS
SELECT
    e.evidence_id,
    e.evidence_number,
    c.case_number,
    cust.full_name                                   AS current_custodian,
    loc.location_name                                 AS current_storage_location,
    latest.custody_action                              AS last_custody_action,
    latest.custody_timestamp                            AS last_custody_timestamp,
    (SELECT COUNT(*) FROM chain_of_custody cc2
      WHERE cc2.evidence_id = e.evidence_id)             AS total_custody_events
FROM evidence e
JOIN cases c ON e.case_id = c.case_id
LEFT JOIN users cust ON e.current_custodian_id = cust.user_id
LEFT JOIN locations loc ON e.storage_location_id = loc.location_id
LEFT JOIN (
    SELECT evidence_id, custody_action, custody_timestamp,
           ROW_NUMBER() OVER (PARTITION BY evidence_id
                               ORDER BY custody_timestamp DESC, custody_id DESC) AS rn
    FROM chain_of_custody
) latest ON latest.evidence_id = e.evidence_id AND latest.rn = 1;

-- =====================================================================
-- VIEW 3: vw_investigator_workload
-- Purpose: Per-user caseload — how many cases they're assigned to (and
--          how many of those are still active), how much evidence
--          they've personally collected, and how many examinations
--          they've performed. Powers a supervisor's team-workload view.
-- =====================================================================
DROP VIEW IF EXISTS vw_investigator_workload;

CREATE VIEW vw_investigator_workload AS
SELECT
    u.user_id,
    u.full_name,
    r.role_name,
    d.department_name,
    COUNT(DISTINCT ci.case_id)                                              AS assigned_case_count,
    COUNT(DISTINCT CASE WHEN c.status NOT IN ('closed','archived','cold')
                         THEN ci.case_id END)                                AS active_case_count,
    COUNT(DISTINCT ev.evidence_id)                                          AS evidence_collected_count,
    COUNT(DISTINCT ex.examination_id)                                       AS examinations_performed_count
FROM users u
JOIN roles r ON u.role_id = r.role_id
JOIN departments d ON u.department_id = d.department_id
LEFT JOIN case_investigators ci ON ci.user_id = u.user_id
LEFT JOIN cases c ON c.case_id = ci.case_id
LEFT JOIN evidence ev ON ev.collected_by = u.user_id
LEFT JOIN evidence_examinations ex ON ex.examiner_id = u.user_id
GROUP BY u.user_id, u.full_name, r.role_name, d.department_name;

-- =====================================================================
-- VIEW 4: vw_case_summary
-- Purpose: The single richest per-case dashboard row — every headline
--          count (investigators, persons, devices, evidence, reports)
--          plus case duration, in one query. See the fan-out note at
--          the top of this file for why every count is COUNT(DISTINCT).
-- =====================================================================
DROP VIEW IF EXISTS vw_case_summary;

CREATE VIEW vw_case_summary AS
SELECT
    c.case_id,
    c.case_number,
    c.case_title,
    ct.type_name                                     AS case_type,
    c.status,
    c.priority,
    COUNT(DISTINCT ci.user_id)                         AS investigator_count,
    COUNT(DISTINCT cp.person_id)                        AS person_count,
    COUNT(DISTINCT dv.device_id)                         AS device_count,
    COUNT(DISTINCT ev.evidence_id)                        AS evidence_count,
    COUNT(DISTINCT rp.report_id)                           AS report_count,
    c.opened_at,
    c.closed_at,
    CASE WHEN c.closed_at IS NULL
         THEN DATEDIFF(CURDATE(), c.opened_at)
         ELSE DATEDIFF(c.closed_at, c.opened_at)
    END                                                      AS days_duration
FROM cases c
JOIN case_types ct ON c.case_type_id = ct.case_type_id
LEFT JOIN case_investigators ci ON ci.case_id = c.case_id
LEFT JOIN case_persons cp ON cp.case_id = c.case_id
LEFT JOIN devices dv ON dv.case_id = c.case_id
LEFT JOIN evidence ev ON ev.case_id = c.case_id
LEFT JOIN forensic_reports rp ON rp.case_id = c.case_id
GROUP BY c.case_id, c.case_number, c.case_title, ct.type_name, c.status, c.priority,
         c.opened_at, c.closed_at;

-- =====================================================================
-- VIEW 5: vw_evidence_integrity
-- Purpose: Every evidence item's integrity picture in one row: current
--          integrity_status, its reference (original) hash, and counts
--          of hash records / custody events / examinations on file.
--          Deliberately NOT pre-filtered to "problem" evidence only —
--          callers add `WHERE integrity_status <> 'intact'` themselves
--          — so the view stays useful for full-coverage integrity
--          audits as well as exception reports.
-- =====================================================================
DROP VIEW IF EXISTS vw_evidence_integrity;

CREATE VIEW vw_evidence_integrity AS
SELECT
    e.evidence_id,
    e.evidence_number,
    c.case_number,
    e.integrity_status,
    et.type_name                                       AS evidence_type,
    ref.hash_algorithm                                   AS reference_algorithm,
    ref.hash_value                                        AS reference_hash_value,
    ref.computed_at                                        AS reference_hash_computed_at,
    COUNT(DISTINCT h.hash_id)                                AS total_hash_records,
    COUNT(DISTINCT cc.custody_id)                             AS total_custody_events,
    COUNT(DISTINCT ex.examination_id)                          AS total_examinations
FROM evidence e
JOIN cases c ON e.case_id = c.case_id
JOIN evidence_types et ON e.evidence_type_id = et.evidence_type_id
LEFT JOIN (
    SELECT evidence_id, hash_algorithm, hash_value, computed_at,
           ROW_NUMBER() OVER (PARTITION BY evidence_id ORDER BY computed_at DESC) AS rn
    FROM evidence_hashes
    WHERE is_original = 1
) ref ON ref.evidence_id = e.evidence_id AND ref.rn = 1
LEFT JOIN evidence_hashes h ON h.evidence_id = e.evidence_id
LEFT JOIN chain_of_custody cc ON cc.evidence_id = e.evidence_id
LEFT JOIN evidence_examinations ex ON ex.evidence_id = e.evidence_id
GROUP BY e.evidence_id, e.evidence_number, c.case_number, e.integrity_status, et.type_name,
         ref.hash_algorithm, ref.hash_value, ref.computed_at;

SELECT 'All 5 FORGE-X views created successfully.' AS status;

-- =====================================================================
-- Quick smoke tests
-- =====================================================================
SELECT * FROM vw_active_cases ORDER BY case_id;
SELECT * FROM vw_evidence_custody ORDER BY evidence_id LIMIT 5;
SELECT * FROM vw_investigator_workload ORDER BY assigned_case_count DESC;
SELECT * FROM vw_case_summary ORDER BY case_id;
SELECT * FROM vw_evidence_integrity WHERE integrity_status <> 'intact';
