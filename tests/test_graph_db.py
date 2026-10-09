"""FORGE-X 2.0 Phase 8 against MySQL: graphs of real cases are consistent and scoped. Read-only."""
import pytest

from app.access import Scope
from app.db import query_one, query_value
from app.graph import services as gs

pytestmark = pytest.mark.db


def test_real_case_graph_is_consistent(app, db_available):
    with app.test_request_context():
        reference = query_value("SELECT case_reference FROM cases ORDER BY case_id LIMIT 1")
        if reference is None:
            pytest.skip("no cases yet")
        data = gs.case_graph(Scope({"user_id": 1, "roles": ["Administrator"]}), reference, "all").as_dict()
        ids = {n["id"] for n in data["nodes"]}
        assert all(e["source"] in ids and e["target"] in ids for e in data["edges"])
        assert {e["kind"] for e in data["edges"]} <= {"recorded", "result", "identity"}
        case_id = query_value("SELECT case_id FROM cases WHERE case_reference = %s", (reference,))
        evidence = query_value("SELECT COUNT(*) FROM evidence WHERE case_id = %s", (case_id,))
        contains = sum(1 for e in data["edges"] if e["source"] == f"case:{case_id}" and e["label"] == "contains")
        assert contains == min(evidence, gs.MAX_NODES)


def test_investigators_cannot_graph_cases_outside_their_assignments(app, db_available):
    with app.test_request_context():
        pair = query_one("SELECT u.user_id, c.case_reference FROM users u JOIN user_roles ur ON ur.user_id = u.user_id "
                         "JOIN roles r ON r.role_id = ur.role_id CROSS JOIN cases c WHERE r.role_name = 'Investigator' "
                         "AND NOT EXISTS (SELECT 1 FROM case_investigators ci WHERE ci.case_id = c.case_id "
                         "AND ci.user_id = u.user_id) LIMIT 1")
        if pair is None:
            pytest.skip("no investigator with an unassigned case")
        scope = Scope({"user_id": pair["user_id"], "roles": ["Investigator"]})
        assert gs.case_graph(scope, pair["case_reference"]) is None
