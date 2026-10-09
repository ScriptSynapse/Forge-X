"""FORGE-X 2.0 Phase 3: file permissions, upload naming and upload size limits (no MySQL)."""
from werkzeug.datastructures import FileStorage

from app.evidence.files import can_attach, can_download, describe_upload

ADMIN = {"user_id": 1, "roles": ["Administrator"]}
CUSTODIAN = {"user_id": 4, "roles": ["Evidence Custodian"]}
INVESTIGATOR = {"user_id": 2, "roles": ["Investigator"]}
AUDITOR = {"user_id": 6, "roles": ["Read-Only Auditor"]}


def test_who_can_download_and_attach():
    assert can_download(ADMIN, False) and can_download(CUSTODIAN, False) and can_download(INVESTIGATOR, True)
    assert not can_download(INVESTIGATOR, False) and not can_download(AUDITOR, False)
    open_item, closed_item = {"case_status": "In Progress"}, {"case_status": "Closed"}
    assert can_attach(CUSTODIAN, open_item, False) and not can_attach(CUSTODIAN, closed_item, False)
    assert not can_attach(AUDITOR, open_item, False)


def test_upload_names_are_sanitised_and_types_guessed_by_extension():
    name, media_type = describe_upload(FileStorage(filename="../../secret dir/disk image.E01"))
    assert name == "secret_dir_disk_image.E01" and "/" not in name and ".." not in name
    assert media_type == "application/octet-stream"
    assert describe_upload(FileStorage(filename="report.pdf"))[1] == "application/pdf"
    assert describe_upload(FileStorage(filename=""))[0] == "evidence"


def test_large_uploads_are_refused_outside_the_evidence_routes(client):
    big = b"x" * (27 * 1024 * 1024)                   # over the app-wide 26 MB limit
    response = client.post("/login", data=big, content_type="application/octet-stream")
    assert response.status_code == 413
