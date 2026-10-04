"""Audit log queries (read-only). The timeline is the view v_activity_feed:
audit_logs UNION ALL login_attempts, so each event is stored only once.
Neither table can be edited or deleted (triggers + app account privileges)."""
import csv
import io
from dataclasses import dataclass
from datetime import date

from flask import current_app

from ..db import query_all, query_one, query_value
from ..pagination import Page

OUTCOMES = ("Success", "Failure", "Denied")
ENTITY_TYPES = ("User", "Role", "Account request", "Case", "Evidence", "Evidence hash", "Custody entry",
                "Examination", "Report", "Storage location")
EXPORT_LIMIT = 50_000
CSV_COLUMNS = ("occurred_at", "user_name", "action", "entity_type", "entity_ref", "outcome", "details", "ip_address", "source")


def _date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _int(value):
    return int(value) if value and str(value).isdigit() else None


@dataclass
class AuditFilters:
    date_from: date = None
    date_to: date = None
    user_id: int = None
    action: str = ""
    entity_type: str = ""
    outcome: str = ""
    ref: str = ""

    @classmethod
    def from_args(cls, args):
        return cls(date_from=_date(args.get("from")), date_to=_date(args.get("to")), user_id=_int(args.get("user")),
                   action=(args.get("action") or "").strip()[:50],
                   entity_type=args.get("entity") if args.get("entity") in ENTITY_TYPES else "",
                   outcome=args.get("outcome") if args.get("outcome") in OUTCOMES else "",
                   ref=(args.get("ref") or "").strip()[:40])

    def as_args(self):
        args = {"from": self.date_from.isoformat() if self.date_from else "",
                "to": self.date_to.isoformat() if self.date_to else "", "user": self.user_id or "",
                "action": self.action, "entity": self.entity_type, "outcome": self.outcome, "ref": self.ref}
        return {k: v for k, v in args.items() if v}

    @property
    def active(self):
        return bool(self.as_args())

    def where(self):
        """(SQL condition, params) over v_activity_feed aliased f. Values are parameters only."""
        clauses, params = ["1 = 1"], []
        if self.date_from:
            clauses.append("f.occurred_at >= %s"); params.append(self.date_from)
        if self.date_to:
            clauses.append("f.occurred_at < %s + INTERVAL 1 DAY"); params.append(self.date_to)
        if self.user_id:
            clauses.append("f.user_id = %s"); params.append(self.user_id)
        if self.action:
            clauses.append("f.action = %s"); params.append(self.action)
        if self.entity_type:
            clauses.append("f.entity_type = %s"); params.append(self.entity_type)
        if self.outcome:
            clauses.append("f.outcome = %s"); params.append(self.outcome)
        if self.ref:
            clauses.append("f.entity_ref = %s"); params.append(self.ref)
        return " AND ".join(clauses), tuple(params)


def list_events(filters, page, per_page):
    condition, params = filters.where()
    total = query_value(f"SELECT COUNT(*) FROM v_activity_feed f WHERE {condition}", params)
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    rows = query_all(f"SELECT f.* FROM v_activity_feed f WHERE {condition} "
                     "ORDER BY f.occurred_at DESC LIMIT %s OFFSET %s", params + (per_page, (page - 1) * per_page))
    return Page(items=rows, page=page, per_page=per_page, total=total)


def summary(filters):
    condition, params = filters.where()
    row = query_one(
        f"""SELECT COUNT(*) AS total, COALESCE(SUM(f.outcome = 'Failure'), 0) AS failures,
                   COALESCE(SUM(f.outcome = 'Denied'), 0) AS denied, COUNT(DISTINCT f.user_id) AS users,
                   MIN(f.occurred_at) AS first_event, MAX(f.occurred_at) AS last_event
              FROM v_activity_feed f WHERE {condition}""", params)
    return row


