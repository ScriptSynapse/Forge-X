"""Phase 6: authentication rules that can be checked without MySQL."""
from app import create_app
from app.auth.passwords import hash_password, password_problems, verify_password
from app.auth.services import is_safe_next
from app.config import TestingConfig


def test_password_policy():
    assert password_problems("short1") != []
    assert any("letter and one number" in p for p in password_problems("onlyletterslong"))
    assert any("username" in p for p in password_problems("priya.nair2026x", "priya.nair"))
    assert any("too common" in p for p in password_problems("Password1234"))
    assert password_problems("Correct-Horse-42-Battery") == []


def test_passwords_are_hashed_with_salt():
    first, second = hash_password("Correct-Horse-42"), hash_password("Correct-Horse-42")
    assert first != "Correct-Horse-42" and first != second       # random salt each time
    assert first.startswith(("scrypt:", "pbkdf2:"))
    assert verify_password(first, "Correct-Horse-42")
    assert not verify_password(first, "wrong-password-42")
    # Seed accounts hold a placeholder that can never match any password.
    assert not verify_password("!no-password-set:run-flask-set-password", "anything-at-all-1")


def test_open_redirects_are_refused():
    assert is_safe_next("/admin/users")
    assert is_safe_next("/account?tab=1")
    for bad in ("https://evil.example/", "//evil.example", "/\\evil.example", "javascript:alert(1)", "", None):
        assert not is_safe_next(bad)


def test_login_and_signup_pages_render(client):
    login = client.get("/login")
    assert login.status_code == 200 and "Log in to FORGE-X" in login.get_data(as_text=True)
    signup = client.get("/signup")
    assert signup.status_code == 200 and "Request access" in signup.get_data(as_text=True)


def test_landing_page_now_links_to_login(client):
    assert 'href="/login"' in client.get("/").get_data(as_text=True)


def test_protected_pages_redirect_anonymous_users(client):
    for path in ("/account", "/account/password", "/admin/users", "/admin/users/create"):
        response = client.get(path)
        assert response.status_code == 302, path
        assert "/login?next=" in response.headers["Location"], path


def test_logout_only_accepts_post(client):
    assert client.get("/logout").status_code == 405


def test_csrf_token_required_when_enabled():
    config = TestingConfig()
    config.WTF_CSRF_ENABLED = True
    app = create_app(config)
    response = app.test_client().post("/login", data={"login": "x", "password": "y"})
    assert response.status_code == 400
    assert "Form expired" in response.get_data(as_text=True)
