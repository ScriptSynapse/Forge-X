"""Case management business logic. Routes call these functions; all data is
read from and written to MySQL. Every value from the user is passed as a
query parameter."""
from datetime import date
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
# The latest thing that happened on a case: its own edits, custody of its
# evidence, notes, examinations or reports. Each part falls back to the case's
# own updated_at, because GREATEST() returns NULL if any argument is NULL.
LAST_ACTIVITY_SQL = """GREATEST(
    c.updated_at,
    COALESCE((SELECT MAX(coc.occurred_at) FROM chain_of_custody coc JOIN evidence e ON e.evidence_id = coc.evidence_id
               WHERE e.case_id = c.case_id), c.updated_at),
    COALESCE((SELECT MAX(n.created_at) FROM case_notes n WHERE n.case_id = c.case_id), c.updated_at),
    COALESCE((SELECT MAX(x.updated_at) FROM examinations x WHERE x.case_id = c.case_id), c.updated_at),
    COALESCE((SELECT MAX(r.updated_at) FROM forensic_reports r WHERE r.case_id = c.case_id), c.updated_at))"""

# Column sorting: ?sort=<column> ascending, ?sort=-<column> descending. Only
# these fixed SQL expressions can ever reach ORDER BY (the key is validated).
SORT_COLUMNS = {
    "reference":  ("Reference", "c.case_reference"),
    "title":      ("Title", "c.title"),
    "type":       ("Type", "ct.type_name"),
    "priority":   ("Priority", "FIELD(c.priority, 'Critical', 'High', 'Medium', 'Low')"),
    "status":     ("Status", "FIELD(c.status, 'Open', 'In Progress', 'On Hold', 'Closed')"),
    "lead":       ("Lead investigator", "lu.full_name"),
    "evidence":   ("Evidence", "evidence_count"),
    "registered": ("Registered", "c.created_at"),
    "due":        ("Due date", "c.due_date IS NULL, c.due_date"),
    "activity":   ("Last activity", "last_activity"),
}
SORTS = {}
for _key, (_label, _expr) in SORT_COLUMNS.items():
    SORTS[_key] = (f"{_label} (ascending)", f"{_expr} ASC, c.case_id DESC")
    SORTS["-" + _key] = (f"{_label} (descending)", f"{_expr} DESC, c.case_id DESC")
# Cases without a due date always come last, whichever way due dates are sorted.
SORTS["due"] = ("Due date (soonest first)", "c.due_date IS NULL, c.due_date ASC, c.case_id DESC")
SORTS["-due"] = ("Due date (latest first)", "c.due_date IS NULL, c.due_date DESC, c.case_id DESC")
# The older names stay valid, so existing links keep working.
SORTS["newest"] = ("Newest first", "c.created_at DESC, c.case_id DESC")
SORTS["oldest"] = ("Oldest first", "c.created_at ASC, c.case_id ASC")
SORTS["priority"] = ("Highest priority", "FIELD(c.priority, 'Critical', 'High', 'Medium', 'Low'), c.created_at DESC")
SORTS["reference"] = ("Reference", "c.case_reference ASC")
SORT_MENU = ("newest", "oldest", "priority", "reference")      # the choices shown in the dropdown

# Group filters used by the dashboard's links.
STATUS_GROUPS = {"active": ("Active (not closed)", "c.status <> 'Closed'")}
PRIORITY_GROUPS = {"urgent": ("High or critical", "c.priority IN ('Critical', 'High')")}


def _parse_date(value):
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


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
    investigator_id: int = None
    date_from: date = None
    date_to: date = None
    overdue: bool = False
    sort: str = "newest"

    @classmethod
    def from_args(cls, args):
        """Read ?q=&status=&priority=&type=&sort= safely: unknown values are ignored."""
        type_raw = args.get("type", "")
        return cls(
            q=(args.get("q") or "").strip()[:100],
            status=args.get("status") if args.get("status") in CASE_STATUSES or args.get("status") in STATUS_GROUPS
            else "",
            priority=args.get("priority") if args.get("priority") in PRIORITIES or args.get("priority") in PRIORITY_GROUPS
            else "",
            case_type_id=int(type_raw) if type_raw.isdigit() else None,
            investigator_id=int(args.get("investigator")) if (args.get("investigator") or "").isdigit() else None,
            date_from=_parse_date(args.get("from")), date_to=_parse_date(args.get("to")),
            overdue=args.get("overdue") == "1",
            sort=args.get("sort") if args.get("sort") in SORTS else "newest",
        )

    def as_args(self):
        """The active filters as URL arguments (used by the pager)."""
        args = {"q": self.q, "status": self.status, "priority": self.priority,
                "type": self.case_type_id or "", "investigator": self.investigator_id or "",
                "from": self.date_from.isoformat() if self.date_from else "",
                "to": self.date_to.isoformat() if self.date_to else "",
                "overdue": "1" if self.overdue else "",
                "sort": self.sort if self.sort != "newest" else ""}
        return {k: v for k, v in args.items() if v}

    @property
    def active(self):
        return bool(self.q or self.status or self.priority or self.case_type_id or self.investigator_id
                    or self.date_from or self.date_to or self.overdue)


