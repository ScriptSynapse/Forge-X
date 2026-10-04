-- =====================================================================
-- FORGE-X  |  database/sample_queries.sql
-- 32 queries for the DBMS viva. Each has: purpose, the concept it
-- demonstrates, and the expected result WITH THE DEMO DATA
-- (install_demo.sql). On an empty lab they run but return few or no rows.
--
-- This file is READ-ONLY in effect: the DML and transaction demos at
-- the end are wrapped in START TRANSACTION ... ROLLBACK.
--
-- Date-dependent queries (Q6, Q21) use CURDATE()/NOW(). Their expected
-- results below assume you run them in early October 2026; later dates
-- will add rows as more due dates pass.
--
-- Concept index
--   CREATE ............ schema.sql, views.sql (and Q30 temp demo)
--   INSERT/UPDATE/DELETE Q30, Q31
--   INNER JOIN ........ Q3, Q10, Q16, Q23
--   LEFT JOIN ......... Q3, Q8, Q9, Q12, Q16
--   RIGHT JOIN ........ Q26
--   GROUP BY / HAVING . Q4, Q9, Q13, Q15, Q17, Q18, Q22, Q25
--   Aggregates ........ Q5, Q9, Q15, Q22, Q25
--   Nested subquery ... Q27
--   Correlated subquery Q2, Q14, Q19, Q28
--   CTE (recursive) ... Q12
--   Window functions .. Q12 (SUM OVER), Q24 (ROW_NUMBER), Q29 (RANK)
--   Views ............. Q6, Q17, Q24 and the "Views in use" section
--   Indexes ........... Q32 (EXPLAIN)
--   Transactions ...... Q30, Q31 (and transactions_demo.sql)
-- =====================================================================

USE forge_x_db;

-- ---------------------------------------------------------------------
-- Q1. Open high-priority cases
-- Concept: WHERE with IN, custom ordering with FIELD().
-- Uses index idx_cases_status_priority on larger data sets.
-- Expected: 5 rows -> FX-2026-0022, FX-2026-0023 (Critical),
--           FX-2026-0018, FX-2026-0021, FX-2026-0024 (High).
-- ---------------------------------------------------------------------
SELECT c.case_reference, c.title, c.priority, c.status, c.created_at
  FROM cases c
 WHERE c.status <> 'Closed'
   AND c.priority IN ('High', 'Critical')
 ORDER BY FIELD(c.priority, 'Critical', 'High'), c.created_at;

-- ---------------------------------------------------------------------
-- Q2. Evidence never successfully verified against its current hash
-- Concept: correlated subquery with NOT EXISTS.
-- Expected: 5 rows -> 00048 and 00055 (no hash at all),
--           00050, 00054, 00057 (hash recorded, never checked).
-- Note: 00047 is NOT here: it passed once, then failed later (see Q10).
-- ---------------------------------------------------------------------
SELECT e.evidence_code, et.type_name, e.description
  FROM evidence e
  JOIN evidence_types et ON et.evidence_type_id = e.evidence_type_id
 WHERE NOT EXISTS (
         SELECT 1
           FROM evidence_hashes h
           JOIN hash_verifications hv ON hv.hash_id = h.hash_id
          WHERE h.evidence_id = e.evidence_id
            AND hv.result = 'Verified'
            AND NOT EXISTS (SELECT 1 FROM evidence_hashes s WHERE s.supersedes_hash_id = h.hash_id))
 ORDER BY e.evidence_code;

