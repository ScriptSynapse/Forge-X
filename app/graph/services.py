"""Evidence relationship graph (FORGE-X 2.0 Phase 8).

Built ONLY from relationships stored in MySQL. Nothing is inferred or
suggested. Every link has one of three kinds, drawn differently:

  recorded  a link someone recorded: case-evidence, investigator-case,
            examination-evidence, report-examination, artifact-examination
  result    the outcome of an analysis that actually ran: a YARA match from the
            item's latest completed scan
  identity  an item has this SHA-256 (its current reference hash, or an
            artifact's hash). Items sharing a hash node have identical bytes;
            that says nothing about intent or maliciousness.

Every query is restricted to the user's visible cases (access.Scope), and
expanding a node re-checks that the node itself is visible. Graphs are capped
at MAX_NODES; the response says when it was truncated.
"""
import re

from flask import url_for

from ..db import query_all, query_one

MAX_NODES = 250
HASH_RE = re.compile(r"^[0-9a-f]{64}$")
NODE_TYPES = ("case", "evidence", "exam", "report", "user", "artifact", "hash", "rule")


class Graph:
    def __init__(self):
        self.nodes, self.edges, self.truncated = {}, {}, False

    def node(self, node_id, kind, label, sub="", url=None, **extra):
        if node_id in self.nodes:
            return True
        if len(self.nodes) >= MAX_NODES:
            self.truncated = True
            return False
        self.nodes[node_id] = {"id": node_id, "type": kind, "label": label, "sub": sub or "", "url": url, **extra}
        return True

    def edge(self, a, b, kind, label):
        if a in self.nodes and b in self.nodes and a != b:
            self.edges[(a, b, kind)] = {"source": a, "target": b, "kind": kind, "label": label}

    def as_dict(self):
        return {"nodes": list(self.nodes.values()), "edges": list(self.edges.values()), "truncated": self.truncated,
                "max_nodes": MAX_NODES}


def _in(values):
    return ", ".join(["%s"] * len(values))


# ---------------------------------------------------------------------------
# Node helpers (labels and links are only produced for visible records)
# ---------------------------------------------------------------------------
def _case_node(g, c):
    g.node(f"case:{c['case_id']}", "case", c["case_reference"], c["title"],
           url_for("cases.detail", reference=c["case_reference"]), status=c.get("status"))


def _evidence_node(g, e, case_reference=None):
    sub = e.get("description") or ""
    if case_reference:
        sub = f"{sub} · {case_reference}" if sub else case_reference
    return g.node(f"evidence:{e['evidence_id']}", "evidence", e["evidence_code"], sub,
                  url_for("evidence.detail", code=e["evidence_code"]), integrity=e.get("integrity_status"))


def _hash_node(g, value):
    return g.node(f"hash:{value}", "hash", value[:12] + "…", "SHA-256 " + value, None, value=value)


def _artifact_node(g, a):
    return g.node(f"artifact:{a['artifact_id']}", "artifact", f"Artifact #{a['artifact_id']}",
                  f"{a['artifact_type']}: {a['description']}",
                  url_for("examinations.detail", code=a["examination_code"], tab="artifacts") + f"#artifact-{a['artifact_id']}")


def _exam_node(g, x):
    return g.node(f"exam:{x['examination_id']}", "exam", x["examination_code"], f"{x['type_name']} · {x['status']}",
                  url_for("examinations.detail", code=x["examination_code"]))


def _report_node(g, r):
    return g.node(f"report:{r['report_id']}", "report", r["report_code"], f"{r['title']} · {r['status']}",
                  url_for("reports.detail", code=r["report_code"]))


def _rule_node(g, rule_id, name):
    return g.node(f"rule:{rule_id}", "rule", name, "YARA rule", url_for("yara.rule_detail", rule_id=rule_id))


# ---------------------------------------------------------------------------
# Shared building blocks
# ---------------------------------------------------------------------------
_EVIDENCE_COLUMNS = ("e.evidence_id, e.evidence_code, e.description, e.case_id, c.case_reference, "
                     "vi.integrity_status, vi.current_hash_value")
_EVIDENCE_FROM = ("FROM evidence e JOIN cases c ON c.case_id = e.case_id "
                  "JOIN v_evidence_integrity vi ON vi.evidence_id = e.evidence_id")
_ARTIFACT_SELECT = ("SELECT a.artifact_id, a.examination_id, a.evidence_id, a.artifact_type, a.description, a.sha256, "
                    "x.examination_code, x.case_id, c.case_reference FROM examination_artifacts a "
                    "JOIN examinations x ON x.examination_id = a.examination_id JOIN cases c ON c.case_id = x.case_id")
