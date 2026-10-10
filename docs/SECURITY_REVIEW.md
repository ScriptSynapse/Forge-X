# FORGE-X Security Review (FORGE-X 2.0)

**Scope:** the FORGE-X application, its MySQL database, evidence storage, the YARA worker, the REST API, and the Docker and CI configuration.

**Method:**
* read the code and schema;
* map each threat to its controls and to the **tests** that demonstrate them;
* record what isn't covered.

**Honesty note:** FORGE-X is an academic project with synthetic data. This review is the authors' own. It hasn't been independently audited or penetration-tested, and nothing here means FORGE-X is fit for real casework.

## 1. Assets and threats

| Asset | Main threats |
|---|---|
| Evidence records and stored files | Alteration, deletion, silent replacement, unauthorised copying |
| Chain of custody and audit history | Rewriting history, gaps, untraced access |
| Case data | Disclosure to users without access; disclosure through the API, graph or search |
| Accounts and sessions | Password guessing, session theft or reuse, privilege escalation |
| Secrets (`FORGE_X_SECRET_KEY`, database and storage passwords, API tokens) | Leakage via code, images, logs or untrusted code |
| The server | Injection (SQL, HTML/JS, CSV formulas), malicious uploads, untrusted YARA rules, resource exhaustion |

## 2. Controls, and the evidence for them

| Threat | Controls | Evidence |
|---|---|---|
| **SQL injection** | `%s` parameters only; sort and filter values from fixed lists; every f-string in SQL reviewed | `test_security::test_sql_fstrings_only_interpolate_reviewed_fragments` (a code scan; it flagged every new query during the upgrade); filter tests; 192-combination custody SQL test |
| **Cross-site scripting** | Jinja autoescaping never switched off; strict CSP (scripts and styles from the server only, no inline styles); graph and API text inserted with `textContent` / JSON only | `test_security` (templates, no inline styles, headers); page checks with hostile text (`<script>`, `<img onerror>`) |
| **CSRF** | Flask-WTF token on every POST; SameSite=Lax cookies; API v1 is GET-only | `test_security::test_every_post_route_rejects_a_missing_csrf_token`, `test_api::test_api_v1_routes_are_get_only` |
| **Broken access control** | Every non-public route requires login; `access.Scope` limits investigators to assigned cases on pages, search, graph and API; hidden records return 404; permission checks repeated inside stored procedures; refusals audited | `test_security::test_every_non_public_route_requires_login`; per-module permission tests; `test_graph`, `test_api` (scope); `*_db` scope tests on real data |
| **Self-approval** | Reports and examinations need an independent reviewer: CHECK constraints plus the trigger `trg_exam_finalised` | `test_exams_phase5`, database probes, the end-to-end workflow test |
| **Password guessing** | scrypt hashes; lockout after 5 failures per account or 20 per address in 15 minutes; generic errors; equal timing | `test_auth`, `test_auth_db` |
| **Session theft or reuse** | Session reissued at login; `session_version` ends all sessions on logout, password change or deactivation; HttpOnly, Secure (when hosted), SameSite | `test_auth_db::test_logout_invalidates_a_copied_session_cookie` |
| **API token abuse** | Only SHA-256 stored; shown once; at most 90-day expiry; revocable; refused for inactive accounts; failed attempts limited per address and audited (prefix only); per-user rate limit | `test_api` (credentials, limits, malformed tokens, hashing), `test_api_write_db::test_token_lifecycle` |
| **Data leakage through the API** | Fixed field lists per resource; file content never served; internal identifiers excluded | `test_api::test_pick_returns_only_listed_fields_in_json_safe_form`, `test_every_endpoint_uses_the_callers_case_scope` |
| **Rewriting history** | 16 append-only tables guarded by triggers **and** by withholding UPDATE/DELETE from the application account; corrections are linked new rows | `test_privileges_db` (over 50 probes); trigger tests; `verify.sql` |
| **Evidence alteration or replacement** | Stored files are write-once (exclusive create; conditional writes on S3), read-only and named by UUID; the reference hash is never replaced; verification re-hashes the stored copy | `test_storage` (tampering detected), `test_evidence_files_write_db`, `test_data_consistency_db::test_stored_files_match_a_recorded_hash_and_exist` |
| **Untraced copies** | Every download is an *Exported* custody entry written **before** sending; the download is refused if that fails | `test_evidence_files_write_db`; Phase 4 checks |
| **Loss in storage moves** | Hash before and after every copy; CHECK on the location row; the source is never deleted | `test_storage_s3::test_migration_*`, `test_data_consistency_db::test_every_storage_move_was_verified` |
| **Malicious uploads** | Size limits per route; files never executed or rendered; downloads as attachments with a generic type and `nosniff` | `test_storage`, `test_evidence_files`, `test_integrity` |
| **Untrusted YARA rules** | Compiled and run only in a separate Python process: isolated mode, no secrets in its environment, empty working folder, includes disabled, time limit and memory watchdog across the **whole process tree** | `test_yara` (including real YARA-X refusing includes; both Windows-specific bugs were found and fixed through these tests) |
| **Exposed object storage** | No public or presigned URLs; `check-db` fails on a public bucket; least-privilege bucket policy documented | `test_storage_s3::test_s3_health_reports_public_or_missing_buckets` |
| **CSV formula injection** | Cells starting with `= + - @` are neutralised in exports | `test_audit` |
| **Secrets in code or images** | Settings from the environment; placeholder secrets refused at start-up; `.env*` excluded from Git and from the Docker image; CI generates its own secrets | `test_security::test_secrets_are_not_shipped`, `test_deploy::test_secrets_are_required_and_never_baked_into_the_image`, `test_example_secrets_are_refused` |
| **Database exposure (Docker)** | MySQL and MinIO only on an internal network; app published on 127.0.0.1; app container non-root, read-only, no capabilities | `test_deploy`; the CI Docker job checks that port 3306 is closed |
| **Vulnerable dependencies** | `pip-audit` in CI (blocking) | CI security job |

