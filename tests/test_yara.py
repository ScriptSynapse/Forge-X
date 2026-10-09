"""FORGE-X 2.0 Phase 7: the YARA worker, its isolation and limits, and scan recording (no MySQL).

Tests marked "real YARA-X" run only where `pip install yara-x` is done (skipped otherwise)."""
import contextlib
import datetime
import hashlib
import importlib.util
import json
import os
import pathlib
import textwrap

import pytest

from app.yara import runner

HERE = pathlib.Path(__file__).resolve().parent
WORKER = HERE.parent / "app" / "yara" / "worker.py"
try:
    import yara_x  # noqa: F401
    HAVE_YARA = True
except ImportError:
    HAVE_YARA = False
needs_yara = pytest.mark.skipif(not HAVE_YARA, reason="real YARA-X not installed (pip install yara-x)")

RULE = ('rule phishing_kit : phish {\n meta:\n  author = "FORGE-X test"\n strings:\n  $a = "leave-portal"\n'
        '  $b = "password"\n condition:\n  all of them\n}')


def _load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _script(tmp_path, code):
    path = tmp_path / "dummy_worker.py"
    path.write_text(textwrap.dedent(code), encoding="utf-8")
    return str(path)


# --- worker logic, against a test double that follows the documented yara_x API ----------
def test_worker_logic_with_the_documented_api(tmp_path):
    worker, yx = _load(WORKER, "forgex_worker"), _load(HERE / "_fake_yara_x.py", "fake_yara_x")
    assert worker.handle({"mode": "validate", "source": RULE}, yx)["ok"]
    assert worker.handle({"mode": "validate", "source": "rule broken {"}, yx)["error_type"] == "compile"
    assert worker.handle({"mode": "validate", "source": 'include "x.yar"\nrule y { condition: true }'}, yx)["ok"] is False
    data = b"..leave-portal.. password .. password"
    target = tmp_path / "evidence.bin"
    target.write_bytes(data)
    result = worker.handle({"mode": "scan", "path": str(target), "sources": {"r1v2": RULE}}, yx)
    assert result["ok"] and result["file_sha256"] == hashlib.sha256(data).hexdigest()
    match = result["matches"][0]
    assert (match["namespace"], match["identifier"]) == ("r1v2", "phishing_kit")
    assert [p["count"] for p in match["patterns"]] == [1, 2]
    assert worker.handle({"mode": "scan", "path": str(tmp_path / "missing"), "sources": {"r1v2": RULE}}, yx)["error_type"] == "file"


def test_worker_imports_nothing_from_the_app():
    source = WORKER.read_text(encoding="utf-8")
    assert "from app" not in source and "import app" not in source and "from .." not in source and "flask" not in source.lower().split('"""', 2)[2]


# --- isolation and limits, with real subprocesses -----------------------------------------
def test_worker_environment_has_no_secrets_and_ignores_pythonpath(tmp_path, monkeypatch):
    monkeypatch.setenv("MYSQL_PASSWORD", "never-leak")
    monkeypatch.setenv("FORGE_X_SECRET_KEY", "never-leak-either")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "injected"))
    result = runner.run_worker({}, timeout=10, script=_script(tmp_path, """
        import json, os, sys
        sys.stdin.read()
        print(json.dumps({"ok": True, "env": list(os.environ), "injected": any("injected" in p for p in sys.path)}))"""))
    assert result["ok"] and not {"MYSQL_PASSWORD", "FORGE_X_SECRET_KEY", "PYTHONPATH"} & set(result["env"])
    assert result["injected"] is False


def test_runaway_worker_is_killed(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "GRACE_SECONDS", 1)
    result = runner.run_worker({}, timeout=1, script=_script(tmp_path, "import sys, time\nsys.stdin.read()\ntime.sleep(60)\n"))
    assert result["error_type"] == "timeout" and result["duration_ms"] < 10_000


@pytest.mark.skipif(runner.psutil is None, reason="psutil not installed")
def test_memory_hungry_worker_is_killed(tmp_path):
    result = runner.run_worker({}, timeout=20, memory_mb=100, script=_script(
        tmp_path, "import sys, time\nsys.stdin.read()\nblob = bytearray(400 * 1024 * 1024)\ntime.sleep(30)\n"))
    assert result["error_type"] == "memory"


@pytest.mark.skipif(runner.psutil is None, reason="psutil not installed")
def test_limits_cover_child_processes_and_leave_no_orphans(tmp_path):
    """On Windows a venv's python.exe is a launcher: the real interpreter runs as
    its CHILD. Memory must be counted, and processes killed, across the tree."""
    child = tmp_path / "child.py"
    pid_file = tmp_path / "child.pid"
    child.write_text("import os, sys, time\nblob = bytearray(400 * 1024 * 1024)\n"
                     "open(sys.argv[1], 'w').write(str(os.getpid()))\ntime.sleep(60)\n", encoding="utf-8")
    launcher = _script(tmp_path, f"""
        import subprocess, sys
        sys.stdin.read()
        subprocess.run([sys.executable, {str(child)!r}, {str(pid_file)!r}])""")
    result = runner.run_worker({}, timeout=20, memory_mb=100, script=launcher)
    assert result["error_type"] == "memory"
    if pid_file.exists():
        import time
        time.sleep(0.5)
        pid = int(pid_file.read_text())
        assert not runner.psutil.pid_exists(pid) or runner.psutil.Process(pid).status() == runner.psutil.STATUS_ZOMBIE


