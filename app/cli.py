"""Command-line tools, run with `flask --app run <command>`."""
import os

import click
from flask import current_app

from . import audit
from .auth.passwords import hash_password, password_problems
from .db import (EXPECTED_OBJECTS, DatabaseError, can_delete_audit_logs, check_connection, execute, query_one,
                 query_value, transaction, triggers_active)

MIN_VERSION = (8, 0, 16)


def register_cli(app):
    @app.cli.command("check-db")
    def check_db():
        """Verify the MySQL connection, schema objects and least privilege."""
        ok = True

        def report(passed, label, detail=""):
            nonlocal ok
            ok = ok and passed
            mark = click.style("PASS", fg="green") if passed else click.style("FAIL", fg="red")
            click.echo(f"  [{mark}] {label}" + (f": {detail}" if detail else ""))

        click.echo("FORGE-X database check")
        try:
            info = check_connection()
        except DatabaseError as err:
            click.echo(click.style("  Could not connect to MySQL.", fg="red"))
            click.echo(f"  Reason: {err.detail or err}")
            click.echo("  Check that the MySQL service is running and that MYSQL_* values in .env are correct.")
            raise SystemExit(1)

        report(True, "Connected", f"{info['current_user_name']} -> {info['database_name']}")
        report(info["version_tuple"] >= MIN_VERSION, "MySQL version",
               f"{info['server_version']} (need 8.0.16+ for CHECK constraints)")
        report(not info["current_user_name"].lower().startswith("root@"), "Not using root",
               info["current_user_name"])
        expected_tz = current_app.config["DB_TIME_ZONE"]
        report(info["time_zone"] == expected_tz, "Session time zone",
               f"{info['time_zone']} (expected {expected_tz})")

        for name, expected in EXPECTED_OBJECTS.items():
            found = info["objects"][name]
            report(found == expected, f"{name.capitalize()}", f"{found} (expected {expected})")

        try:
            active = triggers_active()
            report(active is not False, "Triggers working",
                   "hash verification result set by trg_hv_set_result (test rolled back)" if active
                   else ("no evidence hash to test with" if active is None
                         else "trigger did not fire: run database/triggers.sql as root"))
        except DatabaseError as err:
            report(False, "Triggers working", err.detail or str(err))

        has_column = query_value(
            "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'users' AND COLUMN_NAME = 'session_version'")
        report(bool(has_column), "users.session_version column (Phase 6)",
               "present" if has_column else "missing: run database/migrations/001_add_session_version.sql as root")

        try:
            execute("DELETE FROM cases WHERE 1 = 0")       # matches nothing; only the privilege is tested
            can_delete_cases = True
        except DatabaseError:
            can_delete_cases = False
        report(can_delete_cases, "Delete empty cases (DELETE on cases)",
               "granted" if can_delete_cases else "missing: run database/migrations/003_allow_case_delete.sql as root")

        has_notes = query_value("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() "
                                "AND TABLE_NAME = 'case_notes'")
        has_due = query_value("SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
                              "AND TABLE_NAME = 'cases' AND COLUMN_NAME = 'due_date'")
        report(bool(has_notes and has_due), "Case notes and due dates (FORGE-X 2.0 Phase 2)",
               "present" if has_notes and has_due else
               "missing: run database/migrations/004_case_notes_and_due_date.sql as root")

        has_files = query_value("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() "
                                "AND TABLE_NAME = 'evidence_files'")
        report(bool(has_files), "Stored evidence files (FORGE-X 2.0 Phase 3)",
               "present" if has_files else "missing: run database/migrations/005_evidence_files.sql as root")
        from .storage import StorageError, get_storage
        storage_ok, storage_message = get_storage("local").health()
        report(storage_ok, "Evidence storage folder (EVIDENCE_STORAGE_DIR)", storage_message)
        has_locations = query_value("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() "
                                    "AND TABLE_NAME = 'evidence_file_locations'")
        report(bool(has_locations), "Evidence file locations (FORGE-X 2.0 Phase 9)",
               "present" if has_locations else "missing: run database/migrations/009_evidence_file_locations.sql as root")
        backend = current_app.config["EVIDENCE_STORAGE_BACKEND"]
        if backend == "s3":
            try:
                s3_ok, s3_message = get_storage("s3").health()
            except StorageError as err:
                s3_ok, s3_message = False, str(err)
            report(s3_ok, "Object storage for new evidence files (S3)", s3_message)
        else:
            click.echo("  info  New evidence files go to local storage (EVIDENCE_STORAGE_BACKEND=local)")

        has_yara = query_value("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() "
                               "AND TABLE_NAME = 'yara_rules'")
        report(bool(has_yara), "YARA tables (FORGE-X 2.0 Phase 7)",
               "present" if has_yara else "missing: run database/migrations/008_yara.sql as root")
        from .yara.runner import psutil as _psutil, run_worker
        ping = run_worker({"mode": "ping"}, timeout=20)
        click.echo(f"  info  YARA worker: {ping.get('scanner_version') if ping.get('ok') else ping.get('error')}")
        click.echo("  info  YARA memory limit: " + ("psutil watchdog" if _psutil else
                   "OS limit (Linux)" if os.name != "nt" else "NOT enforced: pip install psutil"))

        has_location_audit = query_value(
            "SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = 'audit_logs' AND COLUMN_NAME = 'entity_type' AND COLUMN_TYPE LIKE %s",
            ("%'Storage location'%",))
        report(bool(has_location_audit), "audit_logs entity type 'Storage location' (Phase 9)",
               "present" if has_location_audit else "missing: run database/migrations/002_audit_storage_location.sql as root")

        try:
            cases = query_value("SELECT COUNT(*) FROM cases")
            report(True, "Read access", f"{cases} cases visible")
        except DatabaseError as err:
            report(False, "Read access", err.detail or str(err))

        try:
            report(not can_delete_audit_logs(), "Least privilege",
                   "DELETE on audit_logs is denied, as intended")
        except DatabaseError as err:
            report(False, "Least privilege", err.detail or str(err))

        click.echo()
        if ok:
            click.echo(click.style("All checks passed.", fg="green"))
        else:
            click.echo(click.style("Some checks failed. Fix them before continuing.", fg="red"))
            raise SystemExit(1)


    @app.cli.command("set-password")
    @click.argument("username")
    @click.option("--temporary", is_flag=True,
                  help="Make the user choose a new password at next login.")
    def set_password(username, temporary):
        """Set a user's password (the seed accounts start without one).

        The password is typed at a hidden prompt, hashed, and only the hash is
        stored. It never appears in the terminal history, a file or the logs.
        """
        user = query_one("SELECT user_id, username, account_status FROM users WHERE username = %s", (username,))
        if user is None:
            click.echo(click.style(f"No user named {username!r}.", fg="red"))
            raise SystemExit(1)
        password = click.prompt("New password", hide_input=True, confirmation_prompt=True)
        problems = password_problems(password, user["username"])
        if problems:
            click.echo(click.style("Password not accepted: " + " ".join(problems), fg="red"))
            raise SystemExit(1)
        with transaction() as cur:
            cur.execute(
                "UPDATE users SET password_hash = %s, must_change_password = %s, "
                "session_version = session_version + 1 WHERE user_id = %s",
                (hash_password(password), temporary, user["user_id"]),
            )
            audit.record("user.password_set", "User", user["username"], user_id=None, cursor=cur,
                         details="Set from the command line" + (" (temporary)" if temporary else ""))
        click.echo(click.style(f"Password set for {user['username']}.", fg="green")
                   + ("" if user["account_status"] == "Active" else " Note: this account is deactivated."))


    @app.cli.command("create-admin")
    @click.argument("username")
    @click.option("--name", "full_name", prompt="Full name", help="The administrator's full name.")
    @click.option("--email", prompt="Email", help="The administrator's email address.")
    def create_admin(username, full_name, email):
        """Create the FIRST administrator of an empty installation.

        Refused while any active administrator exists: after that, accounts
        are created by an administrator in the web interface, where every
        step is checked and audited. The password is typed at a hidden
        prompt; only its hash is stored.
        """
        import re
        from .auth.forms import EMAIL_RE, USERNAME_RE
        from .db import ConstraintViolation

        admins = query_value(
            "SELECT COUNT(*) FROM users u JOIN user_roles ur ON ur.user_id = u.user_id "
            "JOIN roles r ON r.role_id = ur.role_id "
            "WHERE r.role_name = 'Administrator' AND u.account_status = 'Active'")
        if admins:
            click.echo(click.style("An active administrator already exists. Create further accounts from "
                                   "Users & roles in the web interface.", fg="red"))
            raise SystemExit(1)
        full_name, email = full_name.strip(), email.strip().lower()
        if not re.match(USERNAME_RE, username):
            click.echo(click.style("Username must be 3 to 30 letters, numbers, dots or underscores.", fg="red"))
            raise SystemExit(1)
        if not re.match(EMAIL_RE, email) or len(full_name) < 2:
            click.echo(click.style("Enter a full name and a valid email address.", fg="red"))
            raise SystemExit(1)
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
        problems = password_problems(password, username)
        if problems:
            click.echo(click.style("Password not accepted: " + " ".join(problems), fg="red"))
            raise SystemExit(1)
        role_id = query_value("SELECT role_id FROM roles WHERE role_name = 'Administrator'")
        if role_id is None:
            click.echo(click.style("The roles table is empty. Run database/install_all.sql first.", fg="red"))
            raise SystemExit(1)
        try:
            with transaction() as cur:
                cur.execute("INSERT INTO users (full_name, email, username, password_hash) VALUES (%s, %s, %s, %s)",
                            (full_name, email, username, hash_password(password)))
                user_id = cur.lastrowid
                # assigned_by NULL marks the bootstrap administrator (allowed by the schema).
                # Trigger trg_ur_audit_insert writes the role.assign audit row.
                cur.execute("INSERT INTO user_roles (user_id, role_id, assigned_by) VALUES (%s, %s, NULL)",
                            (user_id, role_id))
                audit.record("user.create", "User", username, user_id=None, cursor=cur,
                             details="First administrator created from the command line")
        except ConstraintViolation:
            click.echo(click.style("That username or email is already in use.", fg="red"))
            raise SystemExit(1)
        click.echo(click.style(f"Administrator {username} created. Log in at http://127.0.0.1:5000/login", fg="green"))


    @app.cli.command("seed-mock")
    @click.option("--admin", "admin_username", default="paulson", show_default=True,
                  help="The administrator who registers the cases and approves the report.")
    def seed_mock(admin_username):
        """Add Shreya, Prachiti and Sejal plus six mock cases (synthetic data).

        Safe to run again: each step checks whether it is already done, so a
        rerun finishes an interrupted run instead of duplicating anything.
        Everything goes through the normal stored procedures and services.
        """
        from .mockdata import MockDataError, seed
        click.echo("Adding mock data...")
        try:
            created = seed(app, admin_username, log=click.echo)
        except MockDataError as err:
            click.echo(click.style(str(err), fg="red"))
            raise SystemExit(1)
        click.echo(click.style("Done. Temporary passwords (shown only now; each person must change it at first login):",
                               fg="green"))
        for username, (_uid, password, role) in created.items():
            click.echo(f"  {username:10} {password or '(unchanged: already in use)'}   ({role})")


    # ------------------------------------------------------------------
    # Evidence storage (FORGE-X 2.0 Phase 9)
    # ------------------------------------------------------------------
    @app.cli.command("storage-status")
    def storage_status():
        """Show where every stored evidence file is (local or s3)."""
        from .storage.migrate import status
        rows = status()
        counts = {}
        for row in rows:
            counts[row["backend"]] = counts.get(row["backend"], 0) + 1
        click.echo(f"{len(rows)} stored file(s): " + (", ".join(f"{n} on {b}" for b, n in sorted(counts.items())) or "none"))
        click.echo(f"New files go to: {current_app.config['EVIDENCE_STORAGE_BACKEND']}")

    @app.cli.command("storage-migrate")
    @click.option("--to", "target", type=click.Choice(["local", "s3"]), required=True, help="Backend to move files to.")
    @click.option("--by", "admin_username", required=True, help="The administrator responsible (recorded on every move).")
    @click.option("--limit", type=int, default=None, help="Move at most this many files.")
    @click.option("--dry-run", is_flag=True, help="Only check source hashes and list what would move.")
    def storage_migrate(target, admin_username, limit, dry_run):
        """Copy evidence files to another backend, verifying SHA-256 before and after.

        Never deletes the source copy: to roll back, run it again with --to
        pointing back. Every move is recorded in evidence_file_locations and
        in the audit log."""
        from .storage import StorageError
        from .storage.migrate import migrate
        admin = query_one(
            "SELECT u.user_id FROM users u JOIN user_roles ur ON ur.user_id = u.user_id JOIN roles r "
            "ON r.role_id = ur.role_id WHERE u.username = %s AND u.account_status = 'Active' "
            "AND r.role_name = 'Administrator'", (admin_username,))
        if admin is None:
            click.echo(click.style(f"{admin_username} is not an active administrator.", fg="red"))
            raise SystemExit(1)
        try:
            counts = migrate(target, admin["user_id"], limit=limit, dry_run=dry_run, log=click.echo)
        except StorageError as err:
            click.echo(click.style(str(err), fg="red"))
            raise SystemExit(1)
        click.echo(f"Done: {counts['moved']} copied, {counts['already_there']} already there, "
                   f"{counts['skipped']} skipped (source problem), {counts['failed']} failed.")
        if counts["skipped"] or counts["failed"]:
            raise SystemExit(1)
