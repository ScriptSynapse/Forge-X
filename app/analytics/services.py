"""Analytics: seven charts, each computed by one SQL query at request time.

Every chart is restricted to the cases the user may see ({scope} below is
replaced by the same parameterised case filter the dashboard uses). The SQL
text is also shown on the page ("SQL behind this chart"), so each chart can
be explained in the DBMS viva: recursive CTEs, window functions,
conditional aggregation, LEFT JOINs and GROUP BY ... HAVING.
"""
from datetime import date

from ..db import query_all

PERIODS = (6, 12, 24)
STATUS_ORDER = ("Pending", "In Progress", "Under Review", "Completed", "Cancelled")

# Recursive CTE that produces one row per month for the last :months months.
MONTHS_CTE = """
WITH RECURSIVE months AS (
  SELECT DATE_SUB(DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY),
                  INTERVAL {months_back} MONTH) AS month_start
  UNION ALL
  SELECT month_start + INTERVAL 1 MONTH FROM months
   WHERE month_start < DATE_SUB(CURDATE(), INTERVAL DAYOFMONTH(CURDATE()) - 1 DAY)
)"""

CHARTS = {
    "monthly-activity": {
        "title": "Lab activity per month",
        "kind": "line",
        "description": "Cases registered, evidence registered and custody entries recorded each month, "
                       "including months with no activity.",
        "concepts": "Recursive CTE, LEFT JOIN to grouped subqueries, COALESCE",
        "sql": MONTHS_CTE + """
SELECT m.month_start,
       COALESCE(cs.n, 0) AS cases_opened,
       COALESCE(ev.n, 0) AS evidence_registered,
       COALESCE(cu.n, 0) AS custody_entries
  FROM months m
  LEFT JOIN (SELECT DATE_SUB(DATE(c.created_at), INTERVAL DAYOFMONTH(c.created_at) - 1 DAY) AS month_start, COUNT(*) AS n
               FROM cases c WHERE 1 = 1 {scope} GROUP BY month_start) cs ON cs.month_start = m.month_start
  LEFT JOIN (SELECT DATE_SUB(DATE(e.registered_at), INTERVAL DAYOFMONTH(e.registered_at) - 1 DAY) AS month_start, COUNT(*) AS n
               FROM evidence e JOIN cases c ON c.case_id = e.case_id WHERE 1 = 1 {scope} GROUP BY month_start) ev
         ON ev.month_start = m.month_start
  LEFT JOIN (SELECT DATE_SUB(DATE(coc.occurred_at), INTERVAL DAYOFMONTH(coc.occurred_at) - 1 DAY) AS month_start, COUNT(*) AS n
               FROM chain_of_custody coc JOIN evidence e ON e.evidence_id = coc.evidence_id
               JOIN cases c ON c.case_id = e.case_id WHERE 1 = 1 {scope} GROUP BY month_start) cu
         ON cu.month_start = m.month_start
 ORDER BY m.month_start""",
        "scope_uses": 3,
    },
    "verification-outcomes": {
        "title": "Hash verification outcomes per month",
        "kind": "stacked",
        "description": "Every verification attempt, split into Verified and Failed by the database trigger.",
        "concepts": "Recursive CTE, conditional aggregation SUM(condition)",
        "sql": MONTHS_CTE + """
SELECT m.month_start,
       COALESCE(SUM(hv.result = 'Verified'), 0) AS verified,
       COALESCE(SUM(hv.result = 'Failed'), 0)   AS failed
  FROM months m
  LEFT JOIN (hash_verifications hv
             JOIN evidence_hashes h ON h.hash_id = hv.hash_id
             JOIN evidence e        ON e.evidence_id = h.evidence_id
             JOIN cases c           ON c.case_id = e.case_id {scope})
         ON hv.verified_at >= m.month_start AND hv.verified_at < m.month_start + INTERVAL 1 MONTH
 GROUP BY m.month_start
 ORDER BY m.month_start""",
        "scope_uses": 1,
    },
    "resolution-by-type": {
        "title": "Average days to close, by case type",
        "kind": "hbar",
        "description": "Closed cases only: time from registration to closure, averaged per case type.",
        "concepts": "Aggregates (AVG, COUNT), TIMESTAMPDIFF, GROUP BY",
        "sql": """
SELECT ct.type_name AS label,
       COUNT(*) AS closed_cases,
       ROUND(AVG(TIMESTAMPDIFF(HOUR, c.created_at, c.closed_at)) / 24, 1) AS avg_days
  FROM cases c
  JOIN case_types ct ON ct.case_type_id = c.case_type_id
 WHERE c.status = 'Closed' {scope}
 GROUP BY ct.case_type_id, ct.type_name
 ORDER BY avg_days DESC""",
        "scope_uses": 1,
    },
    "examinations-by-type": {
        "title": "Examinations by type and status",
        "kind": "stacked-h",
        "description": "How many examinations of each type are pending, in progress, completed or cancelled.",
        "concepts": "Conditional aggregation (pivot), LEFT JOIN keeps types with no examinations",
        "sql": """
SELECT xt.type_name AS label,
       COALESCE(SUM(x.status = 'Pending'), 0)     AS pending,
       COALESCE(SUM(x.status = 'In Progress'), 0) AS in_progress,
       COALESCE(SUM(x.status = 'Under Review'), 0) AS under_review,
       COALESCE(SUM(x.status = 'Completed'), 0)   AS completed,
       COALESCE(SUM(x.status = 'Cancelled'), 0)   AS cancelled
  FROM examination_types xt
  LEFT JOIN (examinations x JOIN cases c ON c.case_id = x.case_id {scope})
         ON x.examination_type_id = xt.examination_type_id
 WHERE xt.is_active = TRUE
 GROUP BY xt.examination_type_id, xt.type_name
 ORDER BY xt.type_name""",
        "scope_uses": 1,
    },
    "investigator-workload": {
        "title": "Investigator workload",
        "kind": "hbar2",
        "description": "Open cases and unfinished examinations per active investigator, ranked by open cases.",
        "concepts": "Window function RANK() OVER, correlated subqueries, HAVING",
        "sql": """
SELECT u.full_name AS label,
       COUNT(DISTINCT CASE WHEN c.status <> 'Closed' THEN c.case_id END) AS open_cases,
       (SELECT COUNT(*) FROM examinations x JOIN cases c ON c.case_id = x.case_id {scope}
         WHERE x.examiner_id = u.user_id AND x.status IN ('Pending', 'In Progress')) AS open_examinations,
       RANK() OVER (ORDER BY COUNT(DISTINCT CASE WHEN c.status <> 'Closed' THEN c.case_id END) DESC) AS workload_rank
  FROM users u
  JOIN user_roles ur ON ur.user_id = u.user_id
  JOIN roles r       ON r.role_id = ur.role_id AND r.role_name = 'Investigator'
  JOIN case_investigators ci ON ci.user_id = u.user_id
  JOIN cases c       ON c.case_id = ci.case_id {scope}
 WHERE u.account_status = 'Active'
 GROUP BY u.user_id, u.full_name
HAVING COUNT(*) > 0
 ORDER BY workload_rank, u.full_name""",
        "scope_uses": 2,
    },
    "custody-actions": {
        "title": "Custody actions in the period",
        "kind": "bar",
        "description": "How often each custody action was recorded in the selected period, corrections included.",
        "concepts": "GROUP BY with a date-range filter, FIELD() ordering",
        "sql": """
SELECT coc.action AS label, COUNT(*) AS entries
  FROM chain_of_custody coc
  JOIN evidence e ON e.evidence_id = coc.evidence_id
  JOIN cases c    ON c.case_id = e.case_id
 WHERE coc.occurred_at >= DATE_SUB(CURDATE(), INTERVAL {months} MONTH) {scope}
 GROUP BY coc.action
 ORDER BY FIELD(coc.action, 'Collected', 'Received', 'Transferred', 'Checked Out', 'Examined',
                'Returned', 'Stored', 'Released', 'Archived', 'Exported')""",
        "scope_uses": 1,
    },
    "storage-occupancy": {
        "title": "Items held at each storage location",
        "kind": "hbar",
        "description": "Where evidence is right now, for every active location (empty ones included).",
        "concepts": "LEFT JOIN with the filter in the ON clause, so empty locations still appear",
        "sql": """
SELECT sl.location_name AS label, COUNT(e.evidence_id) AS items
  FROM storage_locations sl
  LEFT JOIN (evidence e JOIN cases c ON c.case_id = e.case_id {scope})
         ON e.current_location_id = sl.location_id
 WHERE sl.is_active = TRUE
 GROUP BY sl.location_id, sl.location_name
 ORDER BY items DESC, sl.location_name""",
        "scope_uses": 1,
    },
}


