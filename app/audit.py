"""Writing application audit records.

Every important action is recorded in audit_logs with who, what, which
record, the outcome and a short non-sensitive description. Passwords,
hashes, tokens and session data are never passed here.
"""
from flask import g, has_request_context, request

from .db import execute

_SQL = ("INSERT INTO audit_logs (user_id, action, entity_type, entity_ref, outcome, details, ip_address) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)")
_CURRENT_USER = object()


def record(action, entity_type, entity_ref=None, outcome="Success", details=None,
           user_id=_CURRENT_USER, cursor=None):
    """Insert one audit row.

    Pass `cursor` (from `with transaction() as cur`) to write the audit row in
    the same transaction as the change it describes, so both commit or
    neither does.
    """
    if user_id is _CURRENT_USER:
        user = g.get("user") if has_request_context() else None
        user_id = user["user_id"] if user else None
    ip = request.remote_addr if has_request_context() else None
    params = (user_id, action[:50], entity_type, (entity_ref or None) and str(entity_ref)[:40],
              outcome, (details or None) and str(details)[:500], ip)
    if cursor is not None:
        cursor.execute(_SQL, params)
    else:
        execute(_SQL, params)
