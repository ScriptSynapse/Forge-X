"""FORGE-X 2.0 Phase 5: independent review rules, artifact types and the examination PDF (no MySQL)."""
import pathlib
import re
from datetime import datetime

from app.access import can_review_examination, can_work_on_examination
from app.examinations import services
from app.examinations.pdf import build_examination_pdf

SCHEMA = (pathlib.Path(__file__).resolve().parent.parent / "database" / "schema.sql").read_text(encoding="utf-8")
ADMIN = {"user_id": 1, "roles": ["Administrator"]}
LEAD = {"user_id": 2, "roles": ["Investigator"]}
EXAMINER = {"user_id": 3, "roles": ["Investigator"]}
OTHER = {"user_id": 4, "roles": ["Investigator"]}


def _enum(table, column):
    block = SCHEMA[SCHEMA.index(f"CREATE TABLE {table} ("):]
    values = re.search(rf"\b{column}\s+ENUM\(([^)]*)\)", block).group(1)
    return tuple(v.strip().strip("'") for v in values.split(","))


def test_app_lists_match_the_database_enums():
    assert set(services.STATUSES) == set(_enum("examinations", "status"))
    assert services.ARTIFACT_TYPES == _enum("examination_artifacts", "artifact_type")


def test_only_an_independent_reviewer_can_approve():
    exam = {"status": "Under Review", "case_status": "In Progress", "examiner_id": 3, "lead_user_id": 2}
    assert can_review_examination(ADMIN, exam) and can_review_examination(LEAD, exam)
    assert not can_review_examination(EXAMINER, exam)                       # not the examiner
    assert not can_review_examination(OTHER, exam)                          # not just any investigator
    assert not can_review_examination(dict(ADMIN, user_id=3), exam)         # an administrator who examined it can't either
    assert not can_review_examination(ADMIN, dict(exam, status="In Progress"))
    assert not can_review_examination(ADMIN, dict(exam, case_status="Closed"))
    assert not can_work_on_examination(EXAMINER, dict(exam))                # frozen while under review


def test_examination_pdf_escapes_text_and_builds():
    now = datetime(2026, 10, 4, 12, 0)
    exam = {"examination_code": "EX-2026-0001", "type_name": "Log Analysis", "case_reference": "FX-2026-0001",
            "case_title": "Case <script>", "examiner_name": "Inv", "status": "Under Review", "started_at": now,
            "completed_at": None, "reviewed_at": None, "reviewer_name": None, "reviewed_by": None, "due_date": None,
            "tools_methods": "<b>tools</b>", "observations": "x & y", "findings": "f", "conclusion": None, "limitations": ""}
    artifacts = [{"artifact_id": 1, "artifact_type": "File", "description": "<para>drop</para>", "location": None,
                  "evidence_code": None, "sha256": None, "corrects_artifact_id": None, "corrected_by": []}]
    data = build_examination_pdf(exam, [], artifacts, [], "Paulson", now)
    assert data.startswith(b"%PDF") and len(data) > 1500
