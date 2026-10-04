"""Forensic report routes (/reports), including PDF export."""
from datetime import datetime

from flask import Blueprint, Response, abort, current_app, flash, g, redirect, render_template, request, url_for

from .. import audit
from ..access import Scope, can_edit_report, can_review_report, is_admin
from ..auth.decorators import login_required
from ..pagination import parse_page
from . import services
from .forms import CreateReportForm, LinkExamsForm, ReturnForm, VersionForm
from .pdf import build_report_pdf

bp = Blueprint("reports", __name__, url_prefix="/reports")


def _load(code):
    report = services.get_report(Scope(g.user), code)
    if report is None:
        abort(404)
    return report


def _deny(code, action):
    audit.record("access.denied", "Report", code, outcome="Denied", details=action)
    abort(403)


@bp.get("")
@login_required
def list_reports():
    scope = Scope(g.user)
    filters = services.ReportFilters.from_args(request.args)
    page = services.list_reports(scope, filters, parse_page(request.args.get("page")), current_app.config["PAGE_SIZE"])
    return render_template("reports/list.html", page=page, filters=filters, counts=services.status_counts(scope),
                           statuses=services.STATUSES,
                           can_create=bool(services.writable_cases(g.user, is_admin(g.user))))


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    cases = services.writable_cases(g.user, is_admin(g.user))
    if not cases:
        _deny(None, "create report")
    form = CreateReportForm()
    form.case_id.choices = [(c["case_id"], f"{c['case_reference']}  {c['title']}") for c in cases]
    wanted = (request.args.get("case") or "").upper()
    if request.method == "GET":
        form.case_id.data = next((c["case_id"] for c in cases if c["case_reference"] == wanted), cases[0]["case_id"])
    elif request.form.get("case_id", "").isdigit():
        form.case_id.data = int(request.form["case_id"])
    form.examination_ids.choices = [(x["examination_id"], f"{x['examination_code']} ({x['status']})")
                                    for x in services.linkable_examinations(form.case_id.data)]
    if request.form.get("change_case"):
        return render_template("reports/form.html", form=form, mode="create")
    if form.validate_on_submit():
        try:
            code = services.create_report(form.case_id.data, form.title.data, g.user["user_id"], form.sections(),
                                          form.examination_ids.data or [])
        except services.ReportError as err:
            flash(str(err), "danger")
        else:
            flash(f"Report {code} created as a Draft (version 1).", "success")
            return redirect(url_for("reports.detail", code=code))
    return render_template("reports/form.html", form=form, mode="create")


@bp.get("/<code>")
@login_required
def detail(code):
    report = _load(code)
    all_versions = services.versions(report["report_id"])
    requested = request.args.get("v", "")
    version = services.get_version(report["report_id"], int(requested) if requested.isdigit() else None)
    if version is None:
        abort(404)
    can_edit, can_review = can_edit_report(g.user, report), can_review_report(g.user, report)
    context = dict(report=report, version=version, versions=all_versions, latest=all_versions[0]["version_no"],
                   examinations=services.linked_examinations(report["report_id"]),
                   evidence=services.referenced_evidence(report["report_id"]),
                   can_edit=can_edit, can_review=can_review, sections=services.SECTIONS)
    if can_edit:
        link_form = LinkExamsForm()
        link_form.examination_ids.choices = [(x["examination_id"], f"{x['examination_code']} ({x['status']})")
                                             for x in services.linkable_examinations(report["case_id"], report["report_id"])]
        context["link_form"] = link_form
    if can_review:
        context["return_form"] = ReturnForm()
    return render_template("reports/detail.html", **context)


@bp.route("/<code>/edit", methods=["GET", "POST"])
@login_required
def edit(code):
    report = _load(code)
    if not can_edit_report(g.user, report):
        if report["status"] != "Draft":
            flash("Only Draft reports can be edited.", "warning")
            return redirect(url_for("reports.detail", code=code))
        _deny(code, "edit report")
    current = services.get_version(report["report_id"])
    form = VersionForm()
    if request.method == "GET":
        for key, _label in services.SECTIONS:
            form[key].data = current[key]
    if form.validate_on_submit():
        if form.sections() == {k: current[k] for k, _l in services.SECTIONS}:
            flash("Nothing changed, so no new version was saved.", "info")
            return redirect(url_for("reports.detail", code=code))
        try:
            number = services.save_version(report, g.user, form.sections(), form.change_note.data)
        except services.ReportError as err:
            flash(str(err), "danger")
        else:
            flash(f"Version {number} saved. Earlier versions are kept unchanged.", "success")
            return redirect(url_for("reports.detail", code=code))
    return render_template("reports/form.html", form=form, mode="edit", report=report, current=current)


@bp.post("/<code>/examinations")
@login_required
def link_examinations(code):
    report = _load(code)
    form = LinkExamsForm()
    form.examination_ids.choices = [(x["examination_id"], x["examination_code"])
                                    for x in services.linkable_examinations(report["case_id"], report["report_id"])]
    if form.validate_on_submit():
        try:
            services.link_examinations(report, g.user, form.examination_ids.data)
        except services.ReportError as err:
            flash(str(err), "danger")
        else:
            flash("Examinations cited.", "success")
    else:
        flash("Choose examinations to cite.", "danger")
    return redirect(url_for("reports.detail", code=code))


def _workflow(code, func, message, *args):
    report = _load(code)
    try:
        func(report["report_id"], g.user, *args)
    except services.ReportError as err:
        flash(str(err), "danger")
    else:
        flash(message, "success")
    return redirect(url_for("reports.detail", code=code))


@bp.post("/<code>/submit")
@login_required
def submit(code):
    return _workflow(code, services.submit, "Report submitted for review.")


@bp.post("/<code>/approve")
@login_required
def approve(code):
    return _workflow(code, services.approve, "Report approved.")


@bp.post("/<code>/return")
@login_required
def return_to_draft(code):
    form = ReturnForm()
    if not form.validate_on_submit():
        flash("Explain what the author should change.", "danger")
        return redirect(url_for("reports.detail", code=code))
    return _workflow(code, services.return_to_draft, "Report returned to the author as a Draft.", form.note.data)


@bp.get("/<code>/pdf")
@login_required
def pdf(code):
    """Build the PDF from the database each time; nothing is stored on disk."""
    report = _load(code)
    all_versions = services.versions(report["report_id"])
    requested = request.args.get("v", "")
    version = services.get_version(report["report_id"], int(requested) if requested.isdigit() else None)
    if version is None:
        abort(404)
    report = dict(report, latest_version_no=all_versions[0]["version_no"])
    data = build_report_pdf(report, version, services.linked_examinations(report["report_id"]),
                            services.referenced_evidence(report["report_id"]), g.user["full_name"], datetime.now())
    services.record_export(report, version["version_no"])
    filename = f"{report['report_code']}-v{version['version_no']}.pdf"
    return Response(data, mimetype="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"})
