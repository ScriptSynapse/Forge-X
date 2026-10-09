# FORGE-X 2.0: Phase 0 Repository Audit

**Audited:** `ScriptSynapse/Forge-X`, branch `main` (14 commits). Its README matches the latest delivered package, so this audit covers the code as committed.
**Date:** 4 October 2026.
**Rule for this phase:** read-only. No application code was changed. The only additions are the three documents in `docs/`: this audit, `CURRENT_ARCHITECTURE.md` and `UPGRADE_ROADMAP.md`.

---

## 1. Summary

FORGE-X is already a substantial, working application. It has:

* 69 routes in 16 Flask blueprints;
* a 22-table normalized MySQL schema, with 22 triggers, 8 views, 12 stored procedures and 2 functions;
* role-based access for 4 roles, enforced in Flask **and** in MySQL;
* 184 automated tests.

**Most of the FORGE-X 2.0 Phases 1, 2, 4 and 5 already exists** and needs improvement rather than building. Avoiding duplication (your rule 5) is therefore the main constraint on the upgrade.

**The biggest gap is a design decision, not a bug.** FORGE-X deliberately **does not store evidence files**. It records metadata and SHA-256 hashes, and verification works by re-hashing a sample file that is then discarded (decision A6). Your Phase 3 asks for stored evidence, re-hashing from storage and authorised download. Phases 7 (YARA) and 9 (object storage) depend on that too. Section 6 lists this and the other decisions I need from you before Phase 1.

**The biggest risk is untested write paths.** The opt-in workflow tests, which exercise every write path end to end, have never been reported as run against your MySQL. One real bug already slipped through this way: locking reads refused by MySQL (error 1142), found when the mock data was loaded and since fixed. Running those tests on a separate test database is the first recommended action (section 4).

---

## 2. How this audit was done

| Step | Method |
|---|---|
| Structure and stack | Read every package, template folder, the SQL scripts and the README; built the route map from the Flask URL map |
| Schema | Counted and read the tables, constraints, triggers, views, procedures and grants in `database/` |
| Security | Reviewed authentication, sessions, CSRF, password hashing, CSP and headers, upload handling, privilege grants and audit logging |
| Workflows | Traced case, evidence, integrity, custody, examination, report and audit flows from route to service to SQL |
| Upgrade fit | Checked each capability your upgrade plan asks for against the code (section 5) |
| Tests | Ran the offline suite in my sandbox; collected the results you reported on your machine |

**Environment limitation (stated as required).** My sandbox has no MySQL server, no `mysql-connector-python` and no Flask-WTF, and no network access to install them. So:

* only the 72 offline tests can run here, against small stand-ins for Flask-WTF and WTForms;
* the 83 read-only database tests and the 29 opt-in workflow tests can only run on your machine;
* the results below are labelled with where they came from.

---

## 3. Size of the code base

| Item | Count |
|---|---|
| Python in `app/` | 6,785 lines, 16 blueprints, 69 routes |
| Jinja2 templates | 45 files, 2,451 lines |
| CSS / JavaScript (own code) | 489 / 250 lines; Bootstrap 5.3, Bootstrap Icons and Chart.js 4 served locally |
| SQL | 3,508 lines: 22 tables, 27 CHECK constraints, 15 secondary indexes, 22 triggers, 8 views, 12 procedures, 2 functions, 3 migrations |
| Tests | 27 files, 2,057 lines, **184 tests**: 72 offline, 83 read-only database, 29 opt-in write |
| Documentation | README, plus 5 guides in `docs/` and the separate project report |

---

## 4. Test baseline

| Run | Where | Result |
|---|---|---|
| `verify_demo.sql`, 40 SQL checks | Your machine, MySQL 8.0.46 | **40 / 40 passed** (Phase 4) |
| `pytest`, after Phase 11 | Your machine | **80 passed, 28 skipped, 0 failed** |
| `pytest`, after Phase 13 | Your machine | **All passed** (about 106 passed, 30 skipped) |
| `pytest`, after Phase 14 and the later fixes | Your machine | **Not yet reported** (expected about 149 passed, 35 skipped) |
| Offline tests, today | My sandbox, with stand-ins | **67 of 69 test functions passed.** The 2 failures are the two CSRF tests, which need the real Flask-WTF; they are expected to pass on your machine |
| Opt-in workflow tests (29) | Your machine | **Never reported as run** against MySQL |
| `flask seed-mock` | Your machine | First run failed with MySQL error 1142; fixed and made resumable; **the rerun hasn't been reported** |

