"""Public pages (no login required)."""
from flask import Blueprint, render_template

bp = Blueprint("public", __name__)


@bp.get("/")
def index():
    return render_template("public/landing.html")
