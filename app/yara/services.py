"""YARA rule library and evidence scans (FORGE-X 2.0 Phase 7).

All YARA work (validating a rule, scanning a file) happens in a separate,
restricted worker process (runner.py / worker.py); this module only stores
and reads records. Rule versions, scans and matches are append-only. A scan
is recorded only after the worker actually ran: "Completed" means YARA-X
finished successfully; otherwise Failed / Timed out / Memory limit with
the worker's reason.
"""
import hashlib
import json
import time

from flask import current_app

from .. import audit
from ..access import ADMIN
from ..db import query_all, query_one, query_value, transaction
from ..storage import StorageError, storage_for
from . import runner

SCOPES = ("All cases", "Selected cases")
STATUS_FOR_ERROR = {"timeout": "Timed out", "memory": "Memory limit"}
_PING = {"at": 0.0, "result": None}


class YaraError(Exception):
    """A refused YARA action; the message is safe to show."""


def _limits():
    cfg = current_app.config
    return int(cfg.get("YARA_TIMEOUT_SECONDS", 60)), int(cfg.get("YARA_MEMORY_MB", 512))


def availability(max_age=60):
    """Ask a worker whether YARA-X is installed (cached briefly)."""
    if _PING["result"] is None or time.monotonic() - _PING["at"] > max_age:
        timeout, memory = _limits()
        _PING["result"], _PING["at"] = runner.run_worker({"mode": "ping"}, timeout=min(timeout, 20), memory_mb=memory), \
            time.monotonic()
    return _PING["result"]


def can_manage(user):
    return ADMIN in user["roles"]


# ---------------------------------------------------------------------------
# Rule library
# ---------------------------------------------------------------------------
def list_rules():
    return query_all(
        """
        SELECT r.rule_id, r.name, r.description, r.author, r.scope, r.is_enabled, r.updated_at,
               (SELECT MAX(v.version_no) FROM yara_rule_versions v WHERE v.rule_id = r.rule_id) AS current_version,
               (SELECT COUNT(*) FROM yara_rule_cases rc WHERE rc.rule_id = r.rule_id) AS case_count
          FROM yara_rules r ORDER BY r.is_enabled DESC, r.name
        """)


def get_rule(rule_id):
    return query_one("SELECT r.*, u.full_name AS created_by_name FROM yara_rules r JOIN users u ON u.user_id = r.created_by "
                     "WHERE r.rule_id = %s", (rule_id,))


def versions(rule_id):
    return query_all("SELECT v.version_id, v.version_no, v.source, v.source_sha256, v.change_note, v.created_at, "
                     "u.full_name AS created_by_name FROM yara_rule_versions v JOIN users u ON u.user_id = v.created_by "
                     "WHERE v.rule_id = %s ORDER BY v.version_no DESC", (rule_id,))


def rule_cases(rule_id):
    return query_all("SELECT c.case_id, c.case_reference, c.title, c.status FROM yara_rule_cases rc "
                     "JOIN cases c ON c.case_id = rc.case_id WHERE rc.rule_id = %s ORDER BY c.case_reference", (rule_id,))


def open_cases():
    return query_all("SELECT case_id, case_reference, title FROM cases WHERE status <> 'Closed' ORDER BY case_reference DESC")


def rule_scan_count(rule_id):
    return query_value("SELECT COUNT(DISTINCT sr.scan_id) FROM yara_scan_rules sr JOIN yara_rule_versions v "
                       "ON v.version_id = sr.version_id WHERE v.rule_id = %s", (rule_id,))


def validate(source):
    """Compile a rule in the worker. Returns warnings; raises YaraError."""
    if not source or not source.strip():
        raise YaraError("Paste the rule source.")
    max_kb = int(current_app.config.get("YARA_MAX_RULE_KB", 256))
    if len(source.encode("utf-8")) > max_kb * 1024:
        raise YaraError(f"Rule sources are limited to {max_kb} KB.")
    timeout, memory = _limits()
    result = runner.run_worker({"mode": "validate", "source": source}, timeout=min(timeout, 30), memory_mb=memory)
    if not result.get("ok"):
        prefix = "The rule doesn't compile: " if result.get("error_type") == "compile" else ""
        raise YaraError(prefix + result.get("error", "Validation failed."))
    return result.get("warnings", [])


def _sha(source):
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def create_rule(user, name, description, author, scope, source):
    if not can_manage(user):
        raise YaraError("Only administrators manage the YARA rule library.")
    if scope not in SCOPES:
        raise YaraError("Choose a scope.")
    warnings = validate(source)
    if query_value("SELECT COUNT(*) FROM yara_rules WHERE name = %s", (name,)):
        raise YaraError("A rule with that name already exists.")
    with transaction() as cur:
        cur.execute("INSERT INTO yara_rules (name, description, author, scope, created_by) VALUES (%s, %s, %s, %s, %s)",
                    (name, description or None, author or None, scope, user["user_id"]))
        rule_id = cur.lastrowid
        cur.execute("INSERT INTO yara_rule_versions (rule_id, version_no, source, source_sha256, change_note, created_by) "
                    "VALUES (%s, 1, %s, %s, 'First version', %s)", (rule_id, source, _sha(source), user["user_id"]))
        audit.record("yara.rule_create", "YARA rule", name, cursor=cur, details=f"Version 1, scope {scope}")
    return rule_id, warnings


