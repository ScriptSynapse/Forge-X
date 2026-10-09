"""Template helpers shared by every page: navigation, status badge colours,
date formatting and small utilities.

Navigation is defined once here. An item is shown only when
  1. its route exists (so a link is never dead, even between phases), and
  2. the signed-in user holds one of its roles (if it lists any).
Hiding a link is only a convenience: every route also checks permissions
on the server (Phase 6).
"""
from dataclasses import dataclass, field
from datetime import date, datetime

from flask import current_app, g, request


@dataclass(frozen=True)
class NavItem:
    label: str
    endpoint: str
    icon: str                                   # Bootstrap Icons name
    roles: frozenset = field(default_factory=frozenset)

    @property
    def blueprint(self):
        return self.endpoint.split(".", 1)[0]


ADMIN = "Administrator"
AUDITOR = "Read-Only Auditor"

NAV_SECTIONS = (
    ("Workspace", (
        NavItem("Dashboard", "dashboard.index", "grid"),
        NavItem("Cases", "cases.list_cases", "folder2"),
        NavItem("Evidence Vault", "evidence.list_evidence", "device-hdd"),
        NavItem("Chain of custody", "custody.index", "link-45deg"),
        NavItem("Examinations", "examinations.list_examinations", "clipboard-data"),
        NavItem("Reports", "reports.list_reports", "file-earmark-text"),
        NavItem("Analytics", "analytics.index", "bar-chart-line"),
        NavItem("Search", "search.index", "search"),
        NavItem("Relationship graph", "graph.index", "diagram-3"),
        NavItem("YARA rules", "yara.rules", "bug"),
        NavItem("Developer API", "api_web.docs", "braces"),
    )),
    ("Administration", (
        NavItem("Audit logs", "audit.index", "list-check", frozenset({ADMIN, AUDITOR})),
        NavItem("Users & roles", "users.index", "people", frozenset({ADMIN})),
        NavItem("Storage locations", "locations.index", "box-seam", frozenset({ADMIN})),
        NavItem("Settings", "settings.index", "sliders"),
    )),
)

# Status value -> badge colour class (see static/css/forge-x.css)
STATUS_TONES = {
    # cases
    "Open": "b-blue", "In Progress": "b-cyan", "On Hold": "b-amber", "Closed": "b-slate",
    # evidence
    "In Transit": "b-amber", "In Storage": "b-blue", "Checked Out": "b-amber",
    "Under Examination": "b-cyan", "Released": "b-slate", "Archived": "b-slate",
    # integrity
    "Verified": "b-green", "Failed": "b-red", "Pending": "b-amber", "Not Verified": "b-slate",
    # examinations
    "Completed": "b-green", "Cancelled": "b-slate",
    # reports
    "Draft": "b-slate", "Under Review": "b-amber", "Approved": "b-green",
    # accounts / requests
    "Active": "b-green", "Deactivated": "b-slate", "Rejected": "b-red",
    # audit outcomes
    "Success": "b-green", "Failure": "b-red", "Denied": "b-amber",
}

PRIORITY_CLASSES = {"Low": "p-low", "Medium": "p-med", "High": "p-high", "Critical": "p-crit"}


def current_user():
    """The signed-in user (a dict set by the auth layer in Phase 6), or None."""
    return g.get("user")


def user_roles():
    user = current_user()
    return set(user.get("roles", ())) if user else set()


def has_endpoint(endpoint):
    return endpoint in current_app.view_functions


def build_navigation():
    roles = user_roles()
    active_bp = request.blueprint if request else None
    sections = []
    for title, items in NAV_SECTIONS:
        visible = [
            {"label": i.label, "endpoint": i.endpoint, "icon": i.icon, "active": i.blueprint == active_bp}
            for i in items
            if has_endpoint(i.endpoint) and (not i.roles or i.roles & roles)
        ]
        if visible:
            sections.append({"title": title, "items": visible})
    return sections


# --- filters ---------------------------------------------------------------
def fmt_datetime(value, fmt="%d %b %Y %H:%M"):
    if not value:
        return ""
    if isinstance(value, (datetime, date)):
        return value.strftime(fmt)
    return str(value)


def fmt_date(value):
    return fmt_datetime(value, "%d %b %Y")


def tone(value):
    return STATUS_TONES.get(value, "b-slate")


def priority_class(value):
    return PRIORITY_CLASSES.get(value, "p-low")


# Integrity results as shown on screen (decision U2). The database keeps its
# values (Verified / Failed / Pending / Not Verified); only the wording differs.
INTEGRITY_LABELS = {
    "Verified": "Verified",
    "Failed": "Integrity mismatch",
    "Pending": "Pending verification",
    "Not Verified": "Verification unavailable",
}


def integrity_label(value):
    return INTEGRITY_LABELS.get(value, value)


def dict_without(mapping, *keys):
    """A copy of a dict without some keys (for links that remove one filter)."""
    return {k: v for k, v in mapping.items() if k not in keys}


def filesize(num_bytes):
    """476.9 GB style size (decimal units, as drive makers use)."""
    if num_bytes is None:
        return ""
    size = float(num_bytes)
    for unit in ("bytes", "KB", "MB", "GB", "TB"):
        if size < 1000 or unit == "TB":
            return f"{int(size):,} bytes" if unit == "bytes" else f"{size:,.1f} {unit}"
        size /= 1000
    return f"{num_bytes} bytes"


def initials(name):
    parts = [p for p in (name or "").split() if p]
    if not parts:
        return "?"
    return (parts[0][0] + (parts[-1][0] if len(parts) > 1 else "")).upper()


def register_template_helpers(app):
    app.add_template_filter(fmt_datetime, "datetime")
    app.add_template_filter(fmt_date, "date")
    app.add_template_filter(tone, "tone")
    app.add_template_filter(priority_class, "priority_class")
    app.add_template_filter(initials, "initials")
    app.add_template_filter(filesize, "filesize")
    app.add_template_filter(integrity_label, "integrity_label")
    app.add_template_filter(dict_without, "dict_without")

    @app.context_processor
    def inject_globals():
        return {
            "app_name": "FORGE-X",
            "app_full_name": "Digital Forensics Evidence Management System",
            "app_tagline": "Secure. Track. Investigate. Maintain Integrity.",
            "current_user": current_user(),
            "has_endpoint": has_endpoint,
            "navigation": build_navigation,
            "current_year": datetime.now().year,
            # Administrators and auditors get "Audit trail" links on record pages.
            "can_view_audit": bool({ADMIN, AUDITOR} & user_roles()),
        }
