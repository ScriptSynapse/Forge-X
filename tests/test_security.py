"""Phase 14: security regression tests (no MySQL needed).

These look at the WHOLE application rather than one feature, so a route,
query or template added later is checked automatically:

* every route except a short public list requires login
* every POST route rejects requests without a CSRF token
* security headers are on every response (HSTS only over HTTPS)
* SQL built with f-strings only interpolates reviewed, fixed fragments
* templates never switch off Jinja's automatic HTML escaping
"""
import ast
import pathlib
import re

import pytest

from app import create_app
from app.config import TestingConfig

APP_DIR = pathlib.Path(__file__).resolve().parent.parent / "app"

# Endpoints that are deliberately reachable without logging in.
PUBLIC_ENDPOINTS = {"static", "public.index", "auth.login", "auth.signup", "auth.signup_done", "system.healthz"}

# Every expression interpolated into an SQL-looking f-string, reviewed in Phase 14.
# SQL fragments: built only from literal SQL with %s placeholders, or validated choices.
REVIEWED_SQL_FRAGMENTS = {
    "condition", "where", "base", "scope.case_filter", "order_by", "SORTS[filters.sort][1]",
    "LOCK_WINDOW_MINUTES", "int(months) - 1",
}
# Not SQL at all: user-facing messages / PDF text that merely contain the word "from".
REVIEWED_NON_SQL = {"code", "file_name", "size", "generated_at", "generated_by", "old['location_name']"}


def _url_for_rule(rule):
    values = {}
    for arg in rule.arguments:
        converter = rule._converters[arg].__class__.__name__
        values[arg] = 1 if converter == "IntegerConverter" else "FX-TEST-0001"
    return rule.build(values, append_unknown=False)[1]


def _rules(app, method):
    return [r for r in app.url_map.iter_rules()
            if method in r.methods and r.endpoint not in PUBLIC_ENDPOINTS]


def test_every_non_public_route_requires_login():
    app = create_app(TestingConfig())
    client = app.test_client()
    checked = 0
    for method in ("GET", "POST"):
        for rule in _rules(app, method):
            url = _url_for_rule(rule)
            response = client.open(url, method=method)
            if url.startswith("/api/"):
                assert response.status_code == 401, f"{method} {url} -> {response.status_code}"
            else:
                assert response.status_code == 302 and "/login" in response.headers["Location"], \
                    f"{method} {url} -> {response.status_code}: not protected by login"
            checked += 1
    assert checked > 60          # guards against the test silently checking nothing


def test_every_post_route_rejects_a_missing_csrf_token():
    config = TestingConfig()
    config.WTF_CSRF_ENABLED = True
    app = create_app(config)
    client = app.test_client()
    posts = [r for r in app.url_map.iter_rules() if "POST" in r.methods]
    assert len(posts) > 20
    for rule in posts:
        response = client.post(_url_for_rule(rule), data={"x": "1"})
        assert response.status_code == 400, f"POST {rule.rule} accepted a request without a CSRF token"


@pytest.mark.parametrize("base_url,expect_hsts", [("http://localhost", False), ("https://localhost", True)])
def test_security_headers(base_url, expect_hsts):
    app = create_app(TestingConfig())
    for path in ("/", "/login", "/no-such-page"):
        response = app.test_client().get(path, base_url=base_url)
        headers = response.headers
        assert "default-src 'self'" in headers["Content-Security-Policy"]
        assert headers["X-Frame-Options"] == "DENY" and headers["X-Content-Type-Options"] == "nosniff"
        assert headers["Cache-Control"] == "no-store" and "noindex" in headers["X-Robots-Tag"]
        assert ("Strict-Transport-Security" in headers) is expect_hsts, path


def test_sql_fstrings_only_interpolate_reviewed_fragments():
    sql_word = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|CALL|FROM|WHERE)\b", re.IGNORECASE)
    unreviewed = []
    for path in APP_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.JoinedStr):
                continue
            literal = "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
            if not sql_word.search(literal):
                continue
            for value in node.values:
                if isinstance(value, ast.FormattedValue):
                    expr = ast.unparse(value.value)
                    if expr not in REVIEWED_SQL_FRAGMENTS | REVIEWED_NON_SQL:
                        unreviewed.append(f"{path.relative_to(APP_DIR.parent)}:{node.lineno}  {{{expr}}}")
    assert not unreviewed, ("New values interpolated into SQL-like f-strings. Use %s parameters, or review "
                            "them and add them to REVIEWED_SQL_FRAGMENTS:\n" + "\n".join(unreviewed))


def test_templates_never_switch_off_escaping():
    offenders = []
    for path in (APP_DIR / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"\|\s*safe\b|autoescape\s+false|Markup\(", text):
            offenders.append(str(path.relative_to(APP_DIR)))
    assert not offenders, f"Templates bypass HTML escaping: {offenders}"


def test_secrets_are_not_shipped():
    root = APP_DIR.parent
    assert ".env" in (root / ".gitignore").read_text(encoding="utf-8").split()
    # The only literal allowed is TestingConfig's key, which is marked "testing-only-"
    # and used by pytest alone (production refuses placeholder keys at startup).
    pattern = re.compile(r"""(password|secret_key)\s*=\s*["'](?!testing-only-)[^"'{}\s]{6,}["']""", re.IGNORECASE)
    for path in APP_DIR.rglob("*.py"):
        assert not pattern.search(path.read_text(encoding="utf-8")), f"Possible hard-coded secret in {path.name}"
