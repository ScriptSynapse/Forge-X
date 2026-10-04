"""Authentication business logic, kept out of the route handlers so it can be
tested and explained on its own. All data lives in MySQL."""
from dataclasses import dataclass
from urllib.parse import urlparse

from flask import current_app

from .. import audit
from ..db import (BusinessRuleError, ConstraintViolation, execute, query_all, query_one, query_value,
                  transaction)
from .passwords import burn_time, hash_password, password_problems, verify_password

# Login throttling is counted from login_attempts (so it survives restarts).
# Limits come from config: LOGIN_MAX_FAILURES_PER_ACCOUNT, LOGIN_MAX_FAILURES_PER_IP,
# SIGNUP_MAX_PER_IP_PER_HOUR (see app/config.py).
LOCK_WINDOW_MINUTES = 15


@dataclass
class AuthResult:
    ok: bool
    reason: str = None            # invalid_credentials | account_inactive | rate_limited
    user_id: int = None
    session_version: int = None


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------
def _record_attempt(identifier, user_id, success, reason, ip, user_agent, cursor=None):
    sql = ("INSERT INTO login_attempts (username_or_email, user_id, success, failure_reason, ip_address, user_agent) "
           "VALUES (%s, %s, %s, %s, %s, %s)")
    params = (identifier[:254], user_id, success, reason, (ip or "unknown")[:45], (user_agent or "")[:255] or None)
    if cursor is not None:
        cursor.execute(sql, params)
    else:
        execute(sql, params)


def _is_rate_limited(identifier, user_id, ip):
    """Too many recent wrong passwords for this account, or from this IP?
    Failures before the account's last successful login are not counted."""
    account_failures = query_value(
        f"""
        SELECT COUNT(*) FROM login_attempts la
         WHERE (la.username_or_email = %s OR (%s IS NOT NULL AND la.user_id = %s))
           AND la.success = FALSE
           AND la.failure_reason = 'invalid_credentials'
           AND la.attempted_at >= NOW() - INTERVAL {LOCK_WINDOW_MINUTES} MINUTE
           AND la.attempted_at > COALESCE(
                 (SELECT MAX(s.attempted_at) FROM login_attempts s
                   WHERE s.success = TRUE AND (s.username_or_email = %s OR (%s IS NOT NULL AND s.user_id = %s))),
                 '1970-01-01')
        """,
        (identifier, user_id, user_id, identifier, user_id, user_id),
    )
    if account_failures >= current_app.config["LOGIN_MAX_FAILURES_PER_ACCOUNT"]:
        return True
    ip_failures = query_value(
        f"""
        SELECT COUNT(*) FROM login_attempts
         WHERE ip_address = %s AND success = FALSE
           AND attempted_at >= NOW() - INTERVAL {LOCK_WINDOW_MINUTES} MINUTE
        """,
        (ip or "unknown",),
    )
    return ip_failures >= current_app.config["LOGIN_MAX_FAILURES_PER_IP"]


def authenticate(identifier, password, ip, user_agent):
    """Check a username/email and password. Every attempt is recorded in
    login_attempts; the password itself is never stored or logged."""
    identifier = (identifier or "").strip()[:254]
    user = query_one(
        "SELECT user_id, password_hash, account_status, session_version "
        "FROM users WHERE username = %s OR email = %s LIMIT 1",
        (identifier, identifier),
    )
    user_id = user["user_id"] if user else None

    if _is_rate_limited(identifier, user_id, ip):
        burn_time(password)
        _record_attempt(identifier, user_id, False, "rate_limited", ip, user_agent)
        return AuthResult(False, "rate_limited")

    if user is None:
        burn_time(password)   # same delay as a real check: don't reveal which usernames exist
        _record_attempt(identifier, None, False, "invalid_credentials", ip, user_agent)
        return AuthResult(False, "invalid_credentials")

    if not verify_password(user["password_hash"], password):
        _record_attempt(identifier, user_id, False, "invalid_credentials", ip, user_agent)
        return AuthResult(False, "invalid_credentials")

    if user["account_status"] != "Active":
        _record_attempt(identifier, user_id, False, "account_inactive", ip, user_agent)
        return AuthResult(False, "account_inactive")

    with transaction() as cur:
        _record_attempt(identifier, user_id, True, None, ip, user_agent, cursor=cur)
        cur.execute("UPDATE users SET last_login_at = NOW() WHERE user_id = %s", (user_id,))
    return AuthResult(True, user_id=user_id, session_version=user["session_version"])


