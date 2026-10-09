"""Relationship graph routes (/graph). Read-only: the page, a case's graph as
JSON, and the neighbours of one node as JSON. All scoped to visible cases."""
from flask import Blueprint, g, jsonify, render_template, request

from ..access import Scope
from ..auth.decorators import login_required
from . import services

bp = Blueprint("graph", __name__, url_prefix="/graph")


def _hash_mode():
    return "all" if request.args.get("hashes") == "all" else "shared"


@bp.get("")
@login_required
def index():
    scope = Scope(g.user)
    reference = (request.args.get("case") or "").strip().upper()
    case = services.visible_case(scope, reference) if reference else None
    return render_template("graph/index.html", cases=services.visible_cases(scope), case=case, scope=scope,
                           hash_mode=_hash_mode(), max_nodes=services.MAX_NODES, node_types=services.NODE_TYPES)


@bp.get("/api/case/<reference>")
@login_required
def case_data(reference):
    graph = services.case_graph(Scope(g.user), reference.upper(), _hash_mode())
    if graph is None:
        return jsonify({"error": "Case not found."}), 404
    return jsonify(graph.as_dict())


@bp.get("/api/expand")
@login_required
def expand():
    graph = services.expand(Scope(g.user), request.args.get("node", ""), _hash_mode())
    if graph is None:
        return jsonify({"error": "Not found."}), 404
    return jsonify(graph.as_dict())
