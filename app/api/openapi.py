"""OpenAPI 3.0 document, generated from the routes actually registered (FORGE-X 2.0 Phase 10).

Paths come from the Flask URL map of the `api` blueprint; each operation's
description comes from the registry the route was declared with. A route
without a registry entry, or an entry without a route, raises, so the
document can't describe endpoints that don't exist.
"""
import re

from flask import current_app

from . import routes

ERROR = {"type": "object", "properties": {"status": {"type": "integer"}, "error": {"type": "string"},
                                          "message": {"type": "string"}}}
SCHEMAS = {
    "Case": routes.CASE_DETAIL, "Evidence": routes.EVIDENCE_DETAIL, "Custody": routes.CUSTODY_EVENT,
    "Examination": routes.EXAM_DETAIL, "Report": routes.REPORT_DETAIL, "Indicator": routes.INDICATOR,
    "Me": ("username", "full_name", "scope", "authenticated_by"),
}


def _path(rule):
    """Flask rule -> OpenAPI path, relative to the server URL (/api/v1)."""
    if rule.startswith(routes.bp.url_prefix):
        rule = rule[len(routes.bp.url_prefix):]
    return re.sub(r"<(?:[a-z]+:)?([a-z_]+)>", r"{\1}", rule)


def build():
    registered = {}
    for rule in current_app.url_map.iter_rules():
        if rule.endpoint.startswith("api.") and rule.endpoint != "api.openapi":
            registered[rule.endpoint.split(".", 1)[1]] = rule.rule
    missing = set(registered) - set(routes.SPEC)
    phantom = set(routes.SPEC) - set(registered)
    if missing or phantom:
        raise RuntimeError(f"API registry out of step: undocumented {sorted(missing)}, nonexistent {sorted(phantom)}")
    paths = {}
    for name, info in sorted(routes.SPEC.items(), key=lambda kv: registered[kv[0]]):
        item_ref = {"$ref": f"#/components/schemas/{info['schema']}"}
        if info["paged"]:
            body = {"type": "object", "properties": {"data": {"type": "array", "items": item_ref},
                                                     "page": {"type": "integer"}, "per_page": {"type": "integer"},
                                                     "total": {"type": "integer"}, "pages": {"type": "integer"}}}
        else:
            body = {"type": "object", "properties": {"data": item_ref}}
        responses = {"200": {"description": "OK", "content": {"application/json": {"schema": body}}},
                     "401": {"$ref": "#/components/responses/Unauthorized"},
                     "429": {"$ref": "#/components/responses/TooMany"}}
        if "{" in _path(registered[name]):
            responses["404"] = {"$ref": "#/components/responses/NotFound"}
        paths[_path(registered[name])] = {"get": {
            "operationId": name, "summary": info["summary"], "description": info["doc"], "tags": [info["schema"]],
            "parameters": info["params"] + (routes.PAGE_PARAMS if info["paged"] else []),
            "responses": responses}}
    paths["/openapi.json"] = {"get": {"operationId": "openapi", "summary": "This document", "tags": ["Meta"],
                                      "responses": {"200": {"description": "OpenAPI 3.0 document"}}}}
    return {
        "openapi": "3.0.3",
        "info": {"title": "FORGE-X API", "version": "1.0.0",
                 "description": "Read-only API of the FORGE-X Digital Forensics Evidence Management System. "
                                "Results are limited to the cases the caller can see on the website. Times are "
                                f"ISO 8601 with the lab offset ({current_app.config.get('DB_TIME_ZONE', '+05:30')})."},
        "servers": [{"url": "/api/v1"}],
        "security": [{"bearerToken": []}, {"session": []}],
        "paths": paths,
        "components": {
            "securitySchemes": {
                "bearerToken": {"type": "http", "scheme": "bearer", "description": "Personal token: Account → API tokens"},
                "session": {"type": "apiKey", "in": "cookie", "name": "session", "description": "Website login"}},
            "schemas": dict({k: routes._schema(v) for k, v in SCHEMAS.items()}, Error=ERROR),
            "responses": {
                "Unauthorized": {"description": "Not signed in, or the token is invalid",
                                 "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                "NotFound": {"description": "Doesn't exist, or not visible to you",
                             "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}},
                "TooMany": {"description": "Rate limit reached (see Retry-After)",
                            "content": {"application/json": {"schema": {"$ref": "#/components/schemas/Error"}}}}}},
    }
