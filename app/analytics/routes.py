"""Analytics page (/analytics) and its JSON chart endpoints."""
from flask import Blueprint, abort, g, jsonify, render_template, request

from ..access import Scope
from ..auth.decorators import login_required
from . import services

bp = Blueprint("analytics", __name__)


@bp.get("/analytics")
@login_required
def index():
    months = services.parse_period(request.args.get("months"))
    charts = [dict(id=cid, sql=services.display_sql(cid), **{k: v for k, v in c.items() if k != "sql"})
              for cid, c in services.CHARTS.items()]
    return render_template("analytics/index.html", charts=charts, months=months, periods=services.PERIODS,
                           scope=Scope(g.user))


@bp.get("/api/analytics/<chart_id>")
@login_required
def chart_data(chart_id):
    if chart_id not in services.CHARTS:
        abort(404)
    return jsonify(services.run(chart_id, Scope(g.user), services.parse_period(request.args.get("months"))))
