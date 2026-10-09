"""Chain of custody: the lab-wide log, transfers and corrections.

Transfers and corrections go through the stored procedures from Phase 4
(sp_transfer_evidence, sp_record_custody_correction). They lock the
evidence row, re-check the rules, append the custody entry, move the
evidence's current custodian/location/status and write the audit record in
ONE transaction. Custody entries are never edited or deleted.
"""
import re
from dataclasses import dataclass
from datetime import date

from ..access import INVESTIGATOR_CUSTODY_ACTIONS
from ..db import BusinessRuleError, ConstraintViolation, call_proc, query_all, query_one, query_value
from ..pagination import Page

ACTIONS = ("Collected", "Received", "Transferred", "Checked Out", "Examined",
           "Returned", "Stored", "Released", "Archived", "Exported")
# Event types in the custody log: every custody action, plus integrity checks
# (read from hash_verifications, never copied into chain_of_custody).
CHECK_EVENT = "Integrity check"
EVENT_TYPES = ACTIONS + (CHECK_EVENT,)
ORDERS = {"newest": "DESC", "oldest": "ASC"}

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
    q: str = ""                     # evidence ID (or part of it)
    case_reference: str = ""
    action: str = ""                # a custody action or CHECK_EVENT
    person_id: int = None           # anyone involved: from, to, recorded by, verified by
    date_from: date = None
    date_to: date = None
    order: str = "newest"

    @classmethod
    def from_args(cls, args):
        def parse(value):
            try:
                return date.fromisoformat(value) if value else None
            except ValueError:
                return None
        case_raw = (args.get("case") or "").strip().upper()
        return cls(q=(args.get("q") or "").strip().upper()[:20],
                   case_reference=case_raw if re.match(r"^FX-\d{4}-\d{4}$", case_raw) else "",
                   action=args.get("action") if args.get("action") in EVENT_TYPES else "",
                   person_id=int(args.get("person")) if (args.get("person") or "").isdigit() else None,
                   date_from=parse(args.get("from")), date_to=parse(args.get("to")),
                   order=args.get("order") if args.get("order") in ORDERS else "newest")

    def as_args(self):
        args = {"q": self.q, "case": self.case_reference, "action": self.action, "person": self.person_id or "",
                "from": self.date_from.isoformat() if self.date_from else "",
                "to": self.date_to.isoformat() if self.date_to else "",
                "order": self.order if self.order != "newest" else ""}
        return {k: v for k, v in args.items() if v}

    @property
    def active(self):
        return bool(self.q or self.case_reference or self.action or self.person_id or self.date_from or self.date_to)


_CUSTODY_BRANCH = """
    SELECT 'custody' AS kind, coc.custody_id AS event_id, coc.occurred_at AS occurred_at, coc.recorded_at,
           coc.action AS event, coc.evidence_condition, coc.corrects_custody_id, coc.reason AS details,
           CAST(NULL AS CHAR(20)) AS result, e.evidence_code, c.case_reference,
           fu.full_name AS from_name, tu.full_name AS to_name, ru.full_name AS actor_name,
           COALESCE(sl.location_name, coc.location_note) AS location
      FROM chain_of_custody coc
      JOIN evidence e                ON e.evidence_id = coc.evidence_id
      JOIN cases c                   ON c.case_id = e.case_id
      LEFT JOIN users fu             ON fu.user_id = coc.from_custodian_id
      JOIN users tu                  ON tu.user_id = coc.to_custodian_id
      JOIN users ru                  ON ru.user_id = coc.recorded_by
      LEFT JOIN storage_locations sl ON sl.location_id = coc.location_id
"""
_CHECK_BRANCH = """
    SELECT 'check' AS kind, hv.verification_id AS event_id, hv.verified_at AS occurred_at, hv.verified_at AS recorded_at,
           'Integrity check' AS event, NULL AS evidence_condition, NULL AS corrects_custody_id,
           CONCAT(hv.method, COALESCE(CONCAT(': ', hv.sample_file_name), '')) AS details,
           hv.result AS result, e.evidence_code, c.case_reference,
           NULL AS from_name, NULL AS to_name, vu.full_name AS actor_name, NULL AS location
      FROM hash_verifications hv
      JOIN evidence_hashes h ON h.hash_id = hv.hash_id
      JOIN evidence e        ON e.evidence_id = h.evidence_id
      JOIN cases c           ON c.case_id = e.case_id
      JOIN users vu          ON vu.user_id = hv.verified_by
"""


def _branch(kind, filters, scope):
    """One half of the event log with every filter applied inside it (so the
    indexes on each table are used). Returns (sql, params)."""
    time_col = "coc.occurred_at" if kind == "custody" else "hv.verified_at"
    where, params = ["1 = 1"], []
    if filters.q:
        where.append("e.evidence_code LIKE %s")
        params.append("%" + re.sub(r"[!%_]", "", filters.q) + "%")
    if filters.case_reference:
        where.append("c.case_reference = %s")
        params.append(filters.case_reference)
    if kind == "custody" and filters.action and filters.action != CHECK_EVENT:
        where.append("coc.action = %s")
        params.append(filters.action)
    if filters.person_id:
        if kind == "custody":
            where.append("(coc.from_custodian_id = %s OR coc.to_custodian_id = %s OR coc.recorded_by = %s)")
            params += [filters.person_id] * 3
        else:
            where.append("hv.verified_by = %s")
            params.append(filters.person_id)
    if filters.date_from:
        where.append(f"{time_col} >= %s")
        params.append(filters.date_from)
    if filters.date_to:
        where.append(f"{time_col} < %s + INTERVAL 1 DAY")
        params.append(filters.date_to)
    body = _CUSTODY_BRANCH if kind == "custody" else _CHECK_BRANCH
    return body + " WHERE " + " AND ".join(where) + scope.case_filter, tuple(params) + scope.params


def custody_log(scope, filters, page, per_page):
    """Custody entries and integrity checks in one chronological log."""
    kinds = ["custody", "check"]
    if filters.action == CHECK_EVENT:
        kinds = ["check"]
    elif filters.action:
        kinds = ["custody"]
    parts = [_branch(kind, filters, scope) for kind in kinds]
    union = " UNION ALL ".join(sql for sql, _ in parts)
    params = tuple(p for _, ps in parts for p in ps)
    total = query_value(f"SELECT COUNT(*) FROM ({union}) t", params)
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    direction = ORDERS[filters.order]
    rows = query_all(f"SELECT t.* FROM ({union}) t ORDER BY t.occurred_at {direction}, t.event_id {direction} "
                     "LIMIT %s OFFSET %s", params + (per_page, (page - 1) * per_page))
    return Page(items=rows, page=page, per_page=per_page, total=total)


def people_for_filter():
    return query_all("SELECT user_id, full_name FROM users ORDER BY full_name")


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
    The original entry is never changed. Export records (a copy was
    downloaded) aren't corrected: the download happened, and correcting it
    could move the original item."""
    if query_value("SELECT action FROM chain_of_custody WHERE custody_id = %s", (original_custody_id,)) == "Exported":
        raise CustodyError("Export records can't be corrected: they record a download that happened.")
    if not location_id and not location_note:
        raise CustodyError("Choose a location, or describe where the item actually was.")
    result = _call("sp_record_custody_correction", (
        original_custody_id, to_user_id, location_id or None,
        (location_note or None) if not location_id else None, condition, seal or None, reason, user_id, None))
    return result[8]           # OUT p_custody_id


