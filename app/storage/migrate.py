"""Move evidence files between storage backends, with verification (FORGE-X 2.0 Phase 9).

For every file not already on the target backend:
  1. hash the SOURCE copy; it must equal the SHA-256 recorded when the file
     was stored, or the file is not moved (reported and audited)
  2. copy it to the target under the same object id (write-once). If the
     target already holds a copy whose hash is right, nothing is copied
     (this is what makes moving back cheap)
  3. hash the TARGET copy; it must equal the recorded SHA-256, or the new
     copy is removed and nothing is recorded
  4. record the new location (hash before and after) and an audit row in one
     transaction; MySQL's CHECK refuses a row whose two hashes differ
The source copy is NEVER deleted, so a rollback is the same command with
--to pointing back, and nothing is lost if a migration stops halfway.
"""
from flask import current_app

from .. import audit
from ..db import query_all, transaction
from . import StorageError, get_storage

LIST_SQL = """
    SELECT f.file_id, f.object_id, f.sha256, f.size_bytes, e.evidence_code,
           COALESCE((SELECT l.backend FROM evidence_file_locations l WHERE l.file_id = f.file_id
                      ORDER BY l.location_id DESC LIMIT 1), 'local') AS backend
      FROM evidence_files f JOIN evidence e ON e.evidence_id = f.evidence_id
     ORDER BY f.file_id
"""


def status():
    """Every stored file with its current backend."""
    return query_all(LIST_SQL)


def migrate(target_name, user_id, limit=None, dry_run=False, log=print):
    """Move files to `target_name`. Returns counts: moved, already_there, skipped, failed."""
    target = get_storage(target_name)
    ok, message = target.health()
    if not ok:
        raise StorageError(f"Target storage isn't usable: {message}")
    counts = {"moved": 0, "already_there": 0, "skipped": 0, "failed": 0}
    todo = [f for f in status() if f["backend"] != target_name][:limit]
    log(f"{len(todo)} file(s) to move to {target_name} ({target.container or current_app.config['EVIDENCE_STORAGE_DIR']})"
        + (" [dry run]" if dry_run else ""))
    max_bytes = max(current_app.config["EVIDENCE_FILE_MAX_BYTES"], max((f["size_bytes"] for f in todo), default=0)) + 1
    for f in todo:
        label = f"{f['evidence_code']} ({f['object_id'][:8]}…)"
        source = get_storage(f["backend"])
        try:
            before, _ = source.sha256(f["object_id"])
        except StorageError as err:
            counts["skipped"] += 1
            log(f"  SKIP  {label}: source unreadable: {err}")
            audit.record("evidence.storage_move", "Evidence", f["evidence_code"], user_id=user_id, outcome="Failure",
                         details=f"Not moved to {target_name}: source unreadable")
            continue
        if before != f["sha256"]:
            counts["skipped"] += 1
            log(f"  SKIP  {label}: the source copy doesn't match its recorded SHA-256. Not moved; verify it first.")
            audit.record("evidence.storage_move", "Evidence", f["evidence_code"], user_id=user_id, outcome="Failure",
                         details=f"Not moved to {target_name}: source hash mismatch")
            continue
        if dry_run:
            log(f"  WOULD MOVE {label}")
            continue
        copied = False
        try:
            if target.exists(f["object_id"]):
                after, _ = target.sha256(f["object_id"])
                if after != f["sha256"]:
                    raise StorageError("an object with this id already exists on the target and does NOT match")
            else:
                with source.open_read(f["object_id"]) as stream:
                    target.put_as(f["object_id"], stream, max_bytes)
                copied = True
                after, _ = target.sha256(f["object_id"])
                if after != f["sha256"]:
                    target.discard_unrecorded(f["object_id"])
                    raise StorageError("the copy's SHA-256 differs from the recorded one; the copy was removed")
            with transaction() as cur:
                cur.execute("INSERT INTO evidence_file_locations (file_id, backend, container, sha256_before, "
                            "sha256_after, note, moved_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                            (f["file_id"], target_name, target.container, before, after,
                             f"Moved from {f['backend']} (verified before and after)" if copied else
                             f"Moved from {f['backend']}: verified copy already present", user_id))
                audit.record("evidence.storage_move", "Evidence", f["evidence_code"], user_id=user_id, cursor=cur,
                             details=f"{f['backend']} -> {target_name}, SHA-256 verified before and after: {after}")
        except Exception as err:                              # one bad file must not stop the rest
            counts["failed"] += 1
            if copied and not isinstance(err, StorageError):
                target.discard_unrecorded(f["object_id"])   # copied but not recorded: remove it
            log(f"  FAIL  {label}: {err}")
            continue
        counts["moved" if copied else "already_there"] += 1
        log(f"  OK    {label}: {'copied and verified' if copied else 'verified copy already there'}")
    return counts
