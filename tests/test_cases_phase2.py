"""FORGE-X 2.0 Phase 2: case filters, notes permissions, deletion blockers (no MySQL needed)."""
from datetime import date

from werkzeug.datastructures import MultiDict

from app.access import can_add_case_note
from app.cases import services


def test_new_case_filters():
    f = services.CaseFilters.from_args(MultiDict({"investigator": "7", "from": "2026-09-01", "to": "2026-10-04",
                                                  "overdue": "1", "sort": "-activity"}))
    assert (f.investigator_id, f.date_from, f.date_to, f.overdue, f.sort) == \
        (7, date(2026, 9, 1), date(2026, 10, 4), True, "-activity")
    assert f.active and f.as_args()["investigator"] == 7 and f.as_args()["overdue"] == "1"
    bad = services.CaseFilters.from_args(MultiDict({"investigator": "7 OR 1=1", "from": "yesterday", "sort": "due;--"}))
    assert (bad.investigator_id, bad.date_from, bad.sort) == (None, None, "newest")
    assert {"due", "-due", "activity", "-activity"} <= set(services.SORTS)


def test_who_can_add_notes():
    open_case, closed_case = {"status": "In Progress"}, {"status": "Closed"}
    admin, custodian = {"user_id": 1, "roles": ["Administrator"]}, {"user_id": 4, "roles": ["Evidence Custodian"]}
    investigator, auditor = {"user_id": 2, "roles": ["Investigator"]}, {"user_id": 6, "roles": ["Read-Only Auditor"]}
    assert can_add_case_note(admin, open_case, False) and can_add_case_note(custodian, open_case, False)
    assert can_add_case_note(investigator, open_case, True) and not can_add_case_note(investigator, open_case, False)
    assert not can_add_case_note(auditor, open_case, False)
    assert not can_add_case_note(admin, closed_case, False)           # closed cases are read-only (D3)


def test_notes_block_case_deletion():
    row = {"status": "Open", "evidence": 0, "examinations": 0, "reports": 0, "notes": 2}
    assert services._blockers(row) == ["It has 2 notes."]
