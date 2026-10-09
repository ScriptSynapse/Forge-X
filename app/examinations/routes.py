"""Examination routes (/examinations)."""
from datetime import datetime

from flask import Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, url_for

from .. import audit
from ..access import Scope, can_review_examination, can_work_on_examination, is_admin
from ..auth.decorators import login_required
from ..pagination import parse_page
from . import services
from .forms import ArtifactForm, CancelForm, CreateExamForm, ExamRecordForm, LinkEvidenceForm, ReviewForm
from .pdf import build_examination_pdf

bp = Blueprint("examinations", __name__, url_prefix="/examinations")


def _load(code):
    exam = services.get_examination(Scope(g.user), code)
    if exam is None:
        abort(404)
    return exam


def _deny(code, action):
    audit.record("access.denied", "Examination", code, outcome="Denied", details=action)
    abort(403)


@bp.get("")
@login_required
def list_examinations():
    scope = Scope(g.user)
    filters = services.ExamFilters.from_args(request.args)
    page = services.list_examinations(scope, filters, g.user["user_id"], parse_page(request.args.get("page")),
                                      current_app.config["PAGE_SIZE"])
    can_create = bool(services.creatable_cases(g.user, is_admin(g.user)))
    return render_template("examinations/list.html", page=page, filters=filters, counts=services.status_counts(scope),
                           statuses=services.STATUSES, types=services.examination_types(), can_create=can_create)


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    cases = services.creatable_cases(g.user, is_admin(g.user))
    if not cases:
        _deny(None, "create examination")
    form = CreateExamForm()
    form.case_id.choices = [(c["case_id"], f"{c['case_reference']}  {c['title']}") for c in cases]
    wanted = (request.args.get("case") or "").upper()
    if request.method == "GET":
        form.case_id.data = next((c["case_id"] for c in cases if c["case_reference"] == wanted), cases[0]["case_id"])
    elif request.form.get("case_id", "").isdigit():
        form.case_id.data = int(request.form["case_id"])
    case_id = form.case_id.data
    form.examination_type_id.choices = [(t["examination_type_id"], t["type_name"]) for t in services.examination_types()]
    form.examiner_id.choices = [(u["user_id"], u["full_name"]) for u in services.case_examiners(case_id)]
    form.evidence_ids.choices = [(e["evidence_id"], f"{e['evidence_code']}  {e['description']}")
                                 for e in services.case_evidence_not_linked(case_id)]

    if request.form.get("change_case"):           # case switched: reload examiners and evidence for it
        return render_template("examinations/form.html", form=form, cases=cases)
    # The case list only contains cases this user may use (creatable_cases), and
    # SelectField refuses any other value, so a forged case_id fails validation.
    if form.validate_on_submit():
        try:
            code = services.create_examination(case_id, form.examination_type_id.data, form.examiner_id.data,
                                               form.due_date.data, form.evidence_ids.data or [], g.user["user_id"])
        except services.ExamError as err:
            flash(str(err), "danger")
        else:
            flash(f"Examination {code} created (Pending).", "success")
            return redirect(url_for("examinations.detail", code=code))
    return render_template("examinations/form.html", form=form, cases=cases)


TABS = ("overview", "evidence", "methodology", "findings", "artifacts", "history", "report")


@bp.get("/<code>")
@login_required
def detail(code):
    exam = _load(code)
    tab = request.args.get("tab", "overview")
    if tab not in TABS:
        tab = "overview"
    can_work = can_work_on_examination(g.user, exam)
    context = dict(exam=exam, tab=tab, can_work=can_work, can_review=can_review_examination(g.user, exam),
                   evidence=services.linked_evidence(exam["examination_id"]),
                   reports=services.citing_reports(exam["examination_id"]),
                   artifacts=services.artifacts(exam["examination_id"]))
    if tab == "history":
        context["history"] = services.history(exam["examination_code"])
    if can_work:
        link_form = LinkEvidenceForm()
        link_form.evidence_ids.choices = [(e["evidence_id"], f"{e['evidence_code']}  {e['description']}")
                                          for e in services.case_evidence_not_linked(exam["case_id"], exam["examination_id"])]
        artifact_form = ArtifactForm()
        artifact_form.artifact_type.choices = [(t, t) for t in services.ARTIFACT_TYPES]
        artifact_form.evidence_id.choices = [(0, "Not tied to one item")] + [
            (e["evidence_id"], e["evidence_code"]) for e in context["evidence"]]
        correct = request.args.get("correct", "")
        if correct.isdigit() and any(a["artifact_id"] == int(correct) for a in context["artifacts"]):
            artifact_form.corrects_artifact_id.data = correct
        context.update(link_form=link_form, cancel_form=CancelForm(), artifact_form=artifact_form)
    if context["can_review"]:
        context["review_form"] = ReviewForm()
    return render_template("examinations/detail.html", **context)


