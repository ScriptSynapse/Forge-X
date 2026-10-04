"""Forensic reports: header + immutable versions + review workflow.

  Draft --submit--> Under Review --approve--> Approved
                       |--return--> Draft (a new version can then be saved)

* Every content change is a NEW row in report_versions (append-only).
* New versions are accepted only while the report is a Draft (trigger).
* The approver must not be the author (CHECK chk_rep_independent).
* Observations are recorded facts; findings and conclusions are the
  examiner's interpretation. The pages and the PDF keep them visibly apart.
"""
from dataclasses import dataclass

from .. import audit
from ..access import can_edit_report, can_review_report
from ..db import BusinessRuleError, ConstraintViolation, call_proc, query_all, query_one, query_value, transaction
from ..pagination import Page

STATUSES = ("Draft", "Under Review", "Approved")
SECTIONS = (("methodology", "Methodology"), ("observations", "Observations"), ("findings", "Findings"),
            ("conclusions", "Conclusions"), ("limitations", "Limitations"))


class ReportError(Exception):
    """A refused report action, with a message that is safe to display."""


@dataclass
class ReportFilters:
    status: str = ""
    case_reference: str = ""

    @classmethod
    def from_args(cls, args):
        return cls(status=args.get("status") if args.get("status") in STATUSES else "",
                   case_reference=(args.get("case") or "").strip().upper()[:12])

    def as_args(self):
        return {k: v for k, v in {"status": self.status, "case": self.case_reference}.items() if v}


def list_reports(scope, filters, page, per_page):
    where, params = ["1 = 1"], []
    if filters.status:
        where.append("r.status = %s"); params.append(filters.status)
    if filters.case_reference:
        where.append("c.case_reference = %s"); params.append(filters.case_reference)
    condition = " AND ".join(where) + scope.case_filter
    all_params = tuple(params) + scope.params
    base = "FROM forensic_reports r JOIN cases c ON c.case_id = r.case_id JOIN users u ON u.user_id = r.author_id"
    total = query_value(f"SELECT COUNT(*) {base} WHERE {condition}", all_params)
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    rows = query_all(
        f"SELECT r.report_id, r.report_code, r.title, r.status, r.updated_at, c.case_reference, u.full_name AS author_name, "
        f"(SELECT MAX(version_no) FROM report_versions v WHERE v.report_id = r.report_id) AS version_no "
        f"{base} WHERE {condition} ORDER BY r.updated_at DESC, r.report_id DESC LIMIT %s OFFSET %s",
        all_params + (per_page, (page - 1) * per_page))
    return Page(items=rows, page=page, per_page=per_page, total=total)


def status_counts(scope):
    rows = query_all(f"SELECT r.status, COUNT(*) AS n FROM forensic_reports r JOIN cases c ON c.case_id = r.case_id "
                     f"WHERE 1 = 1 {scope.case_filter} GROUP BY r.status", scope.params)
    found = {r["status"]: int(r["n"]) for r in rows}
    return {s: found.get(s, 0) for s in STATUSES}


def get_report(scope, code):
    return query_one(
        f"""
        SELECT r.*, c.case_reference, c.title AS case_title, c.status AS case_status, c.case_id,
               au.full_name AS author_name, ap.full_name AS approved_by_name
          FROM forensic_reports r
          JOIN cases c ON c.case_id = r.case_id
          JOIN users au ON au.user_id = r.author_id
          LEFT JOIN users ap ON ap.user_id = r.approved_by
         WHERE r.report_code = %s {scope.case_filter}
        """,
        (code,) + scope.params,
    )


def versions(report_id):
    return query_all("SELECT v.version_id, v.version_no, v.change_note, v.created_at, u.full_name AS created_by_name "
                     "FROM report_versions v JOIN users u ON u.user_id = v.created_by "
                     "WHERE v.report_id = %s ORDER BY v.version_no DESC", (report_id,))


def get_version(report_id, version_no=None):
    """A specific version, or the latest when version_no is None."""
    if version_no is None:
        return query_one("SELECT v.*, u.full_name AS created_by_name FROM report_versions v "
                         "JOIN users u ON u.user_id = v.created_by WHERE v.report_id = %s "
                         "ORDER BY v.version_no DESC LIMIT 1", (report_id,))
    return query_one("SELECT v.*, u.full_name AS created_by_name FROM report_versions v "
                     "JOIN users u ON u.user_id = v.created_by WHERE v.report_id = %s AND v.version_no = %s",
                     (report_id, version_no))


def linked_examinations(report_id):
    return query_all("SELECT v.* FROM report_examinations re JOIN v_examination_summary v "
                     "ON v.examination_id = re.examination_id WHERE re.report_id = %s ORDER BY v.examination_code",
                     (report_id,))


def referenced_evidence(report_id):
    """Evidence reached through the cited examinations (never copied into report text)."""
    return query_all(
        """
        SELECT DISTINCT v.evidence_code, v.evidence_type, v.description, v.integrity_status, vi.current_hash_value
          FROM report_examinations re
          JOIN examination_evidence ee ON ee.examination_id = re.examination_id
          JOIN v_evidence_overview v   ON v.evidence_id = ee.evidence_id
          JOIN v_evidence_integrity vi ON vi.evidence_id = ee.evidence_id
         WHERE re.report_id = %s
         ORDER BY v.evidence_code
        """,
        (report_id,),
    )


