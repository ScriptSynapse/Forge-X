"""Stored evidence files (FORGE-X 2.0 Phase 3, decision U1).

The file is written first (hashing it as it's written), then recorded in
MySQL. If recording fails, the unrecorded file is removed, so storage never
holds a file the database doesn't know about. Recorded files are never
changed or deleted (append-only table + write-once storage).

The trusted reference hash is never replaced by a stored file: when an item
already has a reference hash, a file whose SHA-256 differs is refused.
"""
import mimetypes

from flask import current_app
from werkzeug.utils import secure_filename

from .. import audit
from ..access import ADMIN, CUSTODIAN, INVESTIGATOR
from ..db import BusinessRuleError, ConstraintViolation, DatabaseError, query_one, query_value, transaction
from ..integrity import services as integrity
from ..storage import StorageError, get_storage, storage_for
from . import services


class FileActionError(Exception):
    """A refused file action, with a message that is safe to show."""


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------
def _staff_or_assigned(user, assigned):
    roles = set(user["roles"])
    return bool({ADMIN, CUSTODIAN} & roles) or (INVESTIGATOR in roles and assigned)


def can_download(user, assigned):
    """Administrators, custodians and the case's investigators. Auditors read
    records but don't take copies of evidence content."""
    return _staff_or_assigned(user, assigned)


def can_attach(user, item, assigned):
    return item["case_status"] != "Closed" and _staff_or_assigned(user, assigned)


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------
# Where a file is now: its latest evidence_file_locations row (FORGE-X 2.0 Phase 9);
# files stored before Phase 9 have none and are on local disk.
def get_file(evidence_id):
    return query_one(
        "SELECT f.file_id, f.object_id, f.original_name, f.media_type, f.size_bytes, f.sha256, f.stored_at, "
        "u.full_name AS stored_by_name, "
        "COALESCE((SELECT l.backend FROM evidence_file_locations l WHERE l.file_id = f.file_id "
        "          ORDER BY l.location_id DESC LIMIT 1), 'local') AS backend, "
        "(SELECT l.container FROM evidence_file_locations l WHERE l.file_id = f.file_id "
        " ORDER BY l.location_id DESC LIMIT 1) AS container "
        "FROM evidence_files f JOIN users u ON u.user_id = f.stored_by WHERE f.evidence_id = %s", (evidence_id,))


def describe_upload(upload):
    """(display name, media type) for an upload. The name is only ever shown
    and offered as the download name; the type is guessed from the extension
    (the browser's claim is not trusted)."""
    name = secure_filename(upload.filename or "") or "evidence"
    media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return name[:255], media_type[:100]


def _store(upload):
    """Store an upload in the backend new files go to. Returns (object_id, size, sha256)."""
    if upload is None or not getattr(upload, "filename", ""):
        raise FileActionError("Choose a file.")
    try:
        return get_storage().put(upload.stream, current_app.config["EVIDENCE_FILE_MAX_BYTES"])
    except StorageError as err:
        raise FileActionError(str(err)) from err


def _discard(object_id):
    try:
        get_storage().discard_unrecorded(object_id)
    except (StorageError, OSError):
        current_app.logger.exception("Could not remove unrecorded evidence file %s", object_id)


def _insert_file_row(cur, evidence_id, object_id, name, media_type, size, sha256, user_id):
    """The file record plus its first location row, in the caller's transaction."""
    cur.execute(
        "INSERT INTO evidence_files (evidence_id, object_id, original_name, media_type, size_bytes, sha256, stored_by) "
        "VALUES (%s, %s, %s, %s, %s, %s, %s)", (evidence_id, object_id, name, media_type, size, sha256, user_id))
    backend = get_storage()
    cur.execute("INSERT INTO evidence_file_locations (file_id, backend, container, sha256_after, note, moved_by) "
                "VALUES (%s, %s, %s, %s, 'Stored at registration', %s)",
                (cur.lastrowid, backend.name, backend.container, sha256, user_id))


# ---------------------------------------------------------------------------
# Register evidence together with its file
# ---------------------------------------------------------------------------
def register_with_file(user, upload, fields, typed_hash, typed_source, typed_notes):
    """Store the file, then register the evidence with the file's SHA-256 as
    its original reference hash, then record the file. `fields` holds the
    other register_evidence arguments. Returns (evidence_code, warning)."""
    name, media_type = describe_upload(upload)
    object_id, size, sha256 = _store(upload)
    if typed_hash and typed_hash != sha256:
        _discard(object_id)
        raise FileActionError("The file's SHA-256 doesn't match the original hash you entered, so nothing was "
                              f"registered. The file hashes to {sha256}.")
    notes = (typed_notes if typed_hash and typed_source == "Manual" else None) or \
        f"Computed by FORGE-X while storing {name} ({size:,} bytes)"
    try:
        code = services.register_evidence(
            user, fields["case_id"], fields["evidence_type_id"], fields["description"], fields["source_details"],
            fields["size_bytes"] or size, fields["collected_at"], fields["collected_by"], fields["collection_site"],
            fields["collection_condition"], fields["seal_number"], sha256, "Computed", notes)
    except BaseException:
        _discard(object_id)            # nothing was registered, so the file must not stay either
        raise
    evidence_id = query_value("SELECT evidence_id FROM evidence WHERE evidence_code = %s", (code,))
    try:
        with transaction() as cur:
            _insert_file_row(cur, evidence_id, object_id, name, media_type, size, sha256, user["user_id"])
            audit.record("evidence.file_store", "Evidence", code, cursor=cur,
                         details=f"{name}, {size:,} bytes, SHA-256 {sha256}")
    except DatabaseError:
        _discard(object_id)
        current_app.logger.exception("Evidence %s registered but its file record failed", code)
        return code, ("The evidence and its SHA-256 were registered, but the file couldn't be recorded and was "
                      "removed. Attach it again from the evidence page.")
    return code, None


