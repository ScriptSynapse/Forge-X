# FORGE-X

**Digital Forensics Evidence Management System**
*Secure. Track. Investigate. Maintain Integrity.*

FORGE-X is a web application for a digital forensics laboratory. It manages cases, digital evidence, evidence integrity (SHA-256), chain of custody, forensic examinations, reports, user access and audit records.

It is a B.Tech Computer Science DBMS academic project. It demonstrates:

* relational design and normalization (3NF/BCNF)
* constraints, views, stored procedures and triggers
* transactions and indexing
* role-based access control

All data in the project is synthetic. FORGE-X is a learning project, not a certified forensic tool. It records examination activity; it never runs forensic tools against devices.

---

## Project status

The project is built in 15 phases. This package contains **all 15 phases**.

| Phase | Content | Status |
|---|---|---|
| 1 | Requirements and planning | ✅ Approved |
| 2 | UI/UX design (canvas mockups and design system) | ✅ Approved |
| 3 | Database architecture (ER diagram, normalization, transactions) | ✅ Approved |
| 4 | MySQL implementation (`database/`) | ✅ Verified: 40/40 `verify.sql` tests pass on MySQL 8.0.46 |
| 5 | Flask and MySQL integration | ✅ Verified |
| 6 | Authentication and authorization | ✅ Verified |
| 7 | Landing page and dashboard | ✅ Verified |
| 8 | Case management | ✅ Verified |
| 9 | Evidence management | ✅ Verified |
| 10 | Integrity and chain of custody | ✅ Verified |
| 11 | Examinations, reports and PDF export | ✅ Verified |
| 12 | User administration and audit logs | ✅ Verified |
| 13 | Analytics and global search | ✅ Verified |
| 14 | Testing review and hardening | 🟡 Written; run the tests below to confirm |
| 15 | Documentation and final delivery | ✅ Delivered |
| 2.0-0 | Upgrade audit (`docs/PROJECT_AUDIT.md`, `CURRENT_ARCHITECTURE.md`, `UPGRADE_ROADMAP.md`) | ✅ Delivered |
| 2.0-1 | Premium UI and dashboard | ✅ Verified |
| 2.0-2 | Case management (notes, due dates, custody tab, filters) | ✅ Verified |
| 2.0-3 | Evidence Vault: stored evidence files, verification from storage, downloads | ✅ Verified |
| 2.0-4 | Chain of custody: unified event log, exports as custody events | ✅ Verified |
| 2.0-5 | Examinations: independent review, artifacts, examination PDF | ✅ Verified |
| 2.0-6 | Stabilisation: end-to-end workflow test, schema and consistency checks, stability report | ✅ Verified |
| 2.0-7 | YARA rule library and evidence scans (YARA-X, isolated worker) | ✅ Verified (YARA tests incl. real YARA-X pass on Windows) |
| 2.0-8 | Evidence relationship graph | ✅ Verified |
| 2.0-9 | Optional object storage (MinIO / S3), verified migration | ✅ Verified |
| 2.0-10 | Read-only REST API v1, personal tokens, OpenAPI | 🟡 Written; run migration 010 and the tests |

**Testing.** The SQL verification (40/40) and the pytest suite have been run on MySQL 8.0.46 during the 15 phases. Run them again after every update (see *Running the tests*); `docs/PROJECT_AUDIT.md` records the latest known results.

---

## Technology

| Layer | Technology |
|---|---|
| Frontend | HTML5, CSS3, JavaScript, Bootstrap 5, Jinja2, Bootstrap Icons, Chart.js |
| Backend | Python 3.10+, Flask 3, Flask Blueprints, Flask-WTF (CSRF), Werkzeug password hashing |
| Database | MySQL 8.0.22+ (InnoDB), mysql-connector-python |
| Other | ReportLab (PDF), Waitress (production server), python-dotenv, pytest |

MySQL is the **only** store for application data. The `.env` file holds configuration and secrets only.

---

## Folder structure