def new_version(rule_id, user, source, change_note):
    """Save a new immutable version (earlier versions stay, and scans keep pointing at them)."""
    if not can_manage(user):
        raise YaraError("Only administrators manage the YARA rule library.")
    if not change_note or len(change_note.strip()) < 3:
        raise YaraError("Say what changed in this version.")
    warnings = validate(source)
    with transaction() as cur:
        cur.execute("SELECT name FROM yara_rules WHERE rule_id = %s FOR UPDATE", (rule_id,))
        rule = cur.fetchone()
        if rule is None:
            raise YaraError("Rule not found.")
        cur.execute("SELECT version_no, source_sha256 FROM yara_rule_versions WHERE rule_id = %s "
                    "ORDER BY version_no DESC LIMIT 1", (rule_id,))
        latest = cur.fetchone()
        if latest["source_sha256"] == _sha(source):
            raise YaraError("The source is identical to the current version.")
        number = latest["version_no"] + 1
        cur.execute("INSERT INTO yara_rule_versions (rule_id, version_no, source, source_sha256, change_note, created_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s)", (rule_id, number, source, _sha(source), change_note.strip()[:255],
                                                        user["user_id"]))
        cur.execute("UPDATE yara_rules SET updated_at = NOW() WHERE rule_id = %s", (rule_id,))
        audit.record("yara.rule_version", "YARA rule", rule["name"], cursor=cur,
                     details=f"Version {number}: {change_note.strip()[:300]}")
    return number, warnings


def _update_rule(rule_id, user, sql, params, action, details):
    if not can_manage(user):
        raise YaraError("Only administrators manage the YARA rule library.")
    with transaction() as cur:
        cur.execute("SELECT name FROM yara_rules WHERE rule_id = %s FOR UPDATE", (rule_id,))
        rule = cur.fetchone()
        if rule is None:
            raise YaraError("Rule not found.")
        cur.execute(sql, params)
        audit.record(action, "YARA rule", rule["name"], cursor=cur, details=details)


def set_enabled(rule_id, user, enabled):
    _update_rule(rule_id, user, "UPDATE yara_rules SET is_enabled = %s WHERE rule_id = %s", (bool(enabled), rule_id),
                 "yara.rule_enable" if enabled else "yara.rule_disable", "Enabled" if enabled else "Disabled")


def set_scope(rule_id, user, scope):
    if scope not in SCOPES:
        raise YaraError("Choose a scope.")
    _update_rule(rule_id, user, "UPDATE yara_rules SET scope = %s WHERE rule_id = %s", (scope, rule_id),
                 "yara.rule_scope", f"Scope: {scope}")


def add_case(rule_id, user, case_id):
    reference = query_value("SELECT case_reference FROM cases WHERE case_id = %s AND status <> 'Closed'", (case_id,))
    if reference is None:
        raise YaraError("Choose an open case.")
    if query_value("SELECT COUNT(*) FROM yara_rule_cases WHERE rule_id = %s AND case_id = %s", (rule_id, case_id)):
        raise YaraError("The rule is already associated with that case.")
    _update_rule(rule_id, user, "INSERT INTO yara_rule_cases (rule_id, case_id, added_by) VALUES (%s, %s, %s)",
                 (rule_id, case_id, user["user_id"]), "yara.rule_case_add", f"Associated with {reference}")


def remove_case(rule_id, user, case_id):
    reference = query_value("SELECT case_reference FROM cases WHERE case_id = %s", (case_id,))
    _update_rule(rule_id, user, "DELETE FROM yara_rule_cases WHERE rule_id = %s AND case_id = %s", (rule_id, case_id),
                 "yara.rule_case_remove", f"No longer associated with {reference}")


# ---------------------------------------------------------------------------
# Scans
# ---------------------------------------------------------------------------
def applicable_versions(case_id):
    """The latest version of every enabled rule that applies to this case."""
    return query_all(
        """
        SELECT r.rule_id, r.name, v.version_id, v.version_no, v.source
          FROM yara_rules r
          JOIN yara_rule_versions v ON v.rule_id = r.rule_id
         WHERE r.is_enabled = TRUE
           AND v.version_no = (SELECT MAX(v2.version_no) FROM yara_rule_versions v2 WHERE v2.rule_id = r.rule_id)
           AND (r.scope = 'All cases'
                OR EXISTS (SELECT 1 FROM yara_rule_cases rc WHERE rc.rule_id = r.rule_id AND rc.case_id = %s))
         ORDER BY r.name
        """, (case_id,))