**Open test issues:**

1. **Two pytest warnings** have appeared since Phase 7. FORGE-X's own code uses no deprecated calls (checked), so they most likely come from a library such as `mysql-connector-python` or ReportLab. The `pytest -q -rw` output is needed to name them.
2. **Write paths are under-tested on real MySQL.** The locking-read bug proves the gap is real. **Recommended before Phase 1:** build a separate test database and run `pytest -m db_write -v` with `FORGE_X_DB_WRITE_TESTS=1`.

---

## 5. Feature status against the FORGE-X 2.0 plan

Legend: ✅ works · 🟡 exists, needs improvement · ❌ missing · ⛔ conflicts with a current design decision (section 6).

### Phase 1: UI and dashboard

| Capability | Status | Current state |
|---|---|---|
| Dark command-center design system | ✅ | Navy palette, cyan and blue accents, amber and red states, IBM Plex fonts, tokens in `forge-x.css` |
| Responsive sidebar, active states, breadcrumbs, page headers | ✅ | Bootstrap `offcanvas-lg` sidebar with a menu button on small screens; breadcrumbs on detail pages |
| Sidebar hides unbuilt modules | ✅ | Items only appear once their page exists (`has_endpoint`). "Settings" is already defined and hidden |
| Top bar: branding, global search, user and role, logout | ✅ | Logout is a POST with a CSRF token |
| Notification indicator | ❌ | No notifications (decision A5 deferred them) |
| Settings / profile page | 🟡 | `/account` (profile, password change) exists; there is no Settings page |
| Login: validation, errors, loading state, password visibility toggle | ✅ | Busy state and toggle are present; generic error messages; throttling preserved |
| MFA | ❌ | Optional in your plan |
| Dashboard metric cards from real data | 🟡 | 8 SQL-backed cards. **Missing from your list:** high-priority cases, completed examinations, and an explicit "awaiting examination" figure |
| Clickable cards to filtered pages | 🟡 | Most cards link; not all link to an exactly matching filter |
| Charts: status, priority, evidence by type, trend | ✅ | Chart.js from `/api/dashboard/<chart>`, with loading, empty and error states |
| Recent activity, attention list, quick actions | ✅ | Role-aware |
| Recent custody events, integrity alerts, examination progress on the dashboard | 🟡 | Integrity failures are counted; there's no custody feed or examination-progress panel |
| Date filters on the dashboard | ❌ | Analytics has a 6, 12 or 24-month period; the dashboard has none |
| Sortable tables | 🟡 | Cases and evidence have a sort selector; there is no column-header sorting anywhere |

### Phase 2: Case management

