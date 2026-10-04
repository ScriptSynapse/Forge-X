"""Mock (synthetic) data for demonstrations: three more people and six cases.

Run once:   flask --app run seed-mock

Every record is created through the SAME services and stored procedures the
web pages use, acting as the right person each time. So codes are generated
by the database, custody entries and hashes follow every rule, and the audit
log shows who did what. Nothing is inserted behind the application's back.

All names, devices and hashes are invented. The records are real database
rows and, like any forensic history, cannot be deleted afterwards (apart from
cases that have no evidence, examinations or reports).
"""
import hashlib
import secrets
from datetime import timedelta

from flask import g

from .auth.passwords import password_problems
from .auth.services import load_user
from .db import query_one, query_value, set_audit_user

ROLE_IDS = {"Administrator": 1, "Investigator": 2, "Evidence Custodian": 3, "Read-Only Auditor": 4}

PEOPLE = [
    # (full name, username, email, role)
    ("Shreya", "shreya", "shreya@forge-x.example", "Investigator"),
    ("Prachiti", "prachiti", "prachiti@forge-x.example", "Evidence Custodian"),
    ("Sejal", "sejal", "sejal@forge-x.example", "Read-Only Auditor"),
]


class MockDataError(Exception):
    pass


def fake_sha256(label):
    """A deterministic, obviously synthetic SHA-256 for a mock item."""
    return hashlib.sha256(f"FORGE-X mock data: {label}".encode()).hexdigest()


def temporary_password(username):
    while True:
        candidate = f"Fx{secrets.token_urlsafe(9)}7"
        if not password_problems(candidate, username):
            return candidate


class _Actor:
    """Run a block of service calls as a given user (so audit rows name them)."""

    def __init__(self, app, user_id):
        self.app, self.user_id = app, user_id

    def __enter__(self):
        self.ctx = self.app.test_request_context("/mock-data")
        self.ctx.push()
        g.user = load_user(self.user_id)
        set_audit_user(self.user_id)      # database triggers (role changes) record this person too
        return g.user

    def __exit__(self, *exc):
        self.ctx.pop()


def _id(sql, params, what):
    value = query_value(sql, params)
    if value is None:
        raise MockDataError(f"Missing {what}. Build the database with install_all.sql first.")
    return value


