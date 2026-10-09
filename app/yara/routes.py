"""YARA routes (/yara): the rule library (administrators manage it; everyone
signed in can read it), scans of stored evidence files, and scan results."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from .. import audit
from ..access import Scope
from ..auth.decorators import login_required
from ..evidence import files as evidence_files
from ..evidence import services as evidence_services
from . import services
from .forms import SOURCE_HELP, CaseLinkForm, RuleForm, ScopeForm, VersionForm

bp = Blueprint("yara", __name__, url_prefix="/yara")


def _admin_only(what):
    if not services.can_manage(g.user):
        audit.record("access.denied", "YARA rule", "library", outcome="Denied", details=what)
        abort(403)


def _rule(rule_id):
    rule = services.get_rule(rule_id)
    if rule is None:
        abort(404)
    return rule


@bp.get("/rules")
@login_required
def rules():
    return render_template("yara/rules.html", rules=services.list_rules(), can_manage=services.can_manage(g.user),
                           available=services.availability())


@bp.route("/rules/new", methods=["GET", "POST"])
@login_required
def create_rule():
    _admin_only("create YARA rule")
    form = RuleForm()
    if form.validate_on_submit():
        try:
            rule_id, warnings = services.create_rule(g.user, form.name.data, form.description.data, form.author.data,
                                                     form.scope.data, form.source.data)
        except services.YaraError as err:
            form.source.errors = list(form.source.errors) + [str(err)]
        else:
            flash("Rule saved as version 1." + (f" Compiler warnings: {'; '.join(warnings)}" if warnings else ""), "success")
            return redirect(url_for("yara.rule_detail", rule_id=rule_id))
    return render_template("yara/rule_form.html", form=form, source_help=SOURCE_HELP, available=services.availability())


@bp.get("/rules/<int:rule_id>")
@login_required
def rule_detail(rule_id):
    rule = _rule(rule_id)
    all_versions = services.versions(rule_id)
    wanted = request.args.get("v", "")
    shown = next((v for v in all_versions if str(v["version_no"]) == wanted), all_versions[0] if all_versions else None)
    context = dict(rule=rule, versions=all_versions, shown=shown, cases=services.rule_cases(rule_id),
                   scans=services.rule_scan_count(rule_id), can_manage=services.can_manage(g.user))
    if context["can_manage"]:
        version_form = VersionForm()
        version_form.source.data = all_versions[0]["source"] if all_versions else ""
        scope_form = ScopeForm()
        scope_form.scope.data = rule["scope"]
        link_form = CaseLinkForm()
        linked = {c["case_id"] for c in context["cases"]}
        link_form.case_id.choices = [(c["case_id"], f"{c['case_reference']}  {c['title']}")
                                     for c in services.open_cases() if c["case_id"] not in linked]
        context.update(version_form=version_form, scope_form=scope_form, link_form=link_form, source_help=SOURCE_HELP)
    return render_template("yara/rule_detail.html", **context)


def _manage(rule_id, func, message, *args):
    _admin_only("manage YARA rule")
    _rule(rule_id)
    try:
        result = func(rule_id, g.user, *args)
    except services.YaraError as err:
        flash(str(err), "danger")
    else:
        flash(message(result) if callable(message) else message, "success")
    return redirect(url_for("yara.rule_detail", rule_id=rule_id))


@bp.post("/rules/<int:rule_id>/versions")
@login_required
def add_version(rule_id):
    _admin_only("new YARA rule version")
    form = VersionForm()
    if not form.validate_on_submit():
        flash("Paste the source and say what changed.", "danger")
        return redirect(url_for("yara.rule_detail", rule_id=rule_id))
    return _manage(rule_id, services.new_version,
                   lambda r: f"Version {r[0]} saved." + (f" Compiler warnings: {'; '.join(r[1])}" if r[1] else ""),
                   form.source.data, form.change_note.data)


@bp.post("/rules/<int:rule_id>/enabled")
@login_required
def set_enabled(rule_id):
    enable = request.form.get("enable") == "1"
    return _manage(rule_id, services.set_enabled, "Rule enabled." if enable else "Rule disabled.", enable)


@bp.post("/rules/<int:rule_id>/scope")
@login_required
def set_scope(rule_id):
    _admin_only("change YARA rule scope")
    form = ScopeForm()
    form.validate_on_submit()
    return _manage(rule_id, services.set_scope, "Scope updated.", form.scope.data)


@bp.post("/rules/<int:rule_id>/cases")
@login_required
def add_case(rule_id):
    _admin_only("associate YARA rule")
    form = CaseLinkForm()
    form.case_id.choices = [(c["case_id"], c["case_reference"]) for c in services.open_cases()]
    if not form.validate_on_submit():
        flash("Choose an open case.", "danger")
        return redirect(url_for("yara.rule_detail", rule_id=rule_id))
    return _manage(rule_id, services.add_case, "Case associated.", form.case_id.data)


@bp.post("/rules/<int:rule_id>/cases/<int:case_id>/remove")
@login_required
def remove_case(rule_id, case_id):
    return _manage(rule_id, services.remove_case, "Association removed.", case_id)


@bp.post("/evidence/<code>/scan")
@login_required
def scan(code):
    item = evidence_services.get_evidence(Scope(g.user), code)
    if item is None:
        abort(404)
    from ..integrity.services import is_assigned
    if not evidence_files.can_download(g.user, is_assigned(g.user["user_id"], item["case_id"])):
        audit.record("access.denied", "Evidence", code, outcome="Denied", details="YARA scan")
        abort(403)
    stored = evidence_files.get_file(item["evidence_id"])
    if stored is None:
        flash("Only stored evidence files can be scanned.", "danger")
        return redirect(url_for("evidence.detail", code=code, tab="scans"))
    try:
        scan_id = services.run_scan(item, stored, g.user)
    except services.YaraError as err:
        flash(str(err), "danger")
        return redirect(url_for("evidence.detail", code=code, tab="scans"))
    return redirect(url_for("yara.scan_detail", scan_id=scan_id))


@bp.get("/scans/<int:scan_id>")
@login_required
def scan_detail(scan_id):
    found = services.get_scan(Scope(g.user), scan_id)
    if found is None:
        abort(404)
    return render_template("yara/scan.html", scan=found, rules=services.scan_rules(scan_id),
                           matches=services.scan_matches(scan_id))
