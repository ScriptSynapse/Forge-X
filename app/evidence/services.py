"""Evidence registry business logic. FORGE-X stores evidence METADATA and
hashes only, never the evidence files themselves."""
import re
from dataclasses import dataclass

from .. import audit
from ..access import can_edit_evidence, registers_for_any_case
from ..db import BusinessRuleError, ConstraintViolation, call_proc, query_all, query_one, query_value, transaction
from ..pagination import Page

EVIDENCE_STATUSES = ("In Transit", "In Storage", "Checked Out", "Under Examination", "Released", "Archived")
INTEGRITY_STATUSES = ("Verified", "Failed", "Pending", "Not Verified")
HASH_SOURCES = (("Computed", "Computed at acquisition (tool output)"),
                ("Manual", "Copied from another record (notes required)"))
CASE_REF_RE = re.compile(r"^FX-\d{4}-\d{4}$")
HASH_RE = re.compile(r"^[0-9a-f]{64}$")

SORTS = {
    "newest": ("Newest collected first", "v.collected_at DESC, v.evidence_id DESC"),
    "oldest": ("Oldest collected first", "v.collected_at ASC, v.evidence_id ASC"),
    "code":   ("Evidence ID", "v.evidence_code ASC"),
}


class EvidenceActionError(Exception):
    """A refused evidence action, with a message that is safe to display."""


def normalise_hash(value):
    """Trim and lower-case a pasted SHA-256; return None when empty."""
    value = (value or "").strip().lower()
    return value or None


def is_valid_sha256(value):
    return bool(value) and bool(HASH_RE.match(value))


def like_pattern(text):
    return "%" + text.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


# ---------------------------------------------------------------------------
# Registry list
# ---------------------------------------------------------------------------
@dataclass
class EvidenceFilters:
    q: str = ""
    evidence_type_id: int = None
    status: str = ""
    integrity: str = ""
    case_reference: str = ""
    sort: str = "newest"

    @classmethod
    def from_args(cls, args):
        type_raw = args.get("type", "")
        case_raw = (args.get("case") or "").strip().upper()
        return cls(
            q=(args.get("q") or "").strip()[:100],
            evidence_type_id=int(type_raw) if type_raw.isdigit() else None,
            status=args.get("status") if args.get("status") in EVIDENCE_STATUSES else "",
            integrity=args.get("integrity") if args.get("integrity") in INTEGRITY_STATUSES else "",
            case_reference=case_raw if CASE_REF_RE.match(case_raw) else "",
            sort=args.get("sort") if args.get("sort") in SORTS else "newest",
        )

    def as_args(self):
        args = {"q": self.q, "type": self.evidence_type_id or "", "status": self.status,
                "integrity": self.integrity, "case": self.case_reference,
                "sort": self.sort if self.sort != "newest" else ""}
        return {k: v for k, v in args.items() if v}

    @property
    def active(self):
        return bool(self.q or self.evidence_type_id or self.status or self.integrity or self.case_reference)


def list_evidence(scope, filters, page, per_page):
    where, params = ["1 = 1"], []
    if filters.q:
        where.append("(v.evidence_code LIKE %s ESCAPE '!' OR v.description LIKE %s ESCAPE '!')")
        params += [like_pattern(filters.q)] * 2
    if filters.evidence_type_id:
        where.append("e.evidence_type_id = %s")
        params.append(filters.evidence_type_id)
    if filters.status:
        where.append("v.current_status = %s")
        params.append(filters.status)
    if filters.integrity:
        where.append("v.integrity_status = %s")
        params.append(filters.integrity)
    if filters.case_reference:
        where.append("v.case_reference = %s")
        params.append(filters.case_reference)
    condition = " AND ".join(where) + scope.case_filter
    all_params = tuple(params) + scope.params
    base = """
        FROM v_evidence_overview v
        JOIN evidence e ON e.evidence_id = v.evidence_id
        JOIN cases c    ON c.case_id = v.case_id
    """
    total = query_value(f"SELECT COUNT(*) {base} WHERE {condition}", all_params)
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    rows = query_all(
        f"SELECT v.*, c.status AS case_status {base} WHERE {condition} "
        f"ORDER BY {SORTS[filters.sort][1]} LIMIT %s OFFSET %s",
        all_params + (per_page, (page - 1) * per_page),
    )
    return Page(items=rows, page=page, per_page=per_page, total=total)


def status_counts(scope):
    rows = query_all(f"SELECT e.current_status, COUNT(*) AS n FROM evidence e JOIN cases c ON c.case_id = e.case_id "
                     f"WHERE 1 = 1 {scope.case_filter} GROUP BY e.current_status", scope.params)
    found = {r["current_status"]: int(r["n"]) for r in rows}
    return {s: found.get(s, 0) for s in EVIDENCE_STATUSES}