```
Forge-X/
├── app/
│   ├── __init__.py          Application factory, CSRF, security headers, blueprints
│   ├── config.py            Settings from .env, with startup validation
│   ├── db.py                Connection pool, parameterized queries, transactions, error translation
│   ├── audit.py             Writes audit_logs records
│   ├── errors.py            Friendly HTML/JSON error pages
│   ├── ui.py                Navigation, badge colours, template filters
│   ├── pagination.py        Page helper for list screens
│   ├── cli.py               flask check-db, create-admin, set-password
│   ├── auth/                Login, logout, signup, account, password change, decorators
│   ├── users/               Users & roles administration (search, inactive accounts, requests, roles, status)
│   ├── audit_logs/          Audit log timeline, CSV export and security view (/audit-logs)
│   ├── search/              Global search (/search): records, exact-ID jump, SHA-256 prefix search
│   ├── analytics/           Seven SQL analytics charts with their queries shown (/analytics)
│   ├── dashboard/           Dashboard page and chart JSON endpoints (/api/dashboard/...)
│   ├── cases/               Case list, create, details (tabs), edit, status, investigators, closure
│   ├── evidence/            Evidence registry, register, details (hashes, custody timeline), edit
│   ├── locations/           Storage locations administration (/admin/locations)
│   ├── integrity/           Record / verify / correct SHA-256 hashes (sample files are hashed, never stored)
│   ├── custody/             Custody log (/custody), transfers and corrections
│   ├── examinations/        Examination workflow (record, start, complete, cancel, link evidence)
│   ├── reports/             Versioned reports, review/approval, ReportLab PDF export (pdf.py)
│   ├── access.py            Who may see and change cases and evidence (shared rules)
│   ├── public/              Landing page
│   ├── system/              /healthz
│   ├── templates/           Layouts, partials, macros, pages
│   └── static/              CSS, JS, images (vendor/ is filled by tools/fetch_vendor.py)
├── database/
│   ├── install_all.sql      Builds an EMPTY lab (no users) and runs verify.sql
│   ├── install_demo.sql     Optional: builds the lab WITH demo data and runs verify_demo.sql
│   ├── schema.sql           33 tables, constraints, indexes
│   ├── triggers.sql         41 triggers
│   ├── views.sql            8 views
│   ├── procedures.sql       12 procedures, 2 functions
│   ├── seed_reference.sql   Roles, case/evidence/examination types, storage locations
│   ├── seed_demo.sql        Optional synthetic demo data (8 users, 12 cases, 20 evidence items)
│   ├── verify.sql           Data-independent PASS/FAIL checks (works on an empty lab)
│   ├── verify_demo.sql      Full 40-test suite (needs the demo data)
│   ├── sample_queries.sql   32 explained queries for the viva (results assume the demo data)
│   ├── transactions_demo.sql  COMMIT demonstrations (needs the demo data; changes data)
│   ├── app_user.sql         Least-privilege MySQL account (edit password first)
│   └── migrations/          001 (before Phase 6), 002 (before Phase 9), 003 (case deletion), 004 (case notes, due dates), 005 (evidence files), 006 (Exported custody action), 007 (examination review, artifacts), 008 (YARA), 009 (evidence file locations), 010 (API tokens): run only on older databases
├── tests/                   pytest suite
├── docs/                    User guide, data dictionary, testing, viva guide, Cloudflare hosting
├── tools/
│   ├── fetch_vendor.py      Downloads Bootstrap, icons, Chart.js and fonts locally
│   └── make_data_dictionary.py  Generates docs/DATA_DICTIONARY.md from schema.sql
├── .env.example
├── .gitignore
├── pytest.ini
├── requirements.txt
└── run.py
```

---

## Setup on Windows (Command Prompt)

### 1. Install the prerequisites

* **Python 3.10 or newer** from python.org. Tick *Add python.exe to PATH* during installation.
* **MySQL Community Server 8.0.22 or newer** (8.4 LTS recommended), plus **MySQL Workbench**.
* Add MySQL's `bin` folder to your PATH. For example: `C:\Program Files\MySQL\MySQL Server 8.4\bin`.

Check that both are installed and on your PATH:

```cmd
python --version
mysql --version
```

### 2. Create the virtual environment and install packages

```cmd
cd C:\Users\<you>\Documents\GitHub\Forge-X
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Download the front-end libraries (once, needs internet)

```cmd
python tools\fetch_vendor.py
```

### 4. Build and verify the database (as root)

This builds an **empty lab**: all tables, triggers, views and procedures, plus the reference data (roles, case and evidence types, storage locations). It creates no users, cases or evidence.

```cmd
mysql -u root -p --default-character-set=utf8mb4 --table -e "source database/install_all.sql"
```

The last table printed by `verify.sql` should read **failed 0**.

**This drops and recreates `forge_x_db`,** so all existing data is lost.

**Using MySQL Workbench instead?** Run these files in order: `schema`, `triggers`, `views`, `procedures`, `seed_reference`, `verify`.

### 5. Create the application database account

1. Open `database\app_user.sql` and replace `CHANGE_ME_App#Passw0rd_2026` (it appears twice) with a strong password.
2. Run it:

```cmd
mysql -u root -p -e "source database/app_user.sql"
```

### 6. Configure `.env`

```cmd
copy .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

Edit `.env` and set two values:

* `FORGE_X_SECRET_KEY`: the value printed above.
* `MYSQL_PASSWORD`: the password from step 5.

Never commit `.env`. It is listed in `.gitignore`.

### 7. Check the connection

```cmd
flask --app run check-db
```

This should end with **All checks passed.**

### 8. Create the administrator

The lab starts with no users. Create the first administrator. You'll be asked for the full name, email and password, and the password is typed at a hidden prompt:

```cmd
flask --app run create-admin paulson
```

This command only works while there is **no** active administrator. After that, every account is created from **Users & roles** in the web interface, where each step is checked and audited.

To change a password later:

```cmd
flask --app run set-password paulson
```

### 9. Run the application

```cmd
flask --app run run
```

Open http://127.0.0.1:5000 and log in as `paulson`. You land on the dashboard.

---

## Running the tests

```cmd
pytest -v
```

**Expect about 324 passed and 43 skipped** (with `yara-x` and `psutil` installed). What each test proves, the security test matrix and a manual acceptance checklist are in **[docs/TESTING.md](docs/TESTING.md)**. The exact split depends on your data.

* 6 tests skip because they check specific demo records, or need an evidence hash to test against. The skip reason says "demo data not installed" or "empty lab".
* 33 are the opt-in workflow tests described below (including the 12-step end-to-end test).

With the demo data installed instead (`install_demo.sql`), more tests run.

**The opt-in workflow tests add `pytest_*` users, cases, evidence and storage locations to the database.** None of these can be deleted, by design. **Don't run them on a database where you want only `paulson`.** Use a separate demo or test installation:

```cmd
set FORGE_X_DB_WRITE_TESTS=1
pytest tests\test_auth_db.py tests\test_cases_write_db.py tests\test_evidence_write_db.py tests\test_integrity_custody_write_db.py tests\test_exams_reports_write_db.py tests\test_audit_write_db.py -v

