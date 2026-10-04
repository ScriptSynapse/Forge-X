"""Dashboard figures. Every number comes from a MySQL aggregate query at
request time; nothing is hard-coded or cached.

Metric definitions (also shown in the dashboard's "How these figures are
calculated" panel and documented in the README):

  Total cases          COUNT(*) of cases in scope
  Open cases           status <> 'Closed'  (Open + In Progress + On Hold)
  Closed cases         status = 'Closed'; "recently" = closed_at in the last 30 days
  Total evidence       COUNT(*) of evidence items belonging to cases in scope
  Evidence in storage  current_status = 'In Storage'
  Under examination    current_status = 'Under Examination'
  Pending transfers    current_status IN ('Checked Out', 'In Transit'): items
                       out of storage that still have to be returned or received
  Integrity            v_evidence_integrity: result of the latest check of each
                       item's current reference hash (Verified / Failed /
                       Pending = hash recorded but never checked /
                       Not Verified = no hash recorded)

Scope: Administrators, Read-Only Auditors and Evidence Custodians see the whole
lab. A user whose only role is Investigator sees the cases assigned to them
(assumption A1) and only their own recent activity.
"""
from datetime import date

from ..access import Scope  # noqa: F401  (re-exported for the dashboard routes and tests)
from ..db import query_all, query_one

CASE_STATUSES = ("Open", "In Progress", "On Hold", "Closed")
PRIORITIES = ("Low", "Medium", "High", "Critical")
INTEGRITY_STATUSES = ("Verified", "Failed", "Pending", "Not Verified")
TREND_MONTHS = 12

def _int(value):
    return int(value or 0)


def fill(rows, keys, key_col="label", value_col="n"):
    """Turn GROUP BY rows into values for every expected key (missing -> 0)."""
    found = {row[key_col]: _int(row[value_col]) for row in rows}
    return [found.get(k, 0) for k in keys]


def summary(scope):
    cases = query_one(
        f"""
        SELECT COUNT(*)                                                   AS total,
               SUM(c.status <> 'Closed')                                  AS open_cases,
               SUM(c.status = 'Open')                                     AS s_open,
               SUM(c.status = 'In Progress')                              AS s_progress,
               SUM(c.status = 'On Hold')                                  AS s_hold,
               SUM(c.status = 'Closed')                                   AS closed,
               SUM(c.status = 'Closed' AND c.closed_at >= NOW() - INTERVAL 30 DAY) AS closed_recent
          FROM cases c
         WHERE 1 = 1 {scope.case_filter}
        """,
        scope.params,
    )
    evidence = query_one(
        f"""
        SELECT COUNT(*)                                                  AS total,
               SUM(e.current_status = 'In Storage')                      AS in_storage,
               SUM(e.current_status = 'Under Examination')               AS under_exam,
               SUM(e.current_status IN ('Checked Out', 'In Transit'))    AS pending_transfers,
               SUM(e.current_status = 'Checked Out')                     AS checked_out,
               SUM(e.current_status = 'In Transit')                      AS in_transit,
               COUNT(DISTINCT e.case_id)                                 AS cases_with_evidence
          FROM evidence e
          JOIN cases c ON c.case_id = e.case_id
         WHERE 1 = 1 {scope.case_filter}
        """,
        scope.params,
    )
    integrity_rows = query_all(
        f"""
        SELECT vi.integrity_status AS label, COUNT(*) AS n
          FROM v_evidence_integrity vi
          JOIN evidence e ON e.evidence_id = vi.evidence_id
          JOIN cases c    ON c.case_id = e.case_id
         WHERE 1 = 1 {scope.case_filter}
         GROUP BY vi.integrity_status
        """,
        scope.params,
    )
    integrity = dict(zip(INTEGRITY_STATUSES, fill(integrity_rows, INTEGRITY_STATUSES)))
    evidence_total = _int(evidence["total"])
    return {
        "cases": {k: _int(v) for k, v in cases.items()},
        "evidence": {k: _int(v) for k, v in evidence.items()},
        "integrity": integrity,
        "integrity_pct": {k: (round(v * 100 / evidence_total, 1) if evidence_total else 0)
                          for k, v in integrity.items()},
    }


