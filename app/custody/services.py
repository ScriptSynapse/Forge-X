"""Chain of custody: the lab-wide log, transfers and corrections.

Transfers and corrections go through the stored procedures from Phase 4
(sp_transfer_evidence, sp_record_custody_correction). They lock the
evidence row, re-check the rules, append the custody entry, move the
evidence's current custodian/location/status and write the audit record in
ONE transaction. Custody entries are never edited or deleted.
"""
from dataclasses import dataclass
from datetime import date

from ..access import INVESTIGATOR_CUSTODY_ACTIONS
from ..db import BusinessRuleError, ConstraintViolation, call_proc, query_all, query_one, query_value
from ..pagination import Page

ACTIONS = ("Collected", "Received", "Transferred", "Checked Out", "Examined",
           "Returned", "Stored", "Released", "Archived")

# Which actions are allowed from each evidence status (mirrors sp_transfer_evidence).
ALLOWED_FROM = {
    "In Transit":        ("Received", "Transferred", "Stored"),
    "In Storage":        ("Transferred", "Checked Out", "Stored", "Released", "Archived"),
    "Checked Out":       ("Received", "Transferred", "Examined", "Returned", "Stored"),
    "Under Examination": ("Transferred", "Examined", "Returned"),
    "Released":          ("Archived",),
    "Archived":          (),
}
# The status each action leads to (Transferred keeps the current status).
RESULTING_STATUS = {
    "Received": "In Storage", "Stored": "In Storage", "Returned": "In Storage",
    "Checked Out": "Checked Out", "Examined": "Under Examination",
    "Released": "Released", "Archived": "Archived",
}
NEEDS_STORAGE_LOCATION = {a for a, s in RESULTING_STATUS.items() if s == "In Storage"}


class CustodyError(Exception):
    """A refused custody action, with a message that is safe to display."""


def allowed_actions(status, user_actions=None):
    """Actions valid from `status`, limited to `user_actions` (None = all)."""
    actions = ALLOWED_FROM.get(status, ())
    if user_actions is not None:
        actions = tuple(a for a in actions if a in user_actions)
    return actions


def resulting_status(action, current_status):
    return RESULTING_STATUS.get(action, current_status)


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
@dataclass
class CustodyFilters:
    q: str = ""
    action: str = ""
    date_from: date = None
    date_to: date = None

    @classmethod
    def from_args(cls, args):
        def parse(value):
            try:
                return date.fromisoformat(value) if value else None
            except ValueError:
                return None
        return cls(q=(args.get("q") or "").strip().upper()[:20],
                   action=args.get("action") if args.get("action") in ACTIONS else "",
                   date_from=parse(args.get("from")), date_to=parse(args.get("to")))

    def as_args(self):
        args = {"q": self.q, "action": self.action,
                "from": self.date_from.isoformat() if self.date_from else "",
                "to": self.date_to.isoformat() if self.date_to else ""}
        return {k: v for k, v in args.items() if v}

    @property
    def active(self):
        return bool(self.q or self.action or self.date_from or self.date_to)


def custody_log(scope, filters, page, per_page):
    where, params = ["1 = 1"], []
    if filters.q:
        where.append("e.evidence_code LIKE %s")
        params.append("%" + filters.q.replace("!", "").replace("%", "").replace("_", "") + "%")
    if filters.action:
        where.append("coc.action = %s")
        params.append(filters.action)
    if filters.date_from:
        where.append("coc.occurred_at >= %s")
        params.append(filters.date_from)
    if filters.date_to:
        where.append("coc.occurred_at < %s + INTERVAL 1 DAY")
        params.append(filters.date_to)
    condition = " AND ".join(where) + scope.case_filter
    all_params = tuple(params) + scope.params
    base = """
        FROM chain_of_custody coc
        JOIN evidence e ON e.evidence_id = coc.evidence_id
        JOIN cases c    ON c.case_id = e.case_id
    """
    total = query_value(f"SELECT COUNT(*) {base} WHERE {condition}", all_params)
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    rows = query_all(
        f"""
        SELECT coc.custody_id, coc.occurred_at, coc.recorded_at, coc.action, coc.evidence_condition,
               coc.corrects_custody_id, e.evidence_code, c.case_reference,
               fu.full_name AS from_name, tu.full_name AS to_name, ru.full_name AS recorded_by_name,
               COALESCE(sl.location_name, coc.location_note) AS location
          {base}
          LEFT JOIN users fu             ON fu.user_id = coc.from_custodian_id
          JOIN users tu                  ON tu.user_id = coc.to_custodian_id
          JOIN users ru                  ON ru.user_id = coc.recorded_by
          LEFT JOIN storage_locations sl ON sl.location_id = coc.location_id
         WHERE {condition}
         ORDER BY coc.occurred_at DESC, coc.custody_id DESC
         LIMIT %s OFFSET %s
        """,
        all_params + (per_page, (page - 1) * per_page),
    )
    return Page(items=rows, page=page, per_page=per_page, total=total)


