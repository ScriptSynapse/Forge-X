"""Case management routes (/cases)."""
from flask import Blueprint, abort, current_app, flash, g, redirect, render_template, request, url_for

from .. import audit
from ..access import Scope, can_create_case, can_manage_case, can_register_evidence, is_admin, registers_for_any_case
from ..auth.decorators import login_required
from ..pagination import parse_page
from . import services
from .forms import AssignForm, CaseForm, CloseForm, StatusForm

bp = Blueprint("cases", __name__, url_prefix="/cases")

TABS = ("overview", "evidence", "investigators", "examinations", "reports", "activity")


def _deny(action, ref):
    """Record and refuse an action the user isn't allowed to take."""
    audit.record("access.denied", "Case", ref, outcome="Denied", details=action)
    abort(403)


def _load_case(reference):
    """The case if this user may see it, otherwise 404 (existence isn't revealed)."""
    case = services.get_case(Scope(g.user), reference)
    if case is None:
        abort(404)
    return case


def _require_manage(case, action):
    if not can_manage_case(g.user, case):
        if case["status"] == "Closed":
            flash("Closed cases are read-only.", "warning")
            return redirect(url_for("cases.detail", reference=case["case_reference"]))
        _deny(action, case["case_reference"])
    return None


@bp.get("")
@login_required
def list_cases():
    scope = Scope(g.user)
    filters = services.CaseFilters.from_args(request.args)
    page = services.list_cases(scope, filters, parse_page(request.args.get("page")),
                               per_page=current_app.config["PAGE_SIZE"])
    return render_template(
        "cases/list.html", page=page, filters=filters, scope=scope,
        counts=services.status_counts(scope), types=services.case_types(include_inactive=True),
        statuses=services.CASE_STATUSES, priorities=services.PRIORITIES, sorts=services.SORTS,
        can_create=can_create_case(g.user),
    )


@bp.route("/new", methods=["GET", "POST"])
@login_required
def create():
    if not can_create_case(g.user):
        _deny("create case", None)
    form = CaseForm()
    form.case_type_id.choices = [(t["case_type_id"], t["type_name"]) for t in services.case_types()]
    admin = is_admin(g.user)
    if admin:
        form.lead_user_id.choices = [(u["user_id"], u["full_name"]) for u in services.active_investigators()]
    else:
        # An investigator who registers a case becomes its lead (Phase 1 rule),
        # so the field is removed and can't be submitted.
        del form.lead_user_id

    if form.validate_on_submit():
        lead = form.lead_user_id.data if admin else g.user["user_id"]
        try:
            reference = services.create_case(form.title.data, form.description.data, form.case_type_id.data,
                                             form.priority.data, lead, g.user["user_id"])
        except services.CaseActionError as err:
            flash(str(err), "danger")
        else:
            flash(f"Case {reference} registered.", "success")
            return redirect(url_for("cases.detail", reference=reference))
    return render_template("cases/form.html", form=form, mode="create")


@bp.get("/<reference>")
@login_required
def detail(reference):
    case = _load_case(reference)
    tab = request.args.get("tab", "overview")
    if tab not in TABS:
        tab = "overview"
    manage = can_manage_case(g.user, case)
    investigators = services.case_investigators(case["case_id"])
    assigned_to_me = any(i["user_id"] == g.user["user_id"] for i in investigators)
    can_add_evidence = (case["status"] != "Closed" and can_register_evidence(g.user)
                        and (registers_for_any_case(g.user) or assigned_to_me))
    context = dict(case=case, tab=tab, tabs=TABS, manage=manage, investigators=investigators,
                   counts=services.tab_counts(case["case_id"]), can_add_evidence=can_add_evidence,
                   # examinations and reports: administrators, or investigators on this open case
                   can_add_work=case["status"] != "Closed" and (is_admin(g.user) or (
                       "Investigator" in g.user["roles"] and assigned_to_me)))
    if tab in ("overview", "evidence"):
        context["evidence"] = services.case_evidence(case["case_id"])
    if tab == "examinations":
        context["examinations"] = services.case_examinations(case["case_id"])
    if tab == "reports":
        context["reports"] = services.case_reports(case["case_id"])
    if tab in ("overview", "activity"):
        context["activity"] = services.case_activity(case, limit=6 if tab == "overview" else 100)
    if manage:
        status_form = StatusForm()
        status_form.status.data = case["status"]
        assigned = {i["user_id"] for i in investigators}
        assign_form = AssignForm()
        assign_form.user_id.choices = [(u["user_id"], u["full_name"]) for u in services.active_investigators()
                                       if u["user_id"] not in assigned]
        context.update(status_form=status_form, assign_form=assign_form)
    return render_template("cases/detail.html", **context)