# ---------------------------------------------------------------------------
# Attach a file to an item registered without one
# ---------------------------------------------------------------------------
def attach(item, user, upload):
    """Store a file for an existing item. If the item already has a reference
    hash, the file must match it exactly; otherwise its SHA-256 becomes the
    original reference hash. One transaction, locked on the evidence row."""
    if get_file(item["evidence_id"]):
        raise FileActionError("This item already has a stored file. Stored files are never replaced.")
    name, media_type = describe_upload(upload)
    object_id, size, sha256 = _store(upload)
    try:
        with transaction() as cur:
            cur.execute("SELECT evidence_id FROM evidence WHERE evidence_id = %s FOR UPDATE", (item["evidence_id"],))
            cur.execute("SELECT COUNT(*) AS n FROM evidence_files WHERE evidence_id = %s", (item["evidence_id"],))
            if cur.fetchone()["n"]:
                raise FileActionError("This item already has a stored file. Stored files are never replaced.")
            current = integrity._current_hash(cur, item["evidence_id"])
            if current and current["hash_value"] != sha256:
                raise FileActionError("This file's SHA-256 doesn't match the item's recorded reference hash, so it "
                                      f"wasn't stored. The file hashes to {sha256}. The reference hash is unchanged.")
            if current is None:
                cur.execute("INSERT INTO evidence_hashes (evidence_id, hash_value, source, source_notes, recorded_by) "
                            "VALUES (%s, %s, 'Computed', %s, %s)",
                            (item["evidence_id"], sha256, f"Computed by FORGE-X while storing {name} ({size:,} bytes)",
                             user["user_id"]))
            _insert_file_row(cur, item["evidence_id"], object_id, name, media_type, size, sha256, user["user_id"])
            audit.record("evidence.file_store", "Evidence", item["evidence_code"], cursor=cur,
                         details=(f"{name}, {size:,} bytes, SHA-256 {sha256}"
                                  + ("" if current else "; recorded as the original reference hash"))[:500])
    except BaseException:
        _discard(object_id)
        raise
    return sha256


# ---------------------------------------------------------------------------
# Verify the stored copy
# ---------------------------------------------------------------------------
def verify_stored(item, user):
    """Re-hash the stored file (read-only) and record the check. The database
    trigger decides Verified or Failed against the trusted reference hash."""
    stored = get_file(item["evidence_id"])
    if stored is None:
        raise FileActionError("This item has no stored file. Verification from storage is unavailable.")
    try:
        computed, size = storage_for(stored).sha256(stored["object_id"])
    except (StorageError, OSError) as err:
        audit.record("hash.verify", "Evidence", item["evidence_code"], outcome="Failure",
                     details="Stored file could not be read: verification unavailable")
        raise FileActionError("The stored file couldn't be read, so it wasn't verified. "
                              "Tell an administrator: the file may be missing from evidence storage.") from err
    try:
        result, reference = integrity.verify(item["evidence_id"], user["user_id"], computed, "Stored file",
                                             sample_file_name=stored["original_name"], sample_size=size)
    except integrity.IntegrityError as err:
        raise FileActionError(str(err)) from err
    except (BusinessRuleError, ConstraintViolation) as err:
        raise FileActionError("The database refused the check: " + err.user_message) from err
    return {"outcome": result, "reference": reference, "computed": computed,
            "file_name": stored["original_name"], "size": size}


def open_for_download(item, user):
    """The stored file opened for reading, plus its record.

    Before anything is sent, the download is recorded as an 'Exported'
    custody entry and an audit row, in one transaction locked on the
    evidence row. If that fails, the download is refused (fail closed): no
    copy leaves without a custody record. The original's custodian, location
    and status are repeated unchanged, because only a copy left."""
    stored = get_file(item["evidence_id"])
    if stored is None:
        raise FileActionError("This item has no stored file.")
    try:
        handle = storage_for(stored).open_read(stored["object_id"])
    except (StorageError, OSError) as err:
        raise FileActionError("The stored file couldn't be read. Tell an administrator.") from err
    try:
        with transaction() as cur:
            cur.execute("SELECT current_custodian_id, current_location_id FROM evidence WHERE evidence_id = %s FOR UPDATE",
                        (item["evidence_id"],))
            now = cur.fetchone()
            cur.execute(
                "INSERT INTO chain_of_custody (evidence_id, action, from_custodian_id, to_custodian_id, location_id, "
                "location_note, evidence_condition, reason, occurred_at, recorded_by) "
                "VALUES (%s, 'Exported', %s, %s, %s, %s, %s, %s, NOW(), %s)",
                (item["evidence_id"], now["current_custodian_id"], now["current_custodian_id"], now["current_location_id"],
                 None if now["current_location_id"] else "Not in a storage location",
                 "Original unchanged; a copy was exported",
                 (f"Copy of the stored file {stored['original_name']} downloaded by {user['full_name']} "
                  f"(SHA-256 {stored['sha256']})")[:500],
                 user["user_id"]))
            audit.record("evidence.download", "Evidence", item["evidence_code"], cursor=cur,
                         details=f"{stored['original_name']}, SHA-256 {stored['sha256']}; custody entry Exported")
    except DatabaseError as err:
        handle.close()
        raise FileActionError("The download couldn't be recorded in the chain of custody, so it was refused. "
                              "If this keeps happening, run flask check-db (migration 006 may be missing).") from err
    return handle, stored
