"""Evidence registry routes (/evidence)."""
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from .. import audit
from ..access import (Scope, can_correct_records, can_edit_evidence, can_record_hash, can_register_evidence,
                      can_verify_hash, custody_actions_for)
from ..auth.decorators import login_required
from ..pagination import parse_page
from . import services
from .forms import EditEvidenceForm, RegisterEvidenceForm

bp = Blueprint("evidence", __name__, url_prefix="/evidence")

TABS = ("overview", "hashes", "custody", "examinations", "metadata")


def _load(code):
    item = services.get_evidence(Scope(g.user), code)
    if item is None:
        abort(404)      # missing, or its case is not visible to this user
    return item


@bp.get("")
@login_required
def list_evidence():
    scope = Scope(g.user)
    filters = services.EvidenceFilters.from_args(request.args)
    page = services.list_evidence(scope, filters, parse_page(request.args.get("page")),
                                  current_app.config["PAGE_SIZE"])
    return render_template(
        "evidence/list.html", page=page, filters=filters, scope=scope,
        counts=services.status_counts(scope), types=services.evidence_types(include_inactive=True),
        cases=services.visible_case_refs(scope), statuses=services.EVIDENCE_STATUSES,
        integrity_statuses=services.INTEGRITY_STATUSES, sorts=services.SORTS,
        can_register=can_register_evidence(g.user),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    if not can_register_evidence(g.user):
        audit.record("access.denied", "Evidence", None, outcome="Denied", details="register evidence")
        abort(403)
    cases = services.registrable_cases(g.user)
    form = RegisterEvidenceForm()
    form.case_id.choices = [(c["case_id"], f"{c['case_reference']}  {c['title']}") for c in cases]
    form.evidence_type_id.choices = [(t["evidence_type_id"], t["type_name"]) for t in services.evidence_types()]
    form.collected_by.choices = [(u["user_id"], u["full_name"]) for u in services.active_users()]
    if request.method == "GET":
        form.collected_by.data = g.user["user_id"]
        wanted = (request.args.get("case") or "").upper()
        for c in cases:
            if c["case_reference"] == wanted:
                form.case_id.data = c["case_id"]

    if form.validate_on_submit():
        try:
            code = services.register_evidence(
                g.user, form.case_id.data, form.evidence_type_id.data, form.description.data,
                form.source_details.data, form.size_bytes.data, form.collected_at.data, form.collected_by.data,
                form.collection_site.data, form.collection_condition.data, form.seal_number.data,
                form.original_hash.data, form.hash_source.data, form.hash_notes.data)
        except services.EvidenceActionError as err:
            flash(str(err), "danger")
        else:
            flash(f"Evidence {code} registered. Its chain of custody starts with a Collected entry.", "success")
            return redirect(url_for("evidence.detail", code=code))
    return render_template("evidence/form.html", form=form, mode="create", has_cases=bool(cases))


@bp.get("/<code>")
@login_required
def detail(code):
    item = _load(code)
    tab = request.args.get("tab", "overview")
    if tab not in TABS:
        tab = "overview"
    timeline = services.custody_timeline(item["evidence_id"])
    from ..custody.services import allowed_actions
    from ..integrity.services import is_assigned
    assigned = is_assigned(g.user["user_id"], item["case_id"])
    user_actions = custody_actions_for(g.user, assigned)
    actions = {
        "transfer": user_actions != () and bool(allowed_actions(item["current_status"], user_actions)),
        "verify": can_verify_hash(g.user, item, assigned) and bool(item["current_hash_value"]),
        "record_hash": can_record_hash(g.user, item, assigned),
        "correct_hash": can_correct_records(g.user) and bool(item["current_hash_value"]) and item["case_status"] != "Closed",
        "correct_custody": can_correct_records(g.user),
    }
    context = dict(item=item, tab=tab, counts=services.tab_counts(item["evidence_id"]),
                   can_edit=can_edit_evidence(g.user, item), timeline=timeline, actions=actions,
                   held_since=timeline[-1]["occurred_at"] if timeline else None)
    if tab in ("overview", "hashes"):
        context["hashes"] = services.hash_history(item["evidence_id"])
        context["verifications"] = services.verification_history(item["evidence_id"])
    if tab in ("overview", "examinations"):
        context["examinations"] = services.evidence_examinations(item["evidence_id"])
    return render_template("evidence/detail.html", **context)


@bp.route("/<code>/edit", methods=["GET", "POST"])
@login_required
def edit(code):
    item = _load(code)
    if not can_edit_evidence(g.user, item):
        if item["case_status"] == "Closed":
            flash("This item belongs to a closed case, so it is read-only.", "warning")
            return redirect(url_for("evidence.detail", code=code))
        audit.record("access.denied", "Evidence", code, outcome="Denied", details="edit evidence")
        abort(403)
    form = EditEvidenceForm()
    if request.method == "GET":
        form.description.data, form.source_details.data = item["description"], item["source_details"]
        form.size_bytes.data, form.collection_site.data = item["size_bytes"], item["collection_site"]
        form.version.data = services.version_of(item)
    if form.validate_on_submit():
        try:
            changed = services.update_evidence(g.user, item["evidence_id"], form.description.data,
                                               form.source_details.data, form.size_bytes.data,
                                               form.collection_site.data, form.version.data)
        except services.EvidenceActionError as err:
            flash(str(err), "danger")
        else:
            flash("Evidence details updated." if changed else "No changes to save.",
                  "success" if changed else "info")
            return redirect(url_for("evidence.detail", code=code))
    return render_template("evidence/form.html", form=form, mode="edit", item=item)
