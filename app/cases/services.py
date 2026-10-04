"""Case management business logic. Routes call these functions; all data is
read from and written to MySQL. Every value from the user is passed as a
query parameter."""
from dataclasses import dataclass

from .. import audit
from ..access import Scope, can_manage_case
from ..db import (BusinessRuleError, ConstraintViolation, DatabaseError, call_proc, query_all, query_one,
                  query_value, transaction)
from ..pagination import Page

CASE_STATUSES = ("Open", "In Progress", "On Hold", "Closed")
EDITABLE_STATUSES = ("Open", "In Progress", "On Hold")      # Closed only through the closure workflow
PRIORITIES = ("Low", "Medium", "High", "Critical")

# Sort options -> fixed ORDER BY clauses (never built from user input)
SORTS = {
    "newest":    ("Newest first", "c.created_at DESC, c.case_id DESC"),
    "oldest":    ("Oldest first", "c.created_at ASC, c.case_id ASC"),
    "priority":  ("Highest priority", "FIELD(c.priority, 'Critical', 'High', 'Medium', 'Low'), c.created_at DESC"),
    "reference": ("Reference", "c.case_reference ASC"),
}


class CaseActionError(Exception):
    """A refused case action, with a message that is safe to display."""


# ---------------------------------------------------------------------------
# Filters and search
# ---------------------------------------------------------------------------
@dataclass
class CaseFilters:
    q: str = ""
    status: str = ""
    priority: str = ""
    case_type_id: int = None
    sort: str = "newest"

    @classmethod
    def from_args(cls, args):
        """Read ?q=&status=&priority=&type=&sort= safely: unknown values are ignored."""
        type_raw = args.get("type", "")
        return cls(
            q=(args.get("q") or "").strip()[:100],
            status=args.get("status") if args.get("status") in CASE_STATUSES else "",
            priority=args.get("priority") if args.get("priority") in PRIORITIES else "",
            case_type_id=int(type_raw) if type_raw.isdigit() else None,
            sort=args.get("sort") if args.get("sort") in SORTS else "newest",
        )

    def as_args(self):
        """The active filters as URL arguments (used by the pager)."""
        args = {"q": self.q, "status": self.status, "priority": self.priority,
                "type": self.case_type_id or "", "sort": self.sort if self.sort != "newest" else ""}
        return {k: v for k, v in args.items() if v}

    @property
    def active(self):
        return bool(self.q or self.status or self.priority or self.case_type_id)


def like_pattern(text):
    """Escape LIKE wildcards so a search for '50%' or 'a_b' matches literally.
    Used with ESCAPE '!' in the SQL."""
    return "%" + text.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


def list_cases(scope, filters, page, per_page):
    where, params = ["1 = 1"], []
    if filters.q:
        where.append("(c.case_reference LIKE %s ESCAPE '!' OR c.title LIKE %s ESCAPE '!')")
        params += [like_pattern(filters.q)] * 2
    if filters.status:
        where.append("c.status = %s")
        params.append(filters.status)
    if filters.priority:
        where.append("c.priority = %s")
        params.append(filters.priority)
    if filters.case_type_id:
        where.append("c.case_type_id = %s")
        params.append(filters.case_type_id)
    condition = " AND ".join(where) + scope.case_filter
    all_params = tuple(params) + scope.params

    total = query_value(f"SELECT COUNT(*) FROM cases c WHERE {condition}", all_params)
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    order_by = SORTS[filters.sort][1]
    rows = query_all(
        f"""
        SELECT c.case_id, c.case_reference, c.title, ct.type_name, c.priority, c.status, c.created_at,
               lu.full_name AS lead_name,
               (SELECT COUNT(*) FROM evidence e WHERE e.case_id = c.case_id) AS evidence_count
          FROM cases c
          JOIN case_types ct              ON ct.case_type_id = c.case_type_id
          LEFT JOIN case_investigators ci ON ci.case_id = c.case_id AND ci.is_lead = TRUE
          LEFT JOIN users lu              ON lu.user_id = ci.user_id
         WHERE {condition}
         ORDER BY {order_by}
         LIMIT %s OFFSET %s
        """,
        all_params + (per_page, (page - 1) * per_page),
    )
    return Page(items=rows, page=page, per_page=per_page, total=total)


