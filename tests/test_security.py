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
    # FORGE-X 2.0 Phase 1 (dashboard): `since` is "" or " AND <literal column> >= NOW() - INTERVAL %s DAY"
    # with the days as a parameter; `body` and `alias` come from a fixed tuple in activity_in_period().
    "since", "body", "alias",
    # FORGE-X 2.0 Phase 2: a constant expression defined in app/cases/services.py (no input in it).
    "LAST_ACTIVITY_SQL",
    # FORGE-X 2.0 Phase 3: constant expressions defined in app/evidence/services.py (no input in them).
    "CURRENT_HASH_SQL", "EXAM_STATUS_SQL",
    # FORGE-X 2.0 Phase 4 (custody log): `union` joins two fixed branches built by _branch() with %s
    # parameters only; `direction` comes from the fixed ORDERS dict (ASC/DESC).
    "union", "direction",
    # FORGE-X 2.0 Phase 8 (app/graph/services.py): constants with no input in them, and _in(), which
    # returns only "%s, %s, ..." placeholders (the values are passed as parameters).
    "_EVIDENCE_COLUMNS", "_EVIDENCE_FROM", "_ARTIFACT_SELECT", "_LATEST_MATCHES", "_in(values)", "_in(ids)",
    # FORGE-X 2.0 Phase 9 (app/storage/migrate.py): human-readable NOTE text ("Moved from local ...") passed
    # as a %s parameter value; it is never part of the SQL statement.
    "f['backend']",
    # FORGE-X 2.0 Phase 10 (app/api/routes.py): INDICATOR_SQL with only Scope.case_filter inserted.
    "indicator_sql",
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


def test_every_locking_read_has_the_privilege_it_needs():
    """MySQL 8.0.22+ refuses SELECT ... FOR UPDATE unless the account has UPDATE
    or DELETE on EVERY table the query reads. The application account
    deliberately has neither on append-only tables, so a locking read there
    fails at run time (this happened once, on evidence_hashes). Check every
    locking read in the code against the grants in database/app_user.sql."""
    grants = (APP_DIR.parent / "database" / "app_user.sql").read_text(encoding="utf-8")
    lockable = set()
    for privileges, table in re.findall(r"GRANT ([A-Z, ]+) ON forge_x_db\.(\w+)", grants):
        if {"UPDATE", "DELETE"} & {p.strip() for p in privileges.split(",")}:
            lockable.add(table)
    problems = []
    for path in APP_DIR.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, (ast.Constant, ast.JoinedStr)):
                continue
            text = node.value if isinstance(node, ast.Constant) else "".join(
                v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))
            if not isinstance(text, str) or not re.search(r"\bFOR UPDATE\b", text) or "SELECT ..." in text:
                continue
            for table in re.findall(r"\b(?:FROM|JOIN)\s+(\w+)", text):
                if table not in lockable:
                    problems.append(f"{path.relative_to(APP_DIR.parent)}:{node.lineno} locks {table}")
    assert not problems, "Locking reads on tables without UPDATE/DELETE privilege:\n" + "\n".join(problems)


def test_no_inline_styles_so_the_csp_can_forbid_them():
    """The Content-Security-Policy allows styles only from this server
    ('unsafe-inline' was removed in FORGE-X 2.0 Phase 1). Inline style
    attributes or <style> blocks would be blocked by the browser, so none
    may exist. JavaScript may still set element.style, which CSP allows."""
    from app import CONTENT_SECURITY_POLICY
    style_src = CONTENT_SECURITY_POLICY.split("style-src", 1)[1].split(";", 1)[0]
    assert "unsafe-inline" not in style_src
    offenders = []
    for path in (APP_DIR / "templates").rglob("*.html"):
        text = path.read_text(encoding="utf-8")
        if re.search(r"\sstyle\s*=|<style\b", text, re.IGNORECASE):
            offenders.append(str(path.relative_to(APP_DIR)))
    for path in (APP_DIR / "static" / "js").glob("*.js"):
        if re.search(r"setAttribute\(\s*['\"]style|style=", path.read_text(encoding="utf-8")):
            offenders.append(str(path.relative_to(APP_DIR)))
    assert not offenders, f"Inline styles would be blocked by the CSP: {offenders}"
