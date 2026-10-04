"""Global search (/search)."""
from flask import Blueprint, g, redirect, render_template, request, url_for

from ..access import Scope, is_admin
from ..auth.decorators import login_required
from . import services

bp = Blueprint("search", __name__, url_prefix="/search")


@bp.get("")
@login_required
def index():
    q = services.normalise(request.args.get("q"))
    scope = Scope(g.user)
    if len(q) < services.MIN_LENGTH:
        return render_template("search/index.html", q=q, results=None, too_short=bool(q))
    target = services.exact_target(q)
    results = services.search(q, scope, include_users=is_admin(g.user))
    if target:
        endpoint, arg, value = target
        group = {"evidence.detail": "evidence", "cases.detail": "cases",
                 "examinations.detail": "examinations", "reports.detail": "reports"}[endpoint]
        # Jump only if the record is among the results this user is allowed to see.
        if any(value in row.values() for row in results[group]["rows"]):
            return redirect(url_for(endpoint, **{arg: value}))
    total = sum(group["total"] for group in results.values())
    return render_template("search/index.html", q=q, results=results, total=total, too_short=False,
                           hash_search=services.looks_like_hash(q))