def run_scan(item, stored_file, user):
    """Scan the item's stored file with every applicable rule, in the worker.
    Records the scan (and matches) only after the worker ran. Returns scan_id."""
    if item["case_status"] == "Closed":
        raise YaraError("Closed cases are read-only.")
    rules = applicable_versions(item["case_id"])
    if not rules:
        raise YaraError("No enabled YARA rules apply to this case. Add or enable a rule first.")
    namespaces = {f"r{r['rule_id']}v{r['version_no']}": r for r in rules}
    timeout, memory = _limits()
    started = query_value("SELECT NOW()")
    try:
        # Local files are scanned in place; objects in S3 are downloaded to a
        # read-only temporary copy that is deleted after the scan.
        with storage_for(stored_file).materialize(stored_file["object_id"]) as path:
            result = runner.run_worker({"mode": "scan", "path": path,
                                        "sources": {ns: r["source"] for ns, r in namespaces.items()}},
                                       timeout=timeout, memory_mb=memory)
    except (StorageError, OSError) as err:
        raise YaraError("The stored file isn't available in evidence storage.") from err
    if result.get("error_type") == "unavailable":
        raise YaraError(result["error"])                        # nothing ran, so nothing is recorded
    status = "Completed" if result.get("ok") else STATUS_FOR_ERROR.get(result.get("error_type"), "Failed")
    matches = result.get("matches", []) if status == "Completed" else []
    file_sha = result.get("file_sha256")
    with transaction() as cur:
        cur.execute(
            "INSERT INTO yara_scans (evidence_id, file_id, status, scanner_version, file_sha256, hash_matches, rules_count, "
            "matched_count, duration_ms, limits_note, error_message, requested_by, started_at, finished_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())",
            (item["evidence_id"], stored_file["file_id"], status, (result.get("scanner_version") or "")[:40] or None,
             file_sha, (file_sha == stored_file["sha256"]) if file_sha else None, len(rules), len(matches),
             result.get("duration_ms"), (result.get("limits") or "")[:255] or None,
             None if status == "Completed" else (result.get("error") or "The scan failed.")[:500],
             user["user_id"], started))
        scan_id = cur.lastrowid
        for r in rules:
            cur.execute("INSERT INTO yara_scan_rules (scan_id, version_id) VALUES (%s, %s)", (scan_id, r["version_id"]))
        for m in matches:
            rule = namespaces.get(m.get("namespace"))
            if rule is None:
                continue
            cur.execute("INSERT INTO yara_matches (scan_id, version_id, rule_identifier, tags, metadata_json, patterns_json) "
                        "VALUES (%s, %s, %s, %s, %s, %s)",
                        (scan_id, rule["version_id"], str(m.get("identifier"))[:128],
                         ", ".join(m.get("tags", []))[:500] or None,
                         json.dumps(m.get("metadata", []))[:60000], json.dumps(m.get("patterns", []))))
        audit.record("evidence.yara_scan", "Evidence", item["evidence_code"], cursor=cur,
                     outcome="Success" if status == "Completed" else "Failure",
                     details=(f"Scan #{scan_id}: {status}, {len(rules)} rules, {len(matches)} matched"
                              + ("" if file_sha is None or file_sha == stored_file["sha256"]
                                 else "; stored file no longer matches its recorded SHA-256"))[:500])
    return scan_id


def scans_for_evidence(evidence_id):
    return query_all("SELECT s.scan_id, s.status, s.rules_count, s.matched_count, s.hash_matches, s.started_at, "
                     "s.duration_ms, s.error_message, u.full_name AS requested_by_name FROM yara_scans s "
                     "JOIN users u ON u.user_id = s.requested_by WHERE s.evidence_id = %s "
                     "ORDER BY s.started_at DESC, s.scan_id DESC", (evidence_id,))


def get_scan(scope, scan_id):
    """A scan, only if its evidence is visible to the user (investigators: assigned cases)."""
    return query_one(
        f"""
        SELECT s.*, e.evidence_code, e.description, c.case_reference, c.case_id, f.original_name, f.sha256 AS stored_sha256,
               u.full_name AS requested_by_name
          FROM yara_scans s
          JOIN evidence e       ON e.evidence_id = s.evidence_id
          JOIN cases c          ON c.case_id = e.case_id
          JOIN evidence_files f ON f.file_id = s.file_id
          JOIN users u          ON u.user_id = s.requested_by
         WHERE s.scan_id = %s {scope.case_filter}
        """, (scan_id,) + scope.params)


def scan_rules(scan_id):
    return query_all("SELECT r.rule_id, r.name, v.version_no, v.source_sha256 FROM yara_scan_rules sr "
                     "JOIN yara_rule_versions v ON v.version_id = sr.version_id JOIN yara_rules r ON r.rule_id = v.rule_id "
                     "WHERE sr.scan_id = %s ORDER BY r.name", (scan_id,))


def scan_matches(scan_id):
    rows = query_all("SELECT m.match_id, m.rule_identifier, m.tags, m.metadata_json, m.patterns_json, r.rule_id, "
                     "r.name AS rule_name, v.version_no FROM yara_matches m JOIN yara_rule_versions v "
                     "ON v.version_id = m.version_id JOIN yara_rules r ON r.rule_id = v.rule_id "
                     "WHERE m.scan_id = %s ORDER BY r.name, m.rule_identifier", (scan_id,))
    for row in rows:
        row["metadata"] = json.loads(row.pop("metadata_json") or "[]")
        row["patterns"] = json.loads(row.pop("patterns_json") or "[]")
    return rows