def evidence_types(include_inactive=False):
    sql = "SELECT evidence_type_id, type_name, description FROM evidence_types"
    if not include_inactive:
        sql += " WHERE is_active = TRUE"
    return query_all(sql + " ORDER BY type_name")


def visible_case_refs(scope):
    return query_all(f"SELECT c.case_reference, c.title FROM cases c WHERE 1 = 1 {scope.case_filter} "
                     "ORDER BY c.case_reference DESC", scope.params)


def registrable_cases(user):
    """Open cases this user may add evidence to."""
    if registers_for_any_case(user):
        return query_all("SELECT case_id, case_reference, title FROM cases WHERE status <> 'Closed' "
                         "ORDER BY case_reference DESC")
    return query_all(
        "SELECT c.case_id, c.case_reference, c.title FROM cases c "
        "JOIN case_investigators ci ON ci.case_id = c.case_id AND ci.user_id = %s "
        "WHERE c.status <> 'Closed' ORDER BY c.case_reference DESC",
        (user["user_id"],),
    )


def active_users():
    return query_all("SELECT user_id, full_name FROM users WHERE account_status = 'Active' ORDER BY full_name")


# ---------------------------------------------------------------------------
# One evidence item
# ---------------------------------------------------------------------------
def get_evidence(scope, code):
    """The item, or None if it doesn't exist OR the user may not see its case."""
    return query_one(
        f"""
        SELECT e.*, et.type_name, et.description AS type_description,
               c.case_reference, c.title AS case_title, c.status AS case_status,
               ci.user_id AS lead_user_id,
               col.full_name AS collected_by_name,
               cu.full_name  AS custodian_name,
               sl.location_name, sl.location_type,
               vi.integrity_status, vi.current_hash_value, vi.last_verified_at
          FROM evidence e
          JOIN evidence_types et          ON et.evidence_type_id = e.evidence_type_id
          JOIN cases c                    ON c.case_id = e.case_id
          LEFT JOIN case_investigators ci ON ci.case_id = c.case_id AND ci.is_lead = TRUE
          JOIN users col                  ON col.user_id = e.collected_by
          JOIN users cu                   ON cu.user_id = e.current_custodian_id
          LEFT JOIN storage_locations sl  ON sl.location_id = e.current_location_id
          JOIN v_evidence_integrity vi    ON vi.evidence_id = e.evidence_id
         WHERE e.evidence_code = %s {scope.case_filter}
        """,
        (code,) + scope.params,
    )


def custody_timeline(evidence_id):
    """Every custody entry, oldest first. Corrections are linked both ways:
    a correction shows which entry it corrects, and the original shows
    which entries corrected it (the original itself is never changed)."""
    rows = query_all(
        """
        SELECT coc.custody_id, coc.action, coc.occurred_at, coc.recorded_at, coc.evidence_condition,
               coc.seal_number, coc.reason, coc.corrects_custody_id,
               fu.full_name AS from_name, tu.full_name AS to_name, ru.full_name AS recorded_by_name,
               COALESCE(sl.location_name, coc.location_note) AS location
          FROM chain_of_custody coc
          LEFT JOIN users fu             ON fu.user_id = coc.from_custodian_id
          JOIN users tu                  ON tu.user_id = coc.to_custodian_id
          JOIN users ru                  ON ru.user_id = coc.recorded_by
          LEFT JOIN storage_locations sl ON sl.location_id = coc.location_id
         WHERE coc.evidence_id = %s
         ORDER BY coc.occurred_at, coc.custody_id
        """,
        (evidence_id,),
    )
    corrected_by = {}
    for row in rows:
        if row["corrects_custody_id"]:
            corrected_by.setdefault(row["corrects_custody_id"], []).append(row["custody_id"])
    for position, row in enumerate(rows, start=1):
        row["step"] = position
        row["corrected_by"] = corrected_by.get(row["custody_id"], [])
        row["is_current"] = position == len(rows)
    return rows


def hash_history(evidence_id):
    return query_all(
        """
        SELECT h.hash_id, h.algorithm, h.hash_value, h.source, h.source_notes, h.recorded_at,
               h.supersedes_hash_id, h.correction_reason, u.full_name AS recorded_by_name,
               EXISTS (SELECT 1 FROM evidence_hashes s WHERE s.supersedes_hash_id = h.hash_id) AS superseded
          FROM evidence_hashes h
          JOIN users u ON u.user_id = h.recorded_by
         WHERE h.evidence_id = %s
         ORDER BY h.recorded_at, h.hash_id
        """,
        (evidence_id,),
    )


