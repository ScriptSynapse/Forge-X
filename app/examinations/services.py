"""Forensic examinations. FORGE-X RECORDS examination work (tools, methods,
observations, findings, limitations). It never runs forensic tools and
never touches original evidence.

Status workflow (CHECK chk_exam_state enforces the required fields):
  Pending -> In Progress  (start: sets started_at)
  In Progress -> Completed (needs tools/methods and findings; sets completed_at)
  Pending / In Progress -> Cancelled (needs a reason)
"""
from dataclasses import dataclass

from .. import audit
from ..access import can_work_on_examination
from ..db import BusinessRuleError, ConstraintViolation, query_all, query_one, query_value, transaction
from ..pagination import Page

STATUSES = ("Pending", "In Progress", "Completed", "Cancelled")


class ExamError(Exception):
    """A refused examination action, with a message that is safe to display."""


@dataclass
class ExamFilters:
    status: str = ""
    examination_type_id: int = None
    case_reference: str = ""
    mine: bool = False
    overdue: bool = False

    @classmethod
    def from_args(cls, args):
        type_raw = args.get("type", "")
        return cls(status=args.get("status") if args.get("status") in STATUSES else "",
                   examination_type_id=int(type_raw) if type_raw.isdigit() else None,
                   case_reference=(args.get("case") or "").strip().upper()[:12],
                   mine=args.get("mine") == "1", overdue=args.get("overdue") == "1")

    def as_args(self):
        args = {"status": self.status, "type": self.examination_type_id or "", "case": self.case_reference,
                "mine": "1" if self.mine else "", "overdue": "1" if self.overdue else ""}
        return {k: v for k, v in args.items() if v}

    @property
    def active(self):
        return bool(self.status or self.examination_type_id or self.case_reference or self.mine or self.overdue)


def list_examinations(scope, filters, user_id, page, per_page):
    where, params = ["1 = 1"], []
    if filters.status:
        where.append("v.status = %s"); params.append(filters.status)
    if filters.examination_type_id:
        where.append("x.examination_type_id = %s"); params.append(filters.examination_type_id)
    if filters.case_reference:
        where.append("v.case_reference = %s"); params.append(filters.case_reference)
    if filters.mine:
        where.append("v.examiner_id = %s"); params.append(user_id)
    if filters.overdue:
        where.append("v.is_overdue")
    condition = " AND ".join(where) + scope.case_filter
    all_params = tuple(params) + scope.params
    base = """FROM v_examination_summary v
              JOIN examinations x ON x.examination_id = v.examination_id
              JOIN cases c ON c.case_id = v.case_id"""
    total = query_value(f"SELECT COUNT(*) {base} WHERE {condition}", all_params)
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    rows = query_all(f"SELECT v.* {base} WHERE {condition} "
                     "ORDER BY FIELD(v.status, 'In Progress', 'Pending', 'Completed', 'Cancelled'), "
                     "v.due_date IS NULL, v.due_date, v.examination_code DESC LIMIT %s OFFSET %s",
                     all_params + (per_page, (page - 1) * per_page))
    return Page(items=rows, page=page, per_page=per_page, total=total)


def status_counts(scope):
    rows = query_all(f"SELECT x.status, COUNT(*) AS n FROM examinations x JOIN cases c ON c.case_id = x.case_id "
                     f"WHERE 1 = 1 {scope.case_filter} GROUP BY x.status", scope.params)
    found = {r["status"]: int(r["n"]) for r in rows}
    return {s: found.get(s, 0) for s in STATUSES}


def examination_types():
    return query_all("SELECT examination_type_id, type_name, description FROM examination_types "
                     "WHERE is_active = TRUE ORDER BY type_name")


