"""Personal API tokens (FORGE-X 2.0 Phase 10).

Format:  fx_<prefix>_<secret>   e.g. fx_3f9a1c2e_Q2x...   (prefix: 8 hex, secret: 32 random bytes)

Only SHA-256(token) is stored. The token is high-entropy random data, so a
plain SHA-256 is the right choice (a slow password hash adds nothing and
would cost time on every request). The prefix is kept in clear so a user
can tell their tokens apart; it isn't secret.
"""
import hashlib
import hmac
import re
import secrets
from .. import audit
from ..db import query_all, query_one, query_value, transaction

TOKEN_RE = re.compile(r"^fx_([0-9a-f]{8})_([A-Za-z0-9_-]{40,64})$")
MAX_DAYS = 90
DAY_CHOICES = (7, 30, 90)
MAX_ACTIVE_PER_USER = 5


class TokenError(Exception):
    """A refused token action; the message is safe to show."""


def _hash(token):
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def create(user, name, days):
    name = (name or "").strip()
    if not 2 <= len(name) <= 60:
        raise TokenError("Name the token (2 to 60 characters), e.g. \"Lab report script\".")
    if days not in DAY_CHOICES:
        raise TokenError(f"Choose an expiry of {', '.join(map(str, DAY_CHOICES))} days.")
    if query_value("SELECT COUNT(*) FROM api_tokens WHERE user_id = %s AND revoked_at IS NULL AND expires_at > NOW()",
                   (user["user_id"],)) >= MAX_ACTIVE_PER_USER:
        raise TokenError(f"You already have {MAX_ACTIVE_PER_USER} active tokens. Revoke one first.")
    prefix = secrets.token_hex(4)
    token = f"fx_{prefix}_{secrets.token_urlsafe(32)}"
    with transaction() as cur:
        cur.execute("INSERT INTO api_tokens (user_id, name, token_prefix, token_hash, created_at, expires_at) "
                    "VALUES (%s, %s, %s, %s, NOW(), NOW() + INTERVAL %s DAY)",
                    (user["user_id"], name, prefix, _hash(token), days))
        audit.record("api.token_create", "API token", f"fx_{prefix}", cursor=cur,
                     details=f"{name!r}, expires in {days} days")
    return token


def list_for(user_id):
    return query_all("SELECT token_id, name, token_prefix, created_at, expires_at, last_used_at, revoked_at, "
                     "(revoked_at IS NULL AND expires_at > NOW()) AS is_active FROM api_tokens "
                     "WHERE user_id = %s ORDER BY is_active DESC, created_at DESC", (user_id,))


def revoke(user, token_id):
    """Users revoke their own tokens; administrators may revoke anyone's."""
    with transaction() as cur:
        cur.execute("SELECT token_id, user_id, token_prefix, revoked_at FROM api_tokens WHERE token_id = %s FOR UPDATE",
                    (token_id,))
        row = cur.fetchone()
        if row is None or (row["user_id"] != user["user_id"] and "Administrator" not in user["roles"]):
            raise TokenError("Token not found.")
        if row["revoked_at"] is not None:
            raise TokenError("That token is already revoked.")
        cur.execute("UPDATE api_tokens SET revoked_at = NOW() WHERE token_id = %s", (token_id,))
        audit.record("api.token_revoke", "API token", f"fx_{row['token_prefix']}", cursor=cur)


def authenticate(raw):
    """Return (user_id, token_id) for a valid, active token, or None. Constant-
    time comparison of the stored hash; the lookup itself is by hash."""
    match = TOKEN_RE.match(raw or "")
    if not match:
        return None
    digest = _hash(raw)
    row = query_one("SELECT token_id, user_id, token_hash FROM api_tokens WHERE token_hash = %s "
                    "AND token_prefix = %s AND revoked_at IS NULL AND expires_at > NOW()", (digest, match.group(1)))
    if row is None or not hmac.compare_digest(row["token_hash"], digest):
        return None
    return row["user_id"], row["token_id"]


def mark_used(token_id):
    """Record use at most once a minute per token (keeps writes cheap)."""
    with transaction() as cur:
        cur.execute("UPDATE api_tokens SET last_used_at = NOW() WHERE token_id = %s "
                    "AND (last_used_at IS NULL OR last_used_at < NOW() - INTERVAL 1 MINUTE)", (token_id,))


def prefix_of(raw):
    match = TOKEN_RE.match(raw or "")
    return f"fx_{match.group(1)}" if match else "malformed"

