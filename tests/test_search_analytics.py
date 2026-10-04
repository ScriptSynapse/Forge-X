"""Phase 13: search classification and analytics plumbing (no MySQL needed)."""
import re

from app.access import Scope
from app.analytics import services as analytics
from app.search import services as search


def test_exact_ids_are_recognised():
    assert search.exact_target("fx-2026-0001") == ("cases.detail", "reference", "FX-2026-0001")
    assert search.exact_target("FX-EV-2026-00001") == ("evidence.detail", "code", "FX-EV-2026-00001")
    assert search.exact_target("ex-2026-0003")[0] == "examinations.detail"
    assert search.exact_target("RP-2026-0002")[0] == "reports.detail"
    assert search.exact_target("FX-2026-1") is None and search.exact_target("phishing") is None


def test_hash_prefixes_and_normalising():
    assert search.looks_like_hash("ABCDEF12") and search.looks_like_hash("a" * 64)
    assert not search.looks_like_hash("abcdef1") and not search.looks_like_hash("g" * 10)
    assert search.normalise("  phish   mail ") == "phish mail" and len(search.normalise("x" * 500)) == 100


def test_every_chart_has_matching_placeholders_for_every_scope():
    for user in ({"user_id": 1, "roles": ["Administrator"]}, {"user_id": 7, "roles": ["Investigator"]}):
        for chart_id in analytics.CHARTS:
            sql, params = analytics.sql_for(chart_id, Scope(user), 24)
            assert sql.count("%s") == len(params), chart_id
            assert not re.search(r"%(?!s)", sql) and "{" not in sql, chart_id


def test_period_is_validated():
    assert analytics.parse_period("6") == 6 and analytics.parse_period("999") == 12 and analytics.parse_period("x") == 12


def test_pages_require_login(client):
    for path in ("/search?q=test", "/analytics"):
        response = client.get(path)
        assert response.status_code == 302 and "/login" in response.headers["Location"], path
    assert client.get("/api/analytics/custody-actions").status_code == 401
