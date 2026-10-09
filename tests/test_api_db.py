"""FORGE-X 2.0 Phase 10 against MySQL: every API list matches SQL, and scope holds. Read-only."""
import pytest

from app.db import query_one, query_value
from tests.conftest import sign_in_as

pytestmark = pytest.mark.db


def test_migration_010_is_installed(app, db_available):
    with app.app_context():
        assert query_value("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() "
                           "AND TABLE_NAME = 'api_tokens'") == 1, "run database/migrations/010_api_tokens.sql"


@pytest.mark.parametrize("path,sql", [
    ("/api/v1/cases", "SELECT COUNT(*) FROM cases"),
    ("/api/v1/evidence", "SELECT COUNT(*) FROM evidence"),
    ("/api/v1/examinations", "SELECT COUNT(*) FROM examinations"),
    ("/api/v1/reports", "SELECT COUNT(*) FROM forensic_reports"),
    ("/api/v1/chain-of-custody", "SELECT (SELECT COUNT(*) FROM chain_of_custody) + (SELECT COUNT(*) FROM hash_verifications)"),
])
def test_list_totals_match_sql_for_an_administrator(app, client, admin_id, path, sql):
    sign_in_as(app, client, admin_id)
    body = client.get(path + "?per_page=5").get_json()
    with app.app_context():
        assert body["total"] == query_value(sql)
    assert len(body["data"]) == min(5, body["total"])


def test_details_and_indicators_work_on_real_records(app, client, admin_id):
    sign_in_as(app, client, admin_id)
    with app.app_context():
        case = query_value("SELECT case_reference FROM cases ORDER BY case_id LIMIT 1")
        item = query_value("SELECT evidence_code FROM evidence ORDER BY evidence_id LIMIT 1")
    if case:
        assert client.get(f"/api/v1/cases/{case}").get_json()["data"]["case_reference"] == case
    if item:
        data = client.get(f"/api/v1/evidence/{item}").get_json()["data"]
        assert data["evidence_code"] == item and "object_id" not in str(data)
        assert client.get(f"/api/v1/evidence/{item}/custody").status_code == 200
    assert client.get("/api/v1/indicators").status_code == 200
    assert client.get("/api/v1/openapi.json").get_json()["openapi"] == "3.0.3"


def test_investigators_only_see_their_cases_through_the_api(app, client, db_available):
    with app.app_context():
        pair = query_one("SELECT u.user_id, c.case_reference FROM users u JOIN user_roles ur ON ur.user_id = u.user_id "
                         "JOIN roles r ON r.role_id = ur.role_id CROSS JOIN cases c WHERE r.role_name = 'Investigator' "
                         "AND u.account_status = 'Active' AND NOT EXISTS (SELECT 1 FROM user_roles x JOIN roles y "
                         "ON y.role_id = x.role_id WHERE x.user_id = u.user_id AND y.role_name <> 'Investigator') "
                         "AND NOT EXISTS (SELECT 1 FROM case_investigators ci WHERE ci.case_id = c.case_id "
                         "AND ci.user_id = u.user_id) LIMIT 1")
    if pair is None:
        pytest.skip("no investigator with an unassigned case")
    sign_in_as(app, client, pair["user_id"])
    assert client.get(f"/api/v1/cases/{pair['case_reference']}").status_code == 404
    listed = {c["case_reference"] for c in client.get("/api/v1/cases?per_page=100").get_json()["data"]}
    assert pair["case_reference"] not in listed
    with app.app_context():
        assigned = query_value("SELECT COUNT(*) FROM case_investigators WHERE user_id = %s", (pair["user_id"],))
    assert client.get("/api/v1/cases").get_json()["total"] == assigned