-- ---------------------------------------------------------------------
-- Q3. Complete chain of custody for one evidence item
-- Concept: INNER + LEFT JOINs, the same table (users) joined 3 times.
-- Expected: 6 rows for FX-EV-2026-00051: entries 29, 33, 41, 54, 55, 56.
--           Entry 55 shows "Corrects #54"; 54 is still listed unchanged.
-- ---------------------------------------------------------------------
SELECT coc.custody_id                                  AS entry,
       coc.occurred_at,
       coc.action,
       COALESCE(fu.full_name, '(none)')                AS from_custodian,
       tu.full_name                                    AS to_custodian,
       COALESCE(sl.location_name, coc.location_note)   AS location,
       coc.evidence_condition,
       coc.reason,
       ru.full_name                                    AS recorded_by,
       coc.recorded_at,
       IF(coc.corrects_custody_id IS NULL, '', CONCAT('Corrects #', coc.corrects_custody_id)) AS correction
  FROM chain_of_custody coc
  JOIN evidence e               ON e.evidence_id = coc.evidence_id
  LEFT JOIN users fu            ON fu.user_id = coc.from_custodian_id
  JOIN users tu                 ON tu.user_id = coc.to_custodian_id
  JOIN users ru                 ON ru.user_id = coc.recorded_by
  LEFT JOIN storage_locations sl ON sl.location_id = coc.location_id
 WHERE e.evidence_code = 'FX-EV-2026-00051'
 ORDER BY coc.occurred_at, coc.custody_id;

-- ---------------------------------------------------------------------
-- Q4. Investigators assigned to more than one active case
-- Concept: GROUP BY + HAVING.
-- Expected: Rohan Iyer 6 active cases (lead on 4), Sara Khan 4 (lead on 3).
-- ---------------------------------------------------------------------
SELECT u.full_name,
       COUNT(*)        AS active_cases,
       SUM(ci.is_lead) AS cases_as_lead
  FROM case_investigators ci
  JOIN cases c ON c.case_id = ci.case_id AND c.status <> 'Closed'
  JOIN users u ON u.user_id = ci.user_id
 GROUP BY u.user_id, u.full_name
HAVING COUNT(*) > 1
 ORDER BY active_cases DESC;

-- ---------------------------------------------------------------------
-- Q5. Average case resolution time
-- Concept: aggregate functions over a computed difference.
-- Expected: 5 closed cases, avg 19.5 days, fastest 13.9, slowest 26.2.
-- ---------------------------------------------------------------------
SELECT COUNT(*)                                                         AS closed_cases,
       ROUND(AVG(TIMESTAMPDIFF(HOUR, created_at, closed_at)) / 24, 1)   AS avg_days,
       ROUND(MIN(TIMESTAMPDIFF(HOUR, created_at, closed_at)) / 24, 1)   AS fastest_days,
       ROUND(MAX(TIMESTAMPDIFF(HOUR, created_at, closed_at)) / 24, 1)   AS slowest_days
  FROM cases
 WHERE status = 'Closed';

-- ---------------------------------------------------------------------
-- Q6. Overdue examinations
-- Concept: querying a view; date arithmetic.
-- Expected (early Oct 2026): EX-2026-0026 (due 30 Sep, Pending) and
--           EX-2026-0030 (due 1 Oct, In Progress).
-- ---------------------------------------------------------------------
SELECT examination_code, examination_type, case_reference, examiner_name,
       status, due_date, DATEDIFF(CURDATE(), due_date) AS days_overdue
  FROM v_examination_summary
 WHERE is_overdue
 ORDER BY due_date;

-- ---------------------------------------------------------------------
-- Q7. Reports awaiting review
-- Expected: 1 row -> RP-2026-0012, version 3, by Sara Khan.
-- ---------------------------------------------------------------------
SELECT r.report_code, r.title, c.case_reference, u.full_name AS author,
       cv.version_no, r.submitted_at,
       DATEDIFF(CURDATE(), r.submitted_at) AS days_waiting
  FROM forensic_reports r
  JOIN cases c                       ON c.case_id = r.case_id
  JOIN users u                       ON u.user_id = r.author_id
  JOIN v_current_report_versions cv  ON cv.report_id = r.report_id
 WHERE r.status = 'Under Review'
 ORDER BY r.submitted_at;

-- ---------------------------------------------------------------------
-- Q8. Cases without any evidence
-- Concept: LEFT JOIN ... IS NULL (anti-join).
-- Expected: FX-2026-0019 and FX-2026-0024.
-- ---------------------------------------------------------------------
SELECT c.case_reference, c.title, c.status
  FROM cases c
  LEFT JOIN evidence e ON e.case_id = c.case_id
 WHERE e.evidence_id IS NULL
 ORDER BY c.case_reference;