def status_counts(scope):
    rows = query_all(f"SELECT c.status, COUNT(*) AS n FROM cases c WHERE 1 = 1 {scope.case_filter} "
                     "GROUP BY c.status", scope.params)
    found = {r["status"]: int(r["n"]) for r in rows}
    return {s: found.get(s, 0) for s in CASE_STATUSES}


def case_types(include_inactive=False):
    sql = "SELECT case_type_id, type_name FROM case_types"
    if not include_inactive:
        sql += " WHERE is_active = TRUE"
    return query_all(sql + " ORDER BY type_name")


def active_investigators():
    return query_all(
        """
        SELECT u.user_id, u.full_name FROM users u
          JOIN user_roles ur ON ur.user_id = u.user_id
          JOIN roles r       ON r.role_id = ur.role_id
         WHERE r.role_name = 'Investigator' AND u.account_status = 'Active'
         ORDER BY u.full_name
        """
    )


# ---------------------------------------------------------------------------
# One case and its related records
# ---------------------------------------------------------------------------
_CASE_SELECT = """
    SELECT c.case_id, c.case_reference, c.title, c.description, c.case_type_id, ct.type_name,
           c.priority, c.status, c.created_at, c.updated_at, c.closed_at, c.closure_summary,
           cu.full_name AS created_by_name,
           ci.user_id   AS lead_user_id,
           lu.full_name AS lead_name
      FROM cases c
      JOIN case_types ct              ON ct.case_type_id = c.case_type_id
      JOIN users cu                   ON cu.user_id = c.created_by
      LEFT JOIN case_investigators ci ON ci.case_id = c.case_id AND ci.is_lead = TRUE
      LEFT JOIN users lu              ON lu.user_id = ci.user_id
"""


def get_case(scope, reference):
    """The case, or None if it doesn't exist OR the user may not see it."""
    return query_one(_CASE_SELECT + f" WHERE c.case_reference = %s {scope.case_filter}",
                     (reference,) + scope.params)


def case_investigators(case_id):
    return query_all(
        """
        SELECT ci.user_id, u.full_name, u.username, u.account_status, ci.is_lead, ci.assigned_at,
               a.full_name AS assigned_by_name
          FROM case_investigators ci
          JOIN users u      ON u.user_id = ci.user_id
          LEFT JOIN users a ON a.user_id = ci.assigned_by
         WHERE ci.case_id = %s
         ORDER BY ci.is_lead DESC, u.full_name
        """,
        (case_id,),
    )


def case_evidence(case_id):
    return query_all("SELECT * FROM v_evidence_overview WHERE case_id = %s ORDER BY evidence_code", (case_id,))


def case_examinations(case_id):
    return query_all("SELECT * FROM v_examination_summary WHERE case_id = %s ORDER BY examination_code DESC",
                     (case_id,))


def case_reports(case_id):
    return query_all(
        """
        SELECT r.report_id, r.report_code, r.title, r.status, r.updated_at, u.full_name AS author_name,
               cv.version_no
          FROM forensic_reports r
          JOIN users u ON u.user_id = r.author_id
          LEFT JOIN v_current_report_versions cv ON cv.report_id = r.report_id
         WHERE r.case_id = %s
         ORDER BY r.updated_at DESC
        """,
        (case_id,),
    )


def case_activity(case, limit=50):
    """Audit records about the case itself and its evidence, examinations and reports."""
    return query_all(
        """
        SELECT a.created_at, a.action, a.entity_type, a.entity_ref, a.outcome, a.details, u.full_name AS user_name
          FROM audit_logs a
          LEFT JOIN users u ON u.user_id = a.user_id
         WHERE a.entity_ref = %s
            OR a.entity_ref IN (SELECT evidence_code    FROM evidence         WHERE case_id = %s)
            OR a.entity_ref IN (SELECT examination_code FROM examinations     WHERE case_id = %s)
            OR a.entity_ref IN (SELECT report_code      FROM forensic_reports WHERE case_id = %s)
         ORDER BY a.created_at DESC
         LIMIT %s
        """,
        (case["case_reference"], case["case_id"], case["case_id"], case["case_id"], limit),
    )


