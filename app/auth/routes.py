"""Login, logout, signup, account and password routes."""
from flask import Blueprint, flash, g, jsonify, redirect, render_template, request, session, url_for

from ..db import set_audit_user
from ..ui import has_endpoint
from . import services
from .decorators import ADMIN, has_role, login_required
from .forms import ChangePasswordForm, LoginForm, SignupForm

bp = Blueprint("auth", __name__)

# Pages a user who must change their password may still open.
_ALLOWED_DURING_FORCED_CHANGE = {"auth.change_password", "auth.logout", "static", "system.healthz"}
# home_url() is used by login, signup and the change-password page.


def home_url():
    """Where a signed-in user lands."""
    if has_endpoint("dashboard.index"):
        return url_for("dashboard.index")
    if has_role(ADMIN) and has_endpoint("users.index"):
        return url_for("users.index")
    return url_for("auth.account")


@bp.before_app_request
def load_logged_in_user():
    """Runs before every request: turn the session cookie into g.user."""
    g.user = None
    if request.endpoint in ("static", "system.healthz"):
        return None
    user_id = session.get("uid")
    if user_id is None:
        return None
    user = services.load_user(user_id)
    # Reject the session if the account was deactivated, or if the user logged
    # out / changed password since this cookie was issued (session_version).
    if user is None or user["account_status"] != "Active" or user["session_version"] != session.get("sv"):
        session.clear()
        return None
    g.user = user
    set_audit_user(user["user_id"])
    if user["must_change_password"] and request.endpoint not in _ALLOWED_DURING_FORCED_CHANGE:
        if request.path.startswith("/api/"):
            # JSON callers get a clear answer instead of an HTML redirect.
            return jsonify(status=403, error="Password change required",
                           message="Choose a new password before continuing."), 403
        return redirect(url_for("auth.change_password"))
    return None


def _start_session(user_id, session_version, remember):
    session.clear()                      # drop anything from before login
    session["uid"] = user_id
    session["sv"] = session_version
    session.permanent = bool(remember)   # 7 days if ticked, else until the browser closes


@bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(home_url())
    form = LoginForm()
    error = None
    if form.validate_on_submit():
        result = services.authenticate(form.login.data, form.password.data,
                                       request.remote_addr, request.user_agent.string)
        if result.ok:
            _start_session(result.user_id, result.session_version, form.remember.data)
            target = request.args.get("next")
            # g.user is still empty in this request, so let /home pick the landing page.
            return redirect(target if services.is_safe_next(target) else url_for("auth.home"))
        # One generic message: never say whether the username or the password was wrong.
        error = "locked" if result.reason == "rate_limited" else "invalid"
    status = 429 if error == "locked" else 200
    return render_template("auth/login.html", form=form, error=error), status


@bp.get("/home")
@login_required
def home():
    """Send a signed-in user to the right starting page for their roles."""
    return redirect(home_url())


@bp.post("/logout")
def logout():
    if g.user:
        services.logout(g.user["user_id"])
    session.clear()
    flash("You have been logged out.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(home_url())
    form = SignupForm()
    if form.validate_on_submit():
        if services.signup_rate_limited(request.remote_addr):
            flash("Too many requests from this network. Try again in an hour.", "danger")
        else:
            conflicts = services.signup_conflicts(form.username.data, form.email.data)
            if not conflicts:
                try:
                    code = services.create_access_request(form.full_name.data, form.email.data,
                                                          form.username.data, form.password.data,
                                                          form.reason.data)
                except ValueError as err:
                    conflicts = err.args[0]
                else:
                    session["signup_ref"] = code
                    return redirect(url_for("auth.signup_done"))
            for field_name, message in conflicts.items():
                form[field_name].errors.append(message)
    return render_template("auth/signup.html", form=form)


@bp.get("/signup/submitted")
def signup_done():
    code = session.pop("signup_ref", None)
    if code is None:
        return redirect(url_for("auth.signup"))
    return render_template("auth/signup_done.html", code=code)


@bp.get("/account")
@login_required
def account():
    return render_template("auth/account.html", logins=services.recent_logins(g.user["user_id"]))


@bp.route("/account/password", methods=["GET", "POST"])
@login_required
def change_password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        version, error = services.change_password(g.user["user_id"], form.current_password.data,
                                                  form.new_password.data)
        if error:
            target = form.current_password if "current" in error else form.new_password
            target.errors.append(error)
        else:
            session["sv"] = version     # keep this session; every other session is now invalid
            flash("Password changed.", "success")
            return redirect(home_url())
    forced = g.user["must_change_password"]
    layout = "layouts/auth.html" if forced else "layouts/app.html"
    return render_template("auth/change_password.html", form=form, forced=forced, layout=layout)