## 3. Known limitations and residual risks

1. **Database administrators are trusted.** Anyone with MySQL root (or Docker host) access can bypass triggers and privileges and edit history directly. FORGE-X protects against ordinary use and application bugs, not a malicious server administrator. Recommended mitigations: external backups, and storage with object locking.
2. **The read-only flag on stored files** stops accidental changes, not deliberate ones by an operating-system administrator. Tampering is **detected** by re-hashing; it isn't prevented.
3. **Rate-limit counters are per server process** and reset on restart, which is acceptable for one Waitress process. Several processes would each count separately.
4. **Behind a proxy without `TRUST_CLOUDFLARE`** (for example, Docker plus a tunnel), every visitor shares one address, which weakens the per-address limits.
5. **No multi-factor authentication** (optional in the upgrade plan; not built).
6. **Changing a password doesn't revoke API tokens.** Deactivation does, and users can revoke tokens themselves.
7. **Times are lab-local (IST)** without time-zone data in the database (decision D1); the API states the offset.
8. **`bandit` findings are advisory.** Its SQL warnings are false positives covered by the project's own SQL scan; other findings should be reviewed when they appear.
9. **Not independently tested:** no penetration test, no load test, and no accessibility audit by assistive-technology users.

## 4. Operational checklist

* [ ] Real, unique values for `FORGE_X_SECRET_KEY` and every password; `.env` and `.env.docker` never committed.
* [ ] `FLASK_DEBUG=0`, and `SESSION_COOKIE_SECURE=1` when served over HTTPS.
* [ ] `flask --app run check-db` passes, including the storage-folder, bucket and YARA lines.
* [ ] Backups of the database **and** the evidence files, with a test restore.
* [ ] API tokens revoked when no longer needed; inactive accounts deactivated.
* [ ] CI green, including `pip-audit`.
