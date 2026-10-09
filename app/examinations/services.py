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

STATUSES = ("Pending", "In Progress", "Under Review", "Completed", "Cancelled")
ARTIFACT_TYPES = ("File", "Registry entry", "Log entry", "Network indicator", "Email", "Other")


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
               rv.full_name AS reviewer_name,
               COALESCE(x.status IN ('Pending', 'In Progress') AND x.due_date < CURDATE(), FALSE) AS is_overdue
          FROM examinations x
          JOIN examination_types xt ON xt.examination_type_id = x.examination_type_id
          JOIN cases c ON c.case_id = x.case_id
          JOIN users u ON u.user_id = x.examiner_id
          LEFT JOIN users rv ON rv.user_id = x.reviewed_by
          LEFT JOIN case_investigators ci ON ci.case_id = c.case_id AND ci.is_lead = TRUE
         WHERE x.examination_code = %s {scope.case_filter}
        """,
        (code,) + scope.params,
    )


def linked_evidence(examination_id):
    return query_all("SELECT v.*, ee.linked_at, (SELECT vi.current_hash_value FROM v_evidence_integrity vi "
                     "WHERE vi.evidence_id = v.evidence_id) AS current_hash_value FROM examination_evidence ee "
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


def _lock_row(cur, examination_id):
    cur.execute(
        """
        SELECT x.examination_id, x.examination_code, x.status, x.examiner_id, x.tools_methods, x.findings,
               x.observations, x.conclusion, x.limitations, c.status AS case_status, ci.user_id AS lead_user_id
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
    return exam