@bp.route("/<code>/record", methods=["GET", "POST"])
@login_required
def record(code):
    exam = _load(code)
    if not can_work_on_examination(g.user, exam):
        _deny(code, "edit examination record")
    form = ExamRecordForm()
    if request.method == "GET":
        for field in ("tools_methods", "observations", "findings", "conclusion", "limitations"):
            form[field].data = exam[field]
    if form.validate_on_submit():
        try:
            changed = services.update_record(exam["examination_id"], g.user, form.tools_methods.data,
                                             form.observations.data, form.findings.data, form.limitations.data,
                                             form.conclusion.data)
        except services.ExamError as err:
            flash(str(err), "danger")
        else:
            flash("Examination record saved." if changed else "No changes to save.", "success" if changed else "info")
            return redirect(url_for("examinations.detail", code=code))
    return render_template("examinations/record.html", exam=exam, form=form)


def _action(code, func, message, *args):
    exam = _load(code)
    if not can_work_on_examination(g.user, exam):
        _deny(code, func.__name__)
    try:
        func(exam["examination_id"], g.user, *args)
    except services.ExamError as err:
        flash(str(err), "danger")
    else:
        flash(message, "success")
    return redirect(url_for("examinations.detail", code=code))


@bp.post("/<code>/start")
@login_required
def start(code):
    return _action(code, services.start, "Examination started.")


@bp.post("/<code>/submit")
@login_required
def submit(code):
    return _action(code, services.submit, "Submitted for review. The record is frozen until it is approved or returned.")


def _review(code, func, message, note):
    exam = _load(code)
    if not can_review_examination(g.user, exam):
        _deny(code, "review examination")
    try:
        func(exam["examination_id"], g.user, note)
    except services.ExamError as err:
        flash(str(err), "danger")
    else:
        flash(message, "success")
    return redirect(url_for("examinations.detail", code=code))


@bp.post("/<code>/approve")
@login_required
def approve(code):
    form = ReviewForm()
    form.validate_on_submit()
    return _review(code, services.approve, "Examination approved and completed. Its record is now final.",
                   form.note.data)


@bp.post("/<code>/return")
@login_required
def return_for_revision(code):
    form = ReviewForm()
    form.validate_on_submit()
    return _review(code, services.return_for_revision, "Returned to the examiner for revision.", form.note.data)


@bp.post("/<code>/artifacts")
@login_required
def add_artifact(code):
    exam = _load(code)
    if not can_work_on_examination(g.user, exam):
        _deny(code, "record artifact")
    form = ArtifactForm()
    form.artifact_type.choices = [(t, t) for t in services.ARTIFACT_TYPES]
    form.evidence_id.choices = [(0, "")] + [(e["evidence_id"], e["evidence_code"])
                                            for e in services.linked_evidence(exam["examination_id"])]
    if not form.validate_on_submit():
        problems = [e for field in (form.artifact_type, form.description, form.location, form.evidence_id, form.sha256)
                    for e in field.errors]
        flash("The artifact wasn't saved: " + (" ".join(problems) or "check the fields."), "danger")
        return redirect(url_for("examinations.detail", code=code, tab="artifacts"))
    corrects = int(form.corrects_artifact_id.data) if (form.corrects_artifact_id.data or "").isdigit() else None
    try:
        artifact_id = services.add_artifact(exam["examination_id"], g.user, form.artifact_type.data, form.description.data,
                                            form.location.data, form.evidence_id.data or None, form.sha256.data, corrects)
    except services.ExamError as err:
        flash(str(err), "danger")
    else:
        flash(f"Artifact #{artifact_id} recorded. Artifacts can't be edited; record a correction if needed.", "success")
    return redirect(url_for("examinations.detail", code=code, tab="artifacts"))


@bp.get("/<code>/pdf")
@login_required
def pdf(code):
    """Examination report, built from the database on each request (never stored)."""
    exam = _load(code)
    data = build_examination_pdf(exam, services.linked_evidence(exam["examination_id"]),
                                 services.artifacts(exam["examination_id"]),
                                 services.custody_references(exam["examination_id"]),
                                 g.user["full_name"], datetime.now())
    audit.record("exam.export", "Examination", code, details="Examination report PDF")
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{code}-examination.pdf"',
                             "Cache-Control": "no-store"})


@bp.post("/<code>/cancel")
@login_required
def cancel(code):
    form = CancelForm()
    if not form.validate_on_submit():
        flash("Give a reason for cancelling (at least 5 characters).", "danger")
        return redirect(url_for("examinations.detail", code=code))
    return _action(code, services.cancel, "Examination cancelled.", form.reason.data)


@bp.post("/<code>/evidence")
@login_required
def link_evidence(code):
    exam = _load(code)
    form = LinkEvidenceForm()
    form.evidence_ids.choices = [(e["evidence_id"], e["evidence_code"])
                                 for e in services.case_evidence_not_linked(exam["case_id"], exam["examination_id"])]
    if not form.validate_on_submit():
        flash("Choose evidence to add.", "danger")
        return redirect(url_for("examinations.detail", code=code))
    return _action(code, services.link_evidence, "Evidence linked.", form.evidence_ids.data)
