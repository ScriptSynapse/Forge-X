"""Hash actions on an evidence item: record the original, verify, correct."""
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, url_for

from .. import audit
from ..access import Scope, can_correct_records, can_record_hash, can_verify_hash
from ..auth.decorators import login_required
from ..evidence.services import get_evidence
from . import services
from .forms import HashForm
from .hashing import SampleFileError, sha256_of_upload

bp = Blueprint("integrity", __name__, url_prefix="/evidence")

TITLES = {"record": "Record the original hash", "verify": "Verify integrity", "correct": "Correct the recorded hash"}


def _load(code):
    item = get_evidence(Scope(g.user), code)
    if item is None:
        abort(404)
    return item


def _deny(code, action):
    audit.record("access.denied", "Evidence", code, outcome="Denied", details=action)
    abort(403)


def _hash_from_form(form):
    """(hex, file_name, size, source) from the uploaded file or the typed hash."""
    if form.method.data == "sample":
        digest, size, name = sha256_of_upload(form.sample_file.data, current_app.config["SAMPLE_FILE_MAX_BYTES"])
        return digest, name, size, "Computed"
    return form.hash_value.data, None, None, "Manual"


def _page(mode, code):
    item = _load(code)
    assigned = services.is_assigned(g.user["user_id"], item["case_id"])
    allowed = {"record": can_record_hash(g.user, item, assigned),
               "verify": can_verify_hash(g.user, item, assigned) and bool(item["current_hash_value"]),
               "correct": can_correct_records(g.user) and bool(item["current_hash_value"])
                          and item["case_status"] != "Closed"}[mode]
    if not allowed:
        _deny(code, f"hash {mode}")

    form = HashForm(mode)
    result = None
    if form.validate_on_submit():
        try:
            digest, file_name, size, source = _hash_from_form(form)
            if mode == "record":
                notes = form.notes.data if source == "Manual" else \
                    f"Computed by FORGE-X from sample file {file_name} ({size:,} bytes)"
                services.record_original_hash(item["evidence_id"], g.user["user_id"], digest, source, notes)
                flash("Original SHA-256 recorded.", "success")
                return redirect(url_for("evidence.detail", code=code, tab="hashes"))
            if mode == "verify":
                outcome, reference = services.verify(
                    item["evidence_id"], g.user["user_id"], digest,
                    "Sample file" if source == "Computed" else "Manual entry", file_name, size, form.notes.data)
                result = {"outcome": outcome, "reference": reference, "computed": digest,
                          "file_name": file_name, "size": size}
            if mode == "correct":
                notes = form.notes.data if source == "Manual" else \
                    f"Computed by FORGE-X from sample file {file_name} ({size:,} bytes)"
                services.correct_hash(item["evidence_id"], g.user["user_id"], digest, source, notes, form.reason.data)
                flash("Hash corrected. The previous hash stays on record, marked as superseded.", "success")
                return redirect(url_for("evidence.detail", code=code, tab="hashes"))
        except SampleFileError as err:
            form.sample_file.errors.append(str(err))
        except services.IntegrityError as err:
            flash(str(err), "danger")
    if result is None:
        item = _load(code) if mode != "record" else item
    return render_template("integrity/form.html", item=item, form=form, mode=mode, title=TITLES[mode],
                           result=result, max_mb=current_app.config["SAMPLE_FILE_MAX_BYTES"] // (1024 * 1024))


@bp.route("/<code>/hash/record", methods=["GET", "POST"])
@login_required
def record(code):
    return _page("record", code)


@bp.route("/<code>/hash/verify", methods=["GET", "POST"])
@login_required
def verify(code):
    return _page("verify", code)


@bp.route("/<code>/hash/correct", methods=["GET", "POST"])
@login_required
def correct(code):
    return _page("correct", code)
