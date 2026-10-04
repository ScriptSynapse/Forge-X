# FORGE-X: Testing and Quality Review

This document explains how FORGE-X is tested, what each test proves, and what the Phase 14 review found and fixed. FORGE-X has **177 automated tests**, a **40-check SQL verification script**, and the manual acceptance checklist in section 5.

---

## 1. How to run the tests

Run everything from the project folder in Command Prompt, with `.venv` active.

| What | Command | Expected result |
|---|---|---|
| Configuration and database connection | `flask --app run check-db` | `All checks passed.` |
| All automated tests | `pytest -v` | About **147 passed, 30 skipped**; the exact split depends on your data |
| Database build verification | runs automatically at the end of `install_all.sql` | `failed 0` |
| Full SQL suite (needs the demo data) | runs automatically at the end of `install_demo.sql` | **40 / 40 PASS** |

**Skipped is not the same as passed.**
* **24 skips** are the opt-in tests that *write* to the database (section 2). They are skipped by design.
* **About 6 skips** are tests that check specific demo records when the demo data isn't installed. Their skip reason says so.
* **Any other skip** means MySQL wasn't reachable; the reason is printed.

**Opt-in write tests.** These add `pytest_*` users, cases and evidence, which can never be deleted, by design. Run them only on a separate test or demo installation:

```cmd
set FORGE_X_DB_WRITE_TESTS=1
pytest -m db_write -v
set FORGE_X_DB_WRITE_TESTS=
```

---

## 2. Test inventory

| Area | Offline (no MySQL) | Read-only database | Opt-in write (end to end) |
|---|---|---|---|
| Application factory, configuration, errors | `test_app.py` (15) | `test_db.py` (10) | |
| Authentication and sessions | `test_auth.py` (8) | | `test_auth_db.py` (10) |
| Dashboard | `test_dashboard.py` (6) | `test_dashboard_db.py` (6) | |
| Cases | `test_cases.py` (6) | `test_cases_db.py` (5) | `test_cases_write_db.py` (5) |
| Evidence | `test_evidence.py` (5) | `test_evidence_db.py` (7) | `test_evidence_write_db.py` (4) |
| Integrity and custody | `test_integrity.py` (7) | `test_custody_db.py` (3) | `test_integrity_custody_write_db.py` (2) |
| Examinations and reports, PDF | `test_exams_reports.py` (4) | `test_exams_reports_db.py` (4) | `test_exams_reports_write_db.py` (1, the full workflow) |
| Audit logs, users | `test_audit.py` (4) | `test_audit_db.py` (4) | `test_audit_write_db.py` (2) |
| Search and analytics | `test_search_analytics.py` (5) | `test_search_analytics_db.py` (10) | |
| Hosting behind Cloudflare | `test_proxy.py` (3) | | |
| **Whole-application security (Phase 14)** | `test_security.py` (7) | `test_privileges_db.py` (34) | |
| **Total: 177** | **70** | **83** | **24** |

**How the three kinds of test work:**
* **Offline tests** need no database. They cover rules, permissions, input parsing, hashing, PDF generation, security headers and the protection of every route.
* **Read-only database tests** compare every list, count and chart with an independent SQL query, and run every analytics query. They only ever SELECT, or attempt changes that are refused or match no rows.
* **Write tests** drive complete workflows through the real web pages. Examples:
  * register evidence → record a hash → verify it (Verified, then Failed) → correct it
  * transfer custody, including a refused stale transfer and the investigator restrictions
  * create an examination → complete it → write a report → revise → submit → independent approval → PDF export
  * auditor CSV export, which is itself audited

---

## 3. Security test matrix

