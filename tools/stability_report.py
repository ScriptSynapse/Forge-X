"""Generate docs/CORE_STABILITY_REPORT.md from a REAL test run (FORGE-X 2.0 Phase 6).

Runs `flask check-db` and the whole pytest suite on this machine, then writes
the report from what actually happened: counts per area, every failure and
skip with its reason, the 12-step end-to-end workflow, the security and
database checklists mapped to tests, and the pytest warnings. Nothing in the
results section is typed by hand.

    python tools\\stability_report.py                      read-only tests (any database)
    set MYSQL_DATABASE=forge_x_test
    python tools\\stability_report.py --with-write-tests   also the workflow tests (TEST database only)
"""
import argparse
import datetime
import os
import platform
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from importlib import metadata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPORT = os.path.join(ROOT, "docs", "CORE_STABILITY_REPORT.md")
JUNIT = os.path.join(ROOT, "build", "pytest-results.xml")
REAL_DB = "forge_x_db"

AREAS = [   # (label, test-file prefixes)
    ("Application, configuration, tools", ("test_app", "test_db", "test_tools")),
    ("Authentication and sessions", ("test_auth",)),
    ("Dashboard and lists", ("test_dashboard", "test_ui_phase1", "test_lists")),
    ("Case management", ("test_cases",)),
    ("Evidence and stored files", ("test_evidence", "test_storage")),
    ("Integrity and chain of custody", ("test_integrity", "test_custody")),
    ("Examinations and reports", ("test_exams",)),
    ("Audit logs and users", ("test_audit", "test_people")),
    ("Search and analytics", ("test_search",)),
    ("Hosting", ("test_proxy",)),
    ("Whole-application security", ("test_security", "test_privileges")),
    ("Database structure and consistency", ("test_schema", "test_data_consistency")),
    ("YARA scanning (Phase 7)", ("test_yara",)),
    ("Relationship graph (Phase 8)", ("test_graph",)),
    ("REST API (Phase 10)", ("test_api",)),
    ("Deployment and CI (Phase 11)", ("test_deploy",)),
    ("End-to-end core workflow", ("test_core_workflow",)),
]

SECURITY = [   # (requirement from the Phase 6 plan, test-name fragments that prove it)
    ("Unauthorised access", ["test_every_non_public_route_requires_login", "test_non_admin_is_denied_and_audited"]),
    ("Role-based permissions", ["test_only_an_independent_reviewer_can_approve", "test_who_can_download_and_attach",
                                "test_investigator_cannot_register_for_unassigned_case", "test_investigator_cannot_delete_cases"]),
    ("CSRF protection", ["test_every_post_route_rejects_a_missing_csrf_token", "test_csrf_token_required_when_enabled"]),
    ("Input validation", ["test_filters_ignore_unknown_values", "test_case_group_filters_and_column_sorts",
                          "test_event_types_and_filter_parsing"]),
    ("SQL injection resistance", ["test_sql_fstrings_only_interpolate_reviewed_fragments",
                                  "test_parameterized_query_and_injection_attempt",
                                  "test_every_filter_combination_builds_safe_sql"]),
    ("Upload validation", ["test_refused_uploads_leave_nothing_behind", "test_crafted_identifiers_are_refused",
                           "test_large_uploads_are_refused_outside_the_evidence_routes", "test_bad_sample_files_are_refused"]),
    ("File download permissions", ["test_who_can_download_and_attach", "test_store_download_verify_and_detect_tampering"]),
    ("Evidence hash mismatch handling", ["test_tampering_on_disk_is_detected_by_rehashing",
                                         "test_store_download_verify_and_detect_tampering", "test_mismatched_hash_and_attach"]),
    ("YARA worker isolation and limits", ["test_worker_environment_has_no_secrets_and_ignores_pythonpath",
                                          "test_runaway_worker_is_killed", "test_memory_hungry_worker_is_killed",
                                          "test_real_yara_x_compiles_scans_and_refuses_includes"]),
    ("API authentication, scope and rate limits", ["test_bad_credentials_get_401_json_with_a_challenge",
                                                   "test_every_endpoint_uses_the_callers_case_scope",
                                                   "test_failed_attempts_are_rate_limited_per_address",
                                                   "test_investigators_only_see_their_cases_through_the_api",
                                                   "test_token_lifecycle"]),
    ("Graph scoping (no records from invisible cases)", ["test_investigators_cannot_graph_cases_outside_their_assignments",
                                                         "test_every_graph_query_has_matching_parameters_and_is_scoped",
                                                         "test_malformed_node_ids_are_refused_without_queries"]),
    ("Session invalidation", ["test_logout_invalidates_a_copied_session_cookie", "test_deactivated_account_cannot_log_in"]),
    ("Database transaction consistency", ["test_transaction_rolls_back_on_error", "test_custody_transfers_and_correction",
                                          "test_current_custody_matches_the_latest_entry"]),
]

