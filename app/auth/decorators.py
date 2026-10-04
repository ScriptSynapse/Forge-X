"""Route protection. Every protected view uses these decorators, so access
is enforced on the server whether or not a link is visible in the UI."""
import functools

from flask import abort, g, jsonify, redirect, request, url_for

from .. import audit

ADMIN = "Administrator"
INVESTIGATOR = "Investigator"
CUSTODIAN = "Evidence Custodian"
AUDITOR = "Read-Only Auditor"


def has_role(*roles):
    user = g.get("user")
    return bool(user) and bool(set(roles) & set(user["roles"]))


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.get("user") is None:
            if request.path.startswith("/api/"):
                # JSON endpoints (charts) answer 401 instead of redirecting to a login page.
                return jsonify(status=401, error="Not signed in", message="Log in to continue."), 401
            target = request.full_path if request.method == "GET" else None
            return redirect(url_for("auth.login", next=target.rstrip("?") if target else None))
        return view(*args, **kwargs)
    return wrapped


def roles_required(*roles):
    """Allow the view only for users holding at least one of `roles`.
    Refusals are recorded in the audit log with outcome Denied."""
    def decorator(view):
        @functools.wraps(view)
        @login_required
        def wrapped(*args, **kwargs):
            if not has_role(*roles):
                audit.record("access.denied", "User", g.user["username"], outcome="Denied",
                             details=f"{request.method} {request.path}"[:500])
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorator
