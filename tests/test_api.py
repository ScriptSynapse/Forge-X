"""FORGE-X 2.0 Phase 10: the read-only REST API without MySQL (authentication, rate limits,
field allowlists, scoping, token format, OpenAPI matches the routes)."""
import hashlib
from datetime import date, datetime

import pytest

from app.api import openapi, routes, tokens

ADMIN = {"user_id": 1, "full_name": "Admin", "username": "admin", "roles": ["Administrator"],
         "account_status": "Active", "must_change_password": False, "session_version": 0}
INVESTIGATOR = dict(ADMIN, user_id=7, full_name="Inv", username="inv", roles=["Investigator"])
GOOD = "fx_0123abcd_" + "A" * 43


@pytest.fixture
def api(app, monkeypatch):
    """Token authentication wired to fakes; returns (client, state)."""
    state = {"users": {GOOD: ADMIN}, "audits": [], "used": []}
    routes._HITS.clear()
    monkeypatch.setattr(tokens, "authenticate",
                        lambda raw: (state["users"][raw]["user_id"], 11) if raw in state["users"] else None)
    monkeypatch.setattr(routes, "load_user", lambda uid: next(u for u in state["users"].values() if u["user_id"] == uid))
    monkeypatch.setattr(tokens, "mark_used", lambda tid: state["used"].append(tid))
    monkeypatch.setattr(routes, "set_audit_user", lambda uid: None)
    monkeypatch.setattr(routes.audit, "record", lambda *a, **k: state["audits"].append((a, k)))
    return app.test_client(), state


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def test_valid_token_authenticates_and_is_marked_used(api):
    client, state = api
    response = client.get("/api/v1/me", headers=bearer(GOOD))
    assert response.status_code == 200
    assert response.get_json()["data"] == {"username": "admin", "full_name": "Admin", "roles": ["Administrator"],
                                           "scope": "All cases in the lab", "authenticated_by": "token"}
    assert state["used"] == [11] and response.headers["Cache-Control"].startswith("no-store")


@pytest.mark.parametrize("header", ["Basic abc", "Bearer", "Bearer   ", "token " + GOOD, "Bearer fx_nope"])
def test_bad_credentials_get_401_json_with_a_challenge(api, header):
    client, state = api
    response = client.get("/api/v1/me", headers={"Authorization": header})
    assert response.status_code == 401 and response.is_json
    assert response.get_json()["status"] == 401 and "Bearer" in response.headers["WWW-Authenticate"]


def test_unknown_token_is_audited_without_revealing_it(api):
    client, state = api
    secret = "fx_deadbeef_" + "S" * 43
    assert client.get("/api/v1/cases", headers=bearer(secret)).status_code == 401
    (args, kwargs), = state["audits"]
    assert args[0] == "api.auth_failed" and kwargs["outcome"] == "Denied"
    assert "S" * 43 not in repr(state["audits"]) and args[2] == "fx_deadbeef"      # only the public prefix


def test_inactive_accounts_and_forced_password_changes_are_refused(api):
    client, state = api
    state["users"][GOOD] = dict(ADMIN, account_status="Inactive")
    assert client.get("/api/v1/me", headers=bearer(GOOD)).status_code == 401
    state["users"][GOOD] = dict(ADMIN, must_change_password=True)
    assert client.get("/api/v1/me", headers=bearer(GOOD)).status_code == 403


def test_failed_attempts_are_rate_limited_per_address(api, app):
    client, _ = api
    app.config["API_FAILED_AUTH_PER_MINUTE"] = 3
    codes = [client.get("/api/v1/me", headers=bearer("fx_00000000_" + "x" * 43)).status_code for _ in range(5)]
    assert codes == [401, 401, 401, 429, 429]
    # Even a valid token is held back while the address is blocked.
    response = client.get("/api/v1/me", headers=bearer(GOOD))
    assert response.status_code == 429 and int(response.headers["Retry-After"]) > 0


