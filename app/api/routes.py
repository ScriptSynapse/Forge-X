"""FORGE-X REST API, version 1 (FORGE-X 2.0 Phase 10). Read-only.

Authentication: the browser session, or `Authorization: Bearer fx_...` with a
personal token (Account -> API tokens). Every endpoint uses the same case
scope as the web pages (access.Scope), so a token sees exactly what its owner
sees in the browser. Changes stay in the web workflows, which enforce custody
rules, confirmations and independent review.

Each resource is serialised from a FIXED list of fields: internal values
(storage object ids, password hashes, settings) can never appear. Times are
ISO 8601 with the lab offset (DB_TIME_ZONE, +05:30 by default).

The OpenAPI document (/api/v1/openapi.json) is generated from the same
registry the routes are declared with (`endpoint()` below), and a test
checks that every /api/v1 route is documented and every documented path exists.
"""
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime
from decimal import Decimal

from flask import Blueprint, abort, current_app, g, jsonify, request, url_for

from .. import audit
from ..access import Scope
from ..auth.decorators import login_required
from ..auth.services import load_user
from ..db import query_all, query_value, set_audit_user
from ..pagination import parse_page
from . import tokens

bp = Blueprint("api", __name__, url_prefix="/api/v1")
SPEC = {}          # endpoint name -> OpenAPI operation details


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------
def error(status, title, message, headers=None):
    response = jsonify(status=status, error=title, message=message)
    response.status_code = status
    for key, value in (headers or {}).items():
        response.headers[key] = value
    return response


