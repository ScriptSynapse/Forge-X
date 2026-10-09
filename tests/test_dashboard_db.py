"""Phase 7: dashboard figures against MySQL. Read-only: these tests only
SELECT. Each figure is compared with an independent SQL query, so they
pass whatever data you have (seed data or your own changes)."""
import pytest

from app.dashboard import services
from app.db import query_value
from tests.conftest import sign_in_as

pytestmark = pytest.mark.db


def test_dashboard_renders_for_administrator(app, client, admin_id):
    sign_in_as(app, client, admin_id)
    response = client.get("/dashboard")
    page = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "Total cases" in page and "Integrity verification" in page
    with app.app_context():
        total = query_value("SELECT COUNT(*) FROM cases")
    assert f'<span class="fx-stat-value ">{total}</span>' in page


def test_status_chart_matches_sql_for_administrator(app, client, admin_id):
    sign_in_as(app, client, admin_id)
    data = client.get("/api/dashboard/cases-by-status").get_json()
    with app.app_context():
        expected = [query_value("SELECT COUNT(*) FROM cases WHERE status = %s", (s,)) for s in data["labels"]]
    assert data["values"] == expected
    assert data["labels"] == ["Open", "In Progress", "On Hold", "Closed"]


def test_investigator_sees_only_assigned_cases(app, db_available):
    """Scoping is tested on the query functions directly, so the result does not
    depend on whether the seed investigator still has a temporary password."""
    investigator = services.Scope({"user_id": 2, "roles": ["Investigator"]})      # Rohan Iyer
    with app.app_context():
        data = services.chart_cases_by_priority(investigator)
        summary = services.summary(investigator)
        assigned = query_value("SELECT COUNT(*) FROM case_investigators WHERE user_id = 2")
        everything = query_value("SELECT COUNT(*) FROM cases")
    assert data["total"] == assigned == summary["cases"]["total"]
    assert data["total"] <= everything


def test_api_tells_users_to_change_temporary_password(app, client, db_available):
    with app.app_context():
        user_id = query_value("SELECT user_id FROM users WHERE must_change_password = TRUE "
                              "AND account_status = 'Active' ORDER BY user_id LIMIT 1")
    if user_id is None:
        pytest.skip("every active user has already chosen a password")
    sign_in_as(app, client, user_id)
    response = client.get("/api/dashboard/cases-by-status")
    assert response.status_code == 403
    assert response.get_json()["error"] == "Password change required"


def test_evidence_and_trend_charts(app, client, admin_id):
    sign_in_as(app, client, admin_id)
    by_type = client.get("/api/dashboard/evidence-by-type").get_json()
    trend = client.get("/api/dashboard/case-trend").get_json()
    with app.app_context():
        assert by_type["total"] == query_value("SELECT COUNT(*) FROM evidence")
    assert len(trend["labels"]) == 12 and len(trend["values"]) == 12


def test_unknown_chart_is_404(app, client, admin_id):
    sign_in_as(app, client, admin_id)
    assert client.get("/api/dashboard/no-such-chart").status_code == 404


# ---------------------------------------------------------------------------
# FORGE-X 2.0 Phase 1: every new figure equals an independent SQL query
# ---------------------------------------------------------------------------
def test_new_summary_figures_match_sql(app, db_available):
    with app.app_context():
        stats = services.summary(services.Scope({"user_id": 1, "roles": ["Administrator"]}))
        assert stats["cases"]["high_priority_open"] == query_value(
            "SELECT COUNT(*) FROM cases WHERE status <> 'Closed' AND priority IN ('Critical', 'High')")
        assert stats["evidence"]["awaiting_exam"] == query_value(
            "SELECT COUNT(DISTINCT ee.evidence_id) FROM examination_evidence ee "
            "JOIN examinations x ON x.examination_id = ee.examination_id WHERE x.status = 'Pending'")


def test_work_in_progress_matches_sql(app, db_available):
    with app.app_context():
        work = services.work_in_progress(services.Scope({"user_id": 1, "roles": ["Administrator"]}))
        for status, key in (("Pending", "exams_pending"), ("In Progress", "exams_in_progress"),
                            ("Completed", "exams_completed"), ("Cancelled", "exams_cancelled")):
            assert work[key] == query_value("SELECT COUNT(*) FROM examinations WHERE status = %s", (status,))
        assert work["reports_under_review"] == query_value("SELECT COUNT(*) FROM forensic_reports WHERE status = 'Under Review'")
        assert work["reports_draft"] == query_value("SELECT COUNT(*) FROM forensic_reports WHERE status = 'Draft'")


def test_all_time_activity_equals_table_totals(app, db_available):
    with app.app_context():
        scope = services.Scope({"user_id": 1, "roles": ["Administrator"]})
        everything = services.activity_in_period(scope, None)
        assert everything["cases_opened"] == query_value("SELECT COUNT(*) FROM cases")
        assert everything["evidence_registered"] == query_value("SELECT COUNT(*) FROM evidence")
        assert everything["custody_entries"] == query_value("SELECT COUNT(*) FROM chain_of_custody")
        assert everything["checks_verified"] + everything["checks_failed"] == query_value("SELECT COUNT(*) FROM hash_verifications")
        assert everything["exams_completed"] == query_value("SELECT COUNT(*) FROM examinations WHERE status = 'Completed'")
        week = services.activity_in_period(scope, 7)
        assert all(week[k] <= everything[k] for k in week)
        services.recent_custody(scope, 7)
        services.integrity_alerts(scope)


def test_dashboard_page_with_each_period(app, client, admin_id):
    sign_in_as(app, client, admin_id)
    for period in ("7", "30", "90", "all"):
        assert client.get(f"/dashboard?period={period}").status_code == 200