def tab_counts(case_id):
    row = query_one(
        """
        SELECT (SELECT COUNT(*) FROM evidence           WHERE case_id = %s) AS evidence,
               (SELECT COUNT(*) FROM case_investigators WHERE case_id = %s) AS investigators,
               (SELECT COUNT(*) FROM examinations       WHERE case_id = %s) AS examinations,
               (SELECT COUNT(*) FROM forensic_reports   WHERE case_id = %s) AS reports
        """,
        (case_id,) * 4,
    )
    return {k: int(v) for k, v in row.items()}


def closure_blockers(case_id):
    """What would stop sp_close_case, so the close page can explain it first."""
    return {
        "examinations": query_all(
            "SELECT examination_code, status FROM examinations "
            "WHERE case_id = %s AND status IN ('Pending', 'In Progress') ORDER BY examination_code",
            (case_id,)),
        "evidence": query_all(
            "SELECT evidence_code, current_status FROM evidence "
            "WHERE case_id = %s AND current_status IN ('In Transit', 'Checked Out', 'Under Examination') "
            "ORDER BY evidence_code",
            (case_id,)),
    }


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------
def create_case(title, description, case_type_id, priority, lead_user_id, created_by):
    """sp_register_case: reference number, case row, lead assignment and
    audit record in one transaction. Returns the new case reference."""
    try:
        result = call_proc("sp_register_case",
                           (title, description, case_type_id, priority, lead_user_id, created_by, None, None))
    except BusinessRuleError as err:
        raise CaseActionError(err.user_message) from err
    return result[7]          # OUT p_case_reference


def _lock_case(cur, case_id):
    cur.execute(
        """
        SELECT c.case_id, c.case_reference, c.title, c.description, c.case_type_id, c.priority, c.status,
               c.updated_at, ci.user_id AS lead_user_id
          FROM cases c
          LEFT JOIN case_investigators ci ON ci.case_id = c.case_id AND ci.is_lead = TRUE
         WHERE c.case_id = %s
           FOR UPDATE
        """,
        (case_id,),
    )
    case = cur.fetchone()
    if case is None:
        raise CaseActionError("Case not found.")
    return case


def version_of(case):
    """A token for 'the case as you saw it' (its last-updated time)."""
    return case["updated_at"].isoformat() if case.get("updated_at") else ""


def update_case(case_id, user, title, description, case_type_id, priority, expected_version):
    """Edit the case details. Refuses if someone else changed the case after
    the form was opened (optimistic concurrency check)."""
    with transaction() as cur:
        case = _lock_case(cur, case_id)
        if not can_manage_case(user, case):
            raise CaseActionError("Only an administrator or the lead investigator can edit an open case.")
        if version_of(case) != expected_version:
            raise CaseActionError("This case was changed by someone else while you were editing. "
                                  "Your changes were not saved; reload and try again.")
        cur.execute("SELECT type_name FROM case_types WHERE case_type_id = %s", (case_type_id,))
        new_type = cur.fetchone()
        if new_type is None:
            raise CaseActionError("Choose a valid case type.")

        changes = []
        if title != case["title"]:
            changes.append("title")
        if description != case["description"]:
            changes.append("description")
        if case_type_id != case["case_type_id"]:
            changes.append(f"type (now {new_type['type_name']})")
        if priority != case["priority"]:
            changes.append(f"priority ({case['priority']} to {priority})")
        if not changes:
            return False

        cur.execute(
            "UPDATE cases SET title = %s, description = %s, case_type_id = %s, priority = %s WHERE case_id = %s",
            (title, description, case_type_id, priority, case_id),
        )
        audit.record("case.update", "Case", case["case_reference"], cursor=cur,
                     details="Changed: " + ", ".join(changes))
    return True


def change_status(case_id, user, new_status):
    if new_status not in EDITABLE_STATUSES:
        raise CaseActionError("Choose Open, In Progress or On Hold. Use Close case to close it.")
    with transaction() as cur:
        case = _lock_case(cur, case_id)
        if not can_manage_case(user, case):
            raise CaseActionError("Only an administrator or the lead investigator can change the status.")
        if case["status"] == new_status:
            raise CaseActionError(f"The case is already {new_status}.")
        cur.execute("UPDATE cases SET status = %s WHERE case_id = %s", (new_status, case_id))
        audit.record("case.status", "Case", case["case_reference"], cursor=cur,
                     details=f"{case['status']} to {new_status}")


