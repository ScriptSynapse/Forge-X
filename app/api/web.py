"""Website pages for the API: personal tokens and the developer documentation (FORGE-X 2.0 Phase 10)."""
from flask import Blueprint, abort, flash, g, redirect, render_template, url_for
from flask_wtf import FlaskForm
from wtforms import SelectField, StringField
from wtforms.validators import DataRequired, Length

from ..auth.decorators import login_required
from ..auth.forms import strip
from . import tokens

bp = Blueprint("api_web", __name__)


class TokenForm(FlaskForm):
    name = StringField("Token name", filters=[strip], validators=[DataRequired("Name the token."), Length(min=2, max=60)])
    days = SelectField("Expires after", coerce=int, choices=[(d, f"{d} days") for d in tokens.DAY_CHOICES], default=30)


@bp.route("/account/api-tokens", methods=["GET", "POST"])
@login_required
def tokens_page():
    form = TokenForm()
    new_token = None
    if form.validate_on_submit():
        try:
            new_token = tokens.create(g.user, form.name.data, form.days.data)
        except tokens.TokenError as err:
            flash(str(err), "danger")
        else:
            form = TokenForm(formdata=None)
    # The new token is shown in this response only (never stored, never redirected with it).
    return render_template("api/tokens.html", form=form, new_token=new_token, rows=tokens.list_for(g.user["user_id"]),
                           max_days=tokens.MAX_DAYS)


@bp.post("/account/api-tokens/<int:token_id>/revoke")
@login_required
def revoke(token_id):
    try:
        tokens.revoke(g.user, token_id)
    except tokens.TokenError as err:
        if str(err) == "Token not found.":
            abort(404)
        flash(str(err), "danger")
    else:
        flash("Token revoked. Anything using it now gets 401.", "success")
    return redirect(url_for("api_web.tokens_page"))


@bp.get("/developers")
@login_required
def docs():
    from .openapi import build
    return render_template("api/docs.html", spec=build())
