"""FORGE-X 2.0 Phase 4: custody log filters, SQL composition and export rules (no MySQL)."""
import itertools
import re
from datetime import date

import pytest
from werkzeug.datastructures import MultiDict

from app.access import Scope
from app.custody import services


def test_event_types_and_filter_parsing():
    assert "Exported" in services.ACTIONS and services.CHECK_EVENT in services.EVENT_TYPES
    f = services.CustodyFilters.from_args(MultiDict({"q": "fx-ev", "case": "fx-2026-0002", "action": "Integrity check",
                                                     "person": "3", "from": "2026-09-01", "order": "oldest"}))
    assert (f.q, f.case_reference, f.action, f.person_id, f.date_from, f.order) == \
        ("FX-EV", "FX-2026-0002", "Integrity check", 3, date(2026, 9, 1), "oldest")
    bad = services.CustodyFilters.from_args(MultiDict({"case": "x;--", "action": "Nope", "person": "1 OR 1", "order": "up"}))
    assert (bad.case_reference, bad.action, bad.person_id, bad.order) == ("", "", None, "newest")


def test_every_filter_combination_builds_safe_sql(monkeypatch):
    captured = []
    monkeypatch.setattr(services, "query_value", lambda sql, params=(): captured.append((sql, params)) or 0)
    monkeypatch.setattr(services, "query_all", lambda sql, params=(): captured.append((sql, params)) or [])
    for user in ({"user_id": 1, "roles": ["Administrator"]}, {"user_id": 7, "roles": ["Investigator"]}):
        for q, action, person, day, order in itertools.product(["", "FX-EV"], ["", "Exported", "Integrity check"],
                                                               [None, 3], [None, date(2026, 9, 1)], ["newest", "oldest"]):
            captured.clear()
            filters = services.CustodyFilters(q=q, action=action, person_id=person, date_from=day, date_to=day, order=order)
            services.custody_log(Scope(user), filters, 1, 20)
            for sql, params in captured:
                assert sql.count("%s") == len(params) and not re.search(r"%(?!s)", sql)
            main = captured[-1][0]
            branches = main.count("FROM chain_of_custody coc") + main.count("FROM hash_verifications hv")
            assert branches == (1 if action else 2)          # a single event type queries one table only


def test_export_entries_cannot_be_corrected(monkeypatch):
    monkeypatch.setattr(services, "query_value", lambda sql, params=(): "Exported")
    with pytest.raises(services.CustodyError, match="can't be corrected"):
        services.correct_entry(70, 4, 4, None, "note", "condition", None, "a long enough reason")
