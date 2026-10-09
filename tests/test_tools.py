"""FORGE-X 2.0 Phase 6: the test-database builder and the stability report tool (no MySQL)."""
import importlib.util
import pathlib

import pytest

TOOLS = pathlib.Path(__file__).resolve().parent.parent / "tools"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_test_database_builder_never_targets_the_real_database():
    builder = _load("build_test_database")
    for bad in ("forge_x_db", "Robert'); DROP", ""):
        with pytest.raises(SystemExit):
            builder.build(bad)
    path, grants = builder.build("forge_x_test")
    sql = path.read_text(encoding="utf-8")
    assert "forge_x_db" not in sql and "forge_x_test" in sql and grants > 20


def test_stability_report_refuses_write_tests_on_the_real_database(monkeypatch):
    report = _load("stability_report")
    monkeypatch.setenv("MYSQL_DATABASE", "forge_x_db")
    monkeypatch.setattr("sys.argv", ["stability_report.py", "--with-write-tests"])
    with pytest.raises(SystemExit, match="Refusing"):
        report.main()


def test_stability_report_parses_results_and_maps_checklists(tmp_path):
    report = _load("stability_report")
    xml = tmp_path / "results.xml"
    xml.write_text('<testsuites><testsuite name="pytest">'
                   '<testcase classname="tests.test_security" name="test_every_non_public_route_requires_login"/>'
                   '<testcase classname="tests.test_auth_db" name="test_logout_invalidates_a_copied_session_cookie">'
                   '<skipped message="Skipped: set FORGE_X_DB_WRITE_TESTS=1"/></testcase>'
                   '<testcase classname="tests.test_data_consistency_db" name="test_code_counters_never_fall_behind">'
                   '<failure message="counter behind">trace</failure></testcase>'
                   '</testsuite></testsuites>', encoding="utf-8")
    tests = report.parse_junit(str(xml))
    assert [t["outcome"] for t in tests] == ["passed", "skipped", "failed"]
    assert report.area_of("test_data_consistency_db") == "Database structure and consistency"
    assert report.status_for(tests, ["test_every_non_public_route_requires_login"])[0].startswith("✅")
    assert report.status_for(tests, ["test_logout_invalidates"])[0].startswith("⏭")
    assert report.status_for(tests, ["test_code_counters"])[0].startswith("❌")
    assert report.status_for(tests, ["test_that_does_not_exist"])[0].startswith("⚪")