-- ---------------------------------------------------------------------
-- Q9. Evidence grouped by type (including types with zero items)
-- Expected: Digital Document 4, Log File 4, Disk Image 2, Hard Disk 2,
--   Mobile Device 2, Network Capture 2, USB Drive 2, Memory Card 1,
--   SSD 1, Other Digital Media 0  (total 20).
-- ---------------------------------------------------------------------
SELECT et.type_name, COUNT(e.evidence_id) AS items
  FROM evidence_types et
  LEFT JOIN evidence e ON e.evidence_type_id = et.evidence_type_id
 GROUP BY et.evidence_type_id, et.type_name
 ORDER BY items DESC, et.type_name;

-- ---------------------------------------------------------------------
-- Q10. Failed hash verifications
-- Expected: 1 row -> FX-EV-2026-00047, 30 Sep 2026, Dev Kulkarni.
-- ---------------------------------------------------------------------
SELECT e.evidence_code, hv.verification_id, hv.verified_at, u.full_name AS verified_by,
       h.hash_value AS recorded_hash, hv.computed_hash
  FROM hash_verifications hv
  JOIN evidence_hashes h ON h.hash_id = hv.hash_id
  JOIN evidence e        ON e.evidence_id = h.evidence_id
  JOIN users u           ON u.user_id = hv.verified_by
 WHERE hv.result = 'Failed'
 ORDER BY hv.verified_at DESC;

-- ---------------------------------------------------------------------
-- Q11. Most recent custody movements across the lab
-- Expected: entries 59, 58, 57, 56, 55 (newest first).
-- ---------------------------------------------------------------------
SELECT coc.custody_id, coc.occurred_at, e.evidence_code, coc.action,
       COALESCE(fu.full_name, '(none)')              AS from_custodian,
       tu.full_name                                  AS to_custodian,
       COALESCE(sl.location_name, coc.location_note) AS location
  FROM chain_of_custody coc
  JOIN evidence e                ON e.evidence_id = coc.evidence_id
  LEFT JOIN users fu             ON fu.user_id = coc.from_custodian_id
  JOIN users tu                  ON tu.user_id = coc.to_custodian_id
  LEFT JOIN storage_locations sl ON sl.location_id = coc.location_id
 ORDER BY coc.occurred_at DESC, coc.custody_id DESC
 LIMIT 5;

-- ---------------------------------------------------------------------
-- Q12. Monthly case registrations, including months with none
-- Concept: RECURSIVE CTE to generate months; window SUM() OVER for a
-- running total.
-- Expected: Apr 2, May 0, Jun 0, Jul 1, Aug 4, Sep 5, Oct 0;
--           running total 2, 2, 2, 3, 7, 12, 12.
-- ---------------------------------------------------------------------
WITH RECURSIVE months AS (
  SELECT DATE('2026-04-01') AS month_start
  UNION ALL
  SELECT month_start + INTERVAL 1 MONTH FROM months WHERE month_start < '2026-10-01'
),
counts AS (
  SELECT DATE(DATE_FORMAT(created_at, '%Y-%m-01')) AS month_start, COUNT(*) AS cases_registered
    FROM cases
   GROUP BY DATE(DATE_FORMAT(created_at, '%Y-%m-01'))
)
SELECT DATE_FORMAT(m.month_start, '%b %Y')                              AS month,
       COALESCE(c.cases_registered, 0)                                  AS cases_registered,
       SUM(COALESCE(c.cases_registered, 0)) OVER (ORDER BY m.month_start) AS running_total
  FROM months m
  LEFT JOIN counts c ON c.month_start = m.month_start
 ORDER BY m.month_start;

-- ---------------------------------------------------------------------
-- Q13. Users holding more than one role
-- Expected: Sara Khan, 2 roles: Evidence Custodian, Investigator.
-- ---------------------------------------------------------------------
SELECT u.full_name, u.username, COUNT(*) AS role_count,
       GROUP_CONCAT(r.role_name ORDER BY r.role_name SEPARATOR ', ') AS roles
  FROM users u
  JOIN user_roles ur ON ur.user_id = u.user_id
  JOIN roles r       ON r.role_id = ur.role_id
 GROUP BY u.user_id, u.full_name, u.username
HAVING COUNT(*) > 1;

