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

The project is built in 15 phases. This package contains **Phases 1–12**.

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
| 12 | User administration and audit logs | 🟡 Written; run the tests below to confirm |
| 13 | Analytics and global search | ⬜ Pending |
| 14 | Testing and security review | ⬜ Pending |
| 15 | Documentation and submission | ⬜ Pending |

**About testing so far.** The code was written in an environment without MySQL, so the SQL scripts and the database tests have **not yet been run against a real MySQL server**. The non-database Flask tests were run there using small stand-ins for Flask-WTF, WTForms and mysql-connector. The steps below include verification scripts. Run them and record the actual results before relying on any phase.

---

## Technology

| Layer | Technology |
|---|---|
| Frontend | HTML5, CSS3, JavaScript, Bootstrap 5, Jinja2, Bootstrap Icons, Chart.js |
| Backend | Python 3.10+, Flask 3, Flask Blueprints, Flask-WTF (CSRF), Werkzeug password hashing |
| Database | MySQL 8.0.16+ (InnoDB), mysql-connector-python |
| Other | ReportLab (PDF, later phase), python-dotenv, pytest |

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
│   ├── schema.sql           22 tables, constraints, indexes
│   ├── triggers.sql         22 triggers
│   ├── views.sql            8 views
│   ├── procedures.sql       12 procedures, 2 functions
│   ├── seed_reference.sql   Roles, case/evidence/examination types, storage locations
│   ├── seed_demo.sql        Optional synthetic demo data (8 users, 12 cases, 20 evidence items)
│   ├── verify.sql           Data-independent PASS/FAIL checks (works on an empty lab)
│   ├── verify_demo.sql      Full 40-test suite (needs the demo data)
│   ├── sample_queries.sql   32 explained queries for the viva (results assume the demo data)
│   ├── transactions_demo.sql  COMMIT demonstrations (needs the demo data; changes data)
│   ├── app_user.sql         Least-privilege MySQL account (edit password first)
│   └── migrations/          001 (before Phase 6) and 002 (before Phase 9): run only on older databases
├── tests/                   pytest suite
├── tools/fetch_vendor.py    Downloads Bootstrap, icons, Chart.js and fonts locally
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
* **MySQL Community Server 8.0.16 or newer** (8.4 LTS recommended), plus **MySQL Workbench**.
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

**Expect about 88 passed and 30 skipped.** The exact split depends on your data.

* 6 tests skip because they check specific demo records, or need an evidence hash to test against. The skip reason says "demo data not installed" or "empty lab".
* 24 are the opt-in workflow tests described below.

With the demo data installed instead (`install_demo.sql`), more tests run.

**The opt-in workflow tests add `pytest_*` users, cases, evidence and storage locations to the database.** None of these can be deleted, by design. **Don't run them on a database where you want only `paulson`.** Use a separate demo or test installation:

```cmd
set FORGE_X_DB_WRITE_TESTS=1
pytest tests\test_auth_db.py tests\test_cases_write_db.py tests\test_evidence_write_db.py tests\test_integrity_custody_write_db.py tests\test_exams_reports_write_db.py tests\test_audit_write_db.py -v
set FORGE_X_DB_WRITE_TESTS=
```

**Built the database before Phase 6 or Phase 9 and kept it?** Run the migrations you're missing, once each, as root. `flask check-db` reports which ones are missing. A fresh `install_all.sql` doesn't need them.

```cmd
mysql -u root -p -e "source database/migrations/001_add_session_version.sql"
mysql -u root -p -e "source database/migrations/002_audit_storage_location.sql"
```

## Dashboard figures

Every figure is computed by a MySQL query when the page loads. Nothing is hard-coded or cached. Charts load from `/api/dashboard/<chart>` JSON endpoints.

| Figure | Rule |
|---|---|
| Total cases | All cases in scope |
| Open cases | Status is Open, In Progress or On Hold |
| Closed cases | Status is Closed. "Recently" means closed in the last 30 days |
| Total evidence | Evidence items belonging to cases in scope |
| Evidence in storage | Current status is In Storage |
| Under examination | Current status is Under Examination |
| Pending transfers | Current status is Checked Out or In Transit |
| Integrity | Latest check of each item's current reference hash (`v_evidence_integrity`). Pending means a hash is recorded but never checked; Not Verified means no hash is recorded |
| Needs attention | Overdue examinations, failed integrity checks, reports under review, and pending account requests (administrators only) |

**Who sees what:** administrators, auditors and custodians see the whole lab. Investigators see only the cases they are assigned to, and only their own recent activity.

**With the demo data (`install_demo.sql`), an administrator should see the following.** On the empty lab every figure starts at 0.

* 12 cases: 7 open (2 open, 4 in progress, 1 on hold) and 5 closed
* 20 evidence items: 10 in storage, 3 under examination, 1 pending transfer
* Integrity: 14 of 20 verified, 1 failed, 3 pending, 2 not verified

## Case management rules

| Action | Who |
|---|---|
| See a case | Administrators, auditors and custodians: every case. Investigators: only cases they're assigned to (others answer 404) |
| Register a case | Administrators (they choose the lead) and investigators (they become the lead) |
| Edit, change status, manage investigators, close | An administrator or the case's lead investigator |
| Anything on a closed case | Nobody: closed cases are read-only (decision D3), enforced by Flask and by a database trigger |

* **Case references** such as `FX-2026-0025` are generated inside the database by `sp_register_case`, in the same transaction as the lead assignment.
* **Editing is protected against lost updates.** The edit form carries the case's last-updated time. If someone else saved in between, your save is refused and nothing is overwritten.
* **Closing** goes through `sp_close_case`. It refuses while examinations are Pending or In Progress, or evidence is out of storage.
* **Audit records:** every change is written to `audit_logs`. Refused actions are recorded with outcome Denied.

## Evidence rules

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

## Examination and report rules

| Action | Who |
|---|---|
| Create an examination | Administrators, or an investigator assigned to the open case. The examiner must be an investigator on the case |
| Record notes, start, complete, cancel, link evidence | The examiner, the case lead or an administrator, while the examination is Pending or In Progress |
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
* **Browser protections:** a Content Security Policy (scripts only from this server), `X-Frame-Options: DENY`, `nosniff`, and `no-store` on pages.
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
