"""FORGE-X 2.0 Phase 7 end to end with the REAL YARA-X: rule library, scan, results, versions.
Opt-in (FORGE_X_DB_WRITE_TESTS=1, test database) and only where yara-x is installed."""
import io
import os
import uuid

import pytest

from app.db import query_one, query_value
from tests.conftest import login

try:
    import yara_x  # noqa: F401
    HAVE_YARA = True
except ImportError:
    HAVE_YARA = False

pytestmark = [
    pytest.mark.db,
    pytest.mark.db_write,
    pytest.mark.skipif(os.getenv("FORGE_X_DB_WRITE_TESTS") != "1",
                       reason="set FORGE_X_DB_WRITE_TESTS=1 to run tests that write to MySQL"),
    pytest.mark.skipif(not HAVE_YARA, reason="real YARA-X not installed (pip install yara-x)"),
]


def test_rule_library_scan_and_versions(app, client, make_user, tmp_path):
    app.config["EVIDENCE_STORAGE_DIR"] = str(tmp_path)
    admin, lead, custodian = make_user("Administrator"), make_user("Investigator"), make_user("Evidence Custodian")
    marker = f"pytest-marker-{uuid.uuid4().hex[:8]}"
    login(client, admin["username"], admin["password"])
    reference = client.post("/cases/new", data={"title": "Pytest YARA case", "case_type_id": "1", "priority": "Low",
                                                "description": "Phase 7 YARA.", "lead_user_id": str(lead["user_id"])}
                            ).headers["Location"].rsplit("/", 1)[-1]
    name = f"pytest rule {uuid.uuid4().hex[:6]}"
    refused = client.post("/yara/rules/new", data={"name": name, "scope": "Selected cases", "source": "rule broken {"})
    assert "compile" in refused.get_data(as_text=True)
    response = client.post("/yara/rules/new", data={"name": name, "scope": "Selected cases", "author": "pytest",
                                                     "source": f'rule marker {{ strings: $m = "{marker}" condition: $m }}'})
    assert response.status_code == 302
    rule_id = int(response.headers["Location"].rsplit("/", 1)[-1])
    with app.app_context():
        case_id = query_value("SELECT case_id FROM cases WHERE case_reference = %s", (reference,))
    client.post(f"/yara/rules/{rule_id}/cases", data={"case_id": str(case_id)})
    client.post("/logout")

    login(client, custodian["username"], custodian["password"])
    content = b"header " + marker.encode() + b" footer"
    code = client.post("/evidence/new", content_type="multipart/form-data", data={
        "case_id": str(case_id), "evidence_type_id": "8", "description": "YARA sample", "collection_site": "Lab",
        "collected_at": "2026-10-01T09:00", "collected_by": str(custodian["user_id"]), "collection_condition": "Sealed",
        "hash_source": "Computed", "evidence_file": (io.BytesIO(content), "sample.bin")}).headers["Location"].rsplit("/", 1)[-1]
    response = client.post(f"/yara/evidence/{code}/scan")
    assert response.status_code == 302 and "/yara/scans/" in response.headers["Location"]
    scan_id = int(response.headers["Location"].rsplit("/", 1)[-1])
    with app.app_context():
        scan = query_one("SELECT status, matched_count, hash_matches, scanner_version FROM yara_scans WHERE scan_id = %s", (scan_id,))
        match = query_one("SELECT rule_identifier, patterns_json FROM yara_matches WHERE scan_id = %s", (scan_id,))
    assert (scan["status"], scan["matched_count"], scan["hash_matches"]) == ("Completed", 1, 1)
    assert scan["scanner_version"].startswith("yara-x") and match["rule_identifier"] == "marker"
    assert '"offset": 7' in match["patterns_json"]
    page = client.get(f"/yara/scans/{scan_id}").get_data(as_text=True)
    assert "marker" in page and "Matches the recorded hash" in page
    client.post("/logout")

    # A new version doesn't change what the old scan used; disabling stops future scans
    login(client, admin["username"], admin["password"])
    client.post(f"/yara/rules/{rule_id}/versions", data={"source": 'rule marker { condition: false }', "change_note": "Disabled match"})
    with app.app_context():
        used = query_value("SELECT v.version_no FROM yara_scan_rules sr JOIN yara_rule_versions v ON v.version_id = sr.version_id "
                           "WHERE sr.scan_id = %s", (scan_id,))
    assert used == 1
    client.post(f"/yara/rules/{rule_id}/enabled", data={"enable": "0"})
    refused = client.post(f"/yara/evidence/{code}/scan", follow_redirects=True).get_data(as_text=True)
    assert "No enabled YARA rules apply" in refused
