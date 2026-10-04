"""Error handling: friendly pages for people, JSON for API calls.

No stack traces, SQL text or secrets are ever shown. Unexpected errors get
a short incident reference that also appears in the server log, so the
problem can be found without exposing details.
"""
import secrets

from flask import jsonify, render_template, request
from flask_wtf.csrf import CSRFError
from werkzeug.exceptions import HTTPException

from .db import DatabaseUnavailable

MESSAGES = {
    400: ("Bad request", "The request could not be understood. Check the form and try again."),
    403: ("Access denied", "You don't have permission to view this page."),
    404: ("Page not found", "The page you're looking for doesn't exist or has moved."),
    405: ("Method not allowed", "This page doesn't accept that kind of request."),
    413: ("File too large", "Files must be 25 MB or smaller."),
    429: ("Too many requests", "Too many attempts. Wait a few minutes and try again."),
    500: ("Something went wrong", "An unexpected error occurred and has been logged."),
    503: ("Database unavailable",
          "FORGE-X can't reach its database right now. Check that MySQL is running, then try again."),
}


def _wants_json():
    if request.path.startswith("/api/") or request.path == "/healthz":
        return True
    best = request.accept_mimetypes.best_match(["application/json", "text/html"])
    return best == "application/json" and request.accept_mimetypes[best] > request.accept_mimetypes["text/html"]


def _respond(code, title=None, message=None, incident=None):
    default_title, default_message = MESSAGES.get(code, ("Error", "Something went wrong."))
    title = title or default_title
    message = message or default_message
    if _wants_json():
        body = {"status": code, "error": title, "message": message}
        if incident:
            body["incident"] = incident
        return jsonify(body), code
    return render_template("errors/error.html", code=code, title=title,
                           message=message, incident=incident), code


def register_error_handlers(app):
    @app.errorhandler(CSRFError)
    def csrf_error(err):
        return _respond(400, "Form expired",
                        "This form expired or was already submitted. Reload the page and try again.")

    @app.errorhandler(HTTPException)
    def http_error(err):
        return _respond(err.code or 500)

    @app.errorhandler(DatabaseUnavailable)
    def database_unavailable(err):
        app.logger.error("Database unavailable: %s", err.detail)
        return _respond(503)

    @app.errorhandler(Exception)
    def unexpected_error(err):
        incident = secrets.token_hex(4).upper()
        app.logger.exception("Unhandled error, incident %s", incident)
        return _respond(500, incident=incident)