def verification_history(evidence_id):
    return query_all(
        """
        SELECT hv.verification_id, hv.hash_id, hv.result, hv.method, hv.sample_file_name, hv.notes,
               hv.verified_at, u.full_name AS verified_by_name
          FROM hash_verifications hv
          JOIN evidence_hashes h ON h.hash_id = hv.hash_id
          JOIN users u           ON u.user_id = hv.verified_by
         WHERE h.evidence_id = %s
         ORDER BY hv.verified_at DESC, hv.verification_id DESC
        """,
        (evidence_id,),
    )


def evidence_examinations(evidence_id):
    return query_all(
        "SELECT v.* FROM v_examination_summary v JOIN examination_evidence ee ON ee.examination_id = v.examination_id "
        "WHERE ee.evidence_id = %s ORDER BY v.examination_code DESC",
        (evidence_id,),
    )


def tab_counts(evidence_id):
    row = query_one(
        """
        SELECT (SELECT COUNT(*) FROM evidence_hashes WHERE evidence_id = %s) AS hashes,
               (SELECT COUNT(*) FROM chain_of_custody WHERE evidence_id = %s) AS custody,
               (SELECT COUNT(*) FROM examination_evidence WHERE evidence_id = %s) AS examinations
        """,
        (evidence_id,) * 3,
    )
    return {k: int(v) for k, v in row.items()}


# ---------------------------------------------------------------------------
# Changes
# ---------------------------------------------------------------------------
def register_evidence(user, case_id, evidence_type_id, description, source_details, size_bytes,
                      collected_at, collected_by, collection_site, condition, seal_number,
                      hash_value, hash_source, hash_notes):
    """sp_register_evidence: evidence row, its ID, the first custody entry
    (Collected) and the optional original hash, in one transaction."""
    allowed = {c["case_id"] for c in registrable_cases(user)}
    if case_id not in allowed:
        raise EvidenceActionError("You can't register evidence for that case.")
    if query_value("SELECT %s > NOW()", (collected_at,)):
        raise EvidenceActionError("The collection time can't be in the future.")
    if hash_value is not None and not is_valid_sha256(hash_value):
        raise EvidenceActionError("A SHA-256 hash is exactly 64 hexadecimal characters.")
    if hash_value is not None and hash_source == "Manual" and not hash_notes:
        raise EvidenceActionError("Say where a manually entered hash was copied from.")
    try:
        result = call_proc("sp_register_evidence", (
            case_id, evidence_type_id, description, source_details or None, size_bytes,
            collected_at, collected_by, collection_site, condition, seal_number or None,
            hash_value, hash_source if hash_value else None, (hash_notes or None) if hash_value else None,
            user["user_id"], None, None))
    except BusinessRuleError as err:
        raise EvidenceActionError(err.user_message) from err
    except ConstraintViolation as err:
        raise EvidenceActionError("The database refused these details (" + (err.constraint or "constraint")
                                  + "). Check the values and try again.") from err
    return result[15]       # OUT p_evidence_code


def version_of(evidence):
    return evidence["updated_at"].isoformat() if evidence.get("updated_at") else ""


def update_evidence(user, evidence_id, description, source_details, size_bytes, collection_site, expected_version):
    """Edit the descriptive details. Collection time, collector, condition at
    collection, custody and hashes are part of the forensic record and are
    never edited here. Refuses lost updates (optimistic concurrency)."""
    with transaction() as cur:
        cur.execute(
            """
            SELECT e.evidence_id, e.evidence_code, e.description, e.source_details, e.size_bytes,
                   e.collection_site, e.updated_at, c.status AS case_status, ci.user_id AS lead_user_id
              FROM evidence e
              JOIN cases c ON c.case_id = e.case_id
              LEFT JOIN case_investigators ci ON ci.case_id = c.case_id AND ci.is_lead = TRUE
             WHERE e.evidence_id = %s
               FOR UPDATE
            """,
            (evidence_id,),
        )
        current = cur.fetchone()
        if current is None:
            raise EvidenceActionError("Evidence item not found.")
        if not can_edit_evidence(user, current):
            raise EvidenceActionError("You can't edit this item. Its case may be closed.")
        if version_of(current) != expected_version:
            raise EvidenceActionError("This item was changed by someone else while you were editing "
                                      "(for example, a custody transfer). Reload and try again.")
        new = {"description": description, "source_details": source_details or None,
               "size_bytes": size_bytes, "collection_site": collection_site}
        changes = [name.replace("_", " ") for name, value in new.items() if value != current[name]]
        if not changes:
            return False
        cur.execute(
            "UPDATE evidence SET description = %s, source_details = %s, size_bytes = %s, collection_site = %s "
            "WHERE evidence_id = %s",
            (description, new["source_details"], size_bytes, collection_site, evidence_id),
        )
        audit.record("evidence.update", "Evidence", current["evidence_code"], cursor=cur,
                     details="Changed: " + ", ".join(changes))
    return True