def out_of_storage(scope):
    """Items checked out or in transit: the 'pending transfers' on the dashboard."""
    return query_all(
        f"""
        SELECT e.evidence_code, e.current_status, c.case_reference, u.full_name AS custodian_name,
               COALESCE(sl.location_name, '—') AS location_name,
               (SELECT MAX(coc.occurred_at) FROM chain_of_custody coc WHERE coc.evidence_id = e.evidence_id) AS since
          FROM evidence e
          JOIN cases c ON c.case_id = e.case_id
          JOIN users u ON u.user_id = e.current_custodian_id
          LEFT JOIN storage_locations sl ON sl.location_id = e.current_location_id
         WHERE e.current_status IN ('Checked Out', 'In Transit') {scope.case_filter}
         ORDER BY since
        """,
        scope.params,
    )


def active_users():
    return query_all("SELECT user_id, full_name FROM users WHERE account_status = 'Active' ORDER BY full_name")


def active_locations():
    return query_all("SELECT location_id, location_name, location_type FROM storage_locations "
                     "WHERE is_active = TRUE ORDER BY location_type, location_name")


def latest_entry_time(evidence_id):
    return query_value("SELECT MAX(occurred_at) FROM chain_of_custody WHERE evidence_id = %s", (evidence_id,))


def get_entry(evidence_id, custody_id):
    return query_one(
        """
        SELECT coc.*, fu.full_name AS from_name, tu.full_name AS to_name, ru.full_name AS recorded_by_name,
               COALESCE(sl.location_name, coc.location_note) AS location
          FROM chain_of_custody coc
          LEFT JOIN users fu             ON fu.user_id = coc.from_custodian_id
          JOIN users tu                  ON tu.user_id = coc.to_custodian_id
          JOIN users ru                  ON ru.user_id = coc.recorded_by
          LEFT JOIN storage_locations sl ON sl.location_id = coc.location_id
         WHERE coc.custody_id = %s AND coc.evidence_id = %s
        """,
        (custody_id, evidence_id),
    )


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------
def _call(name, args):
    try:
        return call_proc(name, args)
    except BusinessRuleError as err:
        raise CustodyError(err.user_message) from err
    except ConstraintViolation as err:
        raise CustodyError("The database refused this entry (" + (err.constraint or "constraint") + ").") from err


def transfer(item, user_id, expected_custodian_id, action, to_user_id, location_id, location_note,
             condition, seal, reason, occurred_at):
    """Append a custody entry and move the item (sp_transfer_evidence).
    `expected_custodian_id` is the custodian shown when the form was opened:
    if someone else moved the item meanwhile, the procedure refuses."""
    if action in NEEDS_STORAGE_LOCATION and not location_id:
        raise CustodyError(f"Choose the storage location the item goes to for '{action}'.")
    if not location_id and not location_note:
        raise CustodyError("Choose a location, or describe where the item is going.")
    if occurred_at is not None:
        if query_value("SELECT %s > NOW()", (occurred_at,)):
            raise CustodyError("The time of the handover can't be in the future.")
        latest = latest_entry_time(item["evidence_id"])
        if latest and occurred_at < latest:
            raise CustodyError(f"The handover can't be earlier than the last custody entry ({latest:%d %b %Y %H:%M}).")
    result = _call("sp_transfer_evidence", (
        item["evidence_id"], expected_custodian_id, action, to_user_id, location_id or None,
        (location_note or None) if not location_id else None, condition, seal or None, reason,
        occurred_at, user_id, None))
    return result[11]          # OUT p_custody_id


def correct_entry(original_custody_id, user_id, to_user_id, location_id, location_note, condition, seal, reason):
    """Append a correction linked to an earlier entry (sp_record_custody_correction).
    The original entry is never changed."""
    if not location_id and not location_note:
        raise CustodyError("Choose a location, or describe where the item actually was.")
    result = _call("sp_record_custody_correction", (
        original_custody_id, to_user_id, location_id or None,
        (location_note or None) if not location_id else None, condition, seal or None, reason, user_id, None))
    return result[8]           # OUT p_custody_id


