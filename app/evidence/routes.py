"""Evidence registry routes (/evidence)."""
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, send_file, url_for

from .. import audit
from ..access import (Scope, can_correct_records, can_edit_evidence, can_record_hash, can_register_evidence,
                      can_verify_hash, custody_actions_for)
from ..auth.decorators import login_required
from ..cases.services import active_investigators_for_filter
from ..pagination import parse_page
from . import files, services
from .forms import AttachFileForm, EditEvidenceForm, RegisterEvidenceForm

bp = Blueprint("evidence", __name__, url_prefix="/evidence")

TABS = ("overview", "hashes", "custody", "examinations", "scans", "metadata")


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
        integrity_statuses=services.INTEGRITY_STATUSES, sorts=services.SORTS, sort_menu=services.SORT_MENU,
        investigators=active_investigators_for_filter(),
        can_register=can_register_evidence(g.user),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    _allow_evidence_upload()
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
        upload = form.evidence_file.data
        warning = None
        try:
            if upload and getattr(upload, "filename", ""):
                fields = dict(case_id=form.case_id.data, evidence_type_id=form.evidence_type_id.data,
                              description=form.description.data, source_details=form.source_details.data,
                              size_bytes=form.size_bytes.data, collected_at=form.collected_at.data,
                              collected_by=form.collected_by.data, collection_site=form.collection_site.data,
                              collection_condition=form.collection_condition.data, seal_number=form.seal_number.data)
                code, warning = files.register_with_file(g.user, upload, fields, form.original_hash.data,
                                                         form.hash_source.data, form.hash_notes.data)
            else:
                code = services.register_evidence(
                    g.user, form.case_id.data, form.evidence_type_id.data, form.description.data,
                    form.source_details.data, form.size_bytes.data, form.collected_at.data, form.collected_by.data,
                    form.collection_site.data, form.collection_condition.data, form.seal_number.data,
                    form.original_hash.data, form.hash_source.data, form.hash_notes.data)
        except (services.EvidenceActionError, files.FileActionError) as err:
            flash(str(err), "danger")
        else:
            if warning:
                flash(warning, "warning")
            flash(f"Evidence {code} registered. Its chain of custody starts with a Collected entry.", "success")
            return redirect(url_for("evidence.detail", code=code))
    return render_template("evidence/form.html", form=form, mode="create", has_cases=bool(cases),
                           max_mb=current_app.config["EVIDENCE_FILE_MAX_BYTES"] // (1024 * 1024))


@bp.get("/<code>")
@login_required
def detail(code):
    item = _load(code)
    tab = request.args.get("tab", "overview")
    if tab not in TABS:
        tab = "overview"
    timeline = services.custody_timeline(item["evidence_id"])
    stored_file = files.get_file(item["evidence_id"])
    from ..custody.services import allowed_actions
    from ..integrity.services import is_assigned
    assigned = is_assigned(g.user["user_id"], item["case_id"])
    user_actions = custody_actions_for(g.user, assigned)
    file_actions = {
        "download": bool(stored_file) and files.can_download(g.user, assigned),
        "verify_stored": bool(stored_file) and bool(item["current_hash_value"]) and can_verify_hash(g.user, item, assigned),
        "attach": not stored_file and files.can_attach(g.user, item, assigned),
    }
    actions = {
        "transfer": user_actions != () and bool(allowed_actions(item["current_status"], user_actions)),
        "verify": can_verify_hash(g.user, item, assigned) and bool(item["current_hash_value"]),
        "record_hash": can_record_hash(g.user, item, assigned),
        "correct_hash": can_correct_records(g.user) and bool(item["current_hash_value"]) and item["case_status"] != "Closed",
        "correct_custody": can_correct_records(g.user),
    }
    context = dict(item=item, tab=tab, counts=services.tab_counts(item["evidence_id"]),
                   can_edit=can_edit_evidence(g.user, item), timeline=timeline, actions=actions,
                   stored_file=stored_file, file_actions=file_actions,
                   attach_form=AttachFileForm() if file_actions["attach"] else None,
                   max_mb=current_app.config["EVIDENCE_FILE_MAX_BYTES"] // (1024 * 1024),
                   # Exports don't change who holds the original, so they don't reset "held since".
                   held_since=next((e["occurred_at"] for e in reversed(timeline) if e["action"] != "Exported"), None))
    if tab in ("overview", "hashes"):
        context["hashes"] = services.hash_history(item["evidence_id"])
        context["verifications"] = services.verification_history(item["evidence_id"])
    if tab == "custody":
        context["custody_only"] = request.args.get("only") == "custody"
        events = [dict(e, kind="custody", at=e["occurred_at"]) for e in timeline]
        if not context["custody_only"]:
            events += [dict(v, kind="check", at=v["verified_at"])
                       for v in services.verification_history(item["evidence_id"])]
        # Oldest first; at the same moment, a custody entry comes before a check.
        context["events"] = sorted(events, key=lambda e: (e["at"], e["kind"] != "custody"))
    if tab == "scans":
        from ..yara import services as yara_services
        context["scans"] = yara_services.scans_for_evidence(item["evidence_id"])
        context["can_scan"] = bool(stored_file) and item["case_status"] != "Closed" and files.can_download(g.user, assigned)
        context["applicable_rules"] = yara_services.applicable_versions(item["case_id"]) if context["can_scan"] else []
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


# ---------------------------------------------------------------------------
# Stored evidence files (FORGE-X 2.0 Phase 3)
# ---------------------------------------------------------------------------
def _allow_evidence_upload():
    """Evidence upload routes accept files up to EVIDENCE_FILE_MAX_BYTES; every
    other route keeps the smaller app-wide MAX_CONTENT_LENGTH (Flask 3.1+)."""
    request.max_content_length = current_app.config["EVIDENCE_FILE_MAX_BYTES"] + 1024 * 1024


def _assigned(item):
    from ..integrity.services import is_assigned
    return is_assigned(g.user["user_id"], item["case_id"])


@bp.post("/<code>/file")
@login_required
def attach_file(code):
    _allow_evidence_upload()
    item = _load(code)
    if not files.can_attach(g.user, item, _assigned(item)):
        audit.record("access.denied", "Evidence", code, outcome="Denied", details="attach evidence file")
        abort(403)
    form = AttachFileForm()
    if not form.validate_on_submit():
        flash("Choose a file to store.", "danger")
        return redirect(url_for("evidence.detail", code=code))
    try:
        sha256 = files.attach(item, g.user, form.evidence_file.data)
    except files.FileActionError as err:
        flash(str(err), "danger")
    else:
        flash(f"File stored. SHA-256 {sha256}.", "success")
    return redirect(url_for("evidence.detail", code=code))


@bp.post("/<code>/file/verify")
@login_required
def verify_stored_file(code):
    item = _load(code)
    if not can_verify_hash(g.user, item, _assigned(item)):
        audit.record("access.denied", "Evidence", code, outcome="Denied", details="verify stored file")
        abort(403)
    try:
        result = files.verify_stored(item, g.user)
    except files.FileActionError as err:
        flash(str(err), "danger")
        return redirect(url_for("evidence.detail", code=code, tab="hashes"))
    return render_template("integrity/form.html", item=services.get_evidence(Scope(g.user), code), form=None,
                           mode="verify", title="Verify stored file", result=result, max_mb=0)


@bp.get("/<code>/file/download")
@login_required
def download_file(code):
    item = _load(code)
    if not files.can_download(g.user, _assigned(item)):
        audit.record("access.denied", "Evidence", code, outcome="Denied", details="download evidence file")
        abort(403)
    try:
        handle, stored = files.open_for_download(item, g.user)
    except files.FileActionError as err:
        flash(str(err), "danger")
        return redirect(url_for("evidence.detail", code=code))
    # Always a download, never rendered: evidence can be anything, including malware.
    response = send_file(handle, mimetype="application/octet-stream", as_attachment=True,
                         download_name=f"{item['evidence_code']}_{stored['original_name']}", max_age=0)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response
