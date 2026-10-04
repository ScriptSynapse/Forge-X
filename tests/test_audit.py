"""Phase 12: audit-log filters, CSV safety and user filters (no MySQL needed)."""
from datetime import date

from werkzeug.datastructures import MultiDict

from app.audit_logs.services import AuditFilters, _safe_cell
from app.users.services import UserFilters


def test_csv_cells_cannot_become_formulas():
    for dangerous in ("=1+1", "+cmd", "-2+3", "@SUM(A1)", "\t=x", "\r=x"):
        assert _safe_cell(dangerous).startswith("'"), dangerous
    assert _safe_cell("FX-EV-2026-00001") == "FX-EV-2026-00001"
    assert _safe_cell(None) == "" and _safe_cell(42) == "42"


def test_audit_filters_are_parameterised_and_validated():
    f = AuditFilters.from_args(MultiDict({"from": "2026-10-01", "to": "2026-10-04", "user": "7", "action": "hash.verify",
                                          "entity": "Evidence", "outcome": "Failure", "ref": "FX-EV-2026-00001"}))
    sql, params = f.where()
    assert params == (date(2026, 10, 1), date(2026, 10, 4), 7, "hash.verify", "Evidence", "Failure", "FX-EV-2026-00001")
    assert "FX-EV" not in sql and "hash.verify" not in sql            # values never appear in the SQL text
    bad = AuditFilters.from_args(MultiDict({"from": "yesterday", "user": "1 OR 1=1", "entity": "Nope", "outcome": "Maybe"}))
    assert (bad.date_from, bad.user_id, bad.entity_type, bad.outcome) == (None, None, "", "")
    assert bad.where() == ("1 = 1", ())


def test_user_filters():
    f = UserFilters.from_args(MultiDict({"q": " paul ", "role": "1", "status": "Active", "inactive": "1"}))
    assert (f.q, f.role_id, f.status, f.inactive) == ("paul", 1, "Active", True)
    assert UserFilters.from_args(MultiDict({"status": "Deleted", "role": "x"})).as_args() == {}


def test_audit_pages_require_login(client):
    for path in ("/audit-logs", "/audit-logs/export.csv", "/audit-logs/security"):
        response = client.get(path)
        assert response.status_code == 302 and "/login" in response.headers["Location"], path