def load_user(user_id):
    """The signed-in user's profile and role names, or None."""
    user = query_one(
        "SELECT user_id, full_name, username, email, account_status, must_change_password, "
        "session_version, last_login_at, created_at FROM users WHERE user_id = %s",
        (user_id,),
    )
    if user is None:
        return None
    user["roles"] = [row["role_name"] for row in query_all(
        "SELECT r.role_name FROM user_roles ur JOIN roles r ON r.role_id = ur.role_id "
        "WHERE ur.user_id = %s ORDER BY r.role_id",
        (user_id,),
    )]
    user["must_change_password"] = bool(user["must_change_password"])
    return user


def logout(user_id):
    """Invalidate every session of this user by bumping session_version.
    Old cookies (even copied ones) stop working immediately."""
    with transaction() as cur:
        cur.execute("UPDATE users SET session_version = session_version + 1 WHERE user_id = %s", (user_id,))
        audit.record("logout", "User", _username(user_id), user_id=user_id, cursor=cur)


def _username(user_id):
    return query_value("SELECT username FROM users WHERE user_id = %s", (user_id,))


def recent_logins(user_id, limit=5):
    return query_all(
        "SELECT attempted_at, success, failure_reason, ip_address FROM login_attempts "
        "WHERE user_id = %s ORDER BY attempted_at DESC LIMIT %s",
        (user_id, limit),
    )


# ---------------------------------------------------------------------------
# Password change
# ---------------------------------------------------------------------------
def change_password(user_id, current_password, new_password):
    """Returns (new_session_version, None) on success or (None, error message)."""
    row = query_one("SELECT username, password_hash FROM users WHERE user_id = %s", (user_id,))
    if row is None or not verify_password(row["password_hash"], current_password):
        return None, "Your current password is incorrect."
    problems = password_problems(new_password, row["username"])
    if problems:
        return None, " ".join(problems)
    if verify_password(row["password_hash"], new_password):
        return None, "Choose a password different from your current one."
    with transaction() as cur:
        cur.execute(
            "UPDATE users SET password_hash = %s, must_change_password = FALSE, "
            "session_version = session_version + 1 WHERE user_id = %s",
            (hash_password(new_password), user_id),
        )
        audit.record("user.password_change", "User", row["username"], user_id=user_id, cursor=cur)
        cur.execute("SELECT session_version FROM users WHERE user_id = %s", (user_id,))
        version = cur.fetchone()["session_version"]
    return version, None


# ---------------------------------------------------------------------------
# Signup (access requests)
# ---------------------------------------------------------------------------
def signup_conflicts(username, email):
    """Field errors for a username/email already used by an account or a
    pending request. Comparisons are case-insensitive (column collation)."""
    errors = {}
    if query_value(
        "SELECT (SELECT COUNT(*) FROM users WHERE username = %s) + "
        "(SELECT COUNT(*) FROM account_requests WHERE request_status = 'Pending' AND username = %s)",
        (username, username),
    ):
        errors["username"] = "That username is taken or already has a pending request. Try another."
    if query_value(
        "SELECT (SELECT COUNT(*) FROM users WHERE email = %s) + "
        "(SELECT COUNT(*) FROM account_requests WHERE request_status = 'Pending' AND email = %s)",
        (email, email),
    ):
        errors["email"] = ("This email can't be used. If you already have an account or a pending "
                           "request, contact your administrator.")
    return errors


def signup_rate_limited(ip):
    count = query_value(
        "SELECT COUNT(*) FROM audit_logs WHERE action = 'account.request' AND ip_address = %s "
        "AND created_at >= NOW() - INTERVAL 1 HOUR",
        (ip,),
    )
    return count >= current_app.config["SIGNUP_MAX_PER_IP_PER_HOUR"]


def create_access_request(full_name, email, username, password, reason):
    """Store a Pending request with a hashed password. Returns the AR-#### code,
    or raises ValueError(field_errors) if the username/email was taken meanwhile."""
    try:
        with transaction() as cur:
            cur.execute(
                "INSERT INTO account_requests (full_name, email, username, password_hash, reason) "
                "VALUES (%s, %s, %s, %s, %s)",
                (full_name, email, username, hash_password(password), reason or None),
            )
            code = f"AR-{cur.lastrowid:04d}"
            audit.record("account.request", "Account request", code, user_id=None,
                         details=f"Requested username {username}", cursor=cur)
    except (ConstraintViolation, BusinessRuleError) as err:
        # Lost a race with another request, or the trigger found an existing account.
        raise ValueError(signup_conflicts(username, email) or
                         {"username": "That username or email is no longer available."}) from err
    return code


# ---------------------------------------------------------------------------
# Redirect safety
# ---------------------------------------------------------------------------
def is_safe_next(target):
    """Only allow redirects to paths on this site (prevents open redirects)."""
    if not target or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return False
    parsed = urlparse(target)
    return not parsed.scheme and not parsed.netloc
