# FORGE-X 2.0: Final Implementation Report

**Project:** FORGE-X, Digital Forensics Evidence Management System (B.Tech DBMS academic project)
**Upgrade:** FORGE-X 2.0, Phases 0 to 11, completed 9 October 2026.
**Stack:** Python 3.13/3.14, Flask 3, MySQL 8 (InnoDB), Jinja2, Bootstrap 5, Chart.js, ReportLab, YARA-X; optional S3/MinIO; Docker and GitHub Actions.

## 1. Summary

FORGE-X 2.0 upgraded a working 15-phase application **without rebuilding it**. Every phase:
* reused the existing services, permission rules, stored procedures and triggers;
* changed the schema only through additive migrations (004 to 010);
* kept the forensic guarantees intact: append-only history, reference hashes that are never replaced, and least privilege.

| | Before 2.0 | After 2.0 |
|---|---|---|
| Tables / triggers | 22 / 22 | **33 / 41** |
| Append-only tables | 8 | **16** |
| Routes | 69 | **106** |
| Automated tests | 184 | **374** (162 offline, 177 read-only database, 35 opt-in write; see `docs/TESTING.md`) |
| Migrations | 001 to 003 | **001 to 010** |

## 2. What each phase delivered

| Phase | Delivered | Status |
|---|---|---|
| 0. Audit | `PROJECT_AUDIT.md`, `CURRENT_ARCHITECTURE.md`, `UPGRADE_ROADMAP.md`; decisions U1 to U10 | ✅ |
| 1. UI and dashboard | Ten SQL-backed cards opening exact filtered lists, period filter, examination, integrity and custody panels, sortable columns, clearer integrity wording, strict CSP (no inline styles) | ✅ verified |
| 2. Case management | Investigator and date filters, last activity, due dates, append-only notes with linked corrections, case custody tab (migration 004) | ✅ verified |
| 3. Evidence Vault | Stored evidence files: write-once, outside the web root, SHA-256 on arrival, 100 MB limit per route; verification from storage; audited downloads (005) | ✅ verified |
| 4. Chain of custody | Custody entries and integrity checks in one log, new filters, every download recorded as an *Exported* custody entry before sending (006) | ✅ verified |
| 5. Examinations | Independent review (submit, approve, return) enforced in MySQL, append-only artifacts, workspace tabs, examination PDF (007) | ✅ verified |
| 6. Stabilisation | 12-step end-to-end test, schema and data-consistency checks, separate test database tool, generated stability report | ✅ verified |
| 7. YARA | Rule library with immutable versions and scopes; scans in an isolated worker with time and memory limits; recorded only when actually run (008) | ✅ verified (including real YARA-X on Windows) |
| 8. Relationship graph | Stored relationships only; three link kinds drawn differently; scoped expansion; dependency-free SVG | ✅ verified |
| 9. Object storage | Local or S3/MinIO behind one interface; verified migration with hashes before and after, source never deleted; append-only location history (009) | ✅ verified (local); the real S3 test is opt-in |
| 10. REST API | Read-only `/api/v1` (13 endpoints), personal tokens, rate limits, fixed field lists, OpenAPI generated from the routes (010) | ✅ verified |
| 11. Deployment, CI, docs | Dockerfile, Compose (isolated networks, hardened app container, optional MinIO), GitHub Actions (lint, MySQL tests on 3.13 and 3.14, security scans, Docker smoke test), this report, `DEPLOYMENT_GUIDE.md`, `SECURITY_REVIEW.md` | 🟡 written; see section 4 |

The decisions taken by default (recommendations, where no answer was given) are recorded in the README's *Design decisions* table: U2, U3, U4, U5 and U8.

## 3. How the work was verified

Verification happened in two places, and the difference matters:

* **Your machine** (Windows, Python 3.14, MySQL 8): the full suite, including the database and opt-in write tests, the browser checks after each phase, and the real YARA-X tests. Each phase was approved only after you reported that all tests passed.
* **My sandbox** (no MySQL, no package downloads): offline tests and page checks with small stand-ins for Flask-WTF, WTForms, the MySQL driver and pytest; real subprocesses for the YARA isolation tests; Node.js for the graph layout. The 2 CSRF tests need the real Flask-WTF, so they only pass on your machine.

### Defects found by testing during the upgrade (all fixed)

| Found by | Defect |
|---|---|
| Your run of `seed-mock` | Two locking reads refused by MySQL 8.0.22+ (error 1142) on tables the app account may not update. A test now checks every locking read against the grants |
| Your Windows test run | The YARA memory limit measured the working set instead of committed memory |
| Your Windows test run | The YARA watchdog watched only the venv launcher process, not its child, so a timed-out scan could keep running. It now watches and kills the whole process tree |
| A new OpenAPI test | Documented paths doubled the `/api/v1` prefix |
| A new deployment test | The Docker example secret key would have been accepted at start-up |
| Your test runs | A stale test fake after Phase 9, and 3 pytest collection warnings (`TestingConfig`) |
| The SQL f-string scan | Flagged every new dynamic query for review (by design); all were reviewed and recorded |

The current results are in `docs/CORE_STABILITY_REPORT.md`, generated by `python tools\stability_report.py` and, once pushed, by every CI run.

## 4. Not yet verified

* **Docker and CI have not been run yet.** I couldn't run Docker or GitHub Actions in my sandbox. The YAML and shell syntax were checked, and `tests/test_deploy.py` checks their security properties. The first `docker compose up` and the first push to GitHub are the real test, and may need small fixes.
* **A real MinIO/S3 server:** `test_real_s3_round_trip` is opt-in (`FORGE_X_S3_TESTS=1`).

## 5. Known limitations

The full list is in [SECURITY_REVIEW.md](SECURITY_REVIEW.md), section 3. In short:
* database and operating-system administrators are trusted;
* file tampering is detected, not prevented;
* rate limits are per process;
* there's no MFA;
* times are lab-local.

**Plan items deliberately not built:**

| Item | Reason |
|---|---|
| Notifications and Settings pages | Deferred since decision A5; the sidebar keeps them hidden |
| MFA | Optional in the plan |
| Approval steps for custody actions | No custody action needs one yet |
| Write endpoints in the API | v1 is read-only so the workflow rules aren't duplicated |
| Case archiving | U4: closing stays final |

## 6. Outstanding tasks

1. `docker compose --env-file .env.docker up -d --build`, then `check-db`, as described in `DEPLOYMENT_GUIDE.md`.
2. Push to GitHub and check the **Actions** tab; download the stability report artifact.
3. Capture the screenshots listed in the README into `docs/screenshots/`.
4. Choose a licence and add a `LICENSE` file.
5. Update the project report and `docs/VIVA_GUIDE.md` with the 2.0 features you plan to demonstrate.
