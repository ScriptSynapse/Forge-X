"""User and role administration. Every change is checked here AND by the
database (CHECK constraints, triggers, stored procedures)."""
from .. import audit
from ..auth.passwords import hash_password, password_problems
from ..db import call_proc, query_all, query_one, query_value, transaction

ADMIN_ROLE = "Administrator"


class AdminActionError(Exception):
    """A refused administrative action, with a message safe to display."""


def _not_self(target_id, admin_id):
    if target_id == admin_id:
        raise AdminActionError("You can't change your own account here. Ask another administrator.")


# ---------------------------------------------------------------------------
# Reads
# ---------------------------------------------------------------------------
def list_users():
    rows = query_all(
        """
        SELECT u.user_id, u.full_name, u.email, u.username, u.account_status, u.last_login_at,
               GROUP_CONCAT(r.role_name ORDER BY r.role_id SEPARATOR '|') AS role_list
          FROM users u
          LEFT JOIN user_roles ur ON ur.user_id = u.user_id
          LEFT JOIN roles r       ON r.role_id = ur.role_id
         GROUP BY u.user_id
         ORDER BY u.account_status, u.full_name
        """
    )
    for row in rows:
        row["roles"] = row.pop("role_list").split("|") if row["role_list"] else []
    return rows


def list_pending_requests():
    return query_all(
        "SELECT request_id, full_name, email, username, reason, created_at FROM account_requests "
        "WHERE request_status = 'Pending' ORDER BY created_at"
    )


def list_roles():
    return query_all(
        """
        SELECT r.role_id, r.role_name, r.description,
               (SELECT COUNT(*) FROM user_roles ur JOIN users u ON u.user_id = ur.user_id
                 WHERE ur.role_id = r.role_id AND u.account_status = 'Active') AS active_users
          FROM roles r ORDER BY r.role_id
        """
    )


def get_user(user_id):
    user = query_one(
        "SELECT user_id, full_name, email, username, account_status, must_change_password, "
        "created_at, updated_at, last_login_at FROM users WHERE user_id = %s",
        (user_id,),
    )
    if user:
        user["roles"] = query_all(
            """
            SELECT r.role_id, r.role_name, ur.assigned_at, a.full_name AS assigned_by
              FROM user_roles ur
              JOIN roles r      ON r.role_id = ur.role_id
              LEFT JOIN users a ON a.user_id = ur.assigned_by
             WHERE ur.user_id = %s ORDER BY r.role_id
            """,
            (user_id,),
        )
    return user


def user_activity(user_id, limit=15):
    return query_all(
        "SELECT occurred_at, action, entity_type, entity_ref, outcome, details FROM v_activity_feed "
        "WHERE user_id = %s ORDER BY occurred_at DESC LIMIT %s",
        (user_id, limit),
    )


# ---------------------------------------------------------------------------
# Account requests (stored procedures do the transactional work)
# ---------------------------------------------------------------------------
def approve_request(request_id, role_id, admin_id):
    result = call_proc("sp_approve_account_request", (request_id, role_id, admin_id, None))
    return result[3]   # OUT p_user_id


def reject_request(request_id, admin_id, note=None):
    call_proc("sp_reject_account_request", (request_id, admin_id, (note or "").strip()[:255] or None))


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
def create_user(full_name, email, username, role_id, password, must_change, admin_id):
    """users row + first role + audit row, in one transaction. Duplicate
    username/email raises ConstraintViolation (unique keys)."""
    with transaction() as cur:
        cur.execute(
            "INSERT INTO users (full_name, email, username, password_hash, must_change_password) "
            "VALUES (%s, %s, %s, %s, %s)",
            (full_name, email, username, hash_password(password), bool(must_change)),
        )
        user_id = cur.lastrowid
        # Trigger trg_ur_audit_insert writes the role.assign audit row.
        cur.execute("INSERT INTO user_roles (user_id, role_id, assigned_by) VALUES (%s, %s, %s)",
                    (user_id, role_id, admin_id))
        audit.record("user.create", "User", username, user_id=admin_id, cursor=cur,
                     details="Account created by an administrator")
    return user_id


def _lock_active_admins(cur):
    cur.execute(
        """
        SELECT u.user_id FROM users u
          JOIN user_roles ur ON ur.user_id = u.user_id
          JOIN roles r       ON r.role_id = ur.role_id
         WHERE r.role_name = %s AND u.account_status = 'Active'
           FOR UPDATE
        """,
        (ADMIN_ROLE,),
    )
    return {row["user_id"] for row in cur.fetchall()}


def add_role(target_id, role_id, admin_id):
    _not_self(target_id, admin_id)
    if query_value("SELECT COUNT(*) FROM user_roles WHERE user_id = %s AND role_id = %s", (target_id, role_id)):
        raise AdminActionError("The user already has that role.")
    with transaction() as cur:
        cur.execute("INSERT INTO user_roles (user_id, role_id, assigned_by) VALUES (%s, %s, %s)",
                    (target_id, role_id, admin_id))


def revoke_role(target_id, role_id, admin_id):
    _not_self(target_id, admin_id)
    with transaction() as cur:
        cur.execute("SELECT role_name FROM roles WHERE role_id = %s", (role_id,))
        role = cur.fetchone()
        cur.execute("SELECT role_id FROM user_roles WHERE user_id = %s FOR UPDATE", (target_id,))
        held = {row["role_id"] for row in cur.fetchall()}
        if role is None or role_id not in held:
            raise AdminActionError("The user doesn't have that role.")
        if len(held) == 1:
            raise AdminActionError("Every user needs at least one role. Deactivate the account instead.")
        if role["role_name"] == ADMIN_ROLE and _lock_active_admins(cur) == {target_id}:
            raise AdminActionError("FORGE-X needs at least one active administrator.")
        # Trigger trg_ur_audit_delete writes the role.revoke audit row.
        cur.execute("DELETE FROM user_roles WHERE user_id = %s AND role_id = %s", (target_id, role_id))


def set_active(target_id, active, admin_id):
    _not_self(target_id, admin_id)
    status = "Active" if active else "Deactivated"
    with transaction() as cur:
        if not active and _lock_active_admins(cur) == {target_id}:
            raise AdminActionError("FORGE-X needs at least one active administrator.")
        # Deactivation also bumps session_version, signing the user out everywhere.
        cur.execute(
            "UPDATE users SET account_status = %s, "
            "session_version = session_version + IF(%s = 'Deactivated', 1, 0) WHERE user_id = %s",
            (status, status, target_id),
        )
        if cur.rowcount == 0:
            raise AdminActionError("User not found.")
        cur.execute("SELECT username FROM users WHERE user_id = %s", (target_id,))
        username = cur.fetchone()["username"]
        audit.record("user.activate" if active else "user.deactivate", "User", username,
                     user_id=admin_id, cursor=cur)


def reset_password(target_id, password, admin_id):
    """Admin-assisted recovery (assumption A3): set a temporary password that
    must be changed at next login. The password itself is never logged."""
    _not_self(target_id, admin_id)
    username = query_value("SELECT username FROM users WHERE user_id = %s", (target_id,))
    if username is None:
        raise AdminActionError("User not found.")
    problems = password_problems(password, username)
    if problems:
        raise AdminActionError(" ".join(problems))
    with transaction() as cur:
        cur.execute(
            "UPDATE users SET password_hash = %s, must_change_password = TRUE, "
            "session_version = session_version + 1 WHERE user_id = %s",
            (hash_password(password), target_id),
        )
        audit.record("user.password_reset", "User", username, user_id=admin_id, cursor=cur,
                     details="Temporary password set; change required at next login")