@bp.route("/<reference>/edit", methods=["GET", "POST"])
@login_required
def edit(reference):
    case = _load_case(reference)
    refused = _require_manage(case, "edit case")
    if refused:
        return refused
    form = CaseForm()
    del form.lead_user_id          # the lead is changed on the Investigators tab
    form.case_type_id.choices = [(t["case_type_id"], t["type_name"])
                                 for t in services.case_types(include_inactive=True)]
    if request.method == "GET":
        form.title.data, form.description.data = case["title"], case["description"]
        form.case_type_id.data, form.priority.data = case["case_type_id"], case["priority"]
        form.version.data = services.version_of(case)

    if form.validate_on_submit():
        try:
            changed = services.update_case(case["case_id"], g.user, form.title.data, form.description.data,
                                           form.case_type_id.data, form.priority.data, form.version.data)
        except services.CaseActionError as err:
            flash(str(err), "danger")
        else:
            flash("Case updated." if changed else "No changes to save.", "success" if changed else "info")
            return redirect(url_for("cases.detail", reference=reference))
    return render_template("cases/form.html", form=form, mode="edit", case=case)


@bp.post("/<reference>/status")
@login_required
def change_status(reference):
    case = _load_case(reference)
    refused = _require_manage(case, "change case status")
    if refused:
        return refused
    form = StatusForm()
    if form.validate_on_submit():
        try:
            services.change_status(case["case_id"], g.user, form.status.data)
        except services.CaseActionError as err:
            flash(str(err), "danger")
        else:
            flash(f"Status changed to {form.status.data}.", "success")
    return redirect(url_for("cases.detail", reference=reference))


@bp.post("/<reference>/investigators")
@login_required
def assign(reference):
    case = _load_case(reference)
    refused = _require_manage(case, "assign investigator")
    if refused:
        return refused
    form = AssignForm()
    form.user_id.choices = [(u["user_id"], u["full_name"]) for u in services.active_investigators()]
    if form.validate_on_submit():
        try:
            services.assign_investigator(case["case_id"], form.user_id.data, form.make_lead.data, g.user["user_id"])
        except services.CaseActionError as err:
            flash(str(err), "danger")
        else:
            flash("Investigator assigned." + (" They are now the lead." if form.make_lead.data else ""), "success")
    else:
        flash("Choose an investigator to assign.", "danger")
    return redirect(url_for("cases.detail", reference=reference, tab="investigators"))


@bp.post("/<reference>/investigators/<int:user_id>/lead")
@login_required
def set_lead(reference, user_id):
    case = _load_case(reference)
    refused = _require_manage(case, "change lead investigator")
    if refused:
        return refused
    try:
        services.make_lead(case["case_id"], user_id, g.user["user_id"])
    except services.CaseActionError as err:
        flash(str(err), "danger")
    else:
        flash("Lead investigator changed.", "success")
    return redirect(url_for("cases.detail", reference=reference, tab="investigators"))


@bp.post("/<reference>/investigators/<int:user_id>/remove")
@login_required
def remove_investigator(reference, user_id):
    case = _load_case(reference)
    refused = _require_manage(case, "remove investigator")
    if refused:
        return refused
    try:
        services.remove_investigator(case["case_id"], user_id, g.user["user_id"])
    except services.CaseActionError as err:
        flash(str(err), "danger")
    else:
        flash("Investigator removed from the case.", "success")
    return redirect(url_for("cases.detail", reference=reference, tab="investigators"))


@bp.route("/<reference>/close", methods=["GET", "POST"])
@login_required
def close(reference):
    case = _load_case(reference)
    refused = _require_manage(case, "close case")
    if refused:
        return refused
    form = CloseForm()
    blockers = services.closure_blockers(case["case_id"])
    if form.validate_on_submit():
        try:
            services.close_case(case["case_id"], form.summary.data, g.user["user_id"])
        except services.CaseActionError as err:
            flash(str(err), "danger")
        else:
            flash(f"Case {reference} closed.", "success")
            return redirect(url_for("cases.detail", reference=reference))
    return render_template("cases/close.html", case=case, form=form, blockers=blockers)
