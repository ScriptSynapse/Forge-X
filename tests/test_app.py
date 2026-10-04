"""Phase 5: application factory, configuration, templates and error handling.
These tests do not need MySQL."""
import pytest
from flask import g, render_template_string

from app import create_app
from app.config import Config, TestingConfig, validate_config
from app.pagination import Page, parse_page
from app.ui import build_navigation, initials, tone


def test_app_is_created_in_testing_mode(app):
    assert app.testing is True
    assert "public" in app.blueprints and "system" in app.blueprints


def test_session_cookie_is_protected(app):
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_csrf_is_on_outside_tests(monkeypatch):
    monkeypatch.setenv("FORGE_X_SECRET_KEY", "x" * 64)
    assert Config().WTF_CSRF_ENABLED is True
    assert TestingConfig().WTF_CSRF_ENABLED is False


def test_refuses_root_database_account(monkeypatch):
    monkeypatch.setenv("FORGE_X_SECRET_KEY", "x" * 64)
    monkeypatch.setenv("MYSQL_USER", "root")
    monkeypatch.setenv("MYSQL_PASSWORD", "anything")
    with pytest.raises(RuntimeError, match="root"):
        create_app(Config())


def test_refuses_placeholder_secret(monkeypatch):
    monkeypatch.setenv("FORGE_X_SECRET_KEY", "replace-with-64-hex-characters")
    monkeypatch.setenv("MYSQL_PASSWORD", "anything")
    monkeypatch.setenv("MYSQL_USER", "forge_x_app")
    problems = validate_config(vars(Config()) | {"TESTING": False})
    assert any("FORGE_X_SECRET_KEY" in p for p in problems)


def test_landing_page_renders(client):
    response = client.get("/")
    assert response.status_code == 200
    page = response.get_data(as_text=True)
    assert "FORGE-X" in page
    assert "Maintain Integrity." in page


def test_security_headers_present(client):
    headers = client.get("/").headers
    assert "script-src 'self'" in headers["Content-Security-Policy"]
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"
    assert headers["Cache-Control"] == "no-store"


def test_404_html_page(client):
    response = client.get("/no-such-page")
    assert response.status_code == 404
    assert "Page not found" in response.get_data(as_text=True)


def test_404_json_for_api_clients(client):
    response = client.get("/no-such-page", headers={"Accept": "application/json"})
    assert response.status_code == 404
    assert response.get_json()["status"] == 404


def test_500_page_hides_internal_details():
    app = create_app(TestingConfig())
    app.config["PROPAGATE_EXCEPTIONS"] = False

    @app.get("/boom")
    def boom():
        raise ZeroDivisionError("secret internal detail")

    response = app.test_client().get("/boom")
    body = response.get_data(as_text=True)
    assert response.status_code == 500
    assert "Something went wrong" in body
    assert "Incident reference" in body
    assert "ZeroDivisionError" not in body and "secret internal detail" not in body


def test_healthz_reports_unavailable_database():
    app = create_app(TestingConfig())
    app.config["MYSQL_PORT"] = 1          # nothing listens here
    app.config["MYSQL_CONNECT_TIMEOUT"] = 2
    response = app.test_client().get("/healthz")
    assert response.status_code == 503
    assert response.get_json() == {"status": "degraded", "database": "unavailable"}


def test_navigation_hides_routes_that_do_not_exist_yet(app):
    with app.test_request_context("/"):
        g.user = {"full_name": "Ananya Mehta", "roles": ["Administrator"]}
        endpoints = [i["endpoint"] for s in build_navigation() for i in s["items"]]
        assert all(e in app.view_functions for e in endpoints)


def test_app_shell_renders_for_a_signed_in_user(app):
    with app.test_request_context("/"):
        g.user = {"full_name": "Ananya Mehta", "roles": ["Administrator"]}
        html = render_template_string(
            "{% extends 'layouts/app.html' %}{% block content %}<p>shell ok</p>{% endblock %}"
        )
    assert "shell ok" in html
    assert "Ananya Mehta" in html and ">AM<" in html
    assert 'id="fxSidebar"' in html


def test_badge_tones_and_initials():
    assert tone("Verified") == "b-green"
    assert tone("Failed") == "b-red"
    assert tone("Unknown value") == "b-slate"
    assert initials("Priya Nair") == "PN"
    assert initials("") == "?"


def test_pagination_maths():
    page = Page(items=[], page=2, per_page=20, total=67)
    assert (page.pages, page.offset, page.first_item, page.last_item) == (4, 20, 21, 40)
    assert page.has_prev and page.has_next
    assert Page([], 7, 10, 200).window() == [1, None, 5, 6, 7, 8, 9, None, 20]
    assert parse_page("abc") == 1 and parse_page("-3") == 1 and parse_page("4") == 4