-- ---------------------------------------------------------------------
-- Q14. Cases with no assigned investigator (data-quality check)
-- Concept: correlated NOT EXISTS.
-- Expected: EMPTY. sp_register_case always assigns a lead, so an empty
--           result here is the healthy outcome.
-- ---------------------------------------------------------------------
SELECT c.case_reference, c.title
  FROM cases c
 WHERE NOT EXISTS (SELECT 1 FROM case_investigators ci WHERE ci.case_id = c.case_id);

-- ---------------------------------------------------------------------
-- Q15. Activity by user and date (1 to 3 Oct 2026)
-- Concept: aggregation over the UNION view v_activity_feed.
-- Expected (seed rows): e.g. 1 Oct: Rohan Iyer 3 events (2 failed);
--   3 Oct: "(not logged in)" 5 failed attempts. If you ran seed_demo.sql on
--   one of these dates, the trigger-generated role audit rows (stamped
--   with the time you ran it) will also be counted.
-- ---------------------------------------------------------------------
SELECT DATE(occurred_at)                         AS activity_date,
       COALESCE(user_name, '(not logged in)')    AS user_name,
       COUNT(*)                                  AS events,
       SUM(outcome <> 'Success')                 AS failed_or_denied
  FROM v_activity_feed
 WHERE occurred_at >= '2026-10-01' AND occurred_at < '2026-10-04'
 GROUP BY DATE(occurred_at), COALESCE(user_name, '(not logged in)')
 ORDER BY activity_date, events DESC;

-- ---------------------------------------------------------------------
-- Q16. Evidence currently under examination, with the active examination
-- Expected: 00051 (EX-2026-0031, Rohan Iyer), 00053 (EX-2026-0030,
--           Sara Khan), 00057 (EX-2026-0028, Sara Khan).
-- ---------------------------------------------------------------------
SELECT e.evidence_code, et.type_name, cu.full_name AS custodian,
       x.examination_code, xt.type_name AS examination_type, xu.full_name AS examiner
  FROM evidence e
  JOIN evidence_types et ON et.evidence_type_id = e.evidence_type_id
  JOIN users cu          ON cu.user_id = e.current_custodian_id
  LEFT JOIN (examination_evidence ee
             JOIN examinations x       ON x.examination_id = ee.examination_id
                                      AND x.status = 'In Progress'
             JOIN examination_types xt ON xt.examination_type_id = x.examination_type_id
             JOIN users xu             ON xu.user_id = x.examiner_id)
         ON ee.evidence_id = e.evidence_id
 WHERE e.current_status = 'Under Examination'
 ORDER BY e.evidence_code;

-- ---------------------------------------------------------------------
-- Q17. Current custodians and how many active items each holds
-- Expected: Priya Nair 8, Dev Kulkarni 3, Sara Khan 2, Rohan Iyer 1.
-- ---------------------------------------------------------------------
SELECT custodian_name,
       COUNT(*) AS items_held,
       GROUP_CONCAT(evidence_code ORDER BY evidence_code SEPARATOR ', ') AS items
  FROM v_current_custodians
 WHERE current_status NOT IN ('Released', 'Archived')
 GROUP BY custodian_id, custodian_name
 ORDER BY items_held DESC;

-- ---------------------------------------------------------------------
-- Q18. Cases by priority
-- Expected: Low 2, Medium 4, High 4, Critical 2.
-- ---------------------------------------------------------------------
SELECT priority, COUNT(*) AS cases
  FROM cases
 GROUP BY priority
 ORDER BY FIELD(priority, 'Low', 'Medium', 'High', 'Critical');

-- ---------------------------------------------------------------------
-- Q19. Closed cases without an approved report
-- Expected: 1 row -> FX-2026-0013.
-- ---------------------------------------------------------------------
SELECT c.case_reference, c.title, c.closed_at
  FROM cases c
 WHERE c.status = 'Closed'
   AND NOT EXISTS (SELECT 1 FROM forensic_reports r
                    WHERE r.case_id = c.case_id AND r.status = 'Approved');

