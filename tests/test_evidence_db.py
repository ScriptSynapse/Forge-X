"""Phase 9: evidence queries against MySQL. Read-only (SELECT only)."""
import pytest

from app.access import Scope
from app.db import query_value
from app.evidence import services
from app.locations import services as locations

pytestmark = pytest.mark.db

ADMIN = {"user_id": 1, "roles": ["Administrator"]}
ROHAN = {"user_id": 2, "roles": ["Investigator"]}


def test_admin_list_matches_sql(app, db_available):
    with app.app_context():
        page = services.list_evidence(Scope(ADMIN), services.EvidenceFilters(), 1, 20)
        assert page.total == query_value("SELECT COUNT(*) FROM evidence")


def test_investigator_sees_only_evidence_of_assigned_cases(app, db_available):
    with app.app_context():
        page = services.list_evidence(Scope(ROHAN), services.EvidenceFilters(), 1, 200)
        expected = query_value("SELECT COUNT(*) FROM evidence WHERE case_id IN "
                               "(SELECT case_id FROM case_investigators WHERE user_id = 2)")
        assert page.total == expected
        hidden = query_value("SELECT evidence_code FROM evidence WHERE case_id NOT IN "
                             "(SELECT case_id FROM case_investigators WHERE user_id = 2) LIMIT 1")
        if hidden:
            assert services.get_evidence(Scope(ROHAN), hidden) is None


def test_filters_match_sql(app, db_available):
    with app.app_context():
        failed = services.list_evidence(Scope(ADMIN), services.EvidenceFilters(integrity="Failed"), 1, 50)
        assert failed.total == query_value("SELECT COUNT(*) FROM v_evidence_integrity WHERE integrity_status = 'Failed'")
        stored = services.list_evidence(Scope(ADMIN), services.EvidenceFilters(status="In Storage"), 1, 50)
        assert stored.total == query_value("SELECT COUNT(*) FROM evidence WHERE current_status = 'In Storage'")
        by_case = services.list_evidence(Scope(ADMIN), services.EvidenceFilters(case_reference="FX-2026-0022"), 1, 50)
        assert all(r["case_reference"] == "FX-2026-0022" for r in by_case.items)


def test_custody_timeline_links_corrections(app, demo_data):
    with app.app_context():
        item = services.get_evidence(Scope(ADMIN), "FX-EV-2026-00051")
        timeline = services.custody_timeline(item["evidence_id"])
        assert len(timeline) == query_value("SELECT COUNT(*) FROM chain_of_custody WHERE evidence_id = %s",
                                            (item["evidence_id"],))
        assert timeline[0]["action"] == "Collected" and timeline[-1]["is_current"]
        corrections = [t for t in timeline if t["corrects_custody_id"]]
        for c in corrections:     # each correction is listed on the entry it corrects
            original = next(t for t in timeline if t["custody_id"] == c["corrects_custody_id"])
            assert c["custody_id"] in original["corrected_by"]


def test_hash_history_marks_superseded(app, demo_data):
    with app.app_context():
        item = services.get_evidence(Scope(ADMIN), "FX-EV-2026-00052")
        hashes = services.hash_history(item["evidence_id"])
        current = [h for h in hashes if not h["superseded"]]
        assert len(current) == 1                                  # exactly one current reference hash
        assert current[0]["hash_value"] == item["current_hash_value"]


def test_registrable_cases_exclude_closed(app, db_available):
    with app.app_context():
        closed = {r["case_reference"] for r in services.visible_case_refs(Scope(ADMIN))} - \
                 {c["case_reference"] for c in services.registrable_cases(ADMIN)}
        assert closed == {r for r in closed if query_value("SELECT status FROM cases WHERE case_reference = %s", (r,)) == "Closed"}
        for c in services.registrable_cases(ROHAN):
            assert query_value("SELECT COUNT(*) FROM case_investigators WHERE case_id = %s AND user_id = 2", (c["case_id"],))


def test_location_counts(app, db_available):
    with app.app_context():
        rows = locations.list_locations()
        assert sum(int(r["items_here"]) for r in rows) == query_value(
            "SELECT COUNT(*) FROM evidence WHERE current_location_id IS NOT NULL")
