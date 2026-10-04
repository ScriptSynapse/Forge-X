"""Global search across the records a user may see.

* Exact IDs (FX-2026-0001, FX-EV-2026-00001, EX-..., RP-...) jump straight
  to the record when it is visible.
* 8 to 64 hexadecimal characters also search recorded SHA-256 hashes
  (current and superseded) by prefix, using index idx_hashes_value.
* Everything else is a case-insensitive "contains" search with LIKE
  wildcards escaped. Every value is a query parameter.
"""
import re

from ..db import query_all, query_value

MIN_LENGTH = 2
GROUP_LIMIT = 8

EXACT_PATTERNS = (
    (re.compile(r"^FX-EV-\d{4}-\d{5}$"), "evidence.detail", "code"),
    (re.compile(r"^FX-\d{4}-\d{4}$"), "cases.detail", "reference"),
    (re.compile(r"^EX-\d{4}-\d{4}$"), "examinations.detail", "code"),
    (re.compile(r"^RP-\d{4}-\d{4}$"), "reports.detail", "code"),
)
HEX_RE = re.compile(r"^[0-9a-f]{8,64}$")


def normalise(q):
    return " ".join((q or "").split())[:100]


def exact_target(q):
    """(endpoint, url_argument_name, value) when q is a complete record ID, else None."""
    upper = q.upper()
    for pattern, endpoint, arg in EXACT_PATTERNS:
        if pattern.match(upper):
            return endpoint, arg, upper
    return None


def looks_like_hash(q):
    return bool(HEX_RE.match(q.lower()))


def _like(text):
    return "%" + text.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"


def _group(count_sql, rows_sql, params):
    total = query_value(count_sql, params)
    rows = query_all(rows_sql + " LIMIT %s", params + (GROUP_LIMIT,)) if total else []
    return {"total": int(total or 0), "rows": rows}


def search(q, scope, include_users=False):
    pattern = _like(q)
    sp = scope.params
    results = {}

    where = "(c.case_reference LIKE %s ESCAPE '!' OR c.title LIKE %s ESCAPE '!' OR c.description LIKE %s ESCAPE '!')"
    params = (pattern,) * 3 + sp
    results["cases"] = _group(
        f"SELECT COUNT(*) FROM cases c WHERE {where} {scope.case_filter}",
        f"SELECT c.case_reference, c.title, c.status, c.priority FROM cases c WHERE {where} {scope.case_filter} "
        "ORDER BY c.created_at DESC", params)

    where = ("(e.evidence_code LIKE %s ESCAPE '!' OR e.description LIKE %s ESCAPE '!' "
             "OR e.source_details LIKE %s ESCAPE '!' OR e.collection_site LIKE %s ESCAPE '!')")
    params = (pattern,) * 4 + sp
    results["evidence"] = _group(
        f"SELECT COUNT(*) FROM evidence e JOIN cases c ON c.case_id = e.case_id WHERE {where} {scope.case_filter}",
        f"SELECT e.evidence_code, e.description, e.current_status, c.case_reference FROM evidence e "
        f"JOIN cases c ON c.case_id = e.case_id WHERE {where} {scope.case_filter} ORDER BY e.registered_at DESC", params)

    if looks_like_hash(q):
        params = (q.lower() + "%",) + sp            # prefix match uses the hash_value index
        results["hashes"] = _group(
            f"SELECT COUNT(*) FROM evidence_hashes h JOIN evidence e ON e.evidence_id = h.evidence_id "
            f"JOIN cases c ON c.case_id = e.case_id WHERE h.hash_value LIKE %s {scope.case_filter}",
            f"SELECT h.hash_id, h.hash_value, h.recorded_at, e.evidence_code, e.description, "
            f"EXISTS (SELECT 1 FROM evidence_hashes s WHERE s.supersedes_hash_id = h.hash_id) AS superseded "
            f"FROM evidence_hashes h JOIN evidence e ON e.evidence_id = h.evidence_id "
            f"JOIN cases c ON c.case_id = e.case_id WHERE h.hash_value LIKE %s {scope.case_filter} "
            f"ORDER BY h.recorded_at DESC", params)

    where = "(x.examination_code LIKE %s ESCAPE '!' OR xt.type_name LIKE %s ESCAPE '!' OR x.findings LIKE %s ESCAPE '!')"
    params = (pattern,) * 3 + sp
    results["examinations"] = _group(
        f"SELECT COUNT(*) FROM examinations x JOIN examination_types xt ON xt.examination_type_id = x.examination_type_id "
        f"JOIN cases c ON c.case_id = x.case_id WHERE {where} {scope.case_filter}",
        f"SELECT x.examination_code, xt.type_name, x.status, c.case_reference FROM examinations x "
        f"JOIN examination_types xt ON xt.examination_type_id = x.examination_type_id "
        f"JOIN cases c ON c.case_id = x.case_id WHERE {where} {scope.case_filter} ORDER BY x.created_at DESC", params)

    where = "(r.report_code LIKE %s ESCAPE '!' OR r.title LIKE %s ESCAPE '!')"
    params = (pattern,) * 2 + sp
    results["reports"] = _group(
        f"SELECT COUNT(*) FROM forensic_reports r JOIN cases c ON c.case_id = r.case_id WHERE {where} {scope.case_filter}",
        f"SELECT r.report_code, r.title, r.status, c.case_reference FROM forensic_reports r "
        f"JOIN cases c ON c.case_id = r.case_id WHERE {where} {scope.case_filter} ORDER BY r.updated_at DESC", params)

    if include_users:
        where = "(u.full_name LIKE %s ESCAPE '!' OR u.username LIKE %s ESCAPE '!' OR u.email LIKE %s ESCAPE '!')"
        results["users"] = _group(
            f"SELECT COUNT(*) FROM users u WHERE {where}",
            f"SELECT u.user_id, u.full_name, u.username, u.account_status FROM users u WHERE {where} ORDER BY u.full_name",
            (pattern,) * 3)
    return results
