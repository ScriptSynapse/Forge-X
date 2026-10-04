"""Dashboard page and the JSON endpoints its charts load from."""
from flask import Blueprint, abort, g, jsonify, render_template

from ..access import can_create_case, can_register_evidence
from ..auth.decorators import login_required
from . import services

bp = Blueprint("dashboard", __name__)

ACTION_LABELS = {
    "login": "Logged in", "login.attempt": "Login attempt", "logout": "Logged out",
    "account.request": "Requested an account", "account.approve": "Approved account request",
    "account.reject": "Rejected account request", "role.assign": "Granted a role", "role.revoke": "Removed a role",
    "user.create": "Created a user", "user.activate": "Activated a user", "user.deactivate": "Deactivated a user",
    "user.password_change": "Changed password", "user.password_reset": "Reset a password",
    "user.password_set": "Password set (command line)", "access.denied": "Access denied",
    "case.create": "Registered a case", "case.update": "Updated a case", "case.close": "Closed a case",
    "case.assign_investigator": "Assigned an investigator", "case.set_lead": "Changed the lead investigator",
    "case.remove_investigator": "Removed an investigator", "evidence.register": "Registered evidence",
    "custody.transfer": "Recorded custody transfer", "custody.correct": "Recorded custody correction",
    "hash.verify": "Verified a hash", "report.create": "Created a report", "report.revise": "Saved a report version",
    "report.submit": "Submitted a report for review", "report.approve": "Approved a report",
}


@bp.get("/dashboard")
@login_required
def index():
    scope = services.Scope(g.user)
    return render_template(
        "dashboard/index.html",
        scope=scope,
        stats=services.summary(scope),
        attention=services.attention(scope),
        activity=services.recent_activity(scope),
        action_labels=ACTION_LABELS,
        as_of=services.server_time(),
        can_create_case=can_create_case(g.user),
        can_register_evidence=can_register_evidence(g.user),
    )


@bp.get("/api/dashboard/<chart>")
@login_required
def chart_data(chart):
    builder = services.CHARTS.get(chart)
    if builder is None:
        abort(404)
    data = builder(services.Scope(g.user))
    data["chart"] = chart
    return jsonify(data)