def linkable_examinations(case_id, report_id=None):
    return query_all("SELECT examination_id, examination_code, status FROM examinations WHERE case_id = %s "
                     "AND examination_id NOT IN (SELECT examination_id FROM report_examinations WHERE report_id = %s) "
                     "ORDER BY examination_code", (case_id, report_id or 0))


def writable_cases(user, is_admin):
    if is_admin:
        return query_all("SELECT case_id, case_reference, title FROM cases WHERE status <> 'Closed' "
                         "ORDER BY case_reference DESC")
    return query_all("SELECT c.case_id, c.case_reference, c.title FROM cases c JOIN case_investigators ci "
                     "ON ci.case_id = c.case_id AND ci.user_id = %s WHERE c.status <> 'Closed' "
                     "ORDER BY c.case_reference DESC", (user["user_id"],))


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------
def _link(cur, report_id, examination_ids):
    for examination_id in examination_ids:
        # Trigger trg_re_same_case refuses examinations from another case.
        cur.execute("INSERT INTO report_examinations (report_id, examination_id) VALUES (%s, %s)",
                    (report_id, examination_id))


def create_report(case_id, title, author_id, sections, examination_ids):
    """sp_create_report: report code, header and version 1 in one transaction.
    Cited examinations are then linked in a second, separate transaction."""
    try:
        result = call_proc("sp_create_report", (case_id, title, author_id, sections["methodology"],
                                                sections["observations"], sections["findings"],
                                                sections["conclusions"], sections["limitations"], None, None))
    except BusinessRuleError as err:
        raise ReportError(err.user_message) from err
    report_id, code = result[8], result[9]
    if examination_ids:
        try:
            with transaction() as cur:
                _link(cur, report_id, examination_ids)
                audit.record("report.link_exam", "Report", code, cursor=cur,
                             details=f"{len(examination_ids)} examination(s) cited")
        except (BusinessRuleError, ConstraintViolation) as err:
            raise ReportError(f"Report {code} was created, but its examinations couldn't be linked. "
                              "Link them from the report page.") from err
    return code


def save_version(report, user, sections, change_note):
    if not can_edit_report(user, report):
        raise ReportError("Only the author or an administrator can edit a Draft report on an open case.")
    try:
        result = call_proc("sp_create_report_version", (report["report_id"], sections["methodology"],
                                                         sections["observations"], sections["findings"],
                                                         sections["conclusions"], sections["limitations"],
                                                         change_note, user["user_id"], None))
    except BusinessRuleError as err:
        raise ReportError(err.user_message) from err
    return result[8]


def link_examinations(report, user, examination_ids):
    if not can_edit_report(user, report):
        raise ReportError("Examinations can be cited only while the report is a Draft.")
    if not examination_ids:
        raise ReportError("Choose at least one examination.")
    try:
        with transaction() as cur:
            _link(cur, report["report_id"], examination_ids)
            audit.record("report.link_exam", "Report", report["report_code"], cursor=cur,
                         details=f"{len(examination_ids)} examination(s) cited")
    except (BusinessRuleError, ConstraintViolation) as err:
        raise ReportError("Those examinations can't be cited (already cited, or from another case).") from err


def _lock(cur, report_id):
    cur.execute("SELECT r.report_id, r.report_code, r.status, r.author_id, c.status AS case_status "
                "FROM forensic_reports r JOIN cases c ON c.case_id = r.case_id WHERE r.report_id = %s FOR UPDATE",
                (report_id,))
    report = cur.fetchone()
    if report is None:
        raise ReportError("Report not found.")
    return report


def submit(report_id, user):
    with transaction() as cur:
        report = _lock(cur, report_id)
        if not can_edit_report(user, report):
            raise ReportError("Only the author or an administrator can submit a Draft report.")
        cur.execute("UPDATE forensic_reports SET status = 'Under Review', submitted_at = NOW() WHERE report_id = %s",
                    (report_id,))
        audit.record("report.submit", "Report", report["report_code"], cursor=cur, details="Sent for review")


def approve(report_id, user):
    try:
        with transaction() as cur:
            report = _lock(cur, report_id)
            if not can_review_report(user, report):
                raise ReportError("Reports Under Review are approved by an administrator who is not the author.")
            cur.execute("UPDATE forensic_reports SET status = 'Approved', approved_by = %s, approved_at = NOW() "
                        "WHERE report_id = %s", (user["user_id"], report_id))
            cur.execute("SELECT MAX(version_no) AS v FROM report_versions WHERE report_id = %s", (report_id,))
            audit.record("report.approve", "Report", report["report_code"], cursor=cur,
                         details=f"Version {cur.fetchone()['v']} approved")
    except ConstraintViolation as err:     # chk_rep_independent, as a second line of defence
        raise ReportError("The database refused the approval (" + (err.constraint or "constraint") + ").") from err


def return_to_draft(report_id, user, note):
    if not note or len(note.strip()) < 5:
        raise ReportError("Say what the author should change.")
    with transaction() as cur:
        report = _lock(cur, report_id)
        if not can_review_report(user, report):
            raise ReportError("Only a reviewing administrator who is not the author can return a report.")
        cur.execute("UPDATE forensic_reports SET status = 'Draft' WHERE report_id = %s", (report_id,))
        audit.record("report.return", "Report", report["report_code"], cursor=cur, details=note.strip()[:500])


def record_export(report, version_no):
    audit.record("report.export", "Report", report["report_code"], details=f"PDF of version {version_no}")