-- ---------------------------------------------------------------------
-- Q20. Account requests awaiting approval (oldest first)
-- Expected: AR-0043 Vikram Pillai, AR-0044 Neha Desai, AR-0045 Arjun Rao.
-- ---------------------------------------------------------------------
SELECT CONCAT('AR-', LPAD(request_id, 4, '0')) AS request_code,
       full_name, email, username, reason, created_at,
       TIMESTAMPDIFF(HOUR, created_at, NOW()) AS hours_waiting
  FROM account_requests
 WHERE request_status = 'Pending'
 ORDER BY created_at;

-- ---------------------------------------------------------------------
-- Q21. Inactive accounts: deactivated, never logged in, or idle 30+ days
-- Expected (early Oct 2026): Kabir Shah (Deactivated), Ishaan Verma (never).
-- ---------------------------------------------------------------------
SELECT full_name, username, account_status, last_login_at,
       CASE
         WHEN account_status = 'Deactivated' THEN 'Deactivated'
         WHEN last_login_at IS NULL           THEN 'Never logged in'
         ELSE 'No login for 30+ days'
       END AS reason
  FROM users
 WHERE account_status = 'Deactivated'
    OR last_login_at IS NULL
    OR last_login_at < NOW() - INTERVAL 30 DAY
 ORDER BY full_name;

-- ---------------------------------------------------------------------
-- Q22. Repeated failed login attempts (3 or more per identifier)
-- Expected: 1 row -> arjun.r, 5 failures from 1 IP, 09:55 to 09:59 on 3 Oct.
-- ---------------------------------------------------------------------
SELECT username_or_email,
       COUNT(*)                   AS failed_attempts,
       COUNT(DISTINCT ip_address) AS distinct_ips,
       MIN(attempted_at)          AS first_failure,
       MAX(attempted_at)          AS last_failure
  FROM login_attempts
 WHERE success = FALSE
 GROUP BY username_or_email
HAVING COUNT(*) >= 3
 ORDER BY failed_attempts DESC;

-- ---------------------------------------------------------------------
-- Q23. Evidence currently stored in a particular location
-- Expected: 4 rows in 'Vault B, Shelf 3' -> 00048, 00052, 00054, 00056.
-- ---------------------------------------------------------------------
SELECT e.evidence_code, c.case_reference, et.type_name, e.current_status, u.full_name AS custodian
  FROM evidence e
  JOIN storage_locations sl ON sl.location_id = e.current_location_id
  JOIN cases c              ON c.case_id = e.case_id
  JOIN evidence_types et    ON et.evidence_type_id = e.evidence_type_id
  JOIN users u              ON u.user_id = e.current_custodian_id
 WHERE sl.location_name = 'Vault B, Shelf 3'
 ORDER BY e.evidence_code;

-- ---------------------------------------------------------------------
-- Q24. Most recent report for each case
-- Concept: ROW_NUMBER() OVER (PARTITION BY ...) to pick 1 row per group.
-- Expected: 6 rows -> 0014: RP-0007 v2, 0015: RP-0008 v3, 0016: RP-0009 v2,
--           0017: RP-0010 v2, 0022: RP-0011 v1, 0023: RP-0012 v3.
-- ---------------------------------------------------------------------
SELECT case_reference, report_code, title, status, version_no, updated_at
  FROM (SELECT c.case_reference, r.report_code, r.title, r.status, cv.version_no, r.updated_at,
               ROW_NUMBER() OVER (PARTITION BY r.case_id
                                  ORDER BY r.updated_at DESC, r.report_id DESC) AS rn
          FROM forensic_reports r
          JOIN cases c                      ON c.case_id = r.case_id
          JOIN v_current_report_versions cv ON cv.report_id = r.report_id) ranked
 WHERE rn = 1
 ORDER BY case_reference;

