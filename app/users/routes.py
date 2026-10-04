"""Users & roles administration (administrators only)."""
from flask import Blueprint, abort, flash, g, redirect, render_template, request, url_for

from ..auth.decorators import ADMIN, roles_required
from ..db import BusinessRuleError, ConstraintViolation
from . import services
from .forms import CreateUserForm, ResetPasswordForm, RoleForm

bp = Blueprint("users", __name__, url_prefix="/admin/users")


def _role_choices(exclude=()):
    return [(r["role_id"], r["role_name"]) for r in services.list_roles() if r["role_id"] not in exclude]


@bp.get("")
@roles_required(ADMIN)
def index():
    return render_template(
        "users/index.html",
        users=services.list_users(),
        requests=services.list_pending_requests(),
        roles=services.list_roles(),
    )


@bp.route("/create", methods=["GET", "POST"])
@roles_required(ADMIN)
def create():
    form = CreateUserForm()
    form.role_id.choices = _role_choices()
    if form.validate_on_submit():
        try:
            user_id = services.create_user(form.full_name.data, form.email.data, form.username.data,
                                           form.role_id.data, form.password.data, form.must_change.data,
                                           g.user["user_id"])
        except ConstraintViolation as err:
            if err.constraint == "uq_users_email":
                form.email.errors.append("An account with this email already exists.")
            elif err.constraint == "uq_users_username":
                form.username.errors.append("That username is taken.")
            else:
                flash(err.user_message, "danger")
        else:
            flash(f"Account {form.username.data} created.", "success")
            return redirect(url_for("users.detail", user_id=user_id))
    return render_template("users/create.html", form=form)


@bp.get("/<int:user_id>")
@roles_required(ADMIN)
def detail(user_id):
    user = services.get_user(user_id)
    if user is None:
        abort(404)
    held = {r["role_id"] for r in user["roles"]}
    role_form = RoleForm()
    role_form.role_id.choices = _role_choices(exclude=held)
    return render_template("users/detail.html", user=user, role_form=role_form,
                           reset_form=ResetPasswordForm(), activity=services.user_activity(user_id),
                           is_self=user_id == g.user["user_id"])


def _run(action, success_message, user_id):
    try:
        action()
    except (services.AdminActionError, BusinessRuleError) as err:
        flash(str(err) if isinstance(err, services.AdminActionError) else err.user_message, "danger")
    except ConstraintViolation as err:
        flash("The database refused this change: " + (err.constraint or "constraint violated") + ".", "danger")
    else:
        flash(success_message, "success")
    return redirect(url_for("users.detail", user_id=user_id))


@bp.post("/<int:user_id>/roles")
@roles_required(ADMIN)
def add_role(user_id):
    form = RoleForm()
    form.role_id.choices = _role_choices()
    if not form.validate_on_submit():
        flash("Choose a role to add.", "danger")
        return redirect(url_for("users.detail", user_id=user_id))
    return _run(lambda: services.add_role(user_id, form.role_id.data, g.user["user_id"]), "Role added.", user_id)


@bp.post("/<int:user_id>/roles/<int:role_id>/revoke")
@roles_required(ADMIN)
def revoke_role(user_id, role_id):
    return _run(lambda: services.revoke_role(user_id, role_id, g.user["user_id"]), "Role removed.", user_id)


@bp.post("/<int:user_id>/status")
@roles_required(ADMIN)
def set_status(user_id):
    active = request.form.get("action") == "activate"
    return _run(lambda: services.set_active(user_id, active, g.user["user_id"]),
                "Account activated." if active else "Account deactivated. The user was signed out.", user_id)


@bp.post("/<int:user_id>/reset-password")
@roles_required(ADMIN)
def reset_password(user_id):
    form = ResetPasswordForm()
    if not form.validate_on_submit():
        message = next(iter(form.errors.values()), ["Check the password fields."])[0]
        flash(message, "danger")
        return redirect(url_for("users.detail", user_id=user_id))
    return _run(lambda: services.reset_password(user_id, form.password.data, g.user["user_id"]),
                "Temporary password set. The user must change it at next login.", user_id)


@bp.post("/requests/<int:request_id>/approve")
@roles_required(ADMIN)
def approve_request(request_id):
    try:
        role_id = int(request.form.get("role_id", ""))
    except ValueError:
        flash("Choose a role before approving.", "danger")
        return redirect(url_for("users.index"))
    try:
        user_id = services.approve_request(request_id, role_id, g.user["user_id"])
    except BusinessRuleError as err:
        flash(err.user_message, "danger")
    except ConstraintViolation:
        flash("That username or email now belongs to another account. Reject this request instead.", "danger")
    else:
        flash(f"Request AR-{request_id:04d} approved.", "success")
        return redirect(url_for("users.detail", user_id=user_id))
    return redirect(url_for("users.index"))


@bp.post("/requests/<int:request_id>/reject")
@roles_required(ADMIN)
def reject_request(request_id):
    try:
        services.reject_request(request_id, g.user["user_id"], request.form.get("note"))
    except BusinessRuleError as err:
        flash(err.user_message, "danger")
    else:
        flash(f"Request AR-{request_id:04d} rejected.", "success")
    return redirect(url_for("users.index"))
