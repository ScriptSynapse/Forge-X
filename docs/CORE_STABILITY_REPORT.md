# FORGE-X Core Stability Report

**Not generated yet.** This report is written by `tools/stability_report.py` from a real test run on your machine, so it never contains numbers typed by hand. Generate it as described below; the tool overwrites this file.

## How to generate it

**1. Read-only run** (any database, including your real `forge_x_db`; changes nothing):

```cmd
python tools\stability_report.py
```

**2. Full run, including the 12-step end-to-end workflow and every opt-in write test.** These tests add permanent records, so they run against a **separate test database**:

```cmd
python tools\build_test_database.py
mysql -u root -p --default-character-set=utf8mb4 --table -e "source database/build/install_forge_x_test.sql"
set MYSQL_DATABASE=forge_x_test
flask --app run create-admin pytest_admin
python tools\stability_report.py --with-write-tests
set MYSQL_DATABASE=
```

`set MYSQL_DATABASE=` at the end returns this window to your real database. The setting only ever applies to the current Command Prompt window.

## What the report contains

* **Environment:** database, MySQL, Python and package versions.
* **Results:** passed, failed and skipped counts, overall and by area.
* **The end-to-end workflow:** authenticate → case → investigator → evidence → SHA-256 → verification → custody → examination → methodology and findings → independent approval → examination report → audit log.
* **Checklists:** the security and database requirements from the Phase 6 plan, each mapped to the tests that prove it.
* **Remaining defects:** every failing test, with its message.
* **Skipped tests**, grouped by reason.
* **The full `flask check-db` output**, the **pytest warnings**, and the known limitations.