def filter_options():
    return {
        "actions": [r["action"] for r in query_all("SELECT DISTINCT action FROM v_activity_feed ORDER BY action")],
        "users": query_all("SELECT user_id, full_name, username FROM users ORDER BY full_name"),
    }


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------
def _safe_cell(value):
    """Stop spreadsheet formula injection: a cell starting with = + - @ (or a
    tab / carriage return) is prefixed with an apostrophe so Excel shows it
    as text instead of running it."""
    text = "" if value is None else str(value)
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


def export_csv(filters):
    """Return (csv_text, row_count, truncated). UTF-8 with BOM so Excel reads it correctly."""
    condition, params = filters.where()
    rows = query_all(f"SELECT f.* FROM v_activity_feed f WHERE {condition} ORDER BY f.occurred_at DESC LIMIT %s",
                     params + (EXPORT_LIMIT + 1,))
    truncated = len(rows) > EXPORT_LIMIT
    rows = rows[:EXPORT_LIMIT]
    out = io.StringIO()
    out.write("\ufeff")
    writer = csv.writer(out)
    writer.writerow(CSV_COLUMNS)
    for row in rows:
        writer.writerow([_safe_cell(row[c].strftime("%Y-%m-%d %H:%M:%S") if c == "occurred_at" and row[c] else row[c])
                         for c in CSV_COLUMNS])
    return out.getvalue(), len(rows), truncated


# ---------------------------------------------------------------------------
# Security view (login abuse)
# ---------------------------------------------------------------------------
def locked_accounts():
    """Identifiers currently paused by the login rate limit (same rule as
    app.auth.services: wrong passwords in the last 15 minutes, counting only
    those after the account's last successful login)."""
    return query_all(
        """
        SELECT la.username_or_email, COUNT(*) AS failures, COUNT(DISTINCT la.ip_address) AS ips,
               MAX(la.attempted_at) AS last_failure
          FROM login_attempts la
         WHERE la.success = FALSE AND la.failure_reason = 'invalid_credentials'
           AND la.attempted_at >= NOW() - INTERVAL 15 MINUTE
           AND la.attempted_at > COALESCE((SELECT MAX(s.attempted_at) FROM login_attempts s
                                            WHERE s.success = TRUE AND s.username_or_email = la.username_or_email),
                                           '1970-01-01')
         GROUP BY la.username_or_email
        HAVING COUNT(*) >= %s
         ORDER BY last_failure DESC
        """,
        (current_app.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"],),
    )


def repeated_failures(days=7, minimum=3):
    by_identifier = query_all(
        """
        SELECT la.username_or_email, u.full_name, COUNT(*) AS failures, COUNT(DISTINCT la.ip_address) AS ips,
               MIN(la.attempted_at) AS first_failure, MAX(la.attempted_at) AS last_failure,
               SUM(la.failure_reason = 'account_inactive') AS inactive_attempts
          FROM login_attempts la
          LEFT JOIN users u ON u.user_id = la.user_id
         WHERE la.success = FALSE AND la.attempted_at >= NOW() - INTERVAL %s DAY
         GROUP BY la.username_or_email, u.full_name
        HAVING COUNT(*) >= %s
         ORDER BY failures DESC, last_failure DESC
        """,
        (days, minimum),
    )
    by_ip = query_all(
        """
        SELECT ip_address, COUNT(*) AS failures, COUNT(DISTINCT username_or_email) AS identifiers,
               MAX(attempted_at) AS last_failure
          FROM login_attempts
         WHERE success = FALSE AND attempted_at >= NOW() - INTERVAL %s DAY
         GROUP BY ip_address
        HAVING COUNT(*) >= %s
         ORDER BY failures DESC
        """,
        (days, minimum),
    )
    return by_identifier, by_ip


def denied_actions(days=7, limit=20):
    return query_all("SELECT f.* FROM v_activity_feed f WHERE f.outcome = 'Denied' "
                     "AND f.occurred_at >= NOW() - INTERVAL %s DAY ORDER BY f.occurred_at DESC LIMIT %s", (days, limit))