def like_pattern(text):
    """Escape LIKE wildcards so a search for '50%' or 'a_b' matches literally.
    Used with ESCAPE '!' in the SQL."""
    return "%" + text.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


def list_cases(scope, filters, page, per_page):
    where, params = ["1 = 1"], []
    if filters.q:
        where.append("(c.case_reference LIKE %s ESCAPE '!' OR c.title LIKE %s ESCAPE '!')")
        params += [like_pattern(filters.q)] * 2
    if filters.status in STATUS_GROUPS:
        where.append(STATUS_GROUPS[filters.status][1])
    elif filters.status:
        where.append("c.status = %s")
        params.append(filters.status)
    if filters.priority in PRIORITY_GROUPS:
        where.append(PRIORITY_GROUPS[filters.priority][1])
    elif filters.priority:
        where.append("c.priority = %s")
        params.append(filters.priority)
    if filters.case_type_id:
        where.append("c.case_type_id = %s")
        params.append(filters.case_type_id)
    if filters.investigator_id:
        where.append("EXISTS (SELECT 1 FROM case_investigators fi WHERE fi.case_id = c.case_id AND fi.user_id = %s)")
        params.append(filters.investigator_id)
    if filters.date_from:
        where.append("c.created_at >= %s")
        params.append(filters.date_from)
    if filters.date_to:
        where.append("c.created_at < %s + INTERVAL 1 DAY")
        params.append(filters.date_to)
    if filters.overdue:
        where.append("c.status <> 'Closed' AND c.due_date < CURDATE()")
    condition = " AND ".join(where) + scope.case_filter
    all_params = tuple(params) + scope.params

    total = query_value(f"SELECT COUNT(*) FROM cases c WHERE {condition}", all_params)
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    order_by = SORTS[filters.sort][1]
    rows = query_all(
        f"""
        SELECT c.case_id, c.case_reference, c.title, ct.type_name, c.priority, c.status, c.created_at, c.due_date,
               (c.status <> 'Closed' AND c.due_date < CURDATE()) AS is_overdue,
               lu.full_name AS lead_name,
               (SELECT COUNT(*) FROM evidence e WHERE e.case_id = c.case_id) AS evidence_count,
               {LAST_ACTIVITY_SQL} AS last_activity
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
           c.priority, c.status, c.due_date, c.created_at, c.updated_at, c.closed_at, c.closure_summary,
           (c.status <> 'Closed' AND c.due_date < CURDATE()) AS is_overdue,
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
               (SELECT COUNT(*) FROM forensic_reports   WHERE case_id = %s) AS reports,
               (SELECT COUNT(*) FROM case_notes         WHERE case_id = %s) AS notes,
               (SELECT COUNT(*) FROM chain_of_custody coc JOIN evidence e ON e.evidence_id = coc.evidence_id
                 WHERE e.case_id = %s)                                         AS custody
        """,
        (case_id,) * 6,
    )
    return {k: int(v) for k, v in row.items()}