def test_memory_is_measured_as_committed_memory_on_windows():
    """Windows commits memory without touching it, so the working set (rss) can
    stay small: the limit must use committed private memory instead."""
    from collections import namedtuple
    windows_mem = namedtuple("pmem", "rss vms private")(rss=20 << 20, vms=430 << 20, private=430 << 20)
    linux_mem = namedtuple("pmem", "rss vms")(rss=20 << 20, vms=4 << 30)       # large reserved, unused address space
    assert runner.memory_used(windows_mem, windows=True) == 430 << 20
    assert runner.memory_used(linux_mem, windows=False) == 20 << 20


def test_garbage_from_the_worker_is_a_failure(tmp_path):
    result = runner.run_worker({}, timeout=10, script=_script(tmp_path, "import sys\nsys.stdin.read()\nprint('not json')\n"))
    assert result["ok"] is False and result["error_type"] == "crash"


def test_real_worker_reports_its_state():
    result = runner.run_worker({"mode": "ping"}, timeout=20)
    if HAVE_YARA:
        assert result["ok"] and result["scanner_version"].startswith("yara-x")
    else:
        assert result["error_type"] == "unavailable" and "pip install yara-x" in result["error"]


# --- the real YARA-X, end to end through the isolated worker -------------------------------
@needs_yara
def test_real_yara_x_compiles_scans_and_refuses_includes(tmp_path):
    assert runner.run_worker({"mode": "validate", "source": RULE}, timeout=20)["ok"]
    assert runner.run_worker({"mode": "validate", "source": "rule broken {"}, timeout=20)["error_type"] == "compile"
    secret = tmp_path / "secret.yar"
    secret.write_text("rule leaked { condition: true }", encoding="utf-8")
    included = runner.run_worker({"mode": "validate", "source": f'include "{secret.as_posix()}"\nrule x {{ condition: true }}'},
                                 timeout=20)
    assert included["ok"] is False                                   # include directives are disabled
    data = b"login at leave-portal, enter password"
    target = tmp_path / "evidence.bin"
    target.write_bytes(data)
    result = runner.run_worker({"mode": "scan", "path": str(target), "sources": {"r1v1": RULE}}, timeout=20)
    assert result["ok"] and result["file_sha256"] == hashlib.sha256(data).hexdigest()
    patterns = {p["identifier"]: p["matches"][0] for p in result["matches"][0]["patterns"]}
    assert patterns["$a"]["offset"] == data.index(b"leave-portal") and patterns["$a"]["length"] == len("leave-portal")
    assert target.read_bytes() == data                               # the file is never modified


# --- what gets recorded --------------------------------------------------------------------
def test_scan_recording_rules(app, monkeypatch):
    from app.yara import services
    writes = []

    class Cursor:
        lastrowid = 41

        def execute(self, sql, params=()):
            writes.append((sql.split("(")[0].strip(), params))

    @contextlib.contextmanager
    def fake_transaction():
        yield Cursor()

    rules = [{"rule_id": 3, "name": "Kit", "version_id": 7, "version_no": 2, "source": RULE}]
    monkeypatch.setattr(services, "transaction", fake_transaction)
    monkeypatch.setattr(services, "query_value", lambda sql, params=(): datetime.datetime(2026, 10, 5))
    monkeypatch.setattr(services, "applicable_versions", lambda case_id: rules)
    class FakeStorage:                       # Phase 9: scans read the file via storage_for(file).materialize()
        @contextlib.contextmanager
        def materialize(self, object_id):
            yield "/x/" + object_id

    monkeypatch.setattr(services, "storage_for", lambda stored_file: FakeStorage())
    monkeypatch.setattr(services.audit, "record", lambda *a, **k: writes.append(("AUDIT", k.get("outcome"))))
    item = {"evidence_id": 1, "evidence_code": "FX-EV-2026-00001", "case_id": 1, "case_status": "Open"}
    stored = {"file_id": 2, "object_id": "o", "sha256": "a" * 64}
    user = {"user_id": 4, "roles": ["Evidence Custodian"]}

    def scan(result):
        writes.clear()
        monkeypatch.setattr(services.runner, "run_worker", lambda request, timeout, memory_mb: dict(result))
        with app.app_context():
            return services.run_scan(item, stored, user)

    scan({"ok": True, "file_sha256": "a" * 64, "matches": [{"namespace": "r3v2", "identifier": "kit", "patterns": []}]})
    row = next(p for s, p in writes if s == "INSERT INTO yara_scans")
    assert (row[2], row[5], row[7], row[10]) == ("Completed", True, 1, None)
    assert next(p for s, p in writes if s == "INSERT INTO yara_scan_rules") == (41, 7)
    scan({"ok": False, "error_type": "timeout", "error": "Stopped"})
    row = next(p for s, p in writes if s == "INSERT INTO yara_scans")
    assert (row[2], row[7], row[10]) == ("Timed out", 0, "Stopped")
    assert not any(s == "INSERT INTO yara_matches" for s, _ in writes)
    with pytest.raises(services.YaraError):
        scan({"ok": False, "error_type": "unavailable", "error": "YARA-X is not installed."})
    assert writes == []                                               # nothing ran, nothing recorded