| Capability | Status | Current state |
|---|---|---|
| List with search, status, priority, type filters, pagination | ✅ | |
| Investigator filter, date-range filter, "last activity" column | ❌ | |
| Create, edit (with lost-update protection), status, assign investigators | ✅ | |
| Case workspace tabs | 🟡 | Has Overview, Evidence, Investigators, Examinations, Reports and Activity. **No Chain of custody tab** (it's on each evidence item and in `/custody`) |
| Case notes and references | ❌ | No table |
| Deadlines | 🟡 | Examinations have due dates; cases don't |
| Close (final) / delete (only empty cases) | ✅ | Decisions D3 and D7 |
| Archive cases | ⛔ | Closure is final by design (D3). "Archived" exists for evidence, not for cases |
| Backend authorisation, URL-manipulation protection | ✅ | Hidden cases return 404; a route-wide test checks every route |

### Phase 3: Evidence vault and integrity

| Capability | Status | Current state |
|---|---|---|
| Searchable evidence register | 🟡 | Has ID, case, type, description, status, integrity, collected date, custodian and location. **No SHA-256 column, file type, examination status, or investigator and date filters** |
| Register evidence (one transaction: ID, row, first custody entry, optional hash) | ✅ | `sp_register_evidence` |
| **Upload and store the original evidence file** | ⛔ | Not stored, by design (A6). Only metadata and hashes |
| Re-hash from protected storage to verify | ⛔ | Verification re-hashes an uploaded sample, then discards it |
| States: Verified / mismatch / pending / unavailable | 🟡 | Today: Verified / Failed / Pending / Not Verified. Mostly a renaming; "unavailable" only matters once files are stored |
| Mismatch keeps the trusted hash; alert | ✅ / 🟡 | The trusted hash is never replaced (trigger-protected). The alert appears in the dashboard's attention list, but there are no notifications |
| Evidence detail: hashes, custody, examinations, audit trail | ✅ | Related reports aren't listed directly |
| Authorised download / export | ❌ | Nothing stored to download |
| Upload safety (size limit, allowed types, never executed) | ✅ | 25 MB, allow-list of types, streamed hashing |

### Phase 4: Chain of custody

| Capability | Status | Current state |
|---|---|---|
| Append-only custody events in transactions | ✅ | Triggers, no UPDATE or DELETE privilege, and `sp_transfer_evidence` |
| Correction events with reason and actor | ✅ | `sp_record_custody_correction` |
| Timeline UI with corrections marked | ✅ | Evidence → Chain of custody tab |
| Lab-wide custody log with filters | 🟡 | Filters for evidence ID, action and dates. **No case or investigator filter** |
| Events for verification and export in the same timeline | 🟡 | Verifications are kept in their own history, not as custody events; exports don't exist |
| Rollback tests | ✅ | `verify.sql` R-tests; stale-transfer refusal tested |

### Phase 5: Examinations

| Capability | Status | Current state |
|---|---|---|
| Linked to case and evidence (many-to-many), examiner, type, status, timestamps | ✅ | |
| Tools and methods, observations, findings, limitations | ✅ | Facts and interpretation are kept visibly apart |
| Artifacts, examination-level hashes, conclusion | ❌ | A conclusion exists in reports, not in examinations |
| Submit for review / approve / return | ❌ | Exists for reports only; `chk_exam_state` allows Pending, In Progress, Completed and Cancelled |
| Examination workspace tabs | 🟡 | One page with sections |
| Examination-level PDF report | 🟡 | Case reports cite examinations and export to PDF; there is no separate examination report |

### Phases 6–11

| Capability | Status |
|---|---|
| End-to-end, security and database tests | 🟡 A strong suite exists; the write paths still need a real-MySQL run |
| `docs/CORE_STABILITY_REPORT.md` | ❌ (Phase 6 deliverable) |
| YARA rules and scanning | ❌ Needs stored files (⛔ A6) |
| Evidence relationship graph | ❌ The data for case, evidence, examination, report and investigator links exists; indicators don't |
| Storage abstraction, MinIO/S3 | ❌ Needs stored files |
| Versioned REST API, OpenAPI | ❌ Only internal JSON for charts (`/api/dashboard`, `/api/analytics`) |
| Docker, GitHub Actions CI | ❌ |
| Deployment guide | 🟡 Windows setup in the README; Cloudflare Tunnel guide exists |

### Already present but not in your plan (keep them; rule 3)

Analytics (7 SQL charts with their queries shown), global search with SHA-256 prefix search, storage-location administration, user administration with an inactive-accounts view, audit CSV export and the security view, Cloudflare Tunnel hosting, data dictionary and viva guide.

---

## 6. Decisions needed before Phase 1

These change the design, so I need your choice rather than my assumption.

| # | Decision | Why it matters | My recommendation |
|---|---|---|---|
| **U1** | **Store evidence files?** | Phase 3 (stored originals, re-hash from storage, download), Phase 7 (YARA scans files) and Phase 9 (object storage) all depend on it. Today FORGE-X stores none (A6) | **Yes, within limits.** Store uploaded files outside the web root under generated IDs, write-once, hashed while they're written, with a configurable size limit (for example 100 MB of synthetic samples). Keep "metadata only" registration for large physical evidence such as disk images. Needs a migration (an append-only `evidence_files` table; numbered 005 in the roadmap) |
| U2 | Integrity status names | The plan's four states differ from today's | Rename on screen only: Verified, **Integrity mismatch**, **Pending verification**, **Verification unavailable** (no hash or no stored file). No schema change |
| U3 | Examination review | The plan wants submit, approve and return for examinations | Add *Under Review* and *Approved* to examinations, with an independent reviewer as for reports (migration). Keep case reports, and add an examination PDF built with the existing ReportLab code |
| U4 | Case archiving | The plan says "close or archive" | Keep closure final (D3); don't add a case archive state. Evidence archiving already exists |
| U5 | Case notes and deadlines | Missing today | Add an append-only `case_notes` table and a nullable `cases.due_date` (migration) |
| U6 | Notifications | Sidebar and top bar item; decision A5 deferred it | Database-backed notifications created only by real events (failed verification, overdue examination, report awaiting review, access request). No email |
| U7 | Mock data (rule 9) | `seed-mock` creates demonstration rows in your real database | Keep it as a developer command only. Never call it from the application, and don't run it on a production database |
| U8 | Time zone | Times are stored in IST (D1) | Keep it for now. The REST API (Phase 10) will return ISO 8601 times with the +05:30 offset |
| U9 | Git checkpoints (rule 14) | I can't push to your repository | You commit before and after each phase (one branch per phase is suggested). I deliver each phase as a package, with the list of changed files |
| U10 | Scope and deadline | Phases 7–11 are large | Tell me your submission date, so I can say which phases fit. Phases 1–6 alone make a strong 2.0 |

---

## 7. Defects, risks and drift found

| # | Finding | Severity | Action |
|---|---|---|---|
| 1 | Opt-in workflow tests never run on real MySQL; one real bug already escaped this way | High | Run them on a test database before Phase 1 |
| 2 | Two unexplained pytest warnings | Low | Send `pytest -q -rw` |
| 3 | **README drift:** still says the database tests haven't run on real MySQL; says "24" opt-in tests (now 29); lists only migrations 001–002 (003 exists); calls ReportLab "later phase"; MySQL minimum given as 8.0.16 (8.0.22+ behaviour is now relied on, D8) | Low | Fix in Phase 1 (documentation only) |
| 4 | Dashboard has no date filter; some cards don't open an exactly matching filtered list | Medium | Phase 1 |
| 5 | No column-header sorting on any table | Medium | Phase 1 / 2 |
| 6 | Custody log can't filter by case or investigator; the case workspace has no custody tab | Medium | Phase 2 / 4 |
| 7 | Evidence register lacks SHA-256, examination status, and investigator and date filters | Medium | Phase 3 |
| 8 | Upload limit is global: `MAX_CONTENT_LENGTH` = 26 MB for every request | Medium (once files are stored) | Phase 3: a per-route limit and streaming to disk |
| 9 | Times stored without an offset (D1, IST) | Low now, Medium for an API | Phase 10 (U8) |
| 10 | `style-src 'unsafe-inline'` in the CSP (needed for a few inline style attributes) | Low | Phase 1: move inline styles to CSS, then drop it |
| 11 | No Docker or CI; setup is manual on Windows | Medium | Phase 11 |
| 12 | OFFSET pagination and the `v_activity_feed` UNION scan everything on large data | Low at lab scale | Note only; revisit if data grows |

No security defects were found beyond those already fixed. The route-wide authorisation, CSRF, SQL-injection, privilege and locking-read tests all pass in my sandbox, apart from the two CSRF tests, which need the real Flask-WTF.

---

## 8. Recommended next step

1. Run `pytest -v`, plus the opt-in tests on a separate test database, and send me the results and the `-rw` warnings.
2. Commit this audit (`docs: Phase 0 audit`).
3. Answer decisions **U1–U10** (section 6), at least U1, U3 and U10.
4. Approve Phase 1.

---

## Phase 1 progress (FORGE-X 2.0)

| Audit finding | Status after Phase 1 |
|---|---|
| #3 README drift | Fixed (testing note, MySQL 8.0.22+, migrations 001–003, 29 opt-in tests, ReportLab and Waitress) |
| #4 Dashboard date filter; cards not opening matching lists | Fixed: 7, 30 or 90 days, or all time, for the activity figures; all 10 cards open exactly matching filtered lists |
| #5 No column sorting | Fixed for the case and evidence lists (allow-listed expressions only). Examinations, reports and custody come in Phases 2–5 |
| #10 `'unsafe-inline'` in the CSP | Fixed: `style-src 'self'`; a test forbids inline styles in templates and JavaScript |
| Dashboard metrics missing from the plan | Added: high-priority open cases, awaiting examination, completed examinations, reports pending review |
| U2 integrity wording | Applied on screen, in the PDF and in analytics; database values unchanged |

The other findings stay with their planned phases.

## Phase 2 progress (FORGE-X 2.0)

Decisions applied (recommendations, since none were given): **U4** no case archiving; **U5** append-only case notes and an optional due date.

| Plan item | Status |
|---|---|
| List: investigator filter, date range, last activity | Done, with overdue filter; every column sortable |
| Case workspace: Chain of custody tab | Done (all custody entries of the case's evidence) |
| Notes and references | Done: `case_notes`, append-only (3 triggers plus an INSERT-only grant), corrections linked both ways, refused on closed cases by MySQL |
| Deadlines | Done: `cases.due_date` with a CHECK, overdue badges, set on create or edit |
| Archive | Not added (U4); closure remains final |
| Authorisation | Notes: administrators, custodians and the case's investigators; auditors read only; refusals audited. A route-wide test covers the new route |

**Migration 004** (`database/migrations/004_case_notes_and_due_date.sql`) adds 1 table, 1 column, 2 CHECK constraints, 3 triggers and 1 grant. It is additive only. Fresh installs (`schema.sql`, `triggers.sql`, `app_user.sql`) and both verification scripts (23 tables, 25 triggers) match it, and `flask check-db` reports when it's missing.

## Phase 3 progress (FORGE-X 2.0)

Decision **U1 = store evidence files**, with a **100 MB** limit (Cloudflare free plan).

| Plan item | Status |
|---|---|
| Evidence Vault list: SHA-256, file type, examination status; investigator, date and file filters | Done |
| Upload, validation, size limit | Done: per-route limit (100 MB, set by `EVIDENCE_MAX_MB`; every other route stays at 26 MB); filenames sanitised; type taken from the extension, not trusted from the browser |
| Secure storage | Done: `app/storage` with generated UUID names, write-once (exclusive create), read-only, outside the web root (`EVIDENCE_STORAGE_DIR`); designed for an S3/MinIO backend in Phase 9 |
| SHA-256 at registration; registration, custody, audit | Done: hashed while written; registered through `sp_register_evidence`; file record and audit row in a second transaction. If either step fails, the unrecorded file is removed |
| Verification from storage | Done: *Stored file* method; trusted hash never replaced; missing or unreadable file reported as verification unavailable; audited |
| Detail page: file information, download | Done: Stored file card; downloads for administrators, custodians and the case's investigators, as attachments, audited |
| Audit finding #8 (global upload limit) | Fixed by the per-route limit |
| Never overwrite evidence | Enforced three ways: append-only `evidence_files` (triggers and an INSERT-only grant), one file per item (UNIQUE), exclusive-create writes |

**Migration 005** adds `evidence_files` (2 triggers, INSERT-only grant) and the *Stored file* verification method, replacing `chk_hv_method` with a wider version that every existing row passes. Fresh installs, both verification scripts (24 tables, 27 triggers) and `check-db` match it. `check-db` also checks that the storage folder is writable.

**Limitation:** the read-only flag prevents accidental changes, but not deliberate ones by an operating-system administrator. Re-hashing from storage is what detects tampering, and it is recorded.

## Phase 4 progress (FORGE-X 2.0)

| Plan item | Status |
|---|---|
| Custody events: acquisition, transfer, examination, storage relocation, sealing, release | Already present (Collected, Received, Transferred, Checked Out, Examined, Returned, Stored, Released, Archived; seal numbers) |
| Integrity verification in the history | Done: checks appear in the custody log and the evidence timeline (read from `hash_verifications`; nothing duplicated) |
| Authorised export | Done: every download is an **Exported** custody entry written before sending (fail closed); the original's custodian, location and status are unchanged |
| Event fields: ID, evidence, case, type, actor, time, origin and destination, reason | Present in the log and timeline |
| Approval details | Not applicable yet: no custody action currently requires an approval step |
| Custody log filters: case, evidence, event type, investigator, date; chronological timeline | Done: case, evidence, event type, person involved, dates, newest or oldest first |
| Corrections, never edits; transactions; backend authorisation | Already present; export entries additionally can't be corrected (service rule) |

**Migration 006** appends *Exported* to `chain_of_custody.action`. Every existing row stays valid; no tables or triggers are added.

## Phase 5 progress (FORGE-X 2.0)

Decision **U3 = independent examination review** (my recommendation; not explicitly answered).

| Plan item | Status |
|---|---|
| Examination fields: case, evidence, examiner, type, status, timestamps, tools, methodology, observations, findings | Already present |
| Identified artifacts, relevant hashes, conclusion | Done: append-only `examination_artifacts` (type, description, location, evidence, optional SHA-256, linked corrections); `conclusion`; evidence reference hashes shown in the Evidence tab and the PDF |
| Reviewer or approval information | Done: `reviewed_by`, `reviewed_at`, `review_note`, `submitted_at` |
| Workflow: create, assign, record, save, submit, approve or return, finalise | Done; status *Under Review*; approval by an administrator or the case lead who isn't the examiner |
| No changes to finalised records | Done in MySQL: trigger `trg_exam_finalised` refuses any update to Completed or Cancelled examinations, and completion without review |
| Workspace tabs: Overview, Evidence Details, Methodology, Findings, Artifacts, History, Report | Done |
| Examination report: details, case, evidence and hashes, methodology, findings, conclusion, custody references; audited | Done (`app/examinations/pdf.py`, reusing the report PDF's layout and escaping) |
| Automated analysis only from executed analysis | Respected: FORGE-X still runs no tools; automated results arrive only with Phase 7 (YARA) |

**Migration 007** adds the review columns and constraints, `examination_artifacts`, and 4 triggers, and recreates `sp_close_case` so examinations Under Review block closure. Existing examinations stay valid. Fresh installs, both verification scripts (25 tables, 31 triggers) and `check-db` match it.

## Phase 6 progress (FORGE-X 2.0)

| Plan item | Status |
|---|---|
| End-to-end workflow, steps 1–12 | `tests/test_core_workflow_write_db.py`: one opt-in test, each assertion labelled with its step |
| Security testing (unauthorised access, roles, CSRF, input validation, SQL injection, uploads, downloads, hash mismatch, sessions, transactions) | Covered by existing tests; mapped requirement by requirement in the report |
| Database testing: foreign keys, procedures, triggers, consistency, migrations, rollback | New: `test_schema_matches_db.py` (live schema equals `schema.sql`, so a missed migration fails) and `test_data_consistency_db.py` (6 invariants on real data); plus the existing trigger, privilege and rollback probes |
| `docs/CORE_STABILITY_REPORT.md` with results, remaining defects, limitations | Generated by `tools/stability_report.py` from a real run (never hand-typed); a placeholder until you run it |
| Run the write tests safely | `tools/build_test_database.py` builds `forge_x_test` (same schema and grants); both tools refuse to write test data into `forge_x_db` |
| Audit finding #1 (write paths untested on real MySQL) | Closed once the report is generated with `--with-write-tests` |
| Audit finding #2 (two pytest warnings) | The report captures the pytest warnings summary automatically |

**Fixing defects** found by the generated report is the remaining Phase 6 work: send me sections 6 and 9 of the report if they aren't empty.

## Phase 7 progress (FORGE-X 2.0)

**Engine:** YARA-X (`pip install yara-x`) instead of `yara-python`. The official `yara-python` publishes Windows packages only up to Python 3.13, and this project runs on Python 3.14; YARA-X is the official successor and ships a Windows package that works on 3.14.

| Plan item | Status |
|---|---|
| Rule library: name, identifier, description, author, version | Done: `yara_rules` and immutable `yara_rule_versions` (SHA-256 of each source) |
| Syntax validation | Done, compiled in the isolated worker before saving |
| Enable and disable; rule-to-case associations | Done: scope *All cases* or *Selected cases* with `yara_rule_cases` |
| Authorised scan requests; history and results; matched rule details | Done: evidence **YARA scans** tab, scan pages, `yara_scans`, `yara_scan_rules`, `yara_matches` |
| Error and timeout handling | Done: Completed only on success; otherwise Failed, Timed out or Memory limit, with the reason; nothing is recorded when YARA-X is missing |
| Never in the web process; restricted worker; time and memory limits | Done: separate process (`-I`, minimal environment without secrets, temporary folder), YARA-X timeout plus a hard kill, psutil watchdog plus Linux rlimits |
| Read-only evidence; never modified | Done: the stored copy is opened read-only; includes disabled |
| Record evidence hash, rule version, scanner version, execution time, results | Done |
| Audit logging; no external uploads | Done (`yara.*` and `evidence.yara_scan` actions); nothing leaves the machine |

**Tested here:** the worker logic (against a test double following the documented YARA-X API), and the isolation and limits with real processes: no secrets in the environment, `PYTHONPATH` ignored, killed on timeout, killed by the memory watchdog. **Not tested here:** the real YARA-X, which can't be installed in my sandbox. `tests/test_yara.py::test_real_yara_x_compiles_scans_and_refuses_includes` and `tests/test_yara_write_db.py` run against it on your machine.

**Found on your machine and fixed:** on Windows the memory watchdog measured the working set (`rss`), which doesn't include memory that is committed but not yet touched, so a worker could exceed its limit until the time limit stopped it. It now measures committed private memory on Windows (`runner.memory_used`), with a unit test of both platforms' rules.

**Second finding, also fixed:** on Windows a venv's `python.exe` is a launcher that runs the real interpreter as a child process. The watchdog was watching (and on timeout killing) only the launcher, so the memory limit never fired and a timed-out child could keep running. The runner now measures and kills the whole process tree (`taskkill /T` as the fallback without psutil), tested with a launcher-style worker.

**Migration 008** adds 6 tables, 8 triggers, the audit entity type *YARA rule*, and least-privilege grants.

## Phase 8 progress (FORGE-X 2.0)

No schema change: the graph reads existing records only.

| Plan item | Status |
|---|---|
| Nodes: cases, evidence, file hashes, indicators, examinations, investigators, reports | Done. Indicators are YARA rules matched by each item's latest completed scan; artifacts are included too |
| Relationships: belongs to case, examined, recorded indicator, shared hash, report references evidence | Done (a report references evidence through the examinations it cites) |
| Zoom and pan, selection, detail panel, filters by node and link type, search, links to authorised records | Done; keyboard support and a text list of every relationship |
| Verified relationships vs analyst suggestions | Three link kinds drawn differently (solid, dashed, dotted). There is no suggestion feature, so the graph contains no suggestions, and the page says so |
| No fabricated relationships; no inferring malicious activity from shared attributes | Only stored links; shared hashes are described as identical bytes, explicitly not an accusation |
| Responsive with large datasets: filtering and controlled expansion | Starts from one case, expands one node at a time, capped at 250 nodes with a visible notice |
| Authorisation | Every query scoped to visible cases; expansion re-checks the node; shared-hash holders in invisible cases are never shown |

**Design choice:** a small dependency-free SVG renderer (`app/static/js/graph.js`) instead of a graph library. It keeps the strict CSP without vendoring a large library. Its layout and merge logic run under Node.js in the tests.

## Phase 9 progress (FORGE-X 2.0)

| Plan item | Status |
|---|---|
| Preserve the existing storage backend | Done: local disk stays the default; nothing changes unless `EVIDENCE_STORAGE_BACKEND=s3` |
| Storage abstraction | Done: `LocalStorage` and `S3Storage` share one interface (put, open, hash, exists, materialize, health) |
| Optional MinIO / S3; metadata in MySQL; generated object ids | Done (`app/storage/s3.py`, boto3); object keys `<prefix><UUID>` |
| Preserve SHA-256 verification | Done: hashed on arrival; *Verify stored file* and YARA read from the file's current backend |
| Access control, audit, no public access, no permanent public URLs | Done: no public or presigned URLs, downloads stream through FORGE-X; `check-db` fails on a public bucket; least-privilege bucket policy documented |
| Migration with hashes before and after, recorded | Done: `flask storage-migrate`; `evidence_file_locations` (append-only, CHECK before = after) plus an audit row per move |
| Never remove evidence or change metadata without a verified plan | Done: migrations never delete the source; `evidence_files` is untouched (locations are a separate history) |
| Document migration and rollback | Done: `docs/OBJECT_STORAGE.md` |

**Tested here:** the S3 backend against an in-memory stand-in for the boto3 client (write-once, limits, temporary scan copies, public-bucket check), and the migration end to end with real local files: damaged sources not moved, conflicting objects untouched, corrupted copies removed, rollback without copying. **Not tested here:** a real MinIO/S3 server, which my sandbox can't run. `tests/test_storage_s3.py::test_real_s3_round_trip` runs against one with `FORGE_X_S3_TESTS=1`.

**Migration 009** adds `evidence_file_locations` (2 triggers, INSERT-only grant). Fresh installs, both verification scripts (32 tables, 41 triggers) and `check-db` match it.

**Audit finding #2 (pytest warnings) closed:** the 3 warnings were `PytestCollectionWarning: cannot collect test class 'TestingConfig'`. pytest treats classes named `Test*` as test classes, and `TestingConfig` is imported into test modules. It is now marked `__test__ = False`.

## Phase 10 progress (FORGE-X 2.0)

Decision **U8 = ISO 8601 with the lab offset** (my recommendation; not explicitly answered). **Scope decision:** v1 is read-only (see `docs/API.md`, *Why read-only*).

| Plan item | Status |
|---|---|
| Versioned endpoints: cases, evidence, chain of custody, examinations, reports, indicators | Done (`/api/v1`, 13 GET endpoints) on top of the existing services |
| Authentication consistent with the application | Done: the browser session, or personal tokens tied to the same accounts (inactive accounts and forced password changes refused) |
| Object-level authorisation | Done: every endpoint uses `access.Scope`; hidden records are 404 |
| Input validation, pagination, consistent responses, status codes, structured errors | Done: the existing filter classes validate input; `{data, page, per_page, total, pages}`; JSON errors 401/403/404/405/429 |
| Rate limiting | Done: per user, and per address for failed tokens (in-process counters) |
| Audit logging for sensitive operations | Done: token creation, revocation and failed attempts (prefix only) |
| OpenAPI generated from implemented routes; no nonexistent endpoints | Done; a test fails if the routes and the document ever differ. It already caught one bug: paths doubled the `/api/v1` prefix |
| Never expose evidence, secrets, password hashes or configuration | Done: fixed field lists (checked by a test); file content never served |
| Tested authorised and unauthorised requests | 21 offline tests (run here), 8 read-only database tests, 1 opt-in lifecycle test |

**Migration 010** adds `api_tokens` (INSERT and UPDATE only, never DELETE) and the audit entity type *API token*.

**Sandbox note:** my sandbox was reset during this phase. I rebuilt the stand-ins for Flask-WTF, WTForms, the MySQL driver and pytest, and reran every test file: 151 offline tests pass; the 2 CSRF tests still need the real Flask-WTF. One file, `.gitignore`, had been lost from the working copy and was restored from the last delivered package.