| Threat | Control in FORGE-X | Proven by |
|---|---|---|
| SQL injection | Every value is a `%s` parameter. Sort orders and filters come from fixed lists | `test_db::test_parameterized_query_and_injection_attempt`; `test_security::test_sql_fstrings_only_interpolate_reviewed_fragments` (scans **all** code) |
| Unauthenticated access | `login_required` / `roles_required` on every non-public route | `test_security::test_every_non_public_route_requires_login` (checks **every** route automatically, including future ones) |
| Seeing another investigator's cases | Case-scoped queries; hidden records return 404 | `test_*_db::...investigator...`; `test_search_analytics_db::test_investigator_with_no_cases_sees_nothing` |
| Privilege escalation | Role checks in Flask **and** in stored procedures; self-assigned roles blocked by a CHECK constraint | `test_auth*`, `test_cases*`, `test_exams_reports::test_report_permissions_and_independent_review` |
| Cross-site request forgery | Flask-WTF CSRF token on every POST | `test_security::test_every_post_route_rejects_a_missing_csrf_token` (**every** POST route) |
| Cross-site scripting | Jinja autoescaping, never switched off; Content-Security-Policy | `test_security::test_templates_never_switch_off_escaping`, `test_security_headers`; PDF text escaping in `test_exams_reports` |
| Tampering with evidence history | Append-only triggers **and** no UPDATE/DELETE privilege for the app account | `test_privileges_db` (34 probes); `verify_demo.sql` E-tests |
| Database account misuse | Least-privilege `forge_x_app`: no DDL, no account management | `test_privileges_db::test_no_ddl_or_account_management`; `test_db::test_connected_as_application_account_not_root` |
| Password attacks | scrypt hashing; per-account and per-IP lockout stored in MySQL | `test_auth*`; security view in `test_audit_db` |
| Session theft or fixation | New session at login; HttpOnly, SameSite and (when hosted) Secure cookies; `session_version` logs out every session | `test_auth*`, `test_app` |
| Open redirect after login | Only local `next` URLs are followed | `test_auth` |
| Malicious uploads | Hashed in memory, never stored or executed; size and type limits | `test_integrity::test_bad_sample_files_are_refused` |
| Spreadsheet formula injection | CSV cells starting with `= + - @` are prefixed | `test_audit::test_csv_cells_cannot_become_formulas` |
| Leaking data through caches or search engines | `Cache-Control: no-store` on pages and JSON; `X-Robots-Tag: noindex` | `test_security::test_security_headers` |
| Downgrade to HTTP when hosted | HSTS, sent over HTTPS only | `test_security::test_security_headers[https]` |
| Faked visitor IP when hosted | `CF-Connecting-IP` trusted only when enabled, and only on 127.0.0.1 | `test_proxy` (3) |
| Secrets in the code | `.env` is git-ignored; no literal passwords or keys in `app/` | `test_security::test_secrets_are_not_shipped` |

---

## 4. Phase 14 review findings

| Review | Method | Result |
|---|---|---|
| **SQL built with f-strings** | Automatic scan of every f-string containing SQL in `app/` | **No injection path.** All 14 interpolated expressions are fixed SQL fragments with `%s` placeholders, validated choices or integers, or are not SQL at all (messages that contain the word "from"). This is now a permanent test. |
| **Route protection** | Anonymous GET and POST to every route | **All protected.** Only 6 endpoints are public: landing page, login, signup, signup confirmation, health check and static files. |
| **CSRF** | Code search, plus a test of every POST route with CSRF on | No exemptions anywhere. |
| **Database privileges** | 34 harmless privilege probes | Matches `app_user.sql` exactly. Each probe is designed to be harmless even if a privilege were wrongly granted. |
| **Accessibility** | Automated audit of **125 rendered pages**: one `<h1>`, labelled fields, unique ids, named buttons, image `alt` text | **No issues.** The auditor was checked against a deliberately broken page and found all five planted problems. |
| **HTTP headers** | Review of the response headers | **Fixed three gaps.** Chart and dashboard JSON now also get `no-store`; `X-Robots-Tag: noindex` added; HSTS added over HTTPS. |

**Known limitations:**
* Automated accessibility checks can't judge colour contrast or keyboard flow, so these are in the manual checklist below.
* There is no load testing. FORGE-X is sized for a single lab: Waitress runs one thread per pooled MySQL connection.
* The opt-in write tests add permanent `pytest_*` records, which is why they're off by default.

---

## 5. Manual acceptance checklist

Use your own accounts: one administrator (for example `paulson`) and one investigator. Tick each line when it behaves as expected.

**Accounts and access**
- [ ] A wrong password 5 times pauses login for that account; the Security view lists it as locked out.
- [ ] A new signup can't log in until an administrator approves it.
- [ ] The investigator gets **403** at `/admin/users` and `/audit-logs`, and both refusals appear in the audit log.
- [ ] After logout, the browser's Back button doesn't show case data.

**Cases and evidence (as the investigator, on their own case)**
- [ ] Register evidence; its custody timeline starts with **Collected**.
- [ ] Record a hash from a sample file, then verify it with the same file: **Verified**. A changed file gives **Failed**.
- [ ] Transfer custody: only valid actions are offered, and the investigator sees only Checked Out, Examined and Returned.

**Examinations and reports**
- [ ] Completing an examination without findings is refused.
- [ ] A report goes Draft → new version → Submit. The author has no Approve button.
- [ ] `paulson` approves it, and the PDF shows *Recorded observation* and *Examiner interpretation*, with no watermark. An older version's PDF shows **SUPERSEDED VERSION**.

**Integrity of history**
- [ ] Closing a case makes it read-only, and it can't be reopened.
- [ ] Audit log CSV export opens in Excel, and the export itself appears in the audit log.

**Usability and accessibility**
- [ ] Every page can be used with the **keyboard alone**: Tab, Shift+Tab, Enter and Space, with a visible focus outline.
- [ ] Pages work at 200% browser zoom and on a phone-width window.
- [ ] Search: a full evidence ID opens the item; 10 characters of a hash find it.
