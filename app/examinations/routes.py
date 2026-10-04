"""Examination routes (/examinations)."""
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from .. import audit
from ..access import Scope, can_work_on_examination, is_admin
from ..auth.decorators import login_required
from ..pagination import parse_page
from . import services
from .forms import CancelForm, CreateExamForm, ExamRecordForm, LinkEvidenceForm

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


@bp.get("/<code>")
@login_required
def detail(code):
    exam = _load(code)
    can_work = can_work_on_examination(g.user, exam)
    context = dict(exam=exam, can_work=can_work, evidence=services.linked_evidence(exam["examination_id"]),
                   reports=services.citing_reports(exam["examination_id"]))
    if can_work:
        link_form = LinkEvidenceForm()
        link_form.evidence_ids.choices = [(e["evidence_id"], f"{e['evidence_code']}  {e['description']}")
                                          for e in services.case_evidence_not_linked(exam["case_id"], exam["examination_id"])]
        context.update(link_form=link_form, cancel_form=CancelForm())
    return render_template("examinations/detail.html", **context)


@bp.route("/<code>/record", methods=["GET", "POST"])
@login_required
def record(code):
    exam = _load(code)
    if not can_work_on_examination(g.user, exam):
        _deny(code, "edit examination record")
    form = ExamRecordForm()
    if request.method == "GET":
        for field in ("tools_methods", "observations", "findings", "limitations"):
            form[field].data = exam[field]
    if form.validate_on_submit():
        try:
            changed = services.update_record(exam["examination_id"], g.user, form.tools_methods.data,
                                             form.observations.data, form.findings.data, form.limitations.data)
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


@bp.post("/<code>/complete")
@login_required
def complete(code):
    return _action(code, services.complete, "Examination completed. Its record is now read-only.")


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
