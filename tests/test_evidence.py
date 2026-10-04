"""Phase 9: evidence rules that don't need MySQL."""
from werkzeug.datastructures import MultiDict

from app.access import can_edit_evidence, can_register_evidence, registers_for_any_case
from app.evidence.services import EvidenceFilters, is_valid_sha256, normalise_hash
from app.ui import filesize

ADMIN = {"user_id": 1, "roles": ["Administrator"]}
CUSTODIAN = {"user_id": 4, "roles": ["Evidence Custodian"]}
LEAD = {"user_id": 2, "roles": ["Investigator"]}
MEMBER = {"user_id": 3, "roles": ["Investigator"]}
AUDITOR = {"user_id": 6, "roles": ["Read-Only Auditor"]}
OPEN_ITEM = {"case_status": "In Progress", "lead_user_id": 2}
CLOSED_ITEM = {"case_status": "Closed", "lead_user_id": 2}


def test_evidence_pages_require_login(client):
    for path in ("/evidence", "/evidence/new", "/evidence/FX-EV-2026-00051", "/evidence/FX-EV-2026-00051/edit",
                 "/admin/locations"):
        response = client.get(path)
        assert response.status_code == 302 and "/login" in response.headers["Location"], path


def test_who_can_register_and_edit_evidence():
    assert can_register_evidence(ADMIN) and can_register_evidence(CUSTODIAN) and can_register_evidence(LEAD)
    assert not can_register_evidence(AUDITOR)
    assert registers_for_any_case(CUSTODIAN) and not registers_for_any_case(LEAD)
    assert can_edit_evidence(ADMIN, OPEN_ITEM) and can_edit_evidence(CUSTODIAN, OPEN_ITEM)
    assert can_edit_evidence(LEAD, OPEN_ITEM) and not can_edit_evidence(MEMBER, OPEN_ITEM)
    assert not can_edit_evidence(AUDITOR, OPEN_ITEM)
    assert not can_edit_evidence(ADMIN, CLOSED_ITEM)          # closed cases are read-only


def test_sha256_handling():
    pasted = "  " + "AB" * 32 + "\n"
    assert normalise_hash(pasted) == "ab" * 32 and is_valid_sha256(normalise_hash(pasted))
    assert normalise_hash("   ") is None
    assert not is_valid_sha256("ab" * 31) and not is_valid_sha256("g" * 64)


def test_filters_ignore_unknown_values():
    f = EvidenceFilters.from_args(MultiDict({"status": "Lost", "integrity": "Maybe", "case": "FX-26-1'--", "type": "x", "sort": "?"}))
    assert (f.status, f.integrity, f.case_reference, f.evidence_type_id, f.sort) == ("", "", "", None, "newest")
    good = EvidenceFilters.from_args(MultiDict({"case": "fx-2026-0022", "integrity": "Failed", "status": "In Storage"}))
    assert (good.case_reference, good.integrity, good.status) == ("FX-2026-0022", "Failed", "In Storage")


def test_filesize():
    assert filesize(512110190592) == "512.1 GB"
    assert filesize(4096) == "4.1 KB" and filesize(999) == "999 bytes" and filesize(None) == ""
