"""FORGE-X 2.0 Phase 10 end to end: create a token on the website, use it, revoke it.
Opt-in (FORGE_X_DB_WRITE_TESTS=1, test database)."""
import os
import re

import pytest

from app.db import query_all, query_one
from tests.conftest import login

pytestmark = [
    pytest.mark.db,
    pytest.mark.db_write,
    pytest.mark.skipif(os.getenv("FORGE_X_DB_WRITE_TESTS") != "1",
                       reason="set FORGE_X_DB_WRITE_TESTS=1 to run tests that write to MySQL"),
]


def test_token_lifecycle(app, client, make_user):
    from app.api import routes
    routes._HITS.clear()
    user = make_user("Investigator")
    login(client, user["username"], user["password"])
    page = client.post("/account/api-tokens", data={"name": "pytest script", "days": "7"}).get_data(as_text=True)
    token = re.search(r"fx_[0-9a-f]{8}_[A-Za-z0-9_-]{40,64}", page).group(0)
    client.post("/logout")
    with app.app_context():
        row = query_one("SELECT token_id, token_hash, expires_at > NOW() AS live FROM api_tokens WHERE user_id = %s",
                        (user["user_id"],))
    assert row["live"] and token not in row["token_hash"]

    api = app.test_client()                                              # no session: the token alone
    me = api.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).get_json()["data"]
    assert me["username"] == user["username"] and me["authenticated_by"] == "token"
    assert api.get("/api/v1/cases", headers={"Authorization": f"Bearer {token}"}).get_json()["total"] == 0

    login(client, user["username"], user["password"])
    client.post(f"/account/api-tokens/{row['token_id']}/revoke")
    assert api.get("/api/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401
    with app.app_context():
        actions = {r["action"] for r in query_all("SELECT DISTINCT action FROM audit_logs WHERE entity_ref = %s",
                                                  (token[:11],))}                 # the public prefix fx_xxxxxxxx
    assert {"api.token_create", "api.token_revoke", "api.auth_failed"} <= actions
