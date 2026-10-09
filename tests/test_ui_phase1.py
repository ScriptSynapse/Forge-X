"""FORGE-X 2.0 Phase 1: labels, filters, sorting and period parsing (no MySQL needed)."""
from werkzeug.datastructures import MultiDict

from app.cases import services as cases
from app.dashboard.services import DEFAULT_PERIOD, PERIODS, parse_period
from app.evidence import services as evidence
from app.ui import dict_without, integrity_label


def test_integrity_labels_change_wording_only():
    assert integrity_label("Failed") == "Integrity mismatch"
    assert integrity_label("Pending") == "Pending verification"
    assert integrity_label("Not Verified") == "Verification unavailable"
    assert integrity_label("Verified") == "Verified"
    assert integrity_label("Something else") == "Something else"


def test_case_group_filters_and_column_sorts():
    f = cases.CaseFilters.from_args(MultiDict({"status": "active", "priority": "urgent", "sort": "-evidence"}))
    assert (f.status, f.priority, f.sort) == ("active", "urgent", "-evidence")
    bad = cases.CaseFilters.from_args(MultiDict({"status": "everything", "priority": "x", "sort": "title;DROP TABLE cases"}))
    assert (bad.status, bad.priority, bad.sort) == ("", "", "newest")
    for key in cases.SORT_COLUMNS:                       # every column sorts both ways
        assert key in cases.SORTS and "-" + key in cases.SORTS
    for legacy in ("newest", "oldest", "priority", "reference"):
        assert legacy in cases.SORTS                     # old links keep working


def test_evidence_awaiting_filter_and_sorts():
    f = evidence.EvidenceFilters.from_args(MultiDict({"awaiting": "1", "sort": "-integrity"}))
    assert f.awaiting and f.active and f.sort == "-integrity" and f.as_args()["awaiting"] == "1"
    assert not evidence.EvidenceFilters.from_args(MultiDict({"awaiting": "yes"})).awaiting
    for key in evidence.SORT_COLUMNS:
        assert key in evidence.SORTS and "-" + key in evidence.SORTS


def test_dashboard_period():
    assert parse_period("7") == "7" and parse_period("all") == "all"
    assert parse_period("999") == DEFAULT_PERIOD and parse_period(None) == DEFAULT_PERIOD
    assert PERIODS["all"][1] is None and PERIODS["90"][1] == 90


def test_dict_without():
    assert dict_without({"a": 1, "b": 2, "c": 3}, "b", "c") == {"a": 1}
