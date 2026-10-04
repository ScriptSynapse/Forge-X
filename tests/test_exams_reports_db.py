"""Phase 11: examination and report queries against MySQL. Read-only."""
import pytest

from app.access import Scope
from app.db import query_value
from app.examinations import services as exams
from app.reports import services as reports

pytestmark = pytest.mark.db

ADMIN = {"user_id": 1, "roles": ["Administrator"]}


def test_examination_list_matches_sql(app, db_available):
    with app.app_context():
        page = exams.list_examinations(Scope(ADMIN), exams.ExamFilters(), 1, 1, 20)
        assert page.total == query_value("SELECT COUNT(*) FROM examinations")
        overdue = exams.list_examinations(Scope(ADMIN), exams.ExamFilters(overdue=True), 1, 1, 50)
        assert overdue.total == query_value("SELECT COUNT(*) FROM v_examination_summary WHERE is_overdue")


def test_report_list_matches_sql(app, db_available):
    with app.app_context():
        page = reports.list_reports(Scope(ADMIN), reports.ReportFilters(), 1, 20)
        assert page.total == query_value("SELECT COUNT(*) FROM forensic_reports")


def test_examiners_are_assigned_active_investigators(app, db_available):
    with app.app_context():
        case_id = query_value("SELECT MIN(case_id) FROM cases")
        if case_id is None:
            pytest.skip("no cases yet")
        for examiner in exams.case_examiners(case_id):
            assert query_value("SELECT COUNT(*) FROM case_investigators WHERE case_id = %s AND user_id = %s",
                               (case_id, examiner["user_id"])) == 1


def test_creatable_cases_are_open(app, db_available):
    with app.app_context():
        for case in exams.creatable_cases(ADMIN, True) + reports.writable_cases(ADMIN, True):
            assert query_value("SELECT status FROM cases WHERE case_id = %s", (case["case_id"],)) != "Closed"
