"""FORGE-X YARA worker: compiles rules and scans ONE stored evidence file.

Run only by app/yara/runner.py, as a separate process:
    python -I app/yara/worker.py        (request as JSON on stdin, result as JSON on stdout)

Isolation (why this is a separate script, not part of the app package):
  * It imports only the standard library and yara_x: never Flask, the
    database layer or .env, so the process holds no database password or
    secret key. The runner also starts it with a minimal environment.
  * Rules may be untrusted, so `include` directives are disabled (a rule
    could otherwise read arbitrary files from disk).
  * The evidence file is opened read-only; nothing is ever written.
  * Limits: YARA-X's own scan timeout; on POSIX also CPU and address-space
    limits set here; on every OS the runner kills the process if it runs
    too long or (with psutil) uses too much memory.
"""
import hashlib
import json
import sys

MAX_MATCHES_PER_PATTERN = 20      # offsets recorded per pattern (the scanner itself is capped too)
MAX_MATCHING_RULES = 200


def _limit_resources(timeout, memory_mb):
    try:
        import resource                                   # POSIX only
    except ImportError:
        return "memory limited by the runner's watchdog"
    limit = memory_mb * 1024 * 1024
    resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    cpu = int(timeout) + 5
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
    return f"OS limits: {memory_mb} MB address space, {cpu} s CPU"


def _sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:                           # read-only
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _compiler(yx):
    compiler = yx.Compiler()
    compiler.enable_includes(False)                       # untrusted rules must not read other files
    return compiler


def handle(request, yx, version="unknown"):
    """Pure request handler (testable without a subprocess or real YARA-X)."""
    mode = request.get("mode")
    if mode == "ping":
        return {"ok": True, "scanner_version": version}

    if mode == "validate":
        compiler = _compiler(yx)
        try:
            compiler.add_source(request["source"], origin="rule")
            compiler.build()
        except yx.CompileError as err:
            return {"ok": False, "error_type": "compile", "error": str(err)[:2000]}
        warnings = []
        try:
            warnings = [w.get("title", str(w)) for w in compiler.warnings()][:20]
        except Exception:                                  # warnings are informative only
            pass
        return {"ok": True, "scanner_version": version, "warnings": warnings}

    if mode == "scan":
        compiler = _compiler(yx)
        try:
            for namespace, source in request["sources"].items():
                compiler.new_namespace(namespace)
                compiler.add_source(source, origin=namespace)
            rules = compiler.build()
        except yx.CompileError as err:
            return {"ok": False, "error_type": "compile", "error": str(err)[:2000], "scanner_version": version}
        try:
            file_sha256 = _sha256(request["path"])
        except OSError as err:
            return {"ok": False, "error_type": "file", "error": f"Stored file couldn't be read: {err.strerror}",
                    "scanner_version": version}
        scanner = yx.Scanner(rules)
        scanner.set_timeout(int(request.get("timeout", 60)))
        try:
            scanner.max_matches_per_pattern(1000)
        except AttributeError:
            pass
        try:
            results = scanner.scan_file(request["path"])
        except yx.TimeoutError:
            return {"ok": False, "error_type": "timeout", "error": "The scan reached its time limit.",
                    "scanner_version": version, "file_sha256": file_sha256}
        except yx.ScanError as err:
            return {"ok": False, "error_type": "scan", "error": str(err)[:2000], "scanner_version": version,
                    "file_sha256": file_sha256}
        matches = []
        for rule in list(results.matching_rules)[:MAX_MATCHING_RULES]:
            patterns = []
            for pattern in getattr(rule, "patterns", ()):
                found = [{"offset": m.offset, "length": m.length} for m in list(pattern.matches)[:MAX_MATCHES_PER_PATTERN]]
                if found:
                    patterns.append({"identifier": pattern.identifier, "count": len(pattern.matches), "matches": found})
            matches.append({"namespace": rule.namespace, "identifier": rule.identifier,
                            "tags": [str(t) for t in getattr(rule, "tags", ())],
                            "metadata": [[str(k), str(v)] for k, v in getattr(rule, "metadata", ())],
                            "patterns": patterns})
        return {"ok": True, "scanner_version": version, "file_sha256": file_sha256, "matches": matches}

    return {"ok": False, "error_type": "request", "error": f"Unknown mode {mode!r}"}


def main():
    try:
        request = json.loads(sys.stdin.read())
    except ValueError:
        print(json.dumps({"ok": False, "error_type": "request", "error": "Invalid request"}))
        return
    limits = _limit_resources(request.get("timeout", 60), request.get("memory_mb", 512))
    try:
        import yara_x
        try:
            from importlib.metadata import version as _v
            version = "yara-x " + _v("yara-x")
        except Exception:
            version = "yara-x"
    except ImportError:
        print(json.dumps({"ok": False, "error_type": "unavailable",
                          "error": "YARA-X is not installed. Run: pip install yara-x"}))
        return
    try:
        result = handle(request, yara_x, version)
    except MemoryError:
        result = {"ok": False, "error_type": "memory", "error": "The worker ran out of its memory allowance."}
    result["limits"] = limits
    print(json.dumps(result))


if __name__ == "__main__":
    main()
