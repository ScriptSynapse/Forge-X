"""Operational endpoints."""
from flask import Blueprint, jsonify

from ..db import DatabaseError, query_value

bp = Blueprint("system", __name__)


@bp.get("/healthz")
def healthz():
    """Liveness check for the app and its database.

    Deliberately reveals no versions, names or counts: anyone can call it.
    """
    try:
        query_value("SELECT 1")
    except DatabaseError:
        return jsonify(status="degraded", database="unavailable"), 503
    return jsonify(status="ok", database="ok")
