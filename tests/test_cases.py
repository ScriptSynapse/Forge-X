"""Phase 8: case-management rules that don't need MySQL."""
from werkzeug.datastructures import MultiDict

from app.access import Scope, can_create_case, can_manage_case
from app.cases.services import CaseFilters, like_pattern

ADMIN = {"user_id": 1, "roles": ["Administrator"]}
LEAD = {"user_id": 2, "roles": ["Investigator"]}
OTHER = {"user_id": 3, "roles": ["Investigator"]}
AUDITOR = {"user_id": 6, "roles": ["Read-Only Auditor"]}
CUSTODIAN = {"user_id": 4, "roles": ["Evidence Custodian"]}
OPEN_CASE = {"status": "In Progress", "lead_user_id": 2}
CLOSED_CASE = {"status": "Closed", "lead_user_id": 2}


def test_case_pages_require_login(client):
    for path in ("/cases", "/cases/new", "/cases/FX-2026-0022", "/cases/FX-2026-0022/edit", "/cases/FX-2026-0022/close"):
        response = client.get(path)
        assert response.status_code == 302 and "/login" in response.headers["Location"], path


def test_who_can_manage_a_case():
    assert can_manage_case(ADMIN, OPEN_CASE)
    assert can_manage_case(LEAD, OPEN_CASE)
    assert not can_manage_case(OTHER, OPEN_CASE)          # assigned but not lead
    assert not can_manage_case(AUDITOR, OPEN_CASE)
    assert not can_manage_case(ADMIN, CLOSED_CASE)        # closed cases are read-only for everyone


def test_who_can_create_cases():
    assert can_create_case(ADMIN) and can_create_case(LEAD)
    assert not can_create_case(AUDITOR) and not can_create_case(CUSTODIAN)


def test_visibility_scope():
    assert Scope(ADMIN).lab_wide and Scope(AUDITOR).lab_wide and Scope(CUSTODIAN).lab_wide
    assert not Scope(LEAD).lab_wide and Scope(LEAD).params == (2,)


def test_filters_ignore_unknown_values():
    f = CaseFilters.from_args(MultiDict({"status": "Deleted", "priority": "Urgent", "type": "1;DROP", "sort": "evil", "q": "  ransom  "}))
    assert (f.status, f.priority, f.case_type_id, f.sort, f.q) == ("", "", None, "newest", "ransom")
    good = CaseFilters.from_args(MultiDict({"status": "Open", "priority": "High", "type": "4", "sort": "priority"}))
    assert (good.status, good.priority, good.case_type_id, good.sort) == ("Open", "High", 4, "priority")
    assert good.as_args() == {"status": "Open", "priority": "High", "type": 4, "sort": "priority"}


def test_like_wildcards_are_escaped():
    assert like_pattern("50%_off!") == "%50!%!_off!!%"