def test_requests_are_rate_limited_per_user(api, app):
    client, _ = api
    app.config["API_RATE_LIMIT_PER_MINUTE"] = 2
    codes = [client.get("/api/v1/me", headers=bearer(GOOD)).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_every_endpoint_uses_the_callers_case_scope(api, monkeypatch):
    client, state = api
    state["users"][GOOD] = INVESTIGATOR
    from app.cases import services as cases
    from app.pagination import Page
    seen = {}

    def list_cases(scope, filters, page, per_page):
        seen.update(lab_wide=scope.lab_wide, params=scope.params, per_page=per_page, status=filters.status)
        return Page([{"case_reference": "FX-2026-0002", "title": "T", "status": "Open", "case_id": 2,
                      "password_hash": "x", "created_at": datetime(2026, 10, 9, 19, 39)}], page, per_page, 1)
    monkeypatch.setattr(cases, "list_cases", list_cases)
    body = client.get("/api/v1/cases?status=active&per_page=500", headers=bearer(GOOD)).get_json()
    assert seen == {"lab_wide": False, "params": (7,), "per_page": 100, "status": "active"}
    item = body["data"][0]
    assert "password_hash" not in item and "case_id" not in item                    # allowlist only
    assert item["created_at"] == "2026-10-09T19:39:00+05:30"                        # ISO 8601 with the lab offset
    assert (body["page"], body["per_page"], body["total"], body["pages"]) == (1, 100, 1, 1)


def test_invisible_records_are_404(api, monkeypatch):
    client, _ = api
    from app.cases import services as cases
    monkeypatch.setattr(cases, "get_case", lambda scope, ref: None)
    response = client.get("/api/v1/cases/FX-2026-0099", headers=bearer(GOOD))
    assert response.status_code == 404 and response.get_json()["status"] == 404


def test_pick_returns_only_listed_fields_in_json_safe_form():
    from decimal import Decimal
    row = {"evidence_code": "FX-EV-2026-00001", "object_id": "secret-uuid", "size_bytes": Decimal("10"),
           "collected_at": datetime(2026, 1, 2, 3, 4, 5, 999), "due_date": date(2026, 1, 9), "has_file": 1}
    with _app_ctx():
        out = routes.pick(row, ("evidence_code", "size_bytes", "collected_at", "due_date", "has_file", "missing"),
                          bools=("has_file",))
    assert out == {"evidence_code": "FX-EV-2026-00001", "size_bytes": 10, "collected_at": "2026-01-02T03:04:05+05:30",
                   "due_date": "2026-01-09", "has_file": True}
    for fields in (routes.EVIDENCE_DETAIL, routes.STORED_FILE, routes.CASE_DETAIL, routes.EXAM_DETAIL):
        assert not {"object_id", "password_hash", "token_hash", "session_version"} & set(fields)


def _app_ctx():
    from app import create_app
    from app.config import TestingConfig
    return create_app(TestingConfig()).app_context()


def test_tokens_are_random_and_only_their_hash_is_stored(monkeypatch):
    import contextlib
    stored = []

    class Cursor:
        def execute(self, sql, params=()):
            stored.append(params)

    @contextlib.contextmanager
    def fake_transaction():
        yield Cursor()
    monkeypatch.setattr(tokens, "transaction", fake_transaction)
    monkeypatch.setattr(tokens, "query_value", lambda sql, params=(): 0)
    monkeypatch.setattr(tokens.audit, "record", lambda *a, **k: None)
    first, second = tokens.create(ADMIN, "Script", 30), tokens.create(ADMIN, "Script", 30)
    assert first != second and tokens.TOKEN_RE.match(first)
    params = stored[0]
    assert first not in repr(stored) and params[3] == hashlib.sha256(first.encode()).hexdigest()
    with pytest.raises(tokens.TokenError):
        tokens.create(ADMIN, "Script", 365)                                       # expiry capped
    monkeypatch.setattr(tokens, "query_value", lambda sql, params=(): tokens.MAX_ACTIVE_PER_USER)
    with pytest.raises(tokens.TokenError, match="active tokens"):
        tokens.create(ADMIN, "Another", 7)


@pytest.mark.parametrize("raw", ["", "fx_", "fx_0123abcd_short", "xx_0123abcd_" + "A" * 43, "fx_0123ABCD_" + "A" * 43])
def test_malformed_tokens_never_reach_the_database(raw, monkeypatch):
    monkeypatch.setattr(tokens, "query_one", lambda *a, **k: pytest.fail("database queried for a malformed token"))
    assert tokens.authenticate(raw) is None


def test_openapi_documents_exactly_the_registered_routes(app):
    with app.test_request_context():
        spec = openapi.build()
    api_rules = {r.rule.replace("/api/v1", "", 1) for r in app.url_map.iter_rules() if r.rule.startswith("/api/v1")}
    documented = {p.replace("{", "<").replace("}", ">") for p in spec["paths"]}
    assert documented == api_rules
    assert all(list(item) == ["get"] for item in spec["paths"].values())          # v1 is read-only
    for path, item in spec["paths"].items():
        op = item["get"]
        if path != "/openapi.json":
            assert {"200", "401", "429"} <= set(op["responses"]) and op["summary"]
        if "{" in path:
            assert "404" in op["responses"]


def test_api_v1_routes_are_get_only(app):
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith("/api/v1"):
            assert rule.methods - {"HEAD", "OPTIONS"} == {"GET"}, rule.rule
