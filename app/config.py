"""Centralized configuration.

Every value comes from environment variables (loaded from .env by
python-dotenv). The .env file holds configuration and secrets only,
never application records: those live in MySQL.
"""
import os
from datetime import timedelta

PLACEHOLDER_SECRETS = {"", "replace-with-64-hex-characters", "change-me", "dev"}


def _bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name, default):
    value = os.getenv(name)
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        raise RuntimeError(f"{name} must be a whole number, got {value!r}") from None


class Config:
    """Production-safe defaults. Values are read when the object is created,
    so they always reflect the .env file loaded by create_app()."""

    TESTING = False

    def __init__(self):
        # Flask
        self.SECRET_KEY = os.getenv("FORGE_X_SECRET_KEY", "")

        # MySQL connection
        self.MYSQL_HOST = os.getenv("MYSQL_HOST", "127.0.0.1")
        self.MYSQL_PORT = _int("MYSQL_PORT", 3306)
        self.MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "forge_x_db")
        self.MYSQL_USER = os.getenv("MYSQL_USER", "forge_x_app")
        self.MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "")
        self.MYSQL_POOL_SIZE = _int("MYSQL_POOL_SIZE", 5)
        self.MYSQL_CONNECT_TIMEOUT = _int("MYSQL_CONNECT_TIMEOUT", 5)
        self.DB_TIME_ZONE = os.getenv("DB_TIME_ZONE", "+05:30")

        # Session cookie protection
        self.SESSION_COOKIE_NAME = "forge_x_session"
        self.SESSION_COOKIE_HTTPONLY = True          # JavaScript cannot read the cookie
        self.SESSION_COOKIE_SAMESITE = "Lax"         # not sent on cross-site POSTs
        self.SESSION_COOKIE_SECURE = _bool("SESSION_COOKIE_SECURE", False)  # HTTPS only when enabled
        self.PERMANENT_SESSION_LIFETIME = timedelta(days=7)  # "Keep me logged in" (assumption A4)

        # CSRF (Flask-WTF)
        self.WTF_CSRF_ENABLED = True
        self.WTF_CSRF_TIME_LIMIT = 8 * 3600

        # Uploads: verification sample files are hashed and discarded (assumption A6)
        self.SAMPLE_FILE_MAX_BYTES = 25 * 1024 * 1024
        self.MAX_CONTENT_LENGTH = self.SAMPLE_FILE_MAX_BYTES + 1024 * 1024  # room for form fields

        # Brute-force protection (counted in MySQL, 15-minute window)
        self.LOGIN_MAX_FAILURES_PER_ACCOUNT = 5
        self.LOGIN_MAX_FAILURES_PER_IP = 20
        self.SIGNUP_MAX_PER_IP_PER_HOUR = 5

        # Lists
        self.PAGE_SIZE = 20


class TestingConfig(Config):
    """Used by pytest. Reads the same .env, so database tests run against
    your local MySQL. CSRF is off so tests can post forms directly."""

    TESTING = True

    def __init__(self):
        super().__init__()
        self.WTF_CSRF_ENABLED = False
        # Every test request comes from 127.0.0.1, so per-IP limits would make
        # repeated test runs fail. Per-account limits stay as in production.
        self.LOGIN_MAX_FAILURES_PER_IP = 10_000
        self.SIGNUP_MAX_PER_IP_PER_HOUR = 10_000
        if self.SECRET_KEY in PLACEHOLDER_SECRETS:
            self.SECRET_KEY = "testing-only-secret-key-0123456789abcdef0123456789abcdef"


def validate_config(config):
    """Refuse to start with unsafe or missing settings. Returns a list of problems."""
    problems = []
    secret = config.get("SECRET_KEY") or ""
    if secret in PLACEHOLDER_SECRETS or len(secret) < 32:
        problems.append(
            "FORGE_X_SECRET_KEY is missing or too short. Generate one with: "
            'python -c "import secrets; print(secrets.token_hex(32))"'
        )
    if not config.get("TESTING"):
        if not config.get("MYSQL_PASSWORD"):
            problems.append("MYSQL_PASSWORD is empty. Use the password you set in database/app_user.sql.")
        if (config.get("MYSQL_USER") or "").lower() == "root":
            problems.append("MYSQL_USER is root. FORGE-X must connect with the least-privilege forge_x_app account.")
    return problems
