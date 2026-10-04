"""Phase 13: search and analytics against MySQL. Read-only."""
import pytest

from app.access import Scope
from app.analytics import services as analytics
from app.db import query_one, query_value
from app.search import services as search

pytestmark = pytest.mark.db

ADMIN = Scope({"user_id": 1, "roles": ["Administrator"]})
INVESTIGATOR = Scope({"user_id": 999999, "roles": ["Investigator"]})      # assigned to nothing


@pytest.mark.parametrize("chart_id", list(analytics.CHARTS))
def test_every_chart_query_runs(app, db_available, chart_id):
    with app.app_context():
        for scope in (ADMIN, INVESTIGATOR):
            for months in analytics.PERIODS:
                data = analytics.run(chart_id, scope, months)
                assert all(len(d["values"]) == len(data["labels"]) for d in data["datasets"])
        if chart_id == "monthly-activity":
            assert len(analytics.run(chart_id, ADMIN, 12)["labels"]) == 12       # one row per month, gaps included


def test_investigator_with_no_cases_sees_nothing(app, db_available):
    with app.app_context():
        for chart_id in ("custody-actions", "examinations-by-type", "verification-outcomes"):
            assert analytics.run(chart_id, INVESTIGATOR, 24)["total"] == 0
        results = search.search("FX", INVESTIGATOR)
        assert all(group["total"] == 0 for group in results.values())


def test_search_finds_existing_records(app, db_available):
    with app.app_context():
        case = query_one("SELECT case_reference FROM cases ORDER BY case_id LIMIT 1")
        if case is None:
            pytest.skip("no cases yet")
        results = search.search(case["case_reference"], ADMIN)
        assert case["case_reference"] in [r["case_reference"] for r in results["cases"]["rows"]]
        stored = query_value("SELECT hash_value FROM evidence_hashes LIMIT 1")
        if stored:
            found = search.search(stored[:12], ADMIN)["hashes"]
            assert stored in [r["hash_value"] for r in found["rows"]]


def test_custody_action_totals_match_sql(app, db_available):
    with app.app_context():
        total = analytics.run("custody-actions", ADMIN, 12)["total"]
        assert total == query_value("SELECT COUNT(*) FROM chain_of_custody "
                                    "WHERE occurred_at >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)")