def seed(app, admin_username, log=print):
    """Build (or finish building) the mock data. Every step first checks
    whether its result already exists, so running the command again after an
    interruption completes the rest instead of failing or duplicating."""
    from .access import Scope
    from .cases import services as cases
    from .custody import services as custody
    from .evidence import services as evidence
    from .examinations import services as exams
    from .integrity import services as integrity
    from .reports import services as reports
    from .users import services as users

    # ---- Pre-flight checks ------------------------------------------------------
    with app.test_request_context("/mock-data"):
        admin = query_one(
            "SELECT u.user_id FROM users u JOIN user_roles ur ON ur.user_id = u.user_id "
            "JOIN roles r ON r.role_id = ur.role_id WHERE u.username = %s AND u.account_status = 'Active' "
            "AND r.role_name = 'Administrator'", (admin_username,))
        if admin is None:
            raise MockDataError(f"{admin_username} is not an active administrator.")
        admin_id = admin["user_id"]
        loc = {name: _id("SELECT location_id FROM storage_locations WHERE location_name = %s AND is_active = TRUE",
                         (name,), f"storage location '{name}'")
               for name in ("Vault B, Shelf 3", "Evidence Room A, Locker 2", "Examination Lab 1")}
        ctype = {name: _id("SELECT case_type_id FROM case_types WHERE type_name = %s", (name,), f"case type '{name}'")
                 for name in ("Malware Incident", "Data Breach", "Insider Threat", "Unauthorized Access")}
        etype = {name: _id("SELECT evidence_type_id FROM evidence_types WHERE type_name = %s", (name,),
                           f"evidence type '{name}'")
                 for name in ("Disk Image", "Log File", "Digital Document", "USB Drive", "Mobile Device")}
        xtype = {name: _id("SELECT examination_type_id FROM examination_types WHERE type_name = %s", (name,),
                           f"examination type '{name}'")
                 for name in ("Disk Image Examination", "Log Analysis")}
        other_investigator = query_value(
            "SELECT MIN(u.user_id) FROM users u JOIN user_roles ur ON ur.user_id = u.user_id "
            "JOIN roles r ON r.role_id = ur.role_id WHERE r.role_name = 'Investigator' "
            "AND u.account_status = 'Active' AND u.username NOT IN ('shreya', 'prachiti', 'sejal')")
        now = query_value("SELECT NOW()")

    def as_user(uid):
        return _Actor(app, uid)

    # ---- People: create, or give a never-used mock account a fresh password ------
    created = {}
    with as_user(admin_id):
        for full_name, username, email, role in PEOPLE:
            existing = query_one("SELECT user_id, last_login_at FROM users WHERE username = %s", (username,))
            if existing is None:
                password = temporary_password(username)
                user_id = users.create_user(full_name, email, username, ROLE_IDS[role], password, True, admin_id)
                log(f"  Added {full_name} ({username}), {role}")
            elif existing["last_login_at"] is None:
                user_id, password = existing["user_id"], temporary_password(username)
                users.reset_password(user_id, password, admin_id)
                log(f"  {full_name} ({username}) already exists and has never logged in: new temporary password issued")
            else:
                user_id, password = existing["user_id"], None
                log(f"  {full_name} ({username}) already exists and has logged in: password left unchanged")
            created[username] = (user_id, password, role)
    shreya, prachiti = created["shreya"][0], created["prachiti"][0]

    # ---- Helpers that look before they act ------------------------------------
    def find_case(title):
        return query_value("SELECT case_reference FROM cases WHERE title = %s ORDER BY case_id LIMIT 1", (title,))

    def case_id(ref):
        return query_value("SELECT case_id FROM cases WHERE case_reference = %s", (ref,))

    def case_status(ref):
        return query_value("SELECT status FROM cases WHERE case_reference = %s", (ref,))

    def item(code):
        return query_one("SELECT evidence_id, current_status, current_custodian_id, current_location_id "
                         "FROM evidence WHERE evidence_code = %s", (code,))

    def move(code, action, to_user, location, reason, condition="Sealed, intact"):
        it = item(code)
        custody.transfer(it, g.user["user_id"], it["current_custodian_id"], action, to_user,
                         location, None if location else "Courier to the lab", condition, None, reason, None)

    def checks(code):
        return query_value("SELECT COUNT(*) FROM hash_verifications hv JOIN evidence_hashes h ON h.hash_id = hv.hash_id "
                           "WHERE h.evidence_id = %s", (item(code)["evidence_id"],))

    def find_exam(ref, type_id):
        return query_one("SELECT examination_id, examination_code, status, findings FROM examinations "
                         "WHERE case_id = %s AND examination_type_id = %s ORDER BY examination_id LIMIT 1",
                         (case_id(ref), type_id))

    # ---- Cases ------------------------------------------------------------------
    case_specs = [
        ("a", "Ransomware on accounts file server",
         "Accounts staff found encrypted files and a ransom note on file server FS-ACC-01.",
         "Malware Incident", "Critical", shreya),
        ("b", "Phishing emails sent to HR staff",
         "HR staff received emails that imitate the internal leave portal.", "Data Breach", "High",
         other_investigator or shreya),
        ("c", "Design files copied to a USB drive",
         "A USB drive with design files was found at a shared workstation.", "Insider Threat", "Medium", shreya),
        ("d", "Suspicious VPN logins at night",
         "VPN logins for two accounts happened between 01:00 and 03:00.", "Unauthorized Access", "High", shreya),
        ("e", "Phishing emails sent to HR staff (duplicate)",
         "Registered twice by mistake. Kept empty so the delete-case feature can be shown.", "Data Breach", "Low",
         shreya),
        ("f", "Lost phone data exposure check",
         "A staff phone was lost for a day and returned; checked for signs of access.", "Data Breach", "Low", shreya),
    ]
    ref = {}
    with as_user(admin_id):
        for key, title, description, type_name, priority, lead in case_specs:
            ref[key] = find_case(title) or cases.create_case(title, description, ctype[type_name], priority, lead,
                                                             admin_id)
        for key in ("a", "b"):
            if case_status(ref[key]) == "Open":
                cases.change_status(case_id(ref[key]), g.user, "In Progress")
        log(f"  Cases ready: {', '.join(ref.values())}")
    lead_b = query_value("SELECT user_id FROM case_investigators WHERE case_id = %s AND is_lead = TRUE",
                         (case_id(ref["b"]),))

    # ---- Evidence, hashes, custody (Prachiti, the custodian) --------------------
    evidence_specs = [
        ("image", "a", "Disk Image", "Forensic image of FS-ACC-01 system volume", "E01, 4 segments (synthetic)",
         256060514304, 9, "Accounts server room", "Sealed, intact", "FX-S-2001",
         fake_sha256("FS-ACC-01 image"), "Manual", "Copied from the imaging tool's acquisition report"),
        ("fwlog", "a", "Log File", "Firewall log export, last 7 days", "CSV export (synthetic)", 31457280, 8,
         "Perimeter firewall", "Exported to sealed USB", "FX-S-2002", fake_sha256("firewall log"), "Computed", None),
        ("emails", "b", "Digital Document", "Phishing email samples (.eml)", "9 messages (synthetic)", 2097152, 7,
         "Mail gateway quarantine", "Exported to sealed USB", "FX-S-2003", fake_sha256("phishing emails"),
         "Computed", None),
        ("usb", "c", "USB Drive", "32 GB USB drive found at shared workstation", "Serial SYN-USB-5521 (synthetic)",
         32010928128, 2, "Design studio, desk 4", "Bagged", "FX-S-2004", None, None, None),
        ("phone", "f", "Mobile Device", "Returned staff phone", "Android phone, asset tag SYN-PH-0450 (synthetic)",
         None, 6, "Reception", "Powered off, Faraday bag", "FX-S-2005", fake_sha256("staff phone"), "Computed", None),
    ]
    ev = {}
    with as_user(prachiti):
        for (key, case_key, type_name, description, source, size, hours_ago, site, condition, seal,
             hash_value, hash_source, hash_notes) in evidence_specs:
            ev[key] = query_value("SELECT evidence_code FROM evidence WHERE case_id = %s AND description = %s",
                                  (case_id(ref[case_key]), description))
            if ev[key] is None and case_status(ref[case_key]) != "Closed":
                ev[key] = evidence.register_evidence(
                    g.user, case_id(ref[case_key]), etype[type_name], description, source, size,
                    now - timedelta(hours=hours_ago), prachiti, site, condition, seal,
                    hash_value, hash_source, hash_notes)
        for key in ("image", "fwlog", "emails", "phone"):
            if item(ev[key])["current_status"] == "In Transit":
                move(ev[key], "Received", prachiti, loc["Evidence Room A, Locker 2"], "Arrived at the lab")
        for key in ("fwlog", "phone"):
            it = item(ev[key])
            if it["current_status"] == "In Storage" and it["current_location_id"] != loc["Vault B, Shelf 3"]:
                move(ev[key], "Stored", prachiti, loc["Vault B, Shelf 3"], "Intake complete")
        # Integrity checks: the image verifies; the email sample first fails (wrong file), then verifies.
        if not checks(ev["image"]):
            integrity.verify(item(ev["image"])["evidence_id"], prachiti, fake_sha256("FS-ACC-01 image"),
                             "Manual entry", notes="Recomputed at intake")
        if not checks(ev["emails"]):
            eid = item(ev["emails"])["evidence_id"]
            integrity.verify(eid, prachiti, fake_sha256("wrong sample file"), "Manual entry",
                             notes="Hash of the wrong export; rechecked below")
            integrity.verify(eid, prachiti, fake_sha256("phishing emails"), "Manual entry", notes="Recomputed at intake")
        if item(ev["image"])["current_status"] == "In Storage":
            move(ev["image"], "Checked Out", shreya, loc["Examination Lab 1"], "For disk image examination")
        log(f"  Evidence ready: {', '.join(ev.values())}")

    # ---- Examination and report (Shreya, the investigator) ----------------------
    report_title = "Ransomware on FS-ACC-01: findings"
    with as_user(shreya):
        if item(ev["image"])["current_status"] == "Checked Out":
            move(ev["image"], "Examined", shreya, loc["Examination Lab 1"],
                 "Examination started on a verified working copy", "Seal opened, resealed as FX-S-2101")
        x1 = find_exam(ref["a"], xtype["Disk Image Examination"])
        if x1 is None:
            exams.create_examination(case_id(ref["a"]), xtype["Disk Image Examination"], shreya,
                                     (now + timedelta(days=5)).date(), [item(ev["image"])["evidence_id"]], shreya)
            x1 = find_exam(ref["a"], xtype["Disk Image Examination"])
        if x1["status"] == "Pending":
            exams.start(x1["examination_id"], g.user)
        if x1["findings"] is None and x1["status"] in ("Pending", "In Progress"):
            exams.update_record(
                x1["examination_id"], g.user,
                "Image mounted read-only from a verified working copy; scheduled tasks, startup entries and recently "
                "modified files reviewed.",
                "A scheduled task created two days ago launches an unsigned program every hour. 1,842 files in the "
                "accounts share have the extension .lockacc.",
                "The evidence is consistent with ransomware started by the scheduled task.",
                "How the program first reached the server has not been established yet.")
        if find_exam(ref["a"], xtype["Disk Image Examination"])["status"] == "In Progress":
            exams.complete(x1["examination_id"], g.user)
        sections = {"methodology": f"Disk image examination on a verified working copy ({x1['examination_code']}).",
                    "observations": "An hourly scheduled task launches an unsigned program; 1,842 files carry the "
                                    ".lockacc extension.",
                    "findings": "Consistent with ransomware started by the scheduled task.",
                    "conclusions": "The file server was encrypted by ransomware; initial access is still unknown.",
                    "limitations": "Only the system volume was examined."}
        rp = query_value("SELECT report_code FROM forensic_reports WHERE case_id = %s AND title = %s",
                         (case_id(ref["a"]), report_title))
        if rp is None:
            rp = reports.create_report(case_id(ref["a"]), report_title, shreya, dict(sections),
                                       [x1["examination_id"]])
        report = reports.get_report(Scope(g.user), rp)
        latest = query_value("SELECT MAX(version_no) FROM report_versions WHERE report_id = %s", (report["report_id"],))
        if report["status"] == "Draft" and latest == 1:
            sections["conclusions"] += " The scheduled task should be removed from every accounts server."
            reports.save_version(report, g.user, sections, "Added a recommendation")
        if report["status"] == "Draft":
            reports.submit(report["report_id"], g.user)
        log(f"  Examination {x1['examination_code']} completed; report {rp} submitted")

    with as_user(admin_id):
        report = reports.get_report(Scope(g.user), rp)
        if report["status"] == "Under Review":
            reports.approve(report["report_id"], g.user)
        if case_status(ref["f"]) != "Closed":
            cases.close_case(case_id(ref["f"]), "No sign of access while the phone was lost.", admin_id)
        log(f"  {rp} approved by {admin_username}; {ref['f']} closed")

    with as_user(lead_b):
        x2 = find_exam(ref["b"], xtype["Log Analysis"])
        if x2 is None:
            exams.create_examination(case_id(ref["b"]), xtype["Log Analysis"], lead_b,
                                     (now + timedelta(days=3)).date(), [item(ev["emails"])["evidence_id"]], lead_b)
            x2 = find_exam(ref["b"], xtype["Log Analysis"])
    log(f"  Examination {x2['examination_code']} pending on {ref['b']}; "
        f"{ref['d']} and {ref['e']} have no evidence (deletable)")
    return created