_LATEST_MATCHES = """
    SELECT s.evidence_id, s.scan_id, r.rule_id, r.name, m.rule_identifier
      FROM yara_scans s
      JOIN yara_matches m       ON m.scan_id = s.scan_id
      JOIN yara_rule_versions v ON v.version_id = m.version_id
      JOIN yara_rules r         ON r.rule_id = v.rule_id
     WHERE s.status = 'Completed'
       AND s.scan_id = (SELECT MAX(s2.scan_id) FROM yara_scans s2
                         WHERE s2.evidence_id = s.evidence_id AND s2.status = 'Completed')
"""


def _add_hash_links(g, scope, hashes, mode, exclude_case_id=None):
    """Hash nodes for the given values, linked to every VISIBLE item with that
    hash. mode "shared": only hashes held by 2+ visible items; "all": every hash."""
    if not hashes:
        return
    values = sorted(hashes)
    holders = {v: [] for v in values}
    for e in query_all(f"SELECT {_EVIDENCE_COLUMNS} {_EVIDENCE_FROM} WHERE vi.current_hash_value IN ({_in(values)})"
                       f"{scope.case_filter}", tuple(values) + scope.params):
        holders[e["current_hash_value"]].append(("evidence", e))
    for a in query_all(f"{_ARTIFACT_SELECT} WHERE a.sha256 IN ({_in(values)}){scope.case_filter}",
                       tuple(values) + scope.params):
        holders[a["sha256"]].append(("artifact", a))
    for value in values:
        items = holders[value]
        if mode == "shared" and len(items) < 2:
            continue
        if not _hash_node(g, value):
            return
        for kind, row in items:
            if kind == "evidence":
                outside = row["case_reference"] if row["case_id"] != exclude_case_id else None
                if _evidence_node(g, row, outside):
                    g.edge(f"evidence:{row['evidence_id']}", f"hash:{value}", "identity", "has SHA-256")
            else:
                if _artifact_node(g, row):
                    g.edge(f"artifact:{row['artifact_id']}", f"hash:{value}", "identity", "has SHA-256")


def _add_yara(g, evidence_ids):
    if not evidence_ids:
        return
    ids = sorted(evidence_ids)
    for m in query_all(_LATEST_MATCHES + f" AND s.evidence_id IN ({_in(ids)})", tuple(ids)):
        if _rule_node(g, m["rule_id"], m["name"]):
            g.edge(f"evidence:{m['evidence_id']}", f"rule:{m['rule_id']}", "result",
                   f"matched {m['rule_identifier']} (scan #{m['scan_id']})")


# ---------------------------------------------------------------------------
# Graphs
# ---------------------------------------------------------------------------
def visible_case(scope, reference):
    return query_one(f"SELECT c.case_id, c.case_reference, c.title, c.status FROM cases c "
                     f"WHERE c.case_reference = %s{scope.case_filter}", (reference,) + scope.params)


def visible_cases(scope):
    return query_all(f"SELECT c.case_reference, c.title FROM cases c WHERE 1 = 1{scope.case_filter} "
                     "ORDER BY c.case_reference DESC", scope.params)


def case_graph(scope, reference, hash_mode="shared", g=None):
    """Everything recorded about one visible case, plus items in OTHER visible
    cases that share a hash with it. Returns None if the case isn't visible."""
    case = visible_case(scope, reference)
    if case is None:
        return None
    g = g or Graph()
    cid, cnode = case["case_id"], f"case:{case['case_id']}"
    _case_node(g, case)
    for u in query_all("SELECT u.user_id, u.full_name, ci.is_lead FROM case_investigators ci "
                       "JOIN users u ON u.user_id = ci.user_id WHERE ci.case_id = %s ORDER BY ci.is_lead DESC, u.full_name",
                       (cid,)):
        if g.node(f"user:{u['user_id']}", "user", u["full_name"], "Lead investigator" if u["is_lead"] else "Investigator"):
            g.edge(f"user:{u['user_id']}", cnode, "recorded", "lead investigator" if u["is_lead"] else "assigned to")
    evidence = query_all(f"SELECT {_EVIDENCE_COLUMNS} {_EVIDENCE_FROM} WHERE e.case_id = %s ORDER BY e.evidence_code", (cid,))
    for e in evidence:
        if _evidence_node(g, e):
            g.edge(cnode, f"evidence:{e['evidence_id']}", "recorded", "contains")
    exams = query_all("SELECT x.examination_id, x.examination_code, x.status, t.type_name FROM examinations x "
                      "JOIN examination_types t ON t.examination_type_id = x.examination_type_id "
                      "WHERE x.case_id = %s ORDER BY x.examination_code", (cid,))
    for x in exams:
        if _exam_node(g, x):
            g.edge(cnode, f"exam:{x['examination_id']}", "recorded", "examination")
    for link in query_all("SELECT ee.examination_id, ee.evidence_id FROM examination_evidence ee "
                          "JOIN examinations x ON x.examination_id = ee.examination_id WHERE x.case_id = %s", (cid,)):
        g.edge(f"exam:{link['examination_id']}", f"evidence:{link['evidence_id']}", "recorded", "examined")
    for r in query_all("SELECT report_id, report_code, title, status FROM forensic_reports WHERE case_id = %s "
                       "ORDER BY report_code", (cid,)):
        if _report_node(g, r):
            g.edge(cnode, f"report:{r['report_id']}", "recorded", "report")
    for link in query_all("SELECT re.report_id, re.examination_id FROM report_examinations re "
                          "JOIN forensic_reports r ON r.report_id = re.report_id WHERE r.case_id = %s", (cid,)):
        g.edge(f"report:{link['report_id']}", f"exam:{link['examination_id']}", "recorded", "cites")
    artifacts = query_all(f"{_ARTIFACT_SELECT} WHERE x.case_id = %s ORDER BY a.artifact_id", (cid,))
    for a in artifacts:
        if _artifact_node(g, a):
            g.edge(f"exam:{a['examination_id']}", f"artifact:{a['artifact_id']}", "recorded", "found artifact")
            if a["evidence_id"]:
                g.edge(f"artifact:{a['artifact_id']}", f"evidence:{a['evidence_id']}", "recorded", "found in")
    _add_yara(g, {e["evidence_id"] for e in evidence})
    hashes = {e["current_hash_value"] for e in evidence if e["current_hash_value"]} | \
             {a["sha256"] for a in artifacts if a["sha256"]}
    _add_hash_links(g, scope, hashes, hash_mode, exclude_case_id=cid)
    return g