def get_examination(scope, code):
    return query_one(
        f"""
        SELECT x.*, xt.type_name, xt.description AS type_description, c.case_reference, c.title AS case_title,
               c.status AS case_status, u.full_name AS examiner_name, ci.user_id AS lead_user_id,
               COALESCE(x.status IN ('Pending', 'In Progress') AND x.due_date < CURDATE(), FALSE) AS is_overdue
          FROM examinations x
          JOIN examination_types xt ON xt.examination_type_id = x.examination_type_id
          JOIN cases c ON c.case_id = x.case_id
          JOIN users u ON u.user_id = x.examiner_id
          LEFT JOIN case_investigators ci ON ci.case_id = c.case_id AND ci.is_lead = TRUE
         WHERE x.examination_code = %s {scope.case_filter}
        """,
        (code,) + scope.params,
    )


def linked_evidence(examination_id):
    return query_all("SELECT v.*, ee.linked_at FROM examination_evidence ee "
                     "JOIN v_evidence_overview v ON v.evidence_id = ee.evidence_id "
                     "WHERE ee.examination_id = %s ORDER BY v.evidence_code", (examination_id,))


def case_evidence_not_linked(case_id, examination_id=None):
    return query_all(
        "SELECT evidence_id, evidence_code, description FROM evidence WHERE case_id = %s "
        "AND evidence_id NOT IN (SELECT evidence_id FROM examination_evidence WHERE examination_id = %s) "
        "ORDER BY evidence_code",
        (case_id, examination_id or 0),
    )


def citing_reports(examination_id):
    return query_all("SELECT r.report_code, r.title, r.status FROM report_examinations re "
                     "JOIN forensic_reports r ON r.report_id = re.report_id WHERE re.examination_id = %s "
                     "ORDER BY r.report_code", (examination_id,))


def case_examiners(case_id):
    """Active investigators assigned to the case: the possible examiners."""
    return query_all(
        """
        SELECT u.user_id, u.full_name FROM case_investigators ci
          JOIN users u ON u.user_id = ci.user_id
          JOIN user_roles ur ON ur.user_id = u.user_id
          JOIN roles r ON r.role_id = ur.role_id AND r.role_name = 'Investigator'
         WHERE ci.case_id = %s AND u.account_status = 'Active'
         ORDER BY ci.is_lead DESC, u.full_name
        """,
        (case_id,),
    )


def creatable_cases(user, is_admin):
    """Open cases where this user may create an examination."""
    if is_admin:
        return query_all("SELECT case_id, case_reference, title FROM cases WHERE status <> 'Closed' "
                         "ORDER BY case_reference DESC")
    return query_all("SELECT c.case_id, c.case_reference, c.title FROM cases c JOIN case_investigators ci "
                     "ON ci.case_id = c.case_id AND ci.user_id = %s WHERE c.status <> 'Closed' "
                     "ORDER BY c.case_reference DESC", (user["user_id"],))


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------
def create_examination(case_id, examination_type_id, examiner_id, due_date, evidence_ids, created_by):
    """Code (EX-YYYY-NNNN), examination row, evidence links and audit record in
    one transaction. The code counter is rolled back too if anything fails."""
    if examiner_id not in {e["user_id"] for e in case_examiners(case_id)}:
        raise ExamError("The examiner must be an active investigator assigned to this case.")
    try:
        with transaction() as cur:
            cur.execute("SELECT status FROM cases WHERE case_id = %s FOR UPDATE", (case_id,))
            case = cur.fetchone()
            if case is None or case["status"] == "Closed":
                raise ExamError("Examinations can only be added to open cases.")
            # The same gap-free yearly counter the procedures use.
            cur.execute("CALL sp_next_reference('EXAMINATION', YEAR(CURDATE()), @fx_seq)")
            cur.execute("SELECT CONCAT('EX-', YEAR(CURDATE()), '-', LPAD(@fx_seq, 4, '0')) AS code")
            code = cur.fetchone()["code"]
            cur.execute(
                "INSERT INTO examinations (examination_code, case_id, examination_type_id, examiner_id, status, due_date) "
                "VALUES (%s, %s, %s, %s, 'Pending', %s)",
                (code, case_id, examination_type_id, examiner_id, due_date),
            )
            exam_id = cur.lastrowid
            for evidence_id in evidence_ids:
                # Trigger trg_ee_same_case refuses evidence from another case.
                cur.execute("INSERT INTO examination_evidence (examination_id, evidence_id) VALUES (%s, %s)",
                            (exam_id, evidence_id))
            audit.record("exam.create", "Examination", code, cursor=cur,
                         details=f"{len(evidence_ids)} evidence item(s) linked")
    except (BusinessRuleError, ConstraintViolation) as err:
        raise ExamError(getattr(err, "user_message", "The database refused this examination.")) from err
    return code