def _value(v):
    if isinstance(v, datetime):
        return v.replace(microsecond=0).isoformat() + current_app.config.get("DB_TIME_ZONE", "+05:30")
    if isinstance(v, date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return int(v) if v == v.to_integral_value() else float(v)
    if isinstance(v, bytes):
        return None
    return v


def pick(row, fields, bools=()):
    """Only the listed fields, converted to JSON-safe values. Missing fields are omitted."""
    out = {}
    for field in fields:
        if field in row:
            out[field] = bool(row[field]) if field in bools and row[field] is not None else _value(row[field])
    return out


def _per_page():
    try:
        return max(1, min(100, int(request.args.get("per_page", 25))))
    except ValueError:
        return 25


def paged(page, fields, bools=(), extra=None):
    items = [dict(pick(r, fields, bools), **(extra(r) if extra else {})) for r in page.items]
    return jsonify(data=items, page=page.page, per_page=page.per_page, total=page.total,
                   pages=max(1, -(-page.total // page.per_page)))


# ---------------------------------------------------------------------------
# Authentication and rate limiting
# ---------------------------------------------------------------------------
_LOCK = threading.Lock()
_HITS = defaultdict(deque)          # key -> request times in the last minute (per process)


def _prune(hits, now, window):
    while hits and hits[0] <= now - window:
        hits.popleft()


def _over_limit(key, limit, window=60.0):
    """Count this request; return seconds to wait if it exceeds `limit` per window, else 0."""
    now = time.monotonic()
    with _LOCK:
        hits = _HITS[key]
        _prune(hits, now, window)
        if len(hits) >= limit:
            return int(window - (now - hits[0])) + 1
        hits.append(now)
    return 0


def _blocked(key, limit, window=60.0):
    """Seconds to wait if `key` already reached `limit` (without counting this request)."""
    now = time.monotonic()
    with _LOCK:
        hits = _HITS[key]
        _prune(hits, now, window)
        return int(window - (now - hits[0])) + 1 if len(hits) >= limit else 0


def _note(key):
    with _LOCK:
        _HITS[key].append(time.monotonic())


def _client_ip():
    return request.headers.get("CF-Connecting-IP") if current_app.config.get("TRUST_CLOUDFLARE") else request.remote_addr


@bp.before_request
def authenticate():
    """Bearer token, if one is sent; otherwise the session (or 401 from login_required)."""
    header = request.headers.get("Authorization")
    if header is not None:
        challenge = {"WWW-Authenticate": 'Bearer realm="FORGE-X API"'}
        fail_key = f"api-fail:{_client_ip()}"
        wait = _blocked(fail_key, current_app.config.get("API_FAILED_AUTH_PER_MINUTE", 20))
        if wait:                                   # guessing tokens from this address: stop checking for a while
            return error(429, "Too many failed attempts", f"Try again in {wait} s.", {"Retry-After": str(wait)})
        scheme, _, raw = header.partition(" ")
        raw = raw.strip()
        if scheme.lower() != "bearer" or not raw:
            _note(fail_key)
            return error(401, "Invalid authorization", "Use: Authorization: Bearer <token>.", challenge)
        found = tokens.authenticate(raw)
        user = load_user(found[0]) if found else None
        if user is None or user["account_status"] != "Active":
            _note(fail_key)
            audit.record("api.auth_failed", "API token", tokens.prefix_of(raw), outcome="Denied", user_id=None,
                         details="Unknown, expired, revoked or inactive-account token")
            return error(401, "Invalid token", "The token is unknown, expired or revoked.", challenge)
        if user["must_change_password"]:
            return error(403, "Password change required", "Log in to the website and choose a new password first.")
        g.user, g.api_token_id = user, found[1]
        set_audit_user(user["user_id"])
        tokens.mark_used(found[1])
    if g.get("user") is not None:
        wait = _over_limit(f"api-user:{g.user['user_id']}", current_app.config.get("API_RATE_LIMIT_PER_MINUTE", 120))
        if wait:
            return error(429, "Too many requests", f"Rate limit reached. Try again in {wait} s.",
                         {"Retry-After": str(wait)})
    return None


# ---------------------------------------------------------------------------
# Declaring endpoints (one registry for routing and OpenAPI)
# ---------------------------------------------------------------------------
PAGE_PARAMS = [{"name": "page", "in": "query", "schema": {"type": "integer", "minimum": 1}},
               {"name": "per_page", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100}}]


def endpoint(rule, summary, schema, *, params=(), paged_list=False, tag="FORGE-X"):
    def decorate(view):
        name = view.__name__
        SPEC[name] = {"rule": rule, "summary": summary, "schema": schema, "params": list(params),
                      "paged": paged_list, "tag": tag, "doc": (view.__doc__ or "").strip()}
        return bp.get(rule)(login_required(view))
    return decorate


def q(name, description, enum=None, fmt=None):
    schema = {"type": "string"}
    if enum:
        schema["enum"] = list(enum)
    if fmt:
        schema["format"] = fmt
    return {"name": name, "in": "query", "description": description, "schema": schema}


def path_param(name, description):
    return {"name": name, "in": "path", "required": True, "description": description, "schema": {"type": "string"}}


# ---------------------------------------------------------------------------
# Field lists (the ONLY data the API returns)
# ---------------------------------------------------------------------------
CASE_LIST = ("case_reference", "title", "type_name", "priority", "status", "lead_name", "evidence_count",
             "due_date", "is_overdue", "created_at", "last_activity")
CASE_DETAIL = ("case_reference", "title", "description", "type_name", "priority", "status", "lead_name",
               "created_by_name", "due_date", "is_overdue", "created_at", "updated_at", "closed_at", "closure_summary")
EVIDENCE_LIST = ("evidence_code", "case_reference", "evidence_type", "description", "current_status",
                 "integrity_status", "current_hash", "has_file", "file_type", "exam_status", "collected_at",
                 "current_custodian", "current_location")
EVIDENCE_DETAIL = ("evidence_code", "case_reference", "type_name", "description", "source_details", "size_bytes",
                   "collection_site", "collection_condition", "collected_at", "collected_by_name", "registered_at",
                   "seal_number", "current_status", "current_custodian_name", "current_location_name",
                   "integrity_status", "current_hash_value", "last_verified_at")
STORED_FILE = ("original_name", "media_type", "size_bytes", "sha256", "stored_at", "backend")
CUSTODY_ENTRY = ("custody_id", "action", "occurred_at", "recorded_at", "from_name", "to_name", "location",
                 "evidence_condition", "seal_number", "reason", "corrects_custody_id", "recorded_by_name")
CUSTODY_EVENT = ("kind", "event_id", "event", "occurred_at", "recorded_at", "evidence_code", "case_reference",
                 "from_name", "to_name", "location", "evidence_condition", "details", "result",
                 "corrects_custody_id", "actor_name")
EXAM_LIST = ("examination_code", "case_reference", "type_name", "status", "examiner_name", "due_date",
             "is_overdue", "started_at", "completed_at", "evidence_count")
EXAM_DETAIL = ("examination_code", "case_reference", "type_name", "status", "examiner_name", "due_date",
               "started_at", "submitted_at", "completed_at", "reviewer_name", "reviewed_at", "tools_methods",
               "observations", "findings", "conclusion", "limitations", "cancel_reason")
ARTIFACT = ("artifact_id", "artifact_type", "description", "location", "sha256", "evidence_code",
            "corrects_artifact_id", "recorded_at", "recorded_by_name")
REPORT_LIST = ("report_code", "title", "status", "case_reference", "author_name", "version_no", "updated_at")
REPORT_DETAIL = ("report_code", "title", "status", "case_reference", "author_name", "approver_name",
                 "approved_at", "created_at", "updated_at")
VERSION = ("version_no", "change_note", "created_at", "created_by_name")
INDICATOR = ("kind", "value", "detail", "evidence_code", "case_reference", "source", "observed_at")


def _schema(fields, bools=()):
    props = {}
    for f in fields:
        if f in bools or f.startswith(("is_", "has_")):
            props[f] = {"type": "boolean"}
        elif f.endswith(("_at", "_date")) and f != "due_date":
            props[f] = {"type": "string", "format": "date-time"}
        elif f == "due_date":
            props[f] = {"type": "string", "format": "date"}
        elif f.endswith(("_id", "_count", "_no", "_bytes")):
            props[f] = {"type": "integer"}
        else:
            props[f] = {"type": "string"}
    return {"type": "object", "properties": props}


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------
@endpoint("/me", "The signed-in user and their access", "Me")
def me():
    """Who the request is authenticated as, and what they can see."""
    scope = Scope(g.user)
    return jsonify(data={"username": g.user["username"], "full_name": g.user["full_name"], "roles": g.user["roles"],
                         "scope": scope.label, "authenticated_by": "token" if g.get("api_token_id") else "session"})


@endpoint("/cases", "List cases", "Case", paged_list=True, params=[
    q("q", "Search reference or title"), q("status", "Case status or 'active'"),
    q("priority", "Priority or 'urgent'"), q("investigator", "Investigator user id"),
    q("from", "Registered on or after", fmt="date"), q("to", "Registered on or before", fmt="date"),
    q("overdue", "1 = only overdue cases"), q("sort", "Column, '-' prefix for descending")])
def cases():
    """Cases visible to the user, with the same filters as the case list page."""
    from ..cases import services
    page = services.list_cases(Scope(g.user), services.CaseFilters.from_args(request.args),
                               parse_page(request.args.get("page")), _per_page())
    return paged(page, CASE_LIST, bools=("is_overdue",),
                 extra=lambda r: {"url": url_for("api.case", reference=r["case_reference"], _external=False)})


@endpoint("/cases/<reference>", "One case", "Case", params=[path_param("reference", "e.g. FX-2026-0002")])
def case(reference):
    """A case, its investigators and the codes of its evidence, examinations and reports."""
    from ..cases import services
    found = services.get_case(Scope(g.user), reference.upper())
    if found is None:
        abort(404)
    cid = found["case_id"]
    data = pick(found, CASE_DETAIL, bools=("is_overdue",))
    data["investigators"] = [{"full_name": r["full_name"], "is_lead": bool(r["is_lead"])} for r in query_all(
        "SELECT u.full_name, ci.is_lead FROM case_investigators ci JOIN users u ON u.user_id = ci.user_id "
        "WHERE ci.case_id = %s ORDER BY ci.is_lead DESC, u.full_name", (cid,))]
    data["evidence"] = [r["evidence_code"] for r in query_all(
        "SELECT evidence_code FROM evidence WHERE case_id = %s ORDER BY evidence_code", (cid,))]
    data["examinations"] = [r["examination_code"] for r in query_all(
        "SELECT examination_code FROM examinations WHERE case_id = %s ORDER BY examination_code", (cid,))]
    data["reports"] = [r["report_code"] for r in query_all(
        "SELECT report_code FROM forensic_reports WHERE case_id = %s ORDER BY report_code", (cid,))]
    return jsonify(data=data)


@endpoint("/evidence", "List evidence", "Evidence", paged_list=True, params=[
    q("q", "Search evidence ID or description"), q("case", "Case reference"), q("status", "Custody status"),
    q("integrity", "Verified, Failed, Pending or Not Verified"), q("investigator", "Investigator user id"),
    q("from", "Collected on or after", fmt="date"), q("to", "Collected on or before", fmt="date"),
    q("file", "yes / no: has a stored file"), q("sort", "Column, '-' prefix for descending")])
def evidence_list():
    """Evidence items in visible cases, with the Evidence Vault filters."""
    from ..evidence import services
    page = services.list_evidence(Scope(g.user), services.EvidenceFilters.from_args(request.args),
                                  parse_page(request.args.get("page")), _per_page())
    return paged(page, EVIDENCE_LIST, bools=("has_file",))


def _evidence(code):
    from ..evidence import services
    item = services.get_evidence(Scope(g.user), code.upper())
    if item is None:
        abort(404)
    return item


@endpoint("/evidence/<code>", "One evidence item", "Evidence", params=[path_param("code", "e.g. FX-EV-2026-00001")])
def evidence(code):
    """Metadata, integrity and stored-file details. The file's content is never returned by the API."""
    from ..evidence import files
    item = _evidence(code)
    data = pick(item, EVIDENCE_DETAIL)
    stored = files.get_file(item["evidence_id"])
    data["stored_file"] = pick(stored, STORED_FILE) if stored else None
    return jsonify(data=data)


@endpoint("/evidence/<code>/custody", "Chain of custody of one item", "Custody", params=[
    path_param("code", "e.g. FX-EV-2026-00001")])
def evidence_custody(code):
    """Every custody entry of the item, oldest first. Entries are append-only; corrections are linked entries."""
    from ..evidence import services
    item = _evidence(code)
    return jsonify(data=[pick(e, CUSTODY_ENTRY) for e in services.custody_timeline(item["evidence_id"])])


@endpoint("/chain-of-custody", "Custody and integrity-check events", "Custody", paged_list=True, params=[
    q("q", "Evidence ID (or part of it)"), q("case", "Case reference"),
    q("action", "A custody action, or 'Integrity check'"), q("person", "User id of anyone involved"),
    q("from", "On or after", fmt="date"), q("to", "On or before", fmt="date"),
    q("order", "newest (default) or oldest", enum=("newest", "oldest"))])
def chain_of_custody():
    """The lab-wide (or assigned-case) custody log: custody entries and integrity checks."""
    from ..custody import services
    page = services.custody_log(Scope(g.user), services.CustodyFilters.from_args(request.args),
                                parse_page(request.args.get("page")), _per_page())
    return paged(page, CUSTODY_EVENT)


@endpoint("/examinations", "List examinations", "Examination", paged_list=True, params=[
    q("status", "Pending, In Progress, Under Review, Completed or Cancelled"), q("case", "Case reference"),
    q("type", "Examination type id"), q("mine", "1 = only mine"), q("overdue", "1 = only overdue")])
def examinations():
    """Examinations in visible cases."""
    from ..examinations import services
    page = services.list_examinations(Scope(g.user), services.ExamFilters.from_args(request.args), g.user["user_id"],
                                      parse_page(request.args.get("page")), _per_page())
    return paged(page, EXAM_LIST, bools=("is_overdue",))


@endpoint("/examinations/<code>", "One examination", "Examination", params=[path_param("code", "e.g. EX-2026-0001")])
def examination(code):
    """The examination record, the evidence it examined, and its artifacts."""
    from ..examinations import services
    exam = services.get_examination(Scope(g.user), code.upper())
    if exam is None:
        abort(404)
    data = pick(exam, EXAM_DETAIL)
    data["evidence"] = [e["evidence_code"] for e in services.linked_evidence(exam["examination_id"])]
    data["artifacts"] = [pick(a, ARTIFACT) for a in services.artifacts(exam["examination_id"])]
    return jsonify(data=data)


@endpoint("/reports", "List reports", "Report", paged_list=True, params=[
    q("status", "Draft, Under Review or Approved"), q("case", "Case reference")])
def reports():
    """Forensic reports in visible cases."""
    from ..reports import services
    page = services.list_reports(Scope(g.user), services.ReportFilters.from_args(request.args),
                                 parse_page(request.args.get("page")), _per_page())
    return paged(page, REPORT_LIST)


@endpoint("/reports/<code>", "One report", "Report", params=[path_param("code", "e.g. RP-2026-0001")])
def report(code):
    """Report metadata, its version history and the examinations it cites. The PDF stays on the website."""
    from ..reports import services
    found = services.get_report(Scope(g.user), code.upper())
    if found is None:
        abort(404)
    data = pick(found, REPORT_DETAIL)
    data["versions"] = [pick(v, VERSION) for v in services.versions(found["report_id"])]
    data["examinations"] = [r["examination_code"] for r in query_all(
        "SELECT x.examination_code FROM report_examinations re JOIN examinations x ON x.examination_id = re.examination_id "
        "WHERE re.report_id = %s ORDER BY x.examination_code", (found["report_id"],))]
    return jsonify(data=data)


INDICATOR_SQL = """
SELECT * FROM (
  SELECT 'yara_match' AS kind, m.rule_identifier AS value, CONCAT('Rule ', r.name, ' v', v.version_no) AS detail,
         e.evidence_code, c.case_reference, CONCAT('YARA scan #', s.scan_id) AS source, s.finished_at AS observed_at
    FROM yara_scans s
    JOIN yara_matches m       ON m.scan_id = s.scan_id
    JOIN yara_rule_versions v ON v.version_id = m.version_id
    JOIN yara_rules r         ON r.rule_id = v.rule_id
    JOIN evidence e           ON e.evidence_id = s.evidence_id
    JOIN cases c              ON c.case_id = e.case_id
   WHERE s.status = 'Completed'
     AND s.scan_id = (SELECT MAX(s2.scan_id) FROM yara_scans s2 WHERE s2.evidence_id = s.evidence_id AND s2.status = 'Completed')
     {scope}
  UNION ALL
  SELECT CASE WHEN a.artifact_type = 'Network indicator' THEN 'network' ELSE 'sha256' END AS kind,
         CASE WHEN a.artifact_type = 'Network indicator' THEN a.description ELSE a.sha256 END AS value,
         CONCAT(a.artifact_type, ': ', a.description) AS detail,
         e.evidence_code, c.case_reference, CONCAT('Artifact #', a.artifact_id, ' in ', x.examination_code) AS source,
         a.recorded_at AS observed_at
    FROM examination_artifacts a
    JOIN examinations x ON x.examination_id = a.examination_id
    JOIN cases c        ON c.case_id = x.case_id
    LEFT JOIN evidence e ON e.evidence_id = a.evidence_id
   WHERE (a.sha256 IS NOT NULL OR a.artifact_type = 'Network indicator')
     {scope}
) t WHERE (%s = '' OR t.case_reference = %s) AND (%s = '' OR t.kind = %s)
"""
INDICATOR_KINDS = ("yara_match", "sha256", "network")


@endpoint("/indicators", "Recorded indicators", "Indicator", paged_list=True, params=[
    q("case", "Case reference"), q("kind", "yara_match, sha256 or network", enum=INDICATOR_KINDS)])
def indicators():
    """Indicators recorded in FORGE-X: matches from each item's latest completed YARA scan, artifact SHA-256
    values, and artifacts recorded as network indicators. Nothing is inferred. A match is an indicator for an
    examiner, not a conclusion."""
    scope = Scope(g.user)
    case_ref = (request.args.get("case") or "").strip().upper()[:12]
    kind = request.args.get("kind") if request.args.get("kind") in INDICATOR_KINDS else ""
    # The only text inserted is Scope.case_filter, a fixed fragment whose value is a %s parameter.
    indicator_sql = INDICATOR_SQL.replace("{scope}", scope.case_filter)
    params = scope.params * 2 + (case_ref, case_ref, kind, kind)
    per_page, page = _per_page(), parse_page(request.args.get("page"))
    total = query_value(f"SELECT COUNT(*) FROM ({indicator_sql}) n", params)
    pages = max(1, -(-total // per_page))
    page = min(page, pages)
    rows = query_all(indicator_sql + " ORDER BY t.observed_at DESC, t.value LIMIT %s OFFSET %s",
                     params + (per_page, (page - 1) * per_page))
    return jsonify(data=[pick(r, INDICATOR) for r in rows], page=page, per_page=per_page, total=total, pages=pages)


@bp.get("/openapi.json")
@login_required
def openapi():
    from .openapi import build
    return jsonify(build())