-- ---------------------------------------------------------------------
-- Q25. Examination activity by investigator
-- Concept: conditional aggregation (SUM of boolean expressions).
-- Expected: Rohan Iyer 6 total (3 completed, 1 in progress, 1 pending,
--           1 cancelled, avg 5.0 days); Sara Khan 6 total (4 completed,
--           2 in progress, avg 6.0 days).
-- ---------------------------------------------------------------------
SELECT u.full_name                         AS examiner,
       COUNT(*)                            AS total,
       SUM(x.status = 'Completed')         AS completed,
       SUM(x.status = 'In Progress')       AS in_progress,
       SUM(x.status = 'Pending')           AS pending,
       SUM(x.status = 'Cancelled')         AS cancelled,
       ROUND(AVG(CASE WHEN x.status = 'Completed'
                      THEN TIMESTAMPDIFF(HOUR, x.started_at, x.completed_at) END) / 24, 1) AS avg_days_to_complete
  FROM examinations x
  JOIN users u ON u.user_id = x.examiner_id
 GROUP BY u.user_id, u.full_name
 ORDER BY total DESC, examiner;

-- ---------------------------------------------------------------------
-- Q26. Storage location occupancy, including empty locations
-- Concept: RIGHT JOIN (every row of the right-hand table is kept).
-- Expected: Archive Room 5, Vault B Shelf 3: 4, Vault B Shelf 5: 4,
--   Evidence Room A Locker 9: 2, Examination Lab 1: 2, Examination Lab 2: 1,
--   Imaging bench 1: 1, Lockers 2, 4 and 12: 0.
-- ---------------------------------------------------------------------
SELECT sl.location_name, sl.location_type, COUNT(e.evidence_id) AS items_here
  FROM evidence e
 RIGHT JOIN storage_locations sl ON sl.location_id = e.current_location_id
 GROUP BY sl.location_id, sl.location_name, sl.location_type
 ORDER BY items_here DESC, sl.location_name;

-- ---------------------------------------------------------------------
-- Q27. Cases holding more evidence than the average case
-- Concept: nested (non-correlated) subquery inside HAVING.
-- Average = 20 items / 12 cases = 1.67.
-- Expected: FX-2026-0022 (6), FX-2026-0023 (3), FX-2026-0015, 0018, 0021 (2 each).
-- ---------------------------------------------------------------------
SELECT c.case_reference, c.title, COUNT(e.evidence_id) AS items
  FROM cases c
  LEFT JOIN evidence e ON e.case_id = c.case_id
 GROUP BY c.case_id, c.case_reference, c.title
HAVING COUNT(e.evidence_id) > (SELECT AVG(per_case.n)
                                 FROM (SELECT COUNT(e2.evidence_id) AS n
                                         FROM cases c2
                                         LEFT JOIN evidence e2 ON e2.case_id = c2.case_id
                                        GROUP BY c2.case_id) per_case)
 ORDER BY items DESC, c.case_reference;

-- ---------------------------------------------------------------------
-- Q28. Most-handled evidence items
-- Concept: correlated subqueries in the SELECT list and WHERE clause.
-- Expected: 00051 (6 entries), 00053 (5), 00057 (4).
-- ---------------------------------------------------------------------
SELECT e.evidence_code,
       (SELECT COUNT(*) FROM chain_of_custody coc
         WHERE coc.evidence_id = e.evidence_id) AS custody_entries,
       (SELECT coc.action FROM chain_of_custody coc
         WHERE coc.evidence_id = e.evidence_id
         ORDER BY coc.occurred_at DESC, coc.custody_id DESC LIMIT 1) AS last_action
  FROM evidence e
 WHERE (SELECT COUNT(*) FROM chain_of_custody coc WHERE coc.evidence_id = e.evidence_id) > 3
 ORDER BY custody_entries DESC;

-- ---------------------------------------------------------------------
-- Q29. Investigator workload ranking
-- Concept: RANK() window function over an aggregate.
-- Expected: Rohan Iyer rank 1 (6), Sara Khan rank 2 (4), Ishaan Verma rank 3 (1).
-- ---------------------------------------------------------------------
SELECT u.full_name,
       COUNT(*)                             AS active_assignments,
       RANK() OVER (ORDER BY COUNT(*) DESC) AS workload_rank
  FROM case_investigators ci
  JOIN cases c ON c.case_id = ci.case_id AND c.status <> 'Closed'
  JOIN users u ON u.user_id = ci.user_id
 GROUP BY u.user_id, u.full_name
 ORDER BY workload_rank;