def expand(scope, node_id, hash_mode="shared"):
    """The neighbours of one node, if the node is visible to this user. Returns
    a Graph, or None when the node doesn't exist or isn't visible."""
    kind, _, key = (node_id or "").partition(":")
    g = Graph()
    if kind == "case" and key.isdigit():
        found = query_one(f"SELECT c.case_reference FROM cases c WHERE c.case_id = %s{scope.case_filter}",
                          (int(key),) + scope.params)
        return case_graph(scope, found["case_reference"], hash_mode, g) if found else None

    if kind == "evidence" and key.isdigit():
        e = query_one(f"SELECT {_EVIDENCE_COLUMNS}, c.title, c.status {_EVIDENCE_FROM} WHERE e.evidence_id = %s"
                      f"{scope.case_filter}", (int(key),) + scope.params)
        if e is None:
            return None
        _evidence_node(g, e)
        _case_node(g, {"case_id": e["case_id"], "case_reference": e["case_reference"], "title": e["title"],
                       "status": e["status"]})
        g.edge(f"case:{e['case_id']}", node_id, "recorded", "contains")
        for x in query_all("SELECT x.examination_id, x.examination_code, x.status, t.type_name FROM examination_evidence ee "
                           "JOIN examinations x ON x.examination_id = ee.examination_id "
                           "JOIN examination_types t ON t.examination_type_id = x.examination_type_id "
                           "WHERE ee.evidence_id = %s", (e["evidence_id"],)):
            if _exam_node(g, x):
                g.edge(f"exam:{x['examination_id']}", node_id, "recorded", "examined")
        for a in query_all(f"{_ARTIFACT_SELECT} WHERE a.evidence_id = %s", (e["evidence_id"],)):
            if _artifact_node(g, a):
                g.edge(f"artifact:{a['artifact_id']}", node_id, "recorded", "found in")
        _add_yara(g, {e["evidence_id"]})
        if e["current_hash_value"]:
            _add_hash_links(g, scope, {e["current_hash_value"]}, "all")
        return g

    if kind == "hash" and HASH_RE.match(key):
        _add_hash_links(g, scope, {key}, "all")
        return g if g.nodes else None

    if kind == "rule" and key.isdigit():
        rule = query_one("SELECT rule_id, name FROM yara_rules WHERE rule_id = %s", (int(key),))
        if rule is None:
            return None
        _rule_node(g, rule["rule_id"], rule["name"])
        for m in query_all(f"SELECT m2.*, {_EVIDENCE_COLUMNS} FROM ({_LATEST_MATCHES}) m2 "
                           f"JOIN evidence e ON e.evidence_id = m2.evidence_id JOIN cases c ON c.case_id = e.case_id "
                           f"JOIN v_evidence_integrity vi ON vi.evidence_id = e.evidence_id "
                           f"WHERE m2.rule_id = %s{scope.case_filter}", (rule["rule_id"],) + scope.params):
            if _evidence_node(g, m, m["case_reference"]):
                g.edge(f"evidence:{m['evidence_id']}", node_id, "result",
                       f"matched {m['rule_identifier']} (scan #{m['scan_id']})")
        return g

    if kind == "user" and key.isdigit():
        user = query_one("SELECT user_id, full_name FROM users WHERE user_id = %s", (int(key),))
        if user is None:
            return None
        cases = query_all(f"SELECT c.case_id, c.case_reference, c.title, c.status, ci.is_lead FROM case_investigators ci "
                          f"JOIN cases c ON c.case_id = ci.case_id WHERE ci.user_id = %s{scope.case_filter}",
                          (user["user_id"],) + scope.params)
        if not cases and not scope.lab_wide:
            return None                       # an investigator learns nothing about people outside their cases
        g.node(node_id, "user", user["full_name"], "Investigator")
        for c in cases:
            _case_node(g, c)
            g.edge(node_id, f"case:{c['case_id']}", "recorded", "lead investigator" if c["is_lead"] else "assigned to")
        return g

    if kind == "exam" and key.isdigit():
        x = query_one(f"SELECT x.examination_id, x.examination_code, x.status, t.type_name, c.case_id, c.case_reference, "
                      f"c.title, c.status AS case_status FROM examinations x "
                      f"JOIN examination_types t ON t.examination_type_id = x.examination_type_id "
                      f"JOIN cases c ON c.case_id = x.case_id WHERE x.examination_id = %s{scope.case_filter}",
                      (int(key),) + scope.params)
        if x is None:
            return None
        _exam_node(g, x)
        _case_node(g, {"case_id": x["case_id"], "case_reference": x["case_reference"], "title": x["title"],
                       "status": x["case_status"]})
        g.edge(f"case:{x['case_id']}", node_id, "recorded", "examination")
        for e in query_all(f"SELECT {_EVIDENCE_COLUMNS} {_EVIDENCE_FROM} JOIN examination_evidence ee "
                           "ON ee.evidence_id = e.evidence_id WHERE ee.examination_id = %s", (x["examination_id"],)):
            if _evidence_node(g, e):
                g.edge(node_id, f"evidence:{e['evidence_id']}", "recorded", "examined")
        for r in query_all("SELECT r.report_id, r.report_code, r.title, r.status FROM report_examinations re "
                           "JOIN forensic_reports r ON r.report_id = re.report_id WHERE re.examination_id = %s",
                           (x["examination_id"],)):
            if _report_node(g, r):
                g.edge(f"report:{r['report_id']}", node_id, "recorded", "cites")
        for a in query_all(f"{_ARTIFACT_SELECT} WHERE a.examination_id = %s", (x["examination_id"],)):
            if _artifact_node(g, a):
                g.edge(node_id, f"artifact:{a['artifact_id']}", "recorded", "found artifact")
        return g

    if kind == "report" and key.isdigit():
        r = query_one(f"SELECT r.report_id, r.report_code, r.title, r.status, c.case_id, c.case_reference, "
                      f"c.title AS case_title, c.status AS case_status FROM forensic_reports r "
                      f"JOIN cases c ON c.case_id = r.case_id WHERE r.report_id = %s{scope.case_filter}",
                      (int(key),) + scope.params)
        if r is None:
            return None
        _report_node(g, r)
        _case_node(g, {"case_id": r["case_id"], "case_reference": r["case_reference"], "title": r["case_title"],
                       "status": r["case_status"]})
        g.edge(f"case:{r['case_id']}", node_id, "recorded", "report")
        for x in query_all("SELECT x.examination_id, x.examination_code, x.status, t.type_name FROM report_examinations re "
                           "JOIN examinations x ON x.examination_id = re.examination_id "
                           "JOIN examination_types t ON t.examination_type_id = x.examination_type_id "
                           "WHERE re.report_id = %s", (r["report_id"],)):
            if _exam_node(g, x):
                g.edge(node_id, f"exam:{x['examination_id']}", "recorded", "cites")
        return g

    if kind == "artifact" and key.isdigit():
        a = query_one(f"{_ARTIFACT_SELECT} WHERE a.artifact_id = %s{scope.case_filter}", (int(key),) + scope.params)
        if a is None:
            return None
        _artifact_node(g, a)
        x = query_one("SELECT x.examination_id, x.examination_code, x.status, t.type_name FROM examinations x "
                      "JOIN examination_types t ON t.examination_type_id = x.examination_type_id WHERE x.examination_id = %s",
                      (a["examination_id"],))
        _exam_node(g, x)
        g.edge(f"exam:{x['examination_id']}", node_id, "recorded", "found artifact")
        if a["evidence_id"]:
            e = query_one(f"SELECT {_EVIDENCE_COLUMNS} {_EVIDENCE_FROM} WHERE e.evidence_id = %s", (a["evidence_id"],))
            if _evidence_node(g, e):
                g.edge(node_id, f"evidence:{e['evidence_id']}", "recorded", "found in")
        if a["sha256"]:
            _add_hash_links(g, scope, {a["sha256"]}, "all")
        return g
    return None