def _lock(cur, examination_id, user):
    cur.execute(
        """
        SELECT x.examination_id, x.examination_code, x.status, x.examiner_id, x.tools_methods, x.findings,
               x.observations, x.conclusion, x.limitations, c.status AS case_status, ci.user_id AS lead_user_id
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


def update_record(examination_id, user, tools_methods, observations, findings, limitations, conclusion=None):
    with transaction() as cur:
        exam = _lock(cur, examination_id, user)
        new = {"tools_methods": tools_methods or None, "observations": observations or None,
               "findings": findings or None, "limitations": limitations or None, "conclusion": conclusion or None}
        changed = [k.replace("_", " ") for k, v in new.items() if v != exam[k]]
        if not changed:
            return False
        cur.execute("UPDATE examinations SET tools_methods = %s, observations = %s, findings = %s, limitations = %s, "
                    "conclusion = %s WHERE examination_id = %s", (*new.values(), examination_id))
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


def submit(examination_id, user):
    """In Progress -> Under Review. The examiner's record is then frozen
    until a reviewer approves it (Completed) or returns it (In Progress)."""
    with transaction() as cur:
        exam = _lock(cur, examination_id, user)
        if exam["status"] != "In Progress":
            raise ExamError("Start the examination before submitting it for review.")
        if not exam["tools_methods"] or not exam["findings"]:
            raise ExamError("Record the tools and methods and the findings before submitting for review.")
        cur.execute("UPDATE examinations SET status = 'Under Review', submitted_at = NOW(), review_note = NULL "
                    "WHERE examination_id = %s", (examination_id,))
        audit.record("exam.submit", "Examination", exam["examination_code"], cursor=cur, details="Sent for review")


def _lock_for_review(cur, examination_id, user):
    from ..access import can_review_examination
    exam = _lock_row(cur, examination_id)
    if not can_review_examination(user, exam):
        raise ExamError("Examinations under review are approved or returned by an administrator or the case's "
                        "lead investigator who is not the examiner.")
    return exam


def approve(examination_id, user, note=None):
    """Under Review -> Completed by an independent reviewer. The record is
    final afterwards (trigger trg_exam_finalised)."""
    with transaction() as cur:
        exam = _lock_for_review(cur, examination_id, user)
        cur.execute("UPDATE examinations SET status = 'Completed', completed_at = NOW(), reviewed_by = %s, "
                    "reviewed_at = NOW(), review_note = %s WHERE examination_id = %s",
                    (user["user_id"], (note or "").strip()[:500] or None, examination_id))
        audit.record("exam.approve", "Examination", exam["examination_code"], cursor=cur,
                     details="Approved and completed" + (f": {note.strip()[:400]}" if note and note.strip() else ""))


def return_for_revision(examination_id, user, note):
    if not note or len(note.strip()) < 5:
        raise ExamError("Say what the examiner should revise.")
    with transaction() as cur:
        exam = _lock_for_review(cur, examination_id, user)
        cur.execute("UPDATE examinations SET status = 'In Progress', submitted_at = NULL, review_note = %s "
                    "WHERE examination_id = %s", (note.strip()[:500], examination_id))
        audit.record("exam.return", "Examination", exam["examination_code"], cursor=cur, details=note.strip()[:500])


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


# ---------------------------------------------------------------------------
# Artifacts (append-only) and history
# ---------------------------------------------------------------------------
def artifacts(examination_id):
    rows = query_all(
        "SELECT a.artifact_id, a.artifact_type, a.description, a.location, a.sha256, a.corrects_artifact_id, "
        "a.recorded_at, u.full_name AS recorded_by_name, e.evidence_code FROM examination_artifacts a "
        "JOIN users u ON u.user_id = a.recorded_by LEFT JOIN evidence e ON e.evidence_id = a.evidence_id "
        "WHERE a.examination_id = %s ORDER BY a.recorded_at, a.artifact_id", (examination_id,))
    corrected_by = {}
    for row in rows:
        if row["corrects_artifact_id"]:
            corrected_by.setdefault(row["corrects_artifact_id"], []).append(row["artifact_id"])
    for row in rows:
        row["corrected_by"] = corrected_by.get(row["artifact_id"], [])
    return rows


def add_artifact(examination_id, user, artifact_type, description, location, evidence_id, sha256, corrects_artifact_id):
    """Record an artifact while the examination is open. MySQL re-checks that
    the examination is open, the evidence is linked to it, and a correction
    refers to an artifact of the same examination."""
    if artifact_type not in ARTIFACT_TYPES:
        raise ExamError("Choose an artifact type.")
    try:
        with transaction() as cur:
            exam = _lock(cur, examination_id, user)
            cur.execute(
                "INSERT INTO examination_artifacts (examination_id, evidence_id, artifact_type, description, location, "
                "sha256, corrects_artifact_id, recorded_by) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (examination_id, evidence_id or None, artifact_type, description.strip(), (location or "").strip() or None,
                 sha256 or None, corrects_artifact_id or None, user["user_id"]))
            artifact_id = cur.lastrowid
            audit.record("exam.artifact", "Examination", exam["examination_code"], cursor=cur,
                         details=(f"Artifact #{artifact_id}: {artifact_type}"
                                  + (f", corrects #{corrects_artifact_id}" if corrects_artifact_id else ""))[:500])
    except (BusinessRuleError, ConstraintViolation) as err:
        raise ExamError(getattr(err, "user_message", "The database refused this artifact.")) from err
    return artifact_id


def history(code):
    return query_all("SELECT a.created_at, a.action, a.outcome, a.details, u.full_name AS user_name FROM audit_logs a "
                     "LEFT JOIN users u ON u.user_id = a.user_id WHERE a.entity_ref = %s "
                     "ORDER BY a.created_at DESC, a.audit_id DESC LIMIT 200", (code,))


def custody_references(examination_id, per_item=10):
    """The latest custody entries of each evidence item the examination used (for the PDF)."""
    return query_all(
        """
        SELECT t.evidence_code, t.custody_id, t.action, t.occurred_at, t.to_name FROM (
          SELECT e.evidence_code, coc.custody_id, coc.action, coc.occurred_at, tu.full_name AS to_name,
                 ROW_NUMBER() OVER (PARTITION BY coc.evidence_id ORDER BY coc.occurred_at DESC, coc.custody_id DESC) AS rn
            FROM examination_evidence ee
            JOIN evidence e         ON e.evidence_id = ee.evidence_id
            JOIN chain_of_custody coc ON coc.evidence_id = e.evidence_id
            JOIN users tu           ON tu.user_id = coc.to_custodian_id
           WHERE ee.examination_id = %s) t
         WHERE t.rn <= %s
         ORDER BY t.evidence_code, t.occurred_at
        """, (examination_id, per_item))