def attention(scope):
    """Short list of things that need someone's attention."""
    row = query_one(
        f"""
        SELECT
          (SELECT COUNT(*) FROM examinations x JOIN cases c ON c.case_id = x.case_id
            WHERE x.status IN ('Pending', 'In Progress') AND x.due_date < CURDATE() {scope.case_filter}) AS overdue_exams,
          (SELECT COUNT(*) FROM v_evidence_integrity vi
             JOIN evidence e ON e.evidence_id = vi.evidence_id JOIN cases c ON c.case_id = e.case_id
            WHERE vi.integrity_status = 'Failed' {scope.case_filter}) AS failed_integrity,
          (SELECT COUNT(*) FROM forensic_reports r JOIN cases c ON c.case_id = r.case_id
            WHERE r.status = 'Under Review' {scope.case_filter}) AS reports_in_review,
          (SELECT COUNT(*) FROM account_requests WHERE request_status = 'Pending') AS pending_requests
        """,
        scope.params * 3,
    )
    return {k: _int(v) for k, v in row.items()}


# ---------------------------------------------------------------------------
# Chart data (served as JSON to Chart.js)
# ---------------------------------------------------------------------------
def chart_cases_by_status(scope):
    rows = query_all(f"SELECT c.status AS label, COUNT(*) AS n FROM cases c WHERE 1 = 1 {scope.case_filter} "
                     "GROUP BY c.status", scope.params)
    values = fill(rows, CASE_STATUSES)
    return {"labels": list(CASE_STATUSES), "values": values, "total": sum(values)}


def chart_cases_by_priority(scope):
    rows = query_all(f"SELECT c.priority AS label, COUNT(*) AS n FROM cases c WHERE 1 = 1 {scope.case_filter} "
                     "GROUP BY c.priority", scope.params)
    values = fill(rows, PRIORITIES)
    return {"labels": list(PRIORITIES), "values": values, "total": sum(values)}


def chart_evidence_by_type(scope):
    rows = query_all(
        f"""
        SELECT et.type_name AS label, COUNT(e.evidence_id) AS n
          FROM evidence_types et
          LEFT JOIN (evidence e JOIN cases c ON c.case_id = e.case_id {scope.case_filter})
                 ON e.evidence_type_id = et.evidence_type_id
         WHERE et.is_active = TRUE
         GROUP BY et.evidence_type_id, et.type_name
         ORDER BY n DESC, et.type_name
        """,
        scope.params,
    )
    values = [_int(r["n"]) for r in rows]
    return {"labels": [r["label"] for r in rows], "values": values, "total": sum(values)}


def chart_case_trend(scope, months=TREND_MONTHS):
    """Cases registered per month for the last `months` months, including
    months with none (a recursive CTE generates every month)."""
    rows = query_all(
        f"""
        WITH RECURSIVE months AS (
          SELECT DATE_SUB(DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY),
                          INTERVAL {int(months) - 1} MONTH) AS month_start
          UNION ALL
          SELECT month_start + INTERVAL 1 MONTH FROM months
           WHERE month_start < DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)
        )
        SELECT m.month_start, COUNT(c.case_id) AS n
          FROM months m
          LEFT JOIN cases c
                 ON c.created_at >= m.month_start
                AND c.created_at <  m.month_start + INTERVAL 1 MONTH {scope.case_filter}
         GROUP BY m.month_start
         ORDER BY m.month_start
        """,
        scope.params,
    )
    labels = [month_label(r["month_start"]) for r in rows]
    values = [_int(r["n"]) for r in rows]
    return {"labels": labels, "values": values, "total": sum(values)}


def month_label(value):
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return value.strftime("%b %Y")


CHARTS = {
    "cases-by-status": chart_cases_by_status,
    "cases-by-priority": chart_cases_by_priority,
    "evidence-by-type": chart_evidence_by_type,
    "case-trend": chart_case_trend,
}


def recent_activity(scope, limit=8):
    if scope.sees_all_activity:
        return query_all("SELECT occurred_at, user_name, action, entity_type, entity_ref, outcome "
                         "FROM v_activity_feed ORDER BY occurred_at DESC LIMIT %s", (limit,))
    return query_all("SELECT occurred_at, user_name, action, entity_type, entity_ref, outcome "
                     "FROM v_activity_feed WHERE user_id = %s ORDER BY occurred_at DESC LIMIT %s",
                     (scope.user_id, limit))


def server_time():
    return query_one("SELECT NOW() AS now")["now"]