-- =====================================================================
-- Views in use
-- =====================================================================
SELECT * FROM v_open_cases ORDER BY case_reference;                       -- 7 rows
SELECT * FROM v_evidence_overview ORDER BY evidence_code;                 -- 20 rows
SELECT * FROM v_case_report_summary ORDER BY case_reference;              -- 12 rows
SELECT * FROM v_activity_feed ORDER BY occurred_at DESC LIMIT 10;         -- newest 10 events

-- =====================================================================
-- Q30. INSERT, UPDATE and DELETE, inside a transaction that is rolled back
-- Run as root (the application account deliberately has no DELETE here).
-- =====================================================================
START TRANSACTION;

INSERT INTO storage_locations (location_name, location_type, description)
VALUES ('Vault C, Shelf 1', 'Vault', 'Demo row');
SET @demo_loc = LAST_INSERT_ID();

-- WHERE uses the primary key, so this also works with Workbench's
-- "safe updates" mode switched on.
UPDATE storage_locations
   SET description = 'Demo row (updated)'
 WHERE location_id = @demo_loc;

SELECT location_id, location_name, description
  FROM storage_locations WHERE location_id = @demo_loc;                 -- shows the updated row

-- Allowed: nothing references this new location yet.
DELETE FROM storage_locations WHERE location_id = @demo_loc;

-- Not allowed (try it separately): a referenced location cannot be deleted.
--   DELETE FROM storage_locations WHERE location_id = 1;
--   -> Error 1451: Cannot delete or update a parent row: a foreign key constraint fails

ROLLBACK;

-- =====================================================================
-- Q31. Atomic custody transfer by hand, then ROLLBACK (and a SAVEPOINT)
-- Shows that the custody entry and the evidence update succeed or fail
-- together. sp_transfer_evidence does the same thing, but with COMMIT.
-- =====================================================================
SELECT evidence_code, current_status, current_custodian_id, current_location_id
  FROM evidence WHERE evidence_id = 55;                 -- Checked Out, 5 (Dev), 9

START TRANSACTION;

SELECT current_custodian_id FROM evidence WHERE evidence_id = 55 FOR UPDATE;   -- lock the row

INSERT INTO chain_of_custody (evidence_id, action, from_custodian_id, to_custodian_id, location_id,
                              evidence_condition, reason, occurred_at, recorded_by)
VALUES (55, 'Returned', 5, 4, 4, 'Sealed, intact', 'Imaging complete (demo)', NOW(), 5);

SAVEPOINT after_custody_insert;

UPDATE evidence
   SET current_status = 'In Storage', current_custodian_id = 4, current_location_id = 4
 WHERE evidence_id = 55;

SELECT evidence_code, current_status, current_custodian_id
  FROM evidence WHERE evidence_id = 55;                 -- In Storage, 4 (inside the transaction)

ROLLBACK TO SAVEPOINT after_custody_insert;             -- undoes only the UPDATE

SELECT evidence_code, current_status, current_custodian_id
  FROM evidence WHERE evidence_id = 55;                 -- back to Checked Out, 5

ROLLBACK;                                               -- undoes the INSERT too

SELECT COUNT(*) AS custody_rows_for_00055
  FROM chain_of_custody WHERE evidence_id = 55;         -- still 3

-- =====================================================================
-- Q32. Index usage (EXPLAIN)
-- With only a few rows MySQL may still choose a full scan ("ALL"),
-- because reading 12 rows directly is cheaper than using an index.
-- The `possible_keys` column shows which indexes are candidates.
-- =====================================================================
EXPLAIN SELECT custody_id, action, occurred_at
          FROM chain_of_custody
         WHERE evidence_id = 51
         ORDER BY occurred_at, custody_id;               -- key: idx_coc_evidence_time

EXPLAIN SELECT evidence_id
          FROM evidence_hashes
         WHERE hash_value = '3b7f1c9e04a2d58e6f91c2a7b34d0e85f1c6a9d2e7b40f38c5a1d9e62b7f0c4a';  -- key: idx_hashes_value

EXPLAIN SELECT case_reference
          FROM cases
         WHERE status = 'In Progress' AND priority = 'Critical';   -- possible key: idx_cases_status_priority

SHOW INDEX FROM chain_of_custody;