def _run_procedure(name, args):
    try:
        call_proc(name, args)
    except BusinessRuleError as err:
        raise CaseActionError(err.user_message) from err


def assign_investigator(case_id, user_id, make_lead, by_user_id):
    _run_procedure("sp_assign_investigator", (case_id, user_id, bool(make_lead), by_user_id))


def make_lead(case_id, user_id, by_user_id):
    _run_procedure("sp_assign_investigator", (case_id, user_id, True, by_user_id))


def remove_investigator(case_id, user_id, by_user_id):
    _run_procedure("sp_remove_investigator", (case_id, user_id, by_user_id))


def close_case(case_id, summary, by_user_id):
    _run_procedure("sp_close_case", (case_id, summary, by_user_id))




_BLOCKERS_SQL = (
    "SELECT c.status, "
    "(SELECT COUNT(*) FROM evidence e WHERE e.case_id = c.case_id) AS evidence, "
    "(SELECT COUNT(*) FROM examinations x WHERE x.case_id = c.case_id) AS examinations, "
    "(SELECT COUNT(*) FROM forensic_reports r WHERE r.case_id = c.case_id) AS reports "
    "FROM cases c WHERE c.case_id = %s")


def _blockers(row):
    if row is None:
        return ["The case doesn't exist."]
    names = {"evidence": ("evidence item", "evidence items"), "examinations": ("examination", "examinations"),
             "reports": ("report", "reports")}
    parts = [f"{int(row[k])} {names[k][int(row[k]) != 1]}" for k in names if int(row[k])]
    reasons = [f"It has {', '.join(parts)}."] if parts else []
    if row["status"] == "Closed":
        reasons.append("It is closed, and closure is part of the record.")
    return reasons


def deletion_blockers(case_id):
    """Why a case can't be deleted (empty list = it can be).

    Only a case with NO forensic history may be deleted: one registered by
    mistake or twice. Evidence, examinations and reports are history that
    must survive; the database's RESTRICT foreign keys enforce the same rule.
    """
    return _blockers(query_one(_BLOCKERS_SQL, (case_id,)))


def delete_case(case_id, user, reason, typed_reference):
    """Delete an EMPTY case: its investigator assignments, then the case, plus
    an audit record that keeps its reference, title and the reason. One
    transaction; refused if anything was added to the case meanwhile."""
    if "Administrator" not in user["roles"]:
        raise CaseActionError("Only administrators can delete cases.")
    if not reason or len(reason.strip()) < 10:
        raise CaseActionError("Give a reason of at least 10 characters.")
    try:
        with transaction() as cur:
            case = _lock_case(cur, case_id)
            if typed_reference.strip().upper() != case["case_reference"]:
                raise CaseActionError(f"Type {case['case_reference']} exactly to confirm.")
            cur.execute(_BLOCKERS_SQL, (case_id,))    # same transaction, after the lock
            blockers = _blockers(cur.fetchone())
            if blockers:
                raise CaseActionError("This case can't be deleted. " + " ".join(blockers) + " Close it instead.")
            cur.execute("DELETE FROM case_investigators WHERE case_id = %s", (case_id,))
            cur.execute("DELETE FROM cases WHERE case_id = %s", (case_id,))
            audit.record("case.delete", "Case", case["case_reference"], cursor=cur,
                         details=f"Deleted empty case '{case['title']}'. Reason: {reason.strip()}"[:500])
    except ConstraintViolation as err:          # a RESTRICT foreign key: something was linked after all
        raise CaseActionError("The database refused: this case is referenced by other records. Close it instead.") from err
    except DatabaseError as err:
        if err.errno == 1142:                    # DELETE privilege missing on an older installation
            raise CaseActionError("Deleting cases needs a one-time database update: "
                                  "run database/migrations/003_allow_case_delete.sql as root.") from err
        raise
    return case["case_reference"]