rem or, equivalently, every opt-in test at once:
pytest -m db_write -v
set FORGE_X_DB_WRITE_TESTS=
```

**Built the database before Phase 6 or Phase 9 and kept it?** Run the migrations you're missing, once each, as root. `flask check-db` reports which ones are missing. A fresh `install_all.sql` doesn't need them.

```cmd
mysql -u root -p -e "source database/migrations/001_add_session_version.sql"
mysql -u root -p -e "source database/migrations/002_audit_storage_location.sql"
mysql -u root -p -e "source database/migrations/003_allow_case_delete.sql"
mysql -u root -p -e "source database/migrations/004_case_notes_and_due_date.sql"
mysql -u root -p -e "source database/migrations/005_evidence_files.sql"
mysql -u root -p -e "source database/migrations/006_custody_exported.sql"
mysql -u root -p -e "source database/migrations/007_examination_review_artifacts.sql"
mysql -u root -p -e "source database/migrations/008_yara.sql"
mysql -u root -p -e "source database/migrations/009_evidence_file_locations.sql"
mysql -u root -p -e "source database/migrations/010_api_tokens.sql"
```

## Dashboard figures

Every figure is computed by a MySQL query when the page loads. Nothing is hard-coded or cached. Charts load from `/api/dashboard/<chart>` JSON endpoints, and every card opens the exactly matching filtered list.

**Current state** (the period selector doesn't change these):

| Card | Rule | Opens |
|---|---|---|
| Total cases | All cases in scope | Cases |
| Open cases | Status is Open, In Progress or On Hold | Cases → Active |
| High-priority open | Open, with priority Critical or High | Cases → Active, High or critical |
| Total evidence | Evidence items belonging to cases in scope | Evidence Vault |
| Awaiting examination | Linked to an examination that is still Pending (not started) | Evidence Vault → awaiting examination |
| Under examination | Current custody status is Under Examination | Evidence Vault → Under Examination |
| Pending transfers | Current status is Checked Out or In Transit | Chain of custody (Out of storage list) |
| Completed examinations | Status Completed (the note shows pending and in progress) | Examinations → Completed |
| Reports pending review | Status Under Review (the note shows drafts) | Reports → Under Review |
| Integrity verification | Latest check of each item's current reference hash (`v_evidence_integrity`) | Evidence Vault → mismatches (or verified) |

**Integrity wording (decision U2).** The database keeps its values; the screen shows clearer names:

| Stored value | Shown as |
|---|---|
| Verified | Verified |
| Failed | Integrity mismatch |
| Pending | Pending verification |
| Not Verified | Verification unavailable |

**Activity in a period** (7, 30 or 90 days, or all time; 30 by default): cases opened, evidence registered, custody entries, hash checks verified, integrity mismatches, and examinations completed.

**Panels:**
* **Examination progress:** counts by status, plus the number overdue.
* **Integrity alerts:** items whose latest check failed.
* **Recent custody events:** handovers in the period.
* **Needs attention** and **recent activity.**

**Quick actions:** New case, Register evidence and New examination, each shown only to users who can do it.

**Who sees what:** administrators, auditors and custodians see the whole lab. Investigators see only the cases they are assigned to, and only their own recent activity.

**Lists.** The case and evidence lists sort by clicking a column header; clicking again reverses the order. Only fixed, allow-listed sort expressions ever reach SQL.

## Case management rules

| Action | Who |
|---|---|
| See a case | Administrators, auditors and custodians: every case. Investigators: only cases they're assigned to (others answer 404) |
| Register a case | Administrators (they choose the lead) and investigators (they become the lead) |
| Edit, change status, manage investigators, close | An administrator or the case's lead investigator |
| Anything on a closed case | Nobody: closed cases are read-only (decision D3), enforced by Flask and by a database trigger |
| Delete a case | Administrators, and only a case with no evidence, examinations, reports or notes that isn't closed (decision D7) |
| Add a note | Administrators, evidence custodians and the case's investigators, while the case is open |

* **Case references** such as `FX-2026-0025` are generated inside the database by `sp_register_case`, in the same transaction as the lead assignment.
* **Editing is protected against lost updates.** The edit form carries the case's last-updated time. If someone else saved in between, your save is refused and nothing is overwritten.
* **Closing** goes through `sp_close_case`. It refuses while examinations are Pending or In Progress, or evidence is out of storage.
* **Deleting** a case registered by mistake removes the case and its investigator assignments in one transaction. It needs a reason and the case reference typed to confirm, and the audit log keeps the reference, title and reason. RESTRICT foreign keys refuse the delete if anything was linked to the case meanwhile.
* **Due dates** (optional) can be set when a case is registered or edited. They can't be in the past at registration or before the registration date. An open case past its due date shows as **overdue** on the case page and in the list.
* **Notes and references** (Notes tab) are **append-only**, like custody entries. To fix a note, add a correction: a new note linked to the old one, shown as "Correction of #n" and "Corrected by #n". MySQL enforces this: triggers refuse editing, deleting, notes on closed cases, and corrections pointing to another case. The app account has INSERT only.
* **Chain of custody tab:** every custody entry for all of the case's evidence, newest first.
* **Case list:** filters for status (including *Active*), priority (including *High or critical*), type, investigator, registration date range and overdue. Columns include due date and **last activity**: the latest of the case's own edits, custody events, notes, examinations and reports. Every column sorts.
* **Audit records:** every change is written to `audit_logs`. Refused actions are recorded with outcome Denied.

## Evidence rules

### Chain of custody log (FORGE-X 2.0 Phase 4)

* **One chronological log** (`/custody`) of every custody entry **and** every integrity check. Checks are read from `hash_verifications`, never copied into the custody table.
* **Filters:** evidence ID, case, event type (each custody action, *Exported* or *Integrity check*), person involved (handed over, received, recorded or verified), date range, and newest or oldest first.
* **Evidence page timeline:** integrity checks appear between the custody entries. They can be hidden with *Custody entries only*.
* **Downloads are custody events.** Every download of a stored file is recorded as an **Exported** custody entry before anything is sent.
  * The entry repeats the current custodian and location, because the original doesn't move. So "held since" and the custody-consistency checks are unaffected.
  * If the entry can't be recorded, the download is refused (fail closed).
  * Export entries can't be corrected, because the download happened.
* **Corrections** stay linked new entries (`sp_record_custody_correction`); custody entries are never edited or deleted.

### Stored evidence files (FORGE-X 2.0 Phase 3, decision U1)

FORGE-X can store the evidence file itself, alongside its metadata. Use synthetic data only.

* **Where:** `EVIDENCE_STORAGE_DIR` in `.env`. By default this is `instance/evidence_store/`, which is never served to browsers and is ignored by Git.
  * Each file is saved under a generated UUID, and is **write-once and read-only**.
  * The original filename is kept only as display text.
* **Size:** up to `EVIDENCE_MAX_MB` (100 MB by default, which matches Cloudflare's free-plan upload limit). Only the evidence upload routes accept files this large; every other route keeps the 26 MB limit.
* **The reference hash:**
  * **At registration,** the SHA-256 is computed while the file is written, and becomes the item's original reference hash. If you also type the acquisition tool's hash, the two must match, or nothing is registered.
  * **When attaching a file to an existing item,** the file must match the recorded reference hash. If the item has no hash yet, the file's hash becomes it.
* **Verify stored file:** re-hashes the stored copy without changing it, and records the check (method *Stored file*). The database trigger decides the result.
  * A mismatch is recorded as **Integrity mismatch**, and **the trusted hash is never replaced**.
  * A file that's missing or unreadable is reported as verification unavailable.
* **Download:** administrators, custodians and the case's investigators; auditors can't download content. Files are always sent as attachments with a generic type, and every download is audited.
* **What MySQL enforces:**
  * `evidence_files` is append-only (triggers, plus an INSERT-only grant), and holds one file per item.
  * A file that couldn't be recorded is removed from storage, so storage never holds files the database doesn't know about.
* **Backups:** back up `EVIDENCE_STORAGE_DIR` together with the MySQL database. Each one is incomplete without the other.


| Action | Who |
|---|---|
| See an item | Whoever can see its case |
| Register evidence | Administrators and custodians for any open case; investigators for open cases they're assigned to |
| Edit descriptive details | Administrators, custodians, or the case's lead investigator, while the case is open |
| Manage storage locations | Administrators |

* **Registration is one transaction** in `sp_register_evidence`: the `FX-EV-YYYY-NNNNN` ID, the evidence row, the first custody entry (*Collected*, status *In Transit*) and the optional original SHA-256.
* **What can't be edited.** The collection time, collector, condition at collection, custody entries and hashes are part of the forensic record. Only the description, source details, size and collection site can be edited, with lost-update protection and an audit record.
* **Collection times can't be in the future.** This is checked against the database clock and enforced by a CHECK constraint.
* **Storage locations are never deleted.** They are deactivated instead, which stops new transfers to them.

## Integrity and custody rules

| Action | Who |
|---|---|
| Verify a hash | Administrators, custodians, or an investigator assigned to the case (also allowed on closed cases) |
| Record the original hash | The same people, while the case is open and no hash exists yet |
| Correct a hash or a custody entry | Administrators and custodians |
| Custody transfer | Administrators and custodians: any valid action. Assigned investigators: Checked Out, Examined and Returned only |

* **Sample files** are read in 1 MiB chunks into `hashlib.sha256` (25 MB maximum, permitted file types only). They are never saved, opened by another program, or executed. While a request is being processed, Werkzeug may hold a large upload in a temporary file; that file is deleted automatically when the request ends.
* **The verification result** (Verified or Failed) is decided by the MySQL trigger `trg_hv_set_result`, never by Python. Every attempt is kept, failures included. The integrity status shown everywhere comes from the latest check of the current reference hash.
* **Hash corrections** add a new hash that supersedes the old one, with a reason. **Custody corrections** add a linked entry. In both cases the original record is never changed.
* **Custody transfers** go through `sp_transfer_evidence`.
  * Only actions valid from the item's current status are offered: for example, an archived item accepts nothing.
  * Going into storage (Received, Stored, Returned) requires a storage location.
  * A handover can't be dated in the future, or earlier than the item's last custody entry.
  * If someone else moved the item while your form was open, the transfer is refused instead of recording two conflicting handovers.

## Examination review, artifacts and PDF (FORGE-X 2.0 Phase 5, decision U3)

* **Workflow:** Pending → Start → In Progress → **Submit for review** → **Under Review** → **Approve** → **Completed**, or **Return for revision** → In Progress (the reviewer's note is shown to the examiner).
* **Independent review.** An examination is approved or returned by an **administrator or the case's lead investigator who isn't the examiner**. MySQL enforces this too:
  * the CHECK `chk_exam_independent`: the reviewer is never the examiner;
  * the trigger `trg_exam_finalised`: an examination becomes Completed only from Under Review, with a reviewer recorded.
* **Final means final.** The same trigger refuses **any** change to a completed or cancelled examination. Examinations completed before migration 007 stay valid; they're shown as *completed before independent review was introduced*.
* **Under review is frozen.** While Under Review, the examiner can't edit the record.
* **Case closure** waits for examinations Under Review as well (`sp_close_case`).
* **Artifacts** (Artifacts tab): files, registry entries, log entries, network indicators or emails found during the examination, with location, source evidence and an optional SHA-256.
  * They're append-only, with linked corrections.
  * MySQL accepts them only while the examination is open, and only for evidence linked to it.
* **Workspace tabs:** Overview, Evidence, Methodology, Findings (observations as *recorded fact*; findings and conclusion as *examiner interpretation*), Artifacts, History and Report.
* **Examination PDF:** built from the database on each request, in the same style as report PDFs.
  * It contains the examination and case details, evidence with reference hashes, methodology, observations, findings, conclusion, artifacts and custody references.
  * It's watermarked **NOT REVIEWED** until approved, and every download is audited.

## Examination and report rules

| Action | Who |
|---|---|
| Create an examination | Administrators, or an investigator assigned to the open case. The examiner must be an investigator on the case |
| Record notes, artifacts, start, submit for review, cancel, link evidence | The examiner, the case lead or an administrator, while the examination is Pending or In Progress |
| Approve or return an examination | An administrator or the case's lead investigator who isn't the examiner |
| Write a report | Administrators or investigators assigned to the open case |
| Edit (new version) or submit a report | Its author or an administrator, while it is a Draft |
| Approve or return a report | An administrator who is **not** the author (also the CHECK constraint `chk_rep_independent`) |
| Export a PDF | Anyone who can see the case, for any version |

* **Examination status** moves Pending → In Progress → Completed, or to Cancelled (with a reason). Completing requires tools and methods and findings; the CHECK constraint `chk_exam_state` enforces this in MySQL too. Completed and cancelled examinations are read-only.
* **Report versions are immutable.** Every save creates a new version through `sp_create_report_version`. New versions are allowed only while the report is a Draft (a trigger enforces this), and saving with no changes creates nothing.
* **Report workflow:** Draft → Under Review → Approved. A reviewer can return a report to Draft with a note.
* **Observations vs. interpretation.** Observations are shown as *recorded facts*. Findings and conclusions are shown as *examiner interpretation*, on the page and in the PDF.
* **PDFs** are built with ReportLab from database records each time they're requested, and are never stored. Each one contains:
  * the logo, report ID, case, author, dates, version and approval
  * the five report sections
  * the cited examinations
  * the referenced evidence with its current SHA-256, plus the note that a matching hash alone doesn't prove authenticity

  Anything other than the latest approved version carries a **NOT APPROVED** or **SUPERSEDED VERSION** watermark. Every export is audited.

## Audit logs and user administration

* **Audit logs** (`/audit-logs`) are for administrators and read-only auditors.
  * One timeline (`v_activity_feed`) of every audited action and login attempt.
  * Filters for date range, user, action, record type, outcome and record reference (such as an evidence ID or username).
  * A summary of the filtered events: totals, failures, denials and users involved.
* **"Audit trail" links** on case, evidence, examination and report pages open the timeline for that record.
* **CSV export** uses the same filters, up to 50,000 rows, in UTF-8 that opens correctly in Excel.
  * Cells that start with `=`, `+`, `-` or `@` are prefixed with an apostrophe. This stops *CSV formula injection*: someone could type a formula as a "username" on the login page, and it must never run in a spreadsheet.
  * Every export is itself audited.
* **The security view** shows:
  * accounts currently locked out by the login rate limit
  * repeated failed logins over the last 7 days, grouped by account and by IP address (many different usernames from one IP suggests password spraying)
  * actions refused in the last 7 days
* **Audit records can't be changed.** Triggers block edits and deletions, and the app's MySQL account has no UPDATE or DELETE permission on these tables.
* **Users & roles** has search, role and status filters, pagination, and an *inactive accounts* view (deactivated, never logged in, or no login for 30 days). It also lists recently reviewed access requests and shows each user's full, paginated activity history.

## Mock data, editing people, deleting cases

**Mock data.** One command adds three people and six synthetic cases. Everything is created through the normal stored procedures, so it follows every rule and appears in the audit log. It is safe to run again: a rerun finishes an interrupted run and never duplicates anything.

```cmd
flask --app run seed-mock
```

| Person | Username | Role |
|---|---|---|
| Shreya | `shreya` | Investigator (leads most cases) |
| Prachiti | `prachiti` | Evidence Custodian (registers and moves evidence) |
| Sejal | `sejal` | Read-Only Auditor |

Each person's temporary password is printed once; they must change it at first login. On a rerun, people who have never logged in get a fresh temporary password; anyone who has logged in keeps theirs. The cases include:

* a ransomware case with evidence, hash checks, custody moves, a completed examination and an approved report
* a phishing case with a failed and then passed hash check, and a pending examination
* an item still in transit
* a closed case
* two empty cases that can be used to demonstrate deletion

**Editing people.** Administrators: **Users & roles → a person → Edit details** changes the full name, email or username. Every change is audited. Roles, status and passwords have their own buttons on the same page.

**Deleting cases.** Administrators can delete a case registered by mistake: **case page → Overview → Delete case**, with a reason and the case reference typed to confirm. This works only when the case has **no evidence, examinations or reports** and is not closed. Those records are forensic history, which FORGE-X never deletes, so close such a case instead. The audit log keeps the deleted case's reference, title and the reason.

On a database built before this feature, run this once as root. `flask --app run check-db` tells you if it's missing:

```cmd
mysql -u root -p -e "source database/migrations/003_allow_case_delete.sql"
```

## REST API (FORGE-X 2.0 Phase 10)

A **read-only** JSON API at `/api/v1`: cases, evidence, chain of custody, examinations, reports and recorded indicators.

* **Authentication:** your browser session, or a **personal token** (**My account → API tokens**). A token is shown once, stored only as a hash, always expires (90 days at most) and can be revoked.
* **Permissions:** every endpoint uses the same case scope as the website.
* **Output:** fixed field lists, so evidence file content and internal values are never returned. Times are ISO 8601 with `+05:30`.
* **Limits and audit:** rate limits per user and per address for failed tokens. Token creation, revocation and failed attempts are audited.
* **Documentation:** OpenAPI is generated from the routes (`/api/v1/openapi.json`, and **Developer API** in the sidebar). A test fails if the two ever disagree.

Details are in **[docs/API.md](docs/API.md)**.

## Object storage (FORGE-X 2.0 Phase 9)

Evidence files can live on **local disk** (the default) or in an **S3-compatible object store**: MinIO or AWS S3. `EVIDENCE_STORAGE_BACKEND` chooses where new files go. Existing files are read from wherever `evidence_file_locations` (append-only) says they are.

**The same guarantees on both backends:**
* write-once: conditional writes on S3;
* SHA-256 computed as files arrive;
* private: never public or presigned URLs. Downloads stream through FORGE-X with the permission check, custody entry and audit row;
* `check-db` fails on a public bucket.

**Moving files between backends:**
```cmd
flask --app run storage-migrate --to s3 --by paulson
```
Each file is hashed before and after the copy, and its new location is recorded only if both match the recorded SHA-256. **The source is never deleted, so rollback is `--to local`.**

Setup, the least-privilege bucket policy, and the migration and rollback procedures are in **[docs/OBJECT_STORAGE.md](docs/OBJECT_STORAGE.md)**.

## Relationship graph (FORGE-X 2.0 Phase 8)

Open it from **Relationship graph** in the sidebar, or the button on a case's page.

**What it shows.** Only relationships stored in FORGE-X; nothing is inferred or suggested. The graph starts from one case:
* its investigators, evidence, examinations, reports and artifacts;
* the YARA rules matched by each item's latest completed scan;
* SHA-256 hash nodes that link items with **identical content**, including items in other cases you can see.

**Three kinds of link**, drawn differently and distinguishable without colour:

| Link | Drawn as | Means |
|---|---|---|
| Recorded link | solid line | Someone recorded it: an assignment, examined evidence, a citation |
| Scan result | dashed line | A YARA match from a scan that actually ran |
| Identical SHA-256 | dotted line | Items share a hash. Their bytes are identical; that says nothing about intent |

**Using it:**
* Select a node to see its details and a link to its record. Double-click, or press **E**, to **expand** it.
* Filter by node type and link type; find nodes by label.
* Zoom with the mouse wheel, the buttons or **+**/**−**; pan by dragging or with the arrow keys; **0** fits the graph to the window.
* **Relationships as a list** shows every link as a table, for screen readers and printing.

**Scope.** Every query uses the same case scope as the rest of FORGE-X, and expanding a node re-checks visibility. Records in cases you can't see never appear: not even as a count, and not through a shared hash. The graph stops at 250 nodes; expand single nodes to go further.

**Implementation.** `app/graph/` builds the graph on the server; `app/static/js/graph.js` draws it as dependency-free SVG, under the strict Content-Security-Policy. Record text is inserted with `textContent` only. The layout is deterministic, and expanding never moves nodes already on screen.

## YARA scanning (FORGE-X 2.0 Phase 7)

FORGE-X can scan **stored evidence files** with YARA rules, using **YARA-X**, the official successor to YARA from the same maintainers (VirusTotal). It was chosen over `yara-python` because `yara-python` has no Windows package for Python 3.14, while YARA-X installs without a compiler on any Python from 3.9.

```cmd
pip install yara-x psutil
flask --app run check-db          (shows "info  YARA worker: yara-x …")
```

### The rule library (**YARA rules** in the sidebar)

* **Who:** everyone signed in can read rules; only administrators create and change them.
* **Validation:** a rule is compiled in the isolated worker before it is saved; one that doesn't compile is refused.
* **Versions:** every change is a new, immutable version. Old versions stay viewable, and scans keep pointing at the version they used.
* **Scope:** a rule applies to *All cases*, or to *Selected cases* chosen on the rule's page. Rules can be enabled or disabled.

### Scanning

* **Where:** evidence page → **YARA scans** tab → **Run YARA scan**.
* **Who:** administrators, custodians and the case's investigators; open cases only.
* **What it uses:** the latest version of every enabled rule that applies to the case.

### Isolation and limits

YARA work **never runs in the web process.** Each validation or scan starts `app/yara/worker.py` as a new Python process:
* in isolated mode (`-I`, so `PYTHONPATH` is ignored);
* with a minimal environment: **no database password or secret key**;
* in an empty temporary folder;
* with `include` directives **disabled**, so a rule can't read other files.

The limits are **`YARA_TIMEOUT_SECONDS`** (60 by default, enforced by YARA-X and by a hard kill) and **`YARA_MEMORY_MB`** (512 by default). Memory is enforced by a `psutil` watchdog, and on Linux also by an OS limit; **on Windows, install `psutil`** or memory isn't limited. The stored file is opened read-only and never changed. Nothing is uploaded anywhere.

### What a scan records

* the worker re-hashes the file first, so the scan records whether it still **matches the recorded SHA-256**;
* the scanner version, duration and exact rule versions used;
* for each match: the rule, tags, metadata and the first offsets of each pattern.

*Completed* is recorded only when YARA-X actually finished. Otherwise the scan is *Failed*, *Timed out* or *Memory limit*, with the reason. If YARA-X isn't installed, nothing is recorded.

Scans, matches and rule versions are append-only (triggers and INSERT-only grants). A match is an indicator for the examiner, not a conclusion.

## Stability report and the test database (FORGE-X 2.0 Phase 6)

`docs/CORE_STABILITY_REPORT.md` is **generated from a real test run**, never typed by hand:

```cmd
python tools\stability_report.py
```

That's a read-only run, safe on your real database. For the **full** run, including the 12-step end-to-end workflow and every opt-in write test, build a separate test database first. Those tests add permanent records, so they must never touch `forge_x_db`:

```cmd
python tools\build_test_database.py
mysql -u root -p --default-character-set=utf8mb4 --table -e "source database/build/install_forge_x_test.sql"
set MYSQL_DATABASE=forge_x_test
flask --app run create-admin pytest_admin
python tools\stability_report.py --with-write-tests
set MYSQL_DATABASE=
```

* `build_test_database.py` copies the fresh-install scripts and grants with the database name changed. It refuses to target `forge_x_db`.
* `stability_report.py` refuses `--with-write-tests` unless `MYSQL_DATABASE` names another database.
* `MYSQL_DATABASE` set this way applies only to the current Command Prompt window.

**Phase 6 also added** read-only checks that run on your real database:
* the live schema matches `schema.sql`, which reveals a missed migration;
* data-consistency invariants: custody matches its latest entry; corrections stay on their own record; nothing was added after a case was closed; stored files match a recorded hash and exist in storage; code counters never fall behind.

## Changes after the 15 phases

| Change | Summary |
|---|---|
| Mock data | `flask --app run seed-mock` adds Shreya, Prachiti and Sejal and six synthetic cases through the normal procedures; safe to rerun |
| Editing people | Administrators correct a person's name, email or username (**Users & roles → Edit details**), audited |
| Deleting empty cases | Administrators delete a case registered by mistake, if it has no forensic history (D7). Needs migration 003 on older databases |
| Locking-read fix | Hash recording/verification and the "keep one administrator" check used locking reads on tables the app account can't lock (MySQL error 1142). Fixed, and a test now checks every locking read against the grants (D8) |

## Documentation

| Document | Contents |
|---|---|
| **Project report** | The academic report (separate document, exportable to Word or PDF) |
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | How each role uses FORGE-X |
| [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) | Every table, column, key and CHECK constraint, generated from `schema.sql` |
| [docs/TESTING.md](docs/TESTING.md) | Test inventory, security test matrix, manual acceptance checklist |
| [docs/VIVA_GUIDE.md](docs/VIVA_GUIDE.md) | Likely viva questions, with answers and where to show the proof |
| [docs/DEPLOY_CLOUDFLARE.md](docs/DEPLOY_CLOUDFLARE.md) | Publishing FORGE-X through Cloudflare Tunnel |
| `database/sample_queries.sql` | 32 explained SQL queries with expected results (demo data) |

The data dictionary is generated, never edited by hand. After changing `schema.sql`, regenerate it:

```cmd
python tools\make_data_dictionary.py
```

## Search and analytics

* **Global search** works from the top bar on every page.
  * It covers case references and titles; evidence IDs, descriptions and sites; examination codes, types and findings; report codes and titles; and, for administrators, users.
  * Typing a complete ID such as `FX-EV-2026-00001` opens that record directly, but only if you're allowed to see it.
  * 8 to 64 hexadecimal characters also search **recorded SHA-256 hashes** by prefix, including superseded ones, using index `idx_hashes_value`.
  * Investigators only ever find records from their own cases.
* **Analytics** (`/analytics`) has seven charts for the last 6, 12 or 24 months. Each is one SQL query, and **"SQL behind this chart"** shows it for the viva:

| Chart | SQL concepts |
|---|---|
| Lab activity per month | Recursive CTE, LEFT JOIN to grouped subqueries |
| Hash verification outcomes | Recursive CTE, conditional aggregation |
| Average days to close, by case type | AVG, TIMESTAMPDIFF, GROUP BY |
| Examinations by type and status | Pivot with conditional aggregation |
| Investigator workload | Window function `RANK() OVER`, correlated subquery, HAVING |
| Custody actions in the period | Date-range filter, `FIELD()` ordering |
| Items at each storage location | LEFT JOIN that keeps empty locations |

## Hosting on the internet (Cloudflare Tunnel)

FORGE-X can be published through **Cloudflare Tunnel**: the app and MySQL stay on your PC, and Cloudflare provides a public HTTPS address without opening any router ports. Full steps and a security checklist are in **[docs/DEPLOY_CLOUDFLARE.md](docs/DEPLOY_CLOUDFLARE.md)**.

```cmd
python serve.py                                   (window 1: production server on 127.0.0.1:8000)
cloudflared tunnel --url http://127.0.0.1:8000    (window 2: prints a public https://...trycloudflare.com address)
```

Set `FLASK_DEBUG=0`, `SESSION_COOKIE_SECURE=1` and `TRUST_CLOUDFLARE=1` in `.env` first.

## Optional demonstration data

The normal installation has only your administrator account. For a demonstration, such as walking through the sample queries in a viva, you can build a **separate** installation with synthetic data instead:

```cmd
mysql -u root -p --default-character-set=utf8mb4 --table -e "source database/install_demo.sql"
```

**This replaces the whole database,** including `paulson`. It adds 8 demo users, 12 cases, 20 evidence items and 59 custody entries, then runs the full 40-test `verify_demo.sql`.

The demo accounts have no usable password until you set one, for example `flask --app run set-password ananya.m` (Administrator).

| Username | Name | Role |
|---|---|---|
| `ananya.m` | Ananya Mehta | Administrator |
| `rohan.iyer` | Rohan Iyer | Investigator |
| `sara.khan` | Sara Khan | Investigator, Evidence Custodian |
| `priya.nair` | Priya Nair | Evidence Custodian |
| `dev.k` | Dev Kulkarni | Evidence Custodian |
| `meera.j` | Meera Joshi | Read-Only Auditor |
| `ishaan.v` | Ishaan Verma | Investigator |
| `kabir.shah` | Kabir Shah | Investigator (deactivated) |

To return to the single-administrator lab, run `install_all.sql` and `create-admin` again.

## Security summary

* **Passwords:** salted scrypt hashes from Werkzeug. A password lives in only one table at a time and is never logged.
* **Password rules:** at least 12 characters, with a letter and a number, without the username, and not a common password.
* **Login:** errors never say whether the username or the password was wrong. Response timing is equalized so it doesn't reveal which usernames exist. Every attempt is recorded in `login_attempts`.
* **Brute-force protection:** 5 failures per account or 20 per IP within 15 minutes pauses logging in. The counts are kept in MySQL.
* **Sessions:** the cookie is reissued at login and the session is server-invalidated through `users.session_version`. Logout, password changes and deactivation sign the user out everywhere.
* **Forms and cookies:** CSRF tokens on every form; `HttpOnly` and `SameSite=Lax` cookies, plus `Secure` when served over HTTPS.
* **Authorization:** checked on the server for every route. Refusals are audited as "Denied".
* **Safeguards:** you can't change your own roles (a database CHECK constraint backs this up), and FORGE-X can't lose its last administrator.
* **Database:** every query is parameterized. Flask connects with a least-privilege account: no DDL, and no UPDATE or DELETE on append-only tables.
* **Browser protections:** a strict Content Security Policy (scripts and styles only from this server; no inline styles, enforced by a test), `X-Frame-Options: DENY`, `nosniff`, and `no-store` on pages.
* **Errors:** pages never show stack traces, SQL or secrets. Unexpected errors show a short incident reference that also appears in the server log.

---

## Design decisions to remember

| Decision | Choice |
|---|---|
| D1 | Times are stored in lab local time (IST, UTC+05:30) |
| D2 | Evidence has an *In Transit* status between collection and receipt |
| D3 | Closing a case is final (there is no reopen) |
| D4 | Unassigning an investigator deletes the assignment row; the audit log keeps the history |
| D5 | Role changes are audited by a database trigger, not by Flask |
| D6 | Reports need an approver other than the author |
| D7 | Only empty cases (no evidence, examinations or reports, not closed) can be deleted, by administrators; everything with forensic history is closed instead |
| U4 | No case archiving: closing stays final (D3) |
| U5 | Case notes are append-only with linked corrections; cases have an optional due date (migration 004) |
| U8 | API times are ISO 8601 with the lab offset (+05:30) |
| D11 | API v1 read-only; personal tokens (SHA-256 stored, at most 90 days, revocable); responses from fixed field lists; OpenAPI generated from the routes |
| D10 | Object storage optional (local stays default); file locations append-only; migrations verified before and after and never delete the source |
| D9 | YARA via YARA-X (not yara-python): official successor, installs on Python 3.14 on Windows; all YARA work in an isolated worker process |
| U3 | Examinations get an independent review step (submit, approve or return), plus artifacts and a PDF (migration 007) |
| U1 | Evidence files are stored (write-once, outside the web root, 100 MB limit); verification can re-hash the stored copy (migration 005) |
| D8 | Locking reads (`SELECT ... FOR UPDATE`) are used only on tables where the app account has UPDATE or DELETE, because MySQL 8.0.22+ requires it; append-only tables are protected by locking the parent `evidence` row instead |
| A3 | Password recovery is admin-assisted (temporary password); there is no email reset |
| A5 | Notifications are deferred |
| A6 | Verification sample files are hashed and discarded, up to 25 MB |

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `'mysql' is not recognized` | Add MySQL's `bin` folder to PATH, then open a new terminal |
| `Can't connect to MySQL server` | Start the MySQL service (`services.msc`, then MySQL84 or MySQL80) |
| `Access denied for user 'forge_x_app'` | The password in `.env` doesn't match `app_user.sql`. Rerun `app_user.sql` |
| `FORGE-X cannot start: FORGE_X_SECRET_KEY...` | Generate a key (step 6) and put it in `.env` |
| `MYSQL_USER is root` | Use `forge_x_app`. The app refuses the root account on purpose |
| Pages look unstyled | Run `python tools\fetch_vendor.py` |
| `users.session_version column ... missing` | Run `database\migrations\001_add_session_version.sql` |
| Tests show "skipped" | Read the skip reason. Usually MySQL isn't running or `.env` is incomplete |

---

## Licences of bundled libraries

Bootstrap, Bootstrap Icons and Chart.js are MIT-licensed. The IBM Plex fonts (via Fontsource) use the SIL Open Font License 1.1. They are downloaded by `tools/fetch_vendor.py`, which writes `app/static/vendor/SHA256SUMS.txt`.
