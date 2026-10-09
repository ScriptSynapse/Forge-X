"""Run the YARA worker in a separate, restricted process (FORGE-X 2.0 Phase 7).

The web process never imports yara_x. Each validation or scan starts
app/yara/worker.py as a NEW Python process:

  * isolated mode (-I): ignores PYTHONPATH, PYTHON* variables and user site
    packages, so nothing can be injected into it;
  * a minimal environment: no database password, no secret key;
  * a temporary, empty working directory;
  * a hard wall-clock limit: killed after timeout + grace seconds even if
    YARA-X's own timeout didn't stop it. The WHOLE process tree is watched
    and killed: on Windows a venv's python.exe is a launcher whose child
    process does the actual work;
  * a memory limit: on POSIX the worker sets RLIMIT_AS itself; on every OS a
    psutil watchdog (when psutil is installed) kills it above the limit,
    measuring committed private memory on Windows (see memory_used());
  * stdout is capped, and anything unexpected becomes a failed result.
"""
import json
import os
import subprocess
import sys
import tempfile
import time

WORKER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker.py")
GRACE_SECONDS = 10
MAX_OUTPUT = 8 * 1024 * 1024

try:
    import psutil
except ImportError:                                          # optional, but recommended on Windows
    psutil = None


def memory_used(mem, windows=None):
    """Bytes to compare with the limit, from psutil's memory_info().

    Windows: committed private memory ("private bytes"; psutil `private`, or
    `pagefile`). The working set (`rss`) only counts pages touched recently,
    so a process can commit far more than its limit without raising it.
    Other systems: resident memory (`rss`); the virtual size would count the
    large address ranges YARA-X reserves but never uses.
    """
    windows = (os.name == "nt") if windows is None else windows
    if windows:
        return max(mem.rss, getattr(mem, "private", 0) or getattr(mem, "pagefile", 0) or 0)
    return mem.rss


def _tree(process):
    """The worker and every process it started. On Windows a venv's python.exe
    is a launcher that runs the real interpreter as a CHILD process, so the
    work (and the memory) is in the child, not in the process we started."""
    try:
        return [process] + process.children(recursive=True)
    except psutil.Error:
        return [process]


def _tree_memory(process):
    total = 0
    for member in _tree(process):
        try:
            total += memory_used(member.memory_info())
        except psutil.Error:
            pass
    return total


def _kill_tree(proc, watched):
    """Kill the worker and all its children, so nothing keeps running after a
    timeout or memory stop (children first, then the process we started)."""
    if watched is not None:
        for member in reversed(_tree(watched)):
            try:
                member.kill()
            except psutil.Error:
                pass
    elif os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
    proc.kill()
    proc.communicate()


def _minimal_env():
    env = {"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    if os.name == "nt":
        for key in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP"):  # needed by Python itself on Windows
            if os.environ.get(key):
                env[key] = os.environ[key]
        env["PATH"] = os.path.dirname(sys.executable)
    else:
        env["PATH"] = "/usr/bin:/bin"
    return env


def run_worker(request, timeout=60, memory_mb=512, script=WORKER):
    """Send one request to a fresh worker process. Always returns a dict with
    "ok"; failures carry "error_type" (unavailable, compile, file, scan,
    timeout, memory, crash, request) and a safe "error" message."""
    request = dict(request, timeout=timeout, memory_mb=memory_mb)
    started = time.monotonic()
    limits_note = None
    with tempfile.TemporaryDirectory(prefix="forgex-yara-") as workdir:
        proc = subprocess.Popen([sys.executable, "-I", script], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, cwd=workdir, env=_minimal_env())
        watched = psutil.Process(proc.pid) if psutil else None
        payload, out, err, killed = json.dumps(request).encode(), b"", b"", None
        deadline = started + timeout + GRACE_SECONDS
        while True:
            try:
                o, e = proc.communicate(input=payload, timeout=0.1)
                out, err = out + (o or b""), err + (e or b"")
                break
            except subprocess.TimeoutExpired:
                payload = None                                # already sent
            if time.monotonic() > deadline:
                killed = "timeout"
            elif watched is not None and _tree_memory(watched) > memory_mb * 1024 * 1024:
                killed = "memory"
            if killed:
                _kill_tree(proc, watched)
                break
        if watched is None and os.name == "nt":
            limits_note = "memory limit not enforced on Windows without psutil (pip install psutil)"
    duration_ms = int((time.monotonic() - started) * 1000)

    if killed == "timeout":
        return {"ok": False, "error_type": "timeout", "duration_ms": duration_ms,
                "error": f"Stopped after {timeout + GRACE_SECONDS} s: the scan exceeded its time limit."}
    if killed == "memory":
        return {"ok": False, "error_type": "memory", "duration_ms": duration_ms,
                "error": f"Stopped: the worker used more than {memory_mb} MB of memory."}
    if len(out) > MAX_OUTPUT:
        return {"ok": False, "error_type": "crash", "duration_ms": duration_ms, "error": "The worker's output was too large."}
    try:
        result = json.loads(out.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        # Typical on POSIX when RLIMIT_AS/CPU kills the process before it can answer.
        hint = "memory" if b"MemoryError" in err or proc.returncode in (-9, 137) else "crash"
        return {"ok": False, "error_type": hint, "duration_ms": duration_ms,
                "error": "The worker stopped without a result (exit code "
                         f"{proc.returncode}). It may have hit its memory or CPU limit."}
    result["duration_ms"] = duration_ms
    if limits_note:
        result["limits"] = limits_note
    return result
