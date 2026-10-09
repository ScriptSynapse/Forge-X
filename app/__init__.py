"""FORGE-X application factory.

`create_app()` builds and configures a Flask app. Using a factory (instead
of a global `app = Flask(...)`) lets tests create isolated apps with
different settings, and keeps setup in one readable place.
"""
import os
import logging

from dotenv import load_dotenv
from flask import Flask, request
from flask_wtf.csrf import CSRFProtect

from . import db
from .config import Config, validate_config

csrf = CSRFProtect()

# Content Security Policy: scripts only from our own server (no inline
# scripts, no CDNs). Inline style attributes are allowed because Bootstrap
# components set some at runtime.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "script-src 'self'; "
    "style-src 'self'; "                     # no inline styles anywhere (Phase 2.0-1; a test enforces it)
    "img-src 'self' data:; "
    "font-src 'self'; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'"
)


def create_app(config=None):
    load_dotenv()  # reads .env from the project folder into environment variables

    app = Flask(__name__)
    app.config.from_object(config if config is not None else Config())

    problems = validate_config(app.config)
    if problems:
        raise RuntimeError("FORGE-X cannot start:\n  - " + "\n  - ".join(problems))

    _configure_logging(app)

    if app.config.get("TRUST_CLOUDFLARE"):
        from .proxy import trust_cloudflare
        trust_cloudflare(app)

    if not app.config.get("EVIDENCE_STORAGE_DIR"):
        # Default: the Flask instance folder, which is never served to browsers.
        app.config["EVIDENCE_STORAGE_DIR"] = os.path.join(app.instance_path, "evidence_store")

    csrf.init_app(app)
    db.init_app(app)

    from .errors import register_error_handlers
    from .ui import register_template_helpers
    from .cli import register_cli

    register_template_helpers(app)
    register_error_handlers(app)
    register_cli(app)
    _register_security_headers(app)
    _register_blueprints(app)

    return app


def _register_blueprints(app):
    # Each later phase adds its blueprint here (auth, dashboard, cases, ...).
    from .analytics.routes import bp as analytics_bp
    from .audit_logs.routes import bp as audit_bp
    from .auth.routes import bp as auth_bp
    from .cases.routes import bp as cases_bp
    from .custody.routes import bp as custody_bp
    from .dashboard.routes import bp as dashboard_bp
    from .evidence.routes import bp as evidence_bp
    from .examinations.routes import bp as examinations_bp
    from .integrity.routes import bp as integrity_bp
    from .locations.routes import bp as locations_bp
    from .public.routes import bp as public_bp
    from .reports.routes import bp as reports_bp
    from .search.routes import bp as search_bp
    from .system.routes import bp as system_bp
    from .users.routes import bp as users_bp

    app.register_blueprint(public_bp)
    app.register_blueprint(system_bp)
    app.register_blueprint(auth_bp)     # Phase 6
    app.register_blueprint(users_bp)    # Phase 6
    app.register_blueprint(dashboard_bp)  # Phase 7
    app.register_blueprint(cases_bp)      # Phase 8
    app.register_blueprint(evidence_bp)   # Phase 9
    app.register_blueprint(locations_bp)  # Phase 9
    app.register_blueprint(integrity_bp)  # Phase 10
    app.register_blueprint(custody_bp)    # Phase 10
    app.register_blueprint(examinations_bp)  # Phase 11
    app.register_blueprint(reports_bp)       # Phase 11
    app.register_blueprint(audit_bp)         # Phase 12
    app.register_blueprint(search_bp)        # Phase 13
    app.register_blueprint(analytics_bp)     # Phase 13
    from .yara import bp as yara_bp
    app.register_blueprint(yara_bp)          # FORGE-X 2.0 Phase 7
    from .graph import bp as graph_bp
    app.register_blueprint(graph_bp)         # FORGE-X 2.0 Phase 8
    from .api import bp as api_bp, web_bp as api_web_bp
    app.register_blueprint(api_bp)           # FORGE-X 2.0 Phase 10: /api/v1 (read-only)
    app.register_blueprint(api_web_bp)       # API tokens and developer docs pages


def _register_security_headers(app):
    @app.after_request
    def set_security_headers(response):
        response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if response.mimetype in ("text/html", "application/json"):
            # Pages and chart data can contain case details: never keep them in
            # browser or shared caches (the Back button after logout shows nothing).
            response.headers.setdefault("Cache-Control", "no-store")
        # A hosted FORGE-X (Cloudflare Tunnel) must not appear in search engines.
        response.headers.setdefault("X-Robots-Tag", "noindex, nofollow")
        if request.is_secure:
            # Over HTTPS, tell browsers to use HTTPS only for the next 180 days.
            # (Never sent over plain http, so local development is unaffected.)
            response.headers.setdefault("Strict-Transport-Security", "max-age=15552000")
        return response


def _configure_logging(app):
    if not app.debug and not app.testing:
        from flask.logging import default_handler
        app.logger.removeHandler(default_handler)   # avoid printing each line twice
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s"))
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)
