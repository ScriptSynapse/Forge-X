-- =====================================================================
-- FORGE-X  |  database/views.sql
-- Eight views used by the dashboard, lists and reports.
-- Run after schema.sql (and triggers.sql).
-- =====================================================================

USE forge_x_db;

-- ---------------------------------------------------------------------
-- 1. v_open_cases: every case that is not Closed, with its lead and
--    evidence count. Demonstrates LEFT JOIN + scalar subquery.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_open_cases AS
SELECT c.case_id,
       c.case_reference,
       c.title,
       ct.type_name   AS case_type,
       c.priority,
       c.status,
       c.created_at,
       lu.user_id     AS lead_user_id,
       lu.full_name   AS lead_investigator,
       (SELECT COUNT(*) FROM evidence e WHERE e.case_id = c.case_id) AS evidence_count
  FROM cases c
  JOIN case_types ct            ON ct.case_type_id = c.case_type_id
  LEFT JOIN case_investigators ci ON ci.case_id = c.case_id AND ci.is_lead = TRUE
  LEFT JOIN users lu            ON lu.user_id = ci.user_id
 WHERE c.status <> 'Closed';

-- ---------------------------------------------------------------------
-- 2. v_evidence_integrity: DERIVES each item's integrity status.
--    Not Verified = no reference hash recorded
--    Pending      = reference hash recorded, never verified
--    Verified / Failed = result of the latest verification of the
--                        current (non-superseded) reference hash
--    Demonstrates a window function (ROW_NUMBER) in a derived table.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_evidence_integrity AS
SELECT e.evidence_id,
       e.evidence_code,
       h.hash_id        AS current_hash_id,
       h.hash_value     AS current_hash_value,
       lv.result        AS last_result,
       lv.verified_at   AS last_verified_at,
       lv.verified_by   AS last_verified_by,
       CASE
         WHEN h.hash_id IS NULL          THEN 'Not Verified'
         WHEN lv.verification_id IS NULL THEN 'Pending'
         ELSE lv.result
       END AS integrity_status
  FROM evidence e
  LEFT JOIN evidence_hashes h
         ON h.evidence_id = e.evidence_id
        AND NOT EXISTS (SELECT 1 FROM evidence_hashes s WHERE s.supersedes_hash_id = h.hash_id)
  LEFT JOIN (SELECT hv.verification_id, hv.hash_id, hv.result, hv.verified_at, hv.verified_by,
                    ROW_NUMBER() OVER (PARTITION BY hv.hash_id
                                       ORDER BY hv.verified_at DESC, hv.verification_id DESC) AS rn
               FROM hash_verifications hv) lv
         ON lv.hash_id = h.hash_id
        AND lv.rn = 1;

-- ---------------------------------------------------------------------
-- 3. v_evidence_overview: the evidence registry row, fully labelled.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_evidence_overview AS
SELECT e.evidence_id,
       e.evidence_code,
       c.case_id,
       c.case_reference,
       et.type_name         AS evidence_type,
       e.description,
       e.current_status,
       vi.integrity_status,
       e.collected_at,
       e.current_custodian_id,
       cu.full_name         AS current_custodian,
       sl.location_name     AS current_location
  FROM evidence e
  JOIN cases c                ON c.case_id = e.case_id
  JOIN evidence_types et      ON et.evidence_type_id = e.evidence_type_id
  JOIN users cu               ON cu.user_id = e.current_custodian_id
  LEFT JOIN storage_locations sl ON sl.location_id = e.current_location_id
  JOIN v_evidence_integrity vi ON vi.evidence_id = e.evidence_id;

