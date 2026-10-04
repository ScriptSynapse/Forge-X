"""Chain of custody: lab-wide log (/custody), transfers and corrections."""
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from .. import audit
from ..access import Scope, can_correct_records, custody_actions_for
from ..auth.decorators import login_required
from ..evidence.services import get_evidence
from ..integrity.services import is_assigned
from ..pagination import parse_page
from . import services
from .forms import CorrectionForm, TransferForm

bp = Blueprint("custody", __name__, url_prefix="/custody")

NO_LOCATION = 0      # select value meaning "no storage location (describe it instead)"


def _load(code):
    item = get_evidence(Scope(g.user), code)
    if item is None:
        abort(404)
    return item


def _deny(code, action):
    audit.record("access.denied", "Evidence", code, outcome="Denied", details=action)
    abort(403)


def _location_choices():
    return [(NO_LOCATION, "No storage location (describe below)")] + \
           [(l["location_id"], f"{l['location_name']} ({l['location_type']})") for l in services.active_locations()]


@bp.get("")
@login_required
def index():
    scope = Scope(g.user)
    filters = services.CustodyFilters.from_args(request.args)
    page = services.custody_log(scope, filters, parse_page(request.args.get("page")), current_app.config["PAGE_SIZE"])
    return render_template("custody/index.html", page=page, filters=filters, actions=services.ACTIONS,
                           out=services.out_of_storage(scope), scope=scope)


@bp.get("/go")
@login_required
def go():
    """'Record a transfer' box on the log page: jump to an item's transfer form."""
    code = (request.args.get("code") or "").strip().upper()
    if get_evidence(Scope(g.user), code) is None:
        flash(f"No evidence item {code or '(blank)'} that you can see.", "warning")
        return redirect(url_for("custody.index"))
    return redirect(url_for("custody.transfer", code=code))


@bp.route("/<code>/transfer", methods=["GET", "POST"])
@login_required
def transfer(code):
    item = _load(code)
    user_actions = custody_actions_for(g.user, is_assigned(g.user["user_id"], item["case_id"]))
    actions = services.allowed_actions(item["current_status"], user_actions)
    if user_actions == ():
        _deny(code, "custody transfer")

    form = TransferForm()
    form.action.choices = [(a, f"{a} (item becomes {services.resulting_status(a, item['current_status'])})")
                           for a in actions]
    form.to_user_id.choices = [(u["user_id"], u["full_name"]) for u in services.active_users()]
    form.location_id.choices = _location_choices()
    if request.method == "GET":
        form.expected_custodian_id.data = str(item["current_custodian_id"])
        form.to_user_id.data = g.user["user_id"]
        form.location_id.data = item["current_location_id"] or NO_LOCATION
        form.condition.data = "Sealed, intact"

    if actions and form.validate_on_submit():
        try:
            expected = int(form.expected_custodian_id.data)
        except (TypeError, ValueError):
            expected = -1
        try:
            entry = services.transfer(item, g.user["user_id"], expected, form.action.data, form.to_user_id.data,
                                      form.location_id.data or None, form.location_note.data, form.condition.data,
                                      form.seal_number.data, form.reason.data, form.occurred_at.data)
        except services.CustodyError as err:
            flash(str(err), "danger")
        else:
            flash(f"Custody entry #{entry} recorded: {form.action.data}.", "success")
            return redirect(url_for("evidence.detail", code=code, tab="custody"))
    return render_template("custody/transfer.html", item=item, form=form, has_actions=bool(actions),
                           investigator_only=user_actions is not None)


@bp.route("/<code>/entries/<int:custody_id>/correct", methods=["GET", "POST"])
@login_required
def correct(code, custody_id):
    item = _load(code)
    if not can_correct_records(g.user):
        _deny(code, "custody correction")
    entry = services.get_entry(item["evidence_id"], custody_id)
    if entry is None:
        abort(404)
    form = CorrectionForm()
    form.to_user_id.choices = [(u["user_id"], u["full_name"]) for u in services.active_users()]
    form.location_id.choices = _location_choices()
    if request.method == "GET":
        form.to_user_id.data = entry["to_custodian_id"]
        form.location_id.data = entry["location_id"] or NO_LOCATION
        form.location_note.data = entry["location_note"]
        form.condition.data = entry["evidence_condition"]
        form.seal_number.data = entry["seal_number"]
    if form.validate_on_submit():
        try:
            new_id = services.correct_entry(custody_id, g.user["user_id"], form.to_user_id.data,
                                            form.location_id.data or None, form.location_note.data,
                                            form.condition.data, form.seal_number.data, form.reason.data)
        except services.CustodyError as err:
            flash(str(err), "danger")
        else:
            flash(f"Correction #{new_id} recorded. Entry #{custody_id} is kept unchanged.", "success")
            return redirect(url_for("evidence.detail", code=code, tab="custody"))
    return render_template("custody/correct.html", item=item, entry=entry, form=form)