DATABASE = [
    ("Foreign keys and structure", ["test_every_table_and_column_exists", "test_schema_objects_present"]),
    ("Stored procedures", ["test_procedure_rule_becomes_business_rule_error", "test_core_workflow_end_to_end"]),
    ("Triggers", ["test_triggers_are_active", "test_completed_examinations_are_final",
                  "test_trigger_refuses_notes_on_a_closed_case", "test_append_only_tables_cannot_be_updated"]),
    ("Data consistency", ["test_current_custody_matches_the_latest_entry", "test_corrections_stay_on_their_own_record",
                          "test_stored_files_match_a_recorded_hash_and_exist", "test_code_counters_never_fall_behind"]),
    ("Migration correctness", ["test_every_table_and_column_exists", "test_every_check_constraint_exists",
                               "test_migration_004_is_installed", "test_migration_005_is_installed",
                               "test_migration_006_and_export_entries_keep_custody_consistent",
                               "test_migration_007_is_installed"]),
    ("Rollback behaviour", ["test_transaction_rolls_back_on_error", "test_trigger_refuses_notes_on_a_closed_case",
                            "test_completion_requires_an_independent_review"]),
]

LIMITATIONS = [
    "The opt-in workflow tests are only included when the report is generated with --with-write-tests against a separate "
    "test database; otherwise they appear as skipped.",
    "Tests run against this machine's MySQL and storage only; no load or concurrency stress testing is included.",
    "Automated accessibility checks (run during development) don't judge colour contrast or keyboard flow; see the manual "
    "checklist in docs/TESTING.md.",
    "The read-only flag on stored files prevents accidental changes, not deliberate ones by an operating-system "
    "administrator; tampering is detected by re-hashing, not prevented.",
    "A MySQL administrator can bypass triggers and privileges; FORGE-X protects against ordinary use and application bugs.",
    "Times are stored in lab local time (IST, decision D1).",
]


def run(cmd, env):
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def parse_junit(path):
    tests = []
    root = ET.parse(path).getroot()
    for case in root.iter("testcase"):
        name, file = case.get("name"), (case.get("classname") or "").split(".")[-1]
        outcome, message = "passed", ""
        for tag in ("failure", "error", "skipped"):
            node = case.find(tag)
            if node is not None:
                outcome = {"failure": "failed", "error": "error", "skipped": "skipped"}[tag]
                message = (node.get("message") or (node.text or "")).strip().splitlines()[0][:300] if (
                    node.get("message") or node.text) else ""
                break
        tests.append({"file": file, "name": name, "outcome": outcome, "message": message})
    return tests


def area_of(file):
    for label, prefixes in AREAS:
        if file.startswith(prefixes):
            return label
    return "Other"


def status_for(tests, fragments):
    hits = [t for t in tests if any(t["name"].startswith(f) for f in fragments)]
    if not hits:
        return "⚪ no matching test found", []
    if any(t["outcome"] in ("failed", "error") for t in hits):
        return "❌ failing", hits
    if all(t["outcome"] == "skipped" for t in hits):
        return "⏭ skipped", hits
    return "✅ passing", hits