def closure_blockers(case_id):
    """What would stop sp_close_case, so the close page can explain it first."""
    return {
        "examinations": query_all(
            "SELECT examination_code, status FROM examinations "
            "WHERE case_id = %s AND status IN ('Pending', 'In Progress', 'Under Review') ORDER BY examination_code",
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
def create_case(title, description, case_type_id, priority, lead_user_id, created_by, due_date=None):
    """sp_register_case: reference number, case row, lead assignment and
    audit record in one transaction. Returns the new case reference.

    An optional due date is set right afterwards, in a second transaction
    (sp_register_case predates due dates and its signature is kept)."""
    try:
        result = call_proc("sp_register_case",
                           (title, description, case_type_id, priority, lead_user_id, created_by, None, None))
    except BusinessRuleError as err:
        raise CaseActionError(err.user_message) from err
    reference = result[7]          # OUT p_case_reference
    if due_date:
        try:
            with transaction() as cur:
                cur.execute("UPDATE cases SET due_date = %s WHERE case_reference = %s", (due_date, reference))
                audit.record("case.update", "Case", reference, cursor=cur, details=f"Due date set to {due_date}")
        except DatabaseError as err:
            raise CaseActionError(f"Case {reference} was registered, but its due date couldn't be saved. "
                                  "Set it with Edit details.") from err
    return reference


def _lock_case(cur, case_id):
    cur.execute(
        """
        SELECT c.case_id, c.case_reference, c.title, c.description, c.case_type_id, c.priority, c.status,
               c.due_date, c.created_at, c.updated_at, ci.user_id AS lead_user_id
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


def update_case(case_id, user, title, description, case_type_id, priority, expected_version, due_date=None):
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
        if due_date != case["due_date"]:
            if due_date and due_date < case["created_at"].date():
                raise CaseActionError("The due date can't be before the case was registered.")
            changes.append(f"due date ({case['due_date'] or 'none'} to {due_date or 'none'})")
        if not changes:
            return False

        cur.execute(
            "UPDATE cases SET title = %s, description = %s, case_type_id = %s, priority = %s, due_date = %s "
            "WHERE case_id = %s",
            (title, description, case_type_id, priority, due_date, case_id),
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
    "(SELECT COUNT(*) FROM forensic_reports r WHERE r.case_id = c.case_id) AS reports, "
    "(SELECT COUNT(*) FROM case_notes n WHERE n.case_id = c.case_id) AS notes "
    "FROM cases c WHERE c.case_id = %s")


def _blockers(row):
    if row is None:
        return ["The case doesn't exist."]
    names = {"evidence": ("evidence item", "evidence items"), "examinations": ("examination", "examinations"),
             "reports": ("report", "reports"), "notes": ("note", "notes")}
    parts = [f"{int(row[k])} {names[k][int(row[k]) != 1]}" for k in names if int(row.get(k) or 0)]
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



# ---------------------------------------------------------------------------
# FORGE-X 2.0 Phase 2: the case's chain of custody and its notes
# ---------------------------------------------------------------------------
NOTE_MAX = 4000


def case_custody(case_id, limit=200):
    """Custody entries for every evidence item of the case, newest first."""
    return query_all(
        """
        SELECT coc.custody_id, coc.occurred_at, coc.action, coc.evidence_condition, coc.reason,
               coc.corrects_custody_id, e.evidence_code,
               fu.full_name AS from_name, tu.full_name AS to_name, ru.full_name AS recorded_by_name,
               COALESCE(sl.location_name, coc.location_note) AS location
          FROM chain_of_custody coc
          JOIN evidence e                ON e.evidence_id = coc.evidence_id
          LEFT JOIN users fu             ON fu.user_id = coc.from_custodian_id
          JOIN users tu                  ON tu.user_id = coc.to_custodian_id
          JOIN users ru                  ON ru.user_id = coc.recorded_by
          LEFT JOIN storage_locations sl ON sl.location_id = coc.location_id
         WHERE e.case_id = %s
         ORDER BY coc.occurred_at DESC, coc.custody_id DESC
         LIMIT %s
        """,
        (case_id, limit),
    )


def case_notes(case_id):
    """Notes oldest first, each marked with the notes that correct it."""
    rows = query_all(
        "SELECT n.note_id, n.note_text, n.reference, n.corrects_note_id, n.created_at, u.full_name AS author_name "
        "FROM case_notes n JOIN users u ON u.user_id = n.author_id WHERE n.case_id = %s "
        "ORDER BY n.created_at, n.note_id", (case_id,))
    corrected_by = {}
    for row in rows:
        if row["corrects_note_id"]:
            corrected_by.setdefault(row["corrects_note_id"], []).append(row["note_id"])
    for row in rows:
        row["corrected_by"] = corrected_by.get(row["note_id"], [])
    return rows


def add_note(case, user, text, reference=None, corrects_note_id=None):
    """Append a note (never edited or deleted). Triggers re-check that the case
    is open and that a correction refers to a note on the same case."""
    from ..access import can_add_case_note
    text = (text or "").strip()
    if len(text) < 2 or len(text) > NOTE_MAX:
        raise CaseActionError(f"A note needs 2 to {NOTE_MAX} characters.")
    assigned = bool(query_value("SELECT COUNT(*) FROM case_investigators WHERE case_id = %s AND user_id = %s",
                                (case["case_id"], user["user_id"])))
    if not can_add_case_note(user, case, assigned):
        raise CaseActionError("Only administrators, custodians and the case's investigators can add notes to an open case.")
    try:
        with transaction() as cur:
            cur.execute("INSERT INTO case_notes (case_id, note_text, reference, corrects_note_id, author_id) "
                        "VALUES (%s, %s, %s, %s, %s)",
                        (case["case_id"], text, (reference or "").strip() or None, corrects_note_id, user["user_id"]))
            note_id = cur.lastrowid
            audit.record("case.note", "Case", case["case_reference"], cursor=cur,
                         details=(f"Note #{note_id}" + (f" corrects note #{corrects_note_id}" if corrects_note_id else ""))[:500])
    except BusinessRuleError as err:          # the trigger's message (closed case, wrong case)
        raise CaseActionError(err.user_message) from err
    return note_id


def active_investigators_for_filter():
    return query_all(
        "SELECT DISTINCT u.user_id, u.full_name FROM users u JOIN user_roles ur ON ur.user_id = u.user_id "
        "JOIN roles r ON r.role_id = ur.role_id WHERE r.role_name = 'Investigator' ORDER BY u.full_name")
