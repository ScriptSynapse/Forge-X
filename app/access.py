"""Who may see and change cases (the Phase 1 role-permission matrix).

Visibility
  * Administrators, Read-Only Auditors and Evidence Custodians: every case.
  * A user whose only role is Investigator: the cases assigned to them.
    Other cases answer 404, so their existence is not revealed.

Changes (edit, status, investigators, closure)
  * Administrators, or the case's lead investigator.
  * Never on a Closed case (the database trigger also enforces this).

Creating cases: Administrators and Investigators. An investigator who
creates a case becomes its lead.

Evidence (Phase 9)
  * Visible exactly when its case is visible.
  * Register: Administrators and Evidence Custodians for any open case;
    Investigators for open cases they are assigned to.
  * Edit descriptive details: Administrators, Evidence Custodians, or the
    case's lead investigator, while the case is open.

Integrity and custody (Phase 10)
  * Verify a hash: Administrators, Evidence Custodians, or an investigator
    assigned to the case. Allowed on closed cases too (archived items can be
    re-checked).
  * Record the original hash: the same people, while the case is open and
    the item has no reference hash yet.
  * Correct a recorded hash or a custody entry: Administrators and Evidence
    Custodians only.
  * Custody transfers: Administrators and Evidence Custodians record any
    action; an assigned investigator may record Checked Out, Examined and
    Returned. Allowed after case closure, so items can be archived/released.
    sp_transfer_evidence enforces the same rules in MySQL.

Examinations and reports (Phase 11)
  * Create an examination: Administrators, or an investigator assigned to
    the (open) case. The examiner must be an investigator on the case.
  * Work on an examination (record notes, start, complete, cancel, link
    evidence): its examiner, the case lead or an Administrator, while it is
    Pending or In Progress and the case is open.
  * Write a report: Administrators or investigators assigned to the open
    case. Edit/submit: the author or an Administrator, while it is a Draft.
  * Approve or return a report: an Administrator who is NOT the author
    (independent review, also a CHECK constraint in MySQL).
  * Closed cases: examinations and reports become read-only (decision D3);
    PDFs can still be exported.

These checks run on the server for every request. The stored procedures
repeat the important ones, so a bypassed check in Python still fails in MySQL.
"""
from .auth.decorators import ADMIN, AUDITOR, CUSTODIAN, INVESTIGATOR

LAB_WIDE_ROLES = {ADMIN, AUDITOR, CUSTODIAN}


class Scope:
    """Which cases the current user may see.

    `case_filter` is an SQL fragment safe to append to a WHERE or JOIN ... ON
    clause where the cases table is aliased `c`. Its only value is passed as
    a query parameter (`params`), never formatted into the SQL text.
    """

    def __init__(self, user):
        roles = set(user["roles"])
        self.user_id = user["user_id"]
        self.lab_wide = bool(LAB_WIDE_ROLES & roles)
        self.sees_all_activity = bool({ADMIN, AUDITOR} & roles)
        if self.lab_wide:
            self.case_filter, self.params = "", ()
        else:
            self.case_filter = (" AND c.case_id IN (SELECT ci.case_id FROM case_investigators ci"
                                " WHERE ci.user_id = %s)")
            self.params = (self.user_id,)

    @property
    def label(self):
        return "All cases in the lab" if self.lab_wide else "Cases assigned to you"


def is_admin(user):
    return ADMIN in user["roles"]


def can_create_case(user):
    return bool({ADMIN, INVESTIGATOR} & set(user["roles"]))


def can_manage_case(user, case):
    """Edit, change status, manage investigators or close this case."""
    if case["status"] == "Closed":
        return False
    return is_admin(user) or case.get("lead_user_id") == user["user_id"]


def can_register_evidence(user):
    """May this user register evidence at all? (Which cases: see
    evidence.services.registrable_cases.)"""
    return bool({ADMIN, CUSTODIAN, INVESTIGATOR} & set(user["roles"]))


def registers_for_any_case(user):
    return bool({ADMIN, CUSTODIAN} & set(user["roles"]))


def can_edit_evidence(user, evidence):
    if evidence["case_status"] == "Closed":
        return False
    roles = set(user["roles"])
    return bool({ADMIN, CUSTODIAN} & roles) or evidence.get("lead_user_id") == user["user_id"]


INVESTIGATOR_CUSTODY_ACTIONS = ("Checked Out", "Examined", "Returned")


def _custody_staff(user):
    return bool({ADMIN, CUSTODIAN} & set(user["roles"]))


def can_verify_hash(user, item, assigned):
    return _custody_staff(user) or (INVESTIGATOR in user["roles"] and assigned)


def can_record_hash(user, item, assigned):
    return (item["case_status"] != "Closed" and not item.get("current_hash_value")
            and can_verify_hash(user, item, assigned))


def can_correct_records(user):
    """Correct a recorded hash or a custody entry."""
    return _custody_staff(user)


def custody_actions_for(user, assigned):
    """Which custody actions this user may record (before status rules)."""
    if _custody_staff(user):
        return None                                   # None = every action
    if INVESTIGATOR in user["roles"] and assigned:
        return INVESTIGATOR_CUSTODY_ACTIONS
    return ()


def can_create_examination(user, case, assigned):
    return case["status"] != "Closed" and (ADMIN in user["roles"] or (INVESTIGATOR in user["roles"] and assigned))


def can_work_on_examination(user, exam):
    if exam["status"] not in ("Pending", "In Progress") or exam["case_status"] == "Closed":
        return False
    return ADMIN in user["roles"] or user["user_id"] in (exam["examiner_id"], exam.get("lead_user_id"))


def can_write_report(user, case, assigned):
    return case["status"] != "Closed" and (ADMIN in user["roles"] or (INVESTIGATOR in user["roles"] and assigned))


def can_edit_report(user, report):
    return (report["status"] == "Draft" and report["case_status"] != "Closed"
            and (ADMIN in user["roles"] or user["user_id"] == report["author_id"]))


def can_review_report(user, report):
    return (report["status"] == "Under Review" and report["case_status"] != "Closed"
            and ADMIN in user["roles"] and user["user_id"] != report["author_id"])


def can_add_case_note(user, case, assigned):
    """Notes (FORGE-X 2.0): administrators, evidence custodians and the case's
    investigators may add notes while the case is open. Auditors only read."""
    if case["status"] == "Closed":
        return False
    roles = set(user["roles"])
    return bool({ADMIN, CUSTODIAN} & roles) or (INVESTIGATOR in roles and assigned)



def can_review_examination(user, exam):
    """FORGE-X 2.0 (U3): an examination Under Review is approved or returned by
    an Administrator or the case's lead investigator who is NOT the examiner
    (also CHECK chk_exam_independent in MySQL)."""
    if exam["status"] != "Under Review" or exam["case_status"] == "Closed":
        return False
    if user["user_id"] == exam["examiner_id"]:
        return False
    return ADMIN in user["roles"] or user["user_id"] == exam.get("lead_user_id")
