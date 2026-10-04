"""Phase 7: landing page and dashboard checks that do not need MySQL."""
from datetime import date

from app.dashboard.services import CASE_STATUSES, Scope, fill, month_label


def test_landing_has_all_sections_and_actions(client):
    page = client.get("/").get_data(as_text=True)
    for anchor in ('id="top"', 'id="features"', 'id="workflow"', 'id="about"', 'id="contact"'):
        assert anchor in page
    for step in ("Case registration", "Evidence collection", "Hash verification",
                 "Chain of custody", "Examination", "Report generation"):
        assert step in page
    assert 'href="/login"' in page            # Get started / Log in
    assert 'href="#features"' in page         # Learn more
    assert "(example)" in page                # the hero panel is labelled as an illustration


def test_dashboard_requires_login(client):
    response = client.get("/dashboard")
    assert response.status_code == 302 and "/login?next=" in response.headers["Location"]


def test_chart_api_answers_401_json_when_signed_out(client):
    response = client.get("/api/dashboard/cases-by-status")
    assert response.status_code == 401
    assert response.get_json()["status"] == 401


def test_fill_zero_fills_missing_categories():
    rows = [{"label": "Closed", "n": 5}, {"label": "Open", "n": 2}]
    assert fill(rows, CASE_STATUSES) == [2, 0, 0, 5]


def test_month_label():
    assert month_label(date(2026, 9, 1)) == "Sep 2026"
    assert month_label("2026-10-01") == "Oct 2026"


def test_scope_by_role():
    admin = Scope({"user_id": 1, "roles": ["Administrator"]})
    assert admin.lab_wide and admin.sees_all_activity and admin.params == ()
    custodian = Scope({"user_id": 4, "roles": ["Evidence Custodian"]})
    assert custodian.lab_wide and not custodian.sees_all_activity
    investigator = Scope({"user_id": 2, "roles": ["Investigator"]})
    assert not investigator.lab_wide and investigator.params == (2,)
    assert "%s" in investigator.case_filter and "2" not in investigator.case_filter   # value is a parameter