def parse_period(value):
    try:
        months = int(value)
    except (TypeError, ValueError):
        return 12
    return months if months in PERIODS else 12


def sql_for(chart_id, scope, months):
    chart = CHARTS[chart_id]
    sql = chart["sql"].format(scope=scope.case_filter, months=int(months), months_back=int(months) - 1)
    params = scope.params * chart["scope_uses"]
    return sql, params


def display_sql(chart_id):
    """The SQL as shown on the page: the case filter written as a comment."""
    return CHARTS[chart_id]["sql"].format(
        scope="/* + visibility filter for investigators */", months="{months}", months_back="{months} - 1").strip()


def _month(value):
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return value.strftime("%b %Y")


def run(chart_id, scope, months):
    sql, params = sql_for(chart_id, scope, months)
    rows = query_all(sql, params)
    kind = CHARTS[chart_id]["kind"]
    if chart_id == "monthly-activity":
        labels = [_month(r["month_start"]) for r in rows]
        datasets = [{"label": "Cases opened", "values": [int(r["cases_opened"]) for r in rows]},
                    {"label": "Evidence registered", "values": [int(r["evidence_registered"]) for r in rows]},
                    {"label": "Custody entries", "values": [int(r["custody_entries"]) for r in rows]}]
    elif chart_id == "verification-outcomes":
        labels = [_month(r["month_start"]) for r in rows]
        datasets = [{"label": "Verified", "values": [int(r["verified"]) for r in rows]},
                    {"label": "Integrity mismatch", "values": [int(r["failed"]) for r in rows]}]
    elif chart_id == "resolution-by-type":
        labels = [f"{r['label']} ({int(r['closed_cases'])})" for r in rows]
        datasets = [{"label": "Average days to close", "values": [float(r["avg_days"] or 0) for r in rows]}]
    elif chart_id == "examinations-by-type":
        labels = [r["label"] for r in rows]
        datasets = [{"label": s, "values": [int(r[key]) for r in rows]}
                    for s, key in zip(STATUS_ORDER, ("pending", "in_progress", "under_review", "completed", "cancelled"))]
    elif chart_id == "investigator-workload":
        labels = [f"#{int(r['workload_rank'])} {r['label']}" for r in rows]
        datasets = [{"label": "Open cases", "values": [int(r["open_cases"]) for r in rows]},
                    {"label": "Unfinished examinations", "values": [int(r["open_examinations"]) for r in rows]}]
    else:   # custody-actions, storage-occupancy
        value_key = "entries" if chart_id == "custody-actions" else "items"
        labels = [r["label"] for r in rows]
        datasets = [{"label": "Entries" if chart_id == "custody-actions" else "Items", "values": [int(r[value_key]) for r in rows]}]
    total = sum(sum(d["values"]) for d in datasets) if chart_id != "resolution-by-type" else \
        sum(int(r["closed_cases"]) for r in rows)
    return {"chart": chart_id, "kind": kind, "labels": labels, "datasets": datasets, "total": total, "months": months}
