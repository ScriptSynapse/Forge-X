"""Phase 10: hashing, custody rules and permissions (no MySQL needed)."""
import hashlib
import io

import pytest
from werkzeug.datastructures import FileStorage

from app.access import can_correct_records, can_record_hash, can_verify_hash, custody_actions_for
from app.custody.services import NEEDS_STORAGE_LOCATION, allowed_actions, resulting_status
from app.integrity.hashing import SampleFileError, sha256_of_upload

ADMIN = {"user_id": 1, "roles": ["Administrator"]}
CUSTODIAN = {"user_id": 4, "roles": ["Evidence Custodian"]}
INVESTIGATOR = {"user_id": 2, "roles": ["Investigator"]}
AUDITOR = {"user_id": 6, "roles": ["Read-Only Auditor"]}
ITEM = {"case_status": "In Progress", "current_hash_value": None}


def upload(data, name="image.bin"):
    return FileStorage(stream=io.BytesIO(data), filename=name)


def test_sha256_matches_hashlib_and_streams_large_files():
    data = b"forge-x" * 300_000                       # ~2 MB: read in several 1 MiB chunks
    digest, size, name = sha256_of_upload(upload(data, "../../disk image.dd"), 25 * 1024 * 1024)
    assert digest == hashlib.sha256(data).hexdigest() and size == len(data)
    assert name == "disk_image.dd"                     # path parts removed (secure_filename)


@pytest.mark.parametrize("data,name,limit,message", [
    (b"", "empty.bin", 100, "empty"),
    (b"x" * 101, "big.bin", 100, "or smaller"),
    (b"MZ", "tool.exe", 100, "isn't accepted"),
])
def test_bad_sample_files_are_refused(data, name, limit, message):
    with pytest.raises(SampleFileError, match=message):
        sha256_of_upload(upload(data, name), limit)


def test_custody_transitions_mirror_the_procedure():
    assert allowed_actions("In Storage") == ("Transferred", "Checked Out", "Stored", "Released", "Archived")
    assert allowed_actions("Archived") == ()
    assert allowed_actions("Released") == ("Archived",)
    assert allowed_actions("Under Examination", ("Checked Out", "Examined", "Returned")) == ("Examined", "Returned")
    assert resulting_status("Returned", "Checked Out") == "In Storage"
    assert resulting_status("Transferred", "Checked Out") == "Checked Out"
    assert NEEDS_STORAGE_LOCATION == {"Received", "Stored", "Returned"}


def test_integrity_and_custody_permissions():
    assert can_verify_hash(CUSTODIAN, ITEM, False) and can_verify_hash(INVESTIGATOR, ITEM, True)
    assert not can_verify_hash(INVESTIGATOR, ITEM, False) and not can_verify_hash(AUDITOR, ITEM, False)
    assert can_record_hash(ADMIN, ITEM, False)
    assert not can_record_hash(ADMIN, dict(ITEM, current_hash_value="ab" * 32), False)   # already has one
    assert not can_record_hash(ADMIN, dict(ITEM, case_status="Closed"), False)
    assert can_correct_records(CUSTODIAN) and not can_correct_records(INVESTIGATOR)
    assert custody_actions_for(CUSTODIAN, False) is None                     # every action
    assert custody_actions_for(INVESTIGATOR, True) == ("Checked Out", "Examined", "Returned")
    assert custody_actions_for(INVESTIGATOR, False) == () and custody_actions_for(AUDITOR, False) == ()


def test_pages_require_login(client):
    for path in ("/custody", "/custody/FX-EV-2026-00001/transfer", "/evidence/FX-EV-2026-00001/hash/verify",
                 "/evidence/FX-EV-2026-00001/hash/record", "/custody/FX-EV-2026-00001/entries/1/correct"):
        response = client.get(path)
        assert response.status_code == 302 and "/login" in response.headers["Location"], path
