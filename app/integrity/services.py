"""Evidence integrity: recording, verifying and correcting SHA-256 hashes.

Rules (enforced here AND in MySQL):
  * evidence_hashes and hash_verifications are append-only (triggers).
  * Each item has one original hash; a correction is a NEW hash that
    supersedes the old one, with a reason (UNIQUE keys + trigger).
  * A verification's result is computed by trigger trg_hv_set_result, never
    by this code: we only supply the computed hash.
  * A matching hash shows the content was identical when compared. It does
    not, by itself, prove authenticity, ownership or complete custody.
"""
from .. import audit
from ..db import BusinessRuleError, ConstraintViolation, query_value, transaction


class IntegrityError(Exception):
    """A refused integrity action, with a message that is safe to display."""


def is_assigned(user_id, case_id):
    return bool(query_value("SELECT COUNT(*) FROM case_investigators WHERE case_id = %s AND user_id = %s",
                            (case_id, user_id)))


def _current_hash(cur, evidence_id):
    """The item's current reference hash. Call only after _lock_item().

    Deliberately a plain SELECT, not FOR UPDATE: MySQL 8.0.22+ requires UPDATE
    or DELETE privilege for a locking read, and the application account has
    neither on the append-only evidence_hashes table. It isn't needed either:
    every change to an item's hashes first locks that item's evidence row
    (_lock_item), so they take turns, and this read happens after the lock,
    so it sees every hash committed before it."""
    cur.execute(
        "SELECT h.hash_id, h.hash_value FROM evidence_hashes h WHERE h.evidence_id = %s "
        "AND NOT EXISTS (SELECT 1 FROM evidence_hashes s WHERE s.supersedes_hash_id = h.hash_id)",
        (evidence_id,),
    )
    return cur.fetchone()


def _lock_item(cur, evidence_id):
    # Locking the evidence row makes concurrent hash actions on the same item take turns.
    cur.execute("SELECT evidence_id, evidence_code FROM evidence WHERE evidence_id = %s FOR UPDATE", (evidence_id,))
    item = cur.fetchone()
    if item is None:
        raise IntegrityError("Evidence item not found.")
    return item


def record_original_hash(evidence_id, user_id, hash_value, source, notes):
    """Record the item's first reference hash. `source` is 'Computed' (from a
    sample file or tool output) or 'Manual' (copied from another record)."""
    try:
        with transaction() as cur:
            item = _lock_item(cur, evidence_id)
            if _current_hash(cur, evidence_id):
                raise IntegrityError("This item already has a reference hash. Use Correct hash to replace it.")
            cur.execute(
                "INSERT INTO evidence_hashes (evidence_id, hash_value, source, source_notes, recorded_by) "
                "VALUES (%s, %s, %s, %s, %s)",
                (evidence_id, hash_value, source, notes or None, user_id),
            )
            audit.record("hash.record", "Evidence", item["evidence_code"], cursor=cur,
                         details=f"Original SHA-256 recorded ({source})")
    except (ConstraintViolation, BusinessRuleError) as err:
        raise IntegrityError("The database refused this hash: " + (getattr(err, "constraint", None) or err.user_message)) from err


def verify(evidence_id, user_id, computed_hash, method, sample_file_name=None, sample_size=None, notes=None):
    """Record a verification and return (result, reference_hash). MySQL's
    trigger decides Verified/Failed by comparing with the current hash."""
    with transaction() as cur:
        item = _lock_item(cur, evidence_id)
        current = _current_hash(cur, evidence_id)
        if current is None:
            raise IntegrityError("Record a reference hash for this item before verifying it.")
        cur.execute(
            "INSERT INTO hash_verifications (hash_id, computed_hash, method, sample_file_name, sample_size_bytes, "
            "notes, verified_by) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            (current["hash_id"], computed_hash, method, sample_file_name, sample_size, notes or None, user_id),
        )
        cur.execute("SELECT result FROM hash_verifications WHERE verification_id = LAST_INSERT_ID()")
        result = cur.fetchone()["result"]
        audit.record("hash.verify", "Evidence", item["evidence_code"], cursor=cur,
                     outcome="Success", details=f"Result {result} ({method})")
    return result, current["hash_value"]


def correct_hash(evidence_id, user_id, new_hash, source, notes, reason):
    """Supersede the current reference hash. The old hash stays on record."""
    try:
        with transaction() as cur:
            item = _lock_item(cur, evidence_id)
            current = _current_hash(cur, evidence_id)
            if current is None:
                raise IntegrityError("There is no recorded hash to correct. Record the original hash instead.")
            if current["hash_value"] == new_hash:
                raise IntegrityError("The new hash is the same as the current one.")
            cur.execute(
                "INSERT INTO evidence_hashes (evidence_id, hash_value, source, source_notes, recorded_by, "
                "supersedes_hash_id, correction_reason) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                (evidence_id, new_hash, source, notes or None, user_id, current["hash_id"], reason),
            )
            audit.record("hash.correct", "Evidence", item["evidence_code"], cursor=cur,
                         details=f"Hash #{current['hash_id']} superseded: {reason}"[:500])
    except (ConstraintViolation, BusinessRuleError) as err:
        raise IntegrityError("The database refused this correction: "
                             + (getattr(err, "constraint", None) or err.user_message)) from err
