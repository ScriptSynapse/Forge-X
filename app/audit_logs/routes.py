"""Audit logs (/audit-logs): Administrators and Read-Only Auditors only."""
from datetime import datetime

from flask import Blueprint, Response, current_app, render_template, request

from .. import audit
from ..auth.decorators import ADMIN, AUDITOR, roles_required
from ..dashboard.routes import ACTION_LABELS
from ..pagination import parse_page
from . import services

bp = Blueprint("audit", __name__, url_prefix="/audit-logs")


@bp.get("")
@roles_required(ADMIN, AUDITOR)
def index():
    filters = services.AuditFilters.from_args(request.args)
    page = services.list_events(filters, parse_page(request.args.get("page")), current_app.config["PAGE_SIZE"])
    return render_template("audit/index.html", page=page, filters=filters, summary=services.summary(filters),
                           options=services.filter_options(), outcomes=services.OUTCOMES,
                           entity_types=services.ENTITY_TYPES, action_labels=ACTION_LABELS)


@bp.get("/export.csv")
@roles_required(ADMIN, AUDITOR)
def export():
    filters = services.AuditFilters.from_args(request.args)
    text, count, truncated = services.export_csv(filters)
    # The export is itself an audited action (recorded after the rows were read).
    audit.record("audit.export", "User", None, details=(f"{count} rows exported"
                 + (" (limit reached)" if truncated else "") + (f"; filters {filters.as_args()}" if filters.active else ""))[:500])
    name = f"forge-x-audit-{datetime.now():%Y%m%d-%H%M}.csv"
    return Response(text, mimetype="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="{name}"', "Cache-Control": "no-store"})


@bp.get("/security")
@roles_required(ADMIN, AUDITOR)
def security():
    by_identifier, by_ip = services.repeated_failures()
    return render_template("audit/security.html", locked=services.locked_accounts(), by_identifier=by_identifier,
                           by_ip=by_ip, denied=services.denied_actions(), action_labels=ACTION_LABELS,
                           limit=current_app.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"])
