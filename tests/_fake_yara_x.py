# Test double for yara_x used by tests/test_yara.py (follows the documented Python API).
"""A small stand-in for yara_x following its documented Python API (compile/scan
semantics simplified: a rule matches if every quoted text pattern occurs)."""
import re
class CompileError(Exception): pass
class ScanError(Exception): pass
class TimeoutError(Exception): pass
class _M:
    def __init__(self, o, l): self.offset, self.length = o, l
class _P:
    def __init__(self, ident, ms): self.identifier, self.matches = ident, tuple(ms)
class _R:
    def __init__(self, ns, ident, meta, tags, pats): self.namespace, self.identifier, self.metadata, self.tags, self.patterns = ns, ident, meta, tags, pats
class _Results:
    def __init__(self, rules): self.matching_rules = tuple(rules)
class Compiler:
    def __init__(self): self.ns, self.rules, self.includes = "default", [], True
    def enable_includes(self, flag): self.includes = flag
    def new_namespace(self, ns): self.ns = ns
    def add_source(self, src, origin=None):
        if "include" in src and not self.includes: raise CompileError("include statements are not allowed")
        found = re.findall(r'rule\s+(\w+)\s*(?::\s*([\w ]+))?\{(.*?)condition:', src, re.S)
        if not found or src.count("{") != src.count("}"): raise CompileError("syntax error: unexpected token")
        for name, tags, body in found:
            meta = re.findall(r'(\w+)\s*=\s*"([^"]*)"\s*$', body.split("strings:")[0], re.M)
            pats = re.findall(r'(\$\w+)\s*=\s*"([^"]*)"', body.split("strings:")[1] if "strings:" in body else "")
            self.rules.append((self.ns, name, tuple(meta), tuple(tags.split()), pats))
    def warnings(self): return [{"title": "slow pattern"}] if any(len(p[1]) < 3 for r in self.rules for p in r[4]) else []
    def build(self): return list(self.rules)
class Scanner:
    def __init__(self, rules): self.rules, self.timeout = rules, None
    def set_timeout(self, s): self.timeout = s
    def max_matches_per_pattern(self, n): self.cap = n
    def scan_file(self, path):
        data = open(path, "rb").read()
        if b"TRIGGER_TIMEOUT" in data: raise TimeoutError()
        out = []
        for ns, name, meta, tags, pats in self.rules:
            ps = [_P(i, [_M(m.start(), len(t)) for m in re.finditer(re.escape(t.encode()), data)]) for i, t in pats]
            if pats and all(p.matches for p in ps): out.append(_R(ns, name, meta, tags, ps))
        return _Results(out)
