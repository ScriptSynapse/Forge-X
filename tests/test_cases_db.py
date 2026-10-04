"""Phase 8: case queries against MySQL. Read-only (SELECT only)."""
import pytest

from app.access import Scope
from app.cases import services
from app.db import query_value

pytestmark = pytest.mark.db

ADMIN = {"user_id": 1, "roles": ["Administrator"]}
ROHAN = {"user_id": 2, "roles": ["Investigator"]}      # seed: assigned to 8 cases


def test_admin_list_matches_sql(app, db_available):
    with app.app_context():
        page = services.list_cases(Scope(ADMIN), services.CaseFilters(), 1, 20)
        assert page.total == query_value("SELECT COUNT(*) FROM cases")
        assert len(page.items) == min(20, page.total)


def test_investigator_sees_only_assigned_cases(app, db_available):
    with app.app_context():
        page = services.list_cases(Scope(ROHAN), services.CaseFilters(), 1, 100)
        assigned = query_value("SELECT COUNT(*) FROM case_investigators WHERE user_id = 2")
        unassigned_ref = query_value(
            "SELECT case_reference FROM cases WHERE case_id NOT IN "
            "(SELECT case_id FROM case_investigators WHERE user_id = 2) LIMIT 1")
        assert page.total == assigned
        if unassigned_ref:
            assert services.get_case(Scope(ROHAN), unassigned_ref) is None      # -> 404 for him
            assert services.get_case(Scope(ADMIN), unassigned_ref) is not None


def test_search_and_filters(app, demo_data):
    with app.app_context():
        found = services.list_cases(Scope(ADMIN), services.CaseFilters(q="ransomware"), 1, 20)
        assert any(c["case_reference"] == "FX-2026-0022" for c in found.items)
        # A literal "%" search must not match everything (wildcards are escaped).
        pattern = services.like_pattern("%")
        assert services.list_cases(Scope(ADMIN), services.CaseFilters(q="%"), 1, 20).total == query_value(
            "SELECT COUNT(*) FROM cases WHERE title LIKE %s ESCAPE '!' OR case_reference LIKE %s ESCAPE '!'",
            (pattern, pattern))
        closed = services.list_cases(Scope(ADMIN), services.CaseFilters(status="Closed"), 1, 50)
        assert all(c["status"] == "Closed" for c in closed.items)
        assert closed.total == query_value("SELECT COUNT(*) FROM cases WHERE status = 'Closed'")


def test_case_detail_data(app, demo_data):
    with app.app_context():
        case = services.get_case(Scope(ADMIN), "FX-2026-0022")
        assert case and case["lead_user_id"] is not None
        counts = services.tab_counts(case["case_id"])
        assert counts["evidence"] == len(services.case_evidence(case["case_id"]))
        assert counts["investigators"] == len(services.case_investigators(case["case_id"]))
        blockers = services.closure_blockers(case["case_id"])
        open_exams = query_value("SELECT COUNT(*) FROM examinations WHERE case_id = %s "
                                 "AND status IN ('Pending', 'In Progress')", (case["case_id"],))
        assert len(blockers["examinations"]) == open_exams


def test_case_list_page_renders(app, client, admin_id):
    from tests.conftest import sign_in_as
    sign_in_as(app, client, admin_id)
    page = client.get("/cases").get_data(as_text=True)
    assert "All cases in the lab" in page
    with app.app_context():
        ref = query_value("SELECT case_reference FROM cases ORDER BY case_id DESC LIMIT 1")
    if ref:
        assert ref in page
        assert client.get(f"/cases/{ref}?tab=investigators").status_code == 200