def _lock(cur, examination_id, user):
    cur.execute(
        """
        SELECT x.examination_id, x.examination_code, x.status, x.examiner_id, x.tools_methods, x.findings,
               x.observations, x.limitations, c.status AS case_status, ci.user_id AS lead_user_id
          FROM examinations x
          JOIN cases c ON c.case_id = x.case_id
          LEFT JOIN case_investigators ci ON ci.case_id = c.case_id AND ci.is_lead = TRUE
         WHERE x.examination_id = %s
           FOR UPDATE
        """,
        (examination_id,),
    )
    exam = cur.fetchone()
    if exam is None:
        raise ExamError("Examination not found.")
    if not can_work_on_examination(user, exam):
        raise ExamError("This examination can't be changed: it is finished, its case is closed, "
                        "or you are not its examiner, the case lead or an administrator.")
    return exam


def update_record(examination_id, user, tools_methods, observations, findings, limitations):
    with transaction() as cur:
        exam = _lock(cur, examination_id, user)
        new = {"tools_methods": tools_methods or None, "observations": observations or None,
               "findings": findings or None, "limitations": limitations or None}
        changed = [k.replace("_", " ") for k, v in new.items() if v != exam[k]]
        if not changed:
            return False
        cur.execute("UPDATE examinations SET tools_methods = %s, observations = %s, findings = %s, limitations = %s "
                    "WHERE examination_id = %s", (*new.values(), examination_id))
        audit.record("exam.update", "Examination", exam["examination_code"], cursor=cur,
                     details="Updated: " + ", ".join(changed))
    return True


def start(examination_id, user):
    with transaction() as cur:
        exam = _lock(cur, examination_id, user)
        if exam["status"] != "Pending":
            raise ExamError("Only a Pending examination can be started.")
        cur.execute("UPDATE examinations SET status = 'In Progress', started_at = NOW() WHERE examination_id = %s",
                    (examination_id,))
        audit.record("exam.start", "Examination", exam["examination_code"], cursor=cur)


def complete(examination_id, user):
    with transaction() as cur:
        exam = _lock(cur, examination_id, user)
        if exam["status"] != "In Progress":
            raise ExamError("Start the examination before completing it.")
        if not exam["tools_methods"] or not exam["findings"]:
            raise ExamError("Record the tools and methods and the findings before completing the examination.")
        cur.execute("UPDATE examinations SET status = 'Completed', completed_at = NOW() WHERE examination_id = %s",
                    (examination_id,))
        audit.record("exam.complete", "Examination", exam["examination_code"], cursor=cur)


def cancel(examination_id, user, reason):
    if not reason or len(reason.strip()) < 5:
        raise ExamError("Give a reason for cancelling.")
    with transaction() as cur:
        exam = _lock(cur, examination_id, user)
        cur.execute("UPDATE examinations SET status = 'Cancelled', cancel_reason = %s WHERE examination_id = %s",
                    (reason.strip()[:500], examination_id))
        audit.record("exam.cancel", "Examination", exam["examination_code"], cursor=cur, details=reason[:500])


def link_evidence(examination_id, user, evidence_ids):
    if not evidence_ids:
        raise ExamError("Choose at least one evidence item.")
    try:
        with transaction() as cur:
            exam = _lock(cur, examination_id, user)
            for evidence_id in evidence_ids:
                cur.execute("INSERT INTO examination_evidence (examination_id, evidence_id) VALUES (%s, %s)",
                            (examination_id, evidence_id))
            audit.record("exam.link_evidence", "Examination", exam["examination_code"], cursor=cur,
                         details=f"{len(evidence_ids)} item(s) linked")
    except (BusinessRuleError, ConstraintViolation) as err:
        raise ExamError("These items can't be linked (already linked, or from another case).") from err