-- ---------------------------------------------------------------------
-- 4. v_current_custodians: who holds each item now, and since when.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_current_custodians AS
SELECT e.evidence_id,
       e.evidence_code,
       c.case_reference,
       e.current_status,
       u.user_id          AS custodian_id,
       u.full_name        AS custodian_name,
       sl.location_name   AS location_name,
       (SELECT MAX(coc.occurred_at)
          FROM chain_of_custody coc
         WHERE coc.evidence_id = e.evidence_id) AS held_since
  FROM evidence e
  JOIN cases c   ON c.case_id = e.case_id
  JOIN users u   ON u.user_id = e.current_custodian_id
  LEFT JOIN storage_locations sl ON sl.location_id = e.current_location_id;

-- ---------------------------------------------------------------------
-- 5. v_examination_summary: examinations with an overdue flag.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_examination_summary AS
SELECT x.examination_id,
       x.examination_code,
       xt.type_name      AS examination_type,
       x.case_id,
       c.case_reference,
       x.examiner_id,
       u.full_name       AS examiner_name,
       x.status,
       x.due_date,
       x.started_at,
       x.completed_at,
       (SELECT COUNT(*) FROM examination_evidence ee
         WHERE ee.examination_id = x.examination_id) AS evidence_count,
       COALESCE(x.status IN ('Pending','In Progress') AND x.due_date < CURRENT_DATE, FALSE) AS is_overdue
  FROM examinations x
  JOIN examination_types xt ON xt.examination_type_id = x.examination_type_id
  JOIN cases c              ON c.case_id = x.case_id
  JOIN users u              ON u.user_id = x.examiner_id;

-- ---------------------------------------------------------------------
-- 6. v_current_report_versions: the newest version of every report.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_current_report_versions AS
SELECT ranked.report_id,
       ranked.version_id,
       ranked.version_no,
       ranked.methodology,
       ranked.observations,
       ranked.findings,
       ranked.conclusions,
       ranked.limitations,
       ranked.change_note,
       ranked.created_by,
       ranked.created_at
  FROM (SELECT rv.*,
               ROW_NUMBER() OVER (PARTITION BY rv.report_id ORDER BY rv.version_no DESC) AS rn
          FROM report_versions rv) ranked
 WHERE ranked.rn = 1;

-- ---------------------------------------------------------------------
-- 7. v_case_report_summary: reporting progress per case.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_case_report_summary AS
SELECT c.case_id,
       c.case_reference,
       c.title,
       c.status                                   AS case_status,
       COUNT(r.report_id)                         AS report_count,
       COALESCE(SUM(r.status = 'Draft'), 0)        AS draft_reports,
       COALESCE(SUM(r.status = 'Under Review'), 0) AS reports_under_review,
       COALESCE(SUM(r.status = 'Approved'), 0)     AS approved_reports,
       MAX(r.updated_at)                          AS last_report_activity
  FROM cases c
  LEFT JOIN forensic_reports r ON r.case_id = c.case_id
 GROUP BY c.case_id, c.case_reference, c.title, c.status;

-- ---------------------------------------------------------------------
-- 8. v_activity_feed: audit_logs + login_attempts in one timeline.
--    Login events are stored only once (in login_attempts); this
--    UNION ALL lets the audit page and dashboard show them together.
-- ---------------------------------------------------------------------
CREATE OR REPLACE VIEW v_activity_feed AS
SELECT a.created_at                    AS occurred_at,
       a.user_id,
       u.full_name                     AS user_name,
       a.action,
       CAST(a.entity_type AS CHAR(30)) AS entity_type,
       a.entity_ref,
       CAST(a.outcome AS CHAR(10))     AS outcome,
       a.details,
       a.ip_address,
       'audit'                         AS source
  FROM audit_logs a
  LEFT JOIN users u ON u.user_id = a.user_id
UNION ALL
SELECT la.attempted_at,
       la.user_id,
       u.full_name,
       IF(la.success, 'login', 'login.attempt'),
       'User',
       la.username_or_email,
       IF(la.success, 'Success', 'Failure'),
       CAST(la.failure_reason AS CHAR(30)),
       la.ip_address,
       'login'
  FROM login_attempts la
  LEFT JOIN users u ON u.user_id = la.user_id;