def versions():
    out = {"Python": platform.python_version(), "OS": f"{platform.system()} {platform.release()}"}
    for pkg in ("Flask", "Flask-WTF", "mysql-connector-python", "reportlab", "waitress", "pytest"):
        try:
            out[pkg] = metadata.version(pkg)
        except metadata.PackageNotFoundError:
            out[pkg] = "not installed"
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--with-write-tests", action="store_true",
                        help="also run the opt-in workflow tests (only against a separate test database)")
    args = parser.parse_args()
    env = dict(os.environ)
    database = env.get("MYSQL_DATABASE") or REAL_DB
    if args.with_write_tests:
        if database == REAL_DB:
            sys.exit("Refusing: the workflow tests add permanent records. Set MYSQL_DATABASE to your test database "
                     "(see tools/build_test_database.py) for this window first.")
        env["FORGE_X_DB_WRITE_TESTS"] = "1"
    else:
        env.pop("FORGE_X_DB_WRITE_TESTS", None)
    os.makedirs(os.path.dirname(JUNIT), exist_ok=True)

    print("Running flask check-db ...")
    db_code, db_output = run([sys.executable, "-m", "flask", "--app", "run", "check-db"], env)
    print("Running pytest (this takes a minute) ...")
    py_code, py_output = run([sys.executable, "-m", "pytest", "-q", "-rw", "-p", "no:cacheprovider",
                              f"--junitxml={JUNIT}"], env)
    if not os.path.exists(JUNIT):
        sys.exit("pytest produced no results file. Its output:\n" + py_output[-3000:])
    tests = parse_junit(JUNIT)
    counts = {k: sum(t["outcome"] == k for t in tests) for k in ("passed", "failed", "error", "skipped")}
    warnings = re.search(r"=+ warnings summary =+\n(.*?)(?:\n-- Docs|\n=+ )", py_output, re.S)
    warning_text = warnings.group(1).strip() if warnings else ""
    mysql_version = re.search(r"MySQL server version\D*([\d.]+)", db_output) or re.search(r"(8\.\d+\.\d+)", db_output)

    lines = ["# FORGE-X Core Stability Report", "",
             f"**Generated** {datetime.datetime.now():%d %b %Y %H:%M} by `tools/stability_report.py` from a real test run on "
             f"this machine. Re-run it after any change; don't edit the results by hand.", "",
             "## 1. Environment", "",
             "| Item | Value |", "|---|---|",
             f"| Database | `{database}`{' (test database)' if database != REAL_DB else ''} |",
             f"| MySQL server | {mysql_version.group(1) if mysql_version else 'see check-db output'} |",
             f"| Workflow tests | {'included (FORGE_X_DB_WRITE_TESTS=1)' if args.with_write_tests else 'not included (read-only run)'} |"]
    lines += [f"| {k} | {v} |" for k, v in versions().items()]

    verdict = "✅ **No failures.**" if not (counts["failed"] or counts["error"]) else \
        f"❌ **{counts['failed'] + counts['error']} failing tests** (section 6)."
    lines += ["", "## 2. Summary", "", verdict, "",
              "| Passed | Failed | Errors | Skipped | Total |", "|---|---|---|---|---|",
              f"| {counts['passed']} | {counts['failed']} | {counts['error']} | {counts['skipped']} | {len(tests)} |", "",
              f"`flask check-db`: {'✅ all checks passed' if db_code == 0 else '❌ reported problems (section 8)'}.", "",
              "### By area", "", "| Area | Passed | Failed | Skipped |", "|---|---|---|---|"]
    for label, _ in AREAS + [("Other", ())]:
        group = [t for t in tests if area_of(t["file"]) == label]
        if group:
            lines.append(f"| {label} | {sum(t['outcome'] == 'passed' for t in group)} | "
                         f"{sum(t['outcome'] in ('failed', 'error') for t in group)} | "
                         f"{sum(t['outcome'] == 'skipped' for t in group)} |")

    e2e = [t for t in tests if t["name"] == "test_core_workflow_end_to_end"]
    lines += ["", "## 3. End-to-end core workflow", "",
              "Authenticate → create case → assign investigator → register evidence → SHA-256 stored → verify integrity → "
              "review custody → create examination → record methodology and findings → complete (submit and independent "
              "approval) → examination report → review audit log.", ""]
    if not e2e:
        lines.append("⚪ The end-to-end test wasn't collected.")
    else:
        t = e2e[0]
        lines.append({"passed": "✅ **All 12 steps passed.**",
                      "skipped": "⏭ **Skipped**: run with `--with-write-tests` against a test database to include it."}.get(
            t["outcome"], f"❌ **Failed**: {t['message']}"))

    for title, checklist in (("4. Security testing", SECURITY), ("5. Database testing", DATABASE)):
        lines += ["", f"## {title}", "", "| Requirement | Status | Tests |", "|---|---|---|"]
        for requirement, fragments in checklist:
            status, hits = status_for(tests, fragments)
            names = ", ".join(sorted({f"`{h['name']}`" for h in hits})[:4]) or "—"
            lines.append(f"| {requirement} | {status} | {names} |")

    failing = [t for t in tests if t["outcome"] in ("failed", "error")]
    lines += ["", "## 6. Remaining defects (failing tests)", ""]
    lines += [f"- `{t['file']}::{t['name']}`: {t['message'] or 'see pytest output'}" for t in failing] or ["None."]

    skipped = {}
    for t in tests:
        if t["outcome"] == "skipped":
            skipped.setdefault(re.sub(r"^Skipped: ", "", t["message"]) or "no reason given", []).append(t["name"])
    lines += ["", "## 7. Skipped tests, by reason", ""]
    lines += [f"- **{len(names)}**: {reason}" for reason, names in sorted(skipped.items(), key=lambda kv: -len(kv[1]))] or ["None."]

    lines += ["", "## 8. flask check-db output", "", "```", db_output.strip()[-4000:], "```",
              "", "## 9. pytest warnings", ""]
    lines += (["```", warning_text[-4000:], "```"] if warning_text else ["None."])
    lines += ["", "## 10. Known limitations", ""] + [f"- {item}" for item in LIMITATIONS] + [""]

    with open(REPORT, "w", encoding="utf-8") as out:
        out.write("\n".join(lines))
    print(f"Wrote {os.path.relpath(REPORT, ROOT)}: {counts['passed']} passed, {counts['failed'] + counts['error']} "
          f"failed, {counts['skipped']} skipped.")
    sys.exit(1 if failing or db_code else 0)


if __name__ == "__main__":
    main()
