"""FORGE-X 2.0 Phase 1: group filters and every sortable column run correctly on MySQL. Read-only."""
import pytest

from app.access import Scope
from app.cases import services as cases
from app.db import query_value
from app.evidence import services as evidence

pytestmark = pytest.mark.db

ADMIN = Scope({"user_id": 1, "roles": ["Administrator"]})


def test_case_group_filters_match_sql(app, db_available):
    with app.app_context():
        active = cases.list_cases(ADMIN, cases.CaseFilters(status="active"), 1, 20)
        assert active.total == query_value("SELECT COUNT(*) FROM cases WHERE status <> 'Closed'")
        urgent = cases.list_cases(ADMIN, cases.CaseFilters(status="active", priority="urgent"), 1, 20)
        assert urgent.total == query_value(
            "SELECT COUNT(*) FROM cases WHERE status <> 'Closed' AND priority IN ('Critical', 'High')")


@pytest.mark.parametrize("sort", sorted(cases.SORTS))
def test_every_case_sort_runs(app, db_available, sort):
    with app.app_context():
        page = cases.list_cases(ADMIN, cases.CaseFilters(sort=sort), 1, 5)
        assert page.total == query_value("SELECT COUNT(*) FROM cases")


def test_evidence_awaiting_filter_matches_sql(app, db_available):
    with app.app_context():
        page = evidence.list_evidence(ADMIN, evidence.EvidenceFilters(awaiting=True), 1, 20)
        assert page.total == query_value(
            "SELECT COUNT(DISTINCT ee.evidence_id) FROM examination_evidence ee "
            "JOIN examinations x ON x.examination_id = ee.examination_id WHERE x.status = 'Pending'")


@pytest.mark.parametrize("sort", sorted(evidence.SORTS))
def test_every_evidence_sort_runs(app, db_available, sort):
    with app.app_context():
        page = evidence.list_evidence(ADMIN, evidence.EvidenceFilters(sort=sort), 1, 5)
        assert page.total == query_value("SELECT COUNT(*) FROM evidence")
