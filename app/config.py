"""Centralized configuration.

Every value comes from environment variables (loaded from .env by
python-dotenv). The .env file holds configuration and secrets only,
never application records: those live in MySQL.
"""
import os
from datetime import timedelta

PLACEHOLDER_SECRETS = {"", "replace-with-64-hex-characters", "change-me", "dev",
                       "change-me-to-64-random-hex-characters"}       # the .env.docker.example placeholder


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
        # Stored evidence files (FORGE-X 2.0 Phase 3). 100 MB matches Cloudflare's
        # free-plan upload limit; only the evidence upload routes accept this size.
        self.EVIDENCE_FILE_MAX_BYTES = int(os.getenv("EVIDENCE_MAX_MB", "100")) * 1024 * 1024
        # REST API (FORGE-X 2.0 Phase 10): requests per minute per user; failed token attempts per minute per address.
        self.API_RATE_LIMIT_PER_MINUTE = int(os.getenv("API_RATE_LIMIT_PER_MINUTE", "120"))
        self.API_FAILED_AUTH_PER_MINUTE = int(os.getenv("API_FAILED_AUTH_PER_MINUTE", "20"))
        # YARA scanning (FORGE-X 2.0 Phase 7): limits for the isolated worker process.
        self.YARA_TIMEOUT_SECONDS = int(os.getenv("YARA_TIMEOUT_SECONDS", "60"))
        self.YARA_MEMORY_MB = int(os.getenv("YARA_MEMORY_MB", "512"))
        self.YARA_MAX_RULE_KB = int(os.getenv("YARA_MAX_RULE_KB", "256"))
        self.EVIDENCE_STORAGE_DIR = os.getenv("EVIDENCE_STORAGE_DIR", "")      # default set in create_app (instance folder)
        # Object storage (FORGE-X 2.0 Phase 9). "local" (default) or "s3": where NEW files go.
        self.EVIDENCE_STORAGE_BACKEND = os.getenv("EVIDENCE_STORAGE_BACKEND", "local").strip().lower()
        self.S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")            # e.g. http://127.0.0.1:9000 for MinIO
        self.S3_BUCKET = os.getenv("S3_BUCKET", "")
        self.S3_PREFIX = os.getenv("S3_PREFIX", "evidence/")
        self.S3_REGION = os.getenv("S3_REGION", "us-east-1")
        self.S3_ACCESS_KEY_ID = os.getenv("S3_ACCESS_KEY_ID", "")
        self.S3_SECRET_ACCESS_KEY = os.getenv("S3_SECRET_ACCESS_KEY", "")
        self.S3_SSE = os.getenv("S3_SSE", "")                              # e.g. AES256
        self.S3_CONDITIONAL_WRITES = os.getenv("S3_CONDITIONAL_WRITES", "1") == "1"
        self.S3_VERIFY_TLS = os.getenv("S3_VERIFY_TLS", "1") == "1"
        if self.EVIDENCE_STORAGE_BACKEND not in ("local", "s3"):
            raise RuntimeError("EVIDENCE_STORAGE_BACKEND must be local or s3.")
        if self.EVIDENCE_STORAGE_BACKEND == "s3" and not self.S3_BUCKET:
            raise RuntimeError("EVIDENCE_STORAGE_BACKEND=s3 needs S3_BUCKET (and the S3_* settings) in .env.")
        self.MAX_CONTENT_LENGTH = self.SAMPLE_FILE_MAX_BYTES + 1024 * 1024  # room for form fields

        # Brute-force protection (counted in MySQL, 15-minute window)
        self.LOGIN_MAX_FAILURES_PER_ACCOUNT = 5
        self.LOGIN_MAX_FAILURES_PER_IP = 20
        self.SIGNUP_MAX_PER_IP_PER_HOUR = 5

        # Hosting behind Cloudflare Tunnel (see docs/DEPLOY_CLOUDFLARE.md)
        self.TRUST_CLOUDFLARE = _bool("TRUST_CLOUDFLARE", False)

        # Lists
        self.PAGE_SIZE = 20


class TestingConfig(Config):
    """Used by pytest. Reads the same .env, so database tests run against
    your local MySQL. CSRF is off so tests can post forms directly."""
    __test__ = False      # not a pytest test class (silences PytestCollectionWarning)

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
