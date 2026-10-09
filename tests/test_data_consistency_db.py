"""FORGE-X 2.0 Phase 6: invariants that must hold on any FORGE-X database, checked
against your real data. Read-only (SELECT only; storage files are only read)."""
import pytest

from app.db import query_all, query_value
from app.storage import storage_for

pytestmark = pytest.mark.db


def _zero(sql, what):
    count = query_value(sql)
    assert count == 0, f"{count} {what}"


def test_current_custody_matches_the_latest_entry(app, db_available):
    with app.app_context():
        _zero("""SELECT COUNT(*) FROM evidence e
                 LEFT JOIN (SELECT evidence_id, to_custodian_id, location_id,
                                   ROW_NUMBER() OVER (PARTITION BY evidence_id ORDER BY occurred_at DESC, custody_id DESC) AS rn
                              FROM chain_of_custody) l ON l.evidence_id = e.evidence_id AND l.rn = 1
                 WHERE l.evidence_id IS NULL
                    OR NOT (l.to_custodian_id <=> e.current_custodian_id AND l.location_id <=> e.current_location_id)""",
              "items whose current custodian/location differ from their latest custody entry")


def test_one_lead_per_case_and_consistent_verification_results(app, db_available):
    with app.app_context():
        _zero("SELECT COUNT(*) FROM cases c WHERE (SELECT COUNT(*) FROM case_investigators ci "
              "WHERE ci.case_id = c.case_id AND ci.is_lead) <> 1", "cases without exactly one lead")
        _zero("SELECT COUNT(*) FROM hash_verifications hv JOIN evidence_hashes h ON h.hash_id = hv.hash_id "
              "WHERE hv.result <> IF(hv.computed_hash = h.hash_value, 'Verified', 'Failed')",
              "verification results that disagree with their hashes")


def test_corrections_stay_on_their_own_record(app, db_available):
    with app.app_context():
        _zero("SELECT COUNT(*) FROM chain_of_custody c JOIN chain_of_custody o ON o.custody_id = c.corrects_custody_id "
              "WHERE o.evidence_id <> c.evidence_id", "custody corrections pointing at another item")
        _zero("SELECT COUNT(*) FROM evidence_hashes h JOIN evidence_hashes o ON o.hash_id = h.supersedes_hash_id "
              "WHERE o.evidence_id <> h.evidence_id", "hash corrections pointing at another item")
        _zero("SELECT COUNT(*) FROM case_notes n JOIN case_notes o ON o.note_id = n.corrects_note_id "
              "WHERE o.case_id <> n.case_id", "note corrections pointing at another case")
        _zero("SELECT COUNT(*) FROM examination_artifacts a JOIN examination_artifacts o ON o.artifact_id = a.corrects_artifact_id "
              "WHERE o.examination_id <> a.examination_id", "artifact corrections pointing at another examination")


def test_closed_cases_received_nothing_after_closure(app, db_available):
    with app.app_context():
        _zero("SELECT COUNT(*) FROM case_notes n JOIN cases c ON c.case_id = n.case_id "
              "WHERE c.status = 'Closed' AND n.created_at > c.closed_at", "notes added after their case was closed")


def test_stored_files_match_a_recorded_hash_and_exist(app, db_available):
    with app.app_context():
        _zero("SELECT COUNT(*) FROM evidence_files f WHERE NOT EXISTS (SELECT 1 FROM evidence_hashes h "
              "WHERE h.evidence_id = f.evidence_id AND h.hash_value = f.sha256)",
              "stored files whose SHA-256 isn't one of their item's recorded hashes")
        rows = query_all("SELECT f.object_id, COALESCE((SELECT l.backend FROM evidence_file_locations l "
                         "WHERE l.file_id = f.file_id ORDER BY l.location_id DESC LIMIT 1), 'local') AS backend "
                         "FROM evidence_files f")
        missing = [f"{r['object_id']} ({r['backend']})" for r in rows if not storage_for(r).exists(r["object_id"])]
    assert not missing, (f"{len(missing)} recorded files are missing from their storage backend: "
                         f"{missing[:5]}. Restore them from backup")


def test_code_counters_never_fall_behind(app, db_available):
    """Gap-free numbering: each yearly counter is at least the highest number in use."""
    with app.app_context():
        for seq, sql in (("CASE", "SELECT MAX(CAST(SUBSTRING(case_reference, 9) AS UNSIGNED)) FROM cases "
                                  "WHERE SUBSTRING(case_reference, 4, 4) = %s"),
                         ("EVIDENCE", "SELECT MAX(CAST(SUBSTRING(evidence_code, 12) AS UNSIGNED)) FROM evidence "
                                      "WHERE SUBSTRING(evidence_code, 7, 4) = %s")):
            for row in query_all("SELECT seq_year, last_number FROM reference_sequences WHERE seq_name = %s", (seq,)):
                used = query_value(sql, (str(row["seq_year"]),)) or 0
                assert row["last_number"] >= used, f"{seq} {row['seq_year']}: counter {row['last_number']} < used {used}"



def test_every_storage_move_was_verified(app, db_available):
    """A location row records the same SHA-256 before and after a move, and it
    equals the hash recorded when the file was stored."""
    with app.app_context():
        _zero("SELECT COUNT(*) FROM evidence_file_locations l JOIN evidence_files f ON f.file_id = l.file_id "
              "WHERE l.sha256_after <> f.sha256 OR (l.sha256_before IS NOT NULL AND l.sha256_before <> l.sha256_after)",
              "storage moves whose hashes don't match the recorded SHA-256")
