"""FORGE-X 2.0 Phase 8: relationship graph rules, query safety and the browser logic (no MySQL)."""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

from app.access import Scope
from app.graph import services as gs

ROOT = pathlib.Path(__file__).resolve().parent.parent
GRAPH_JS = ROOT / "app" / "static" / "js" / "graph.js"


def test_graph_caps_nodes_and_keeps_links_consistent():
    g = gs.Graph()
    for i in range(gs.MAX_NODES + 5):
        g.node(f"evidence:{i}", "evidence", f"E{i}")
    assert len(g.nodes) == gs.MAX_NODES and g.truncated
    g.edge("evidence:1", "evidence:2", "recorded", "x")
    g.edge("evidence:1", "evidence:2", "recorded", "x")            # duplicate
    g.edge("evidence:1", "evidence:99999", "recorded", "x")        # unknown node
    g.edge("evidence:1", "evidence:1", "recorded", "x")            # self-link
    assert len(g.edges) == 1


@pytest.mark.parametrize("node", ["", "nope", "case:x", "evidence:1;DROP", "hash:zz", "hash:" + "A" * 64, "rule:-1"])
def test_malformed_node_ids_are_refused_without_queries(node, monkeypatch):
    def fail(*a, **k):
        raise AssertionError("a malformed node id must not reach the database")
    monkeypatch.setattr(gs, "query_one", fail)
    monkeypatch.setattr(gs, "query_all", fail)
    assert gs.expand(Scope({"user_id": 1, "roles": ["Administrator"]}), node) is None


def test_every_graph_query_has_matching_parameters_and_is_scoped(app, monkeypatch):
    captured = []
    row = {"case_id": 2, "case_reference": "FX-2026-0002", "title": "T", "status": "Open", "rule_id": 3, "name": "Kit",
           "user_id": 4, "full_name": "U", "artifact_id": 1, "examination_id": 3, "evidence_id": 51, "artifact_type": "File",
           "description": "d", "sha256": "a" * 64, "examination_code": "EX-2026-0001", "type_name": "T", "case_status": "Open",
           "report_id": 1, "report_code": "RP-2026-0001", "case_title": "T", "evidence_code": "FX-EV-2026-00051",
           "integrity_status": "Verified", "current_hash_value": "a" * 64, "rule_identifier": "kit", "scan_id": 41}
    monkeypatch.setattr(gs, "query_one", lambda sql, p=(): captured.append((sql, p)) or dict(row))
    monkeypatch.setattr(gs, "query_all", lambda sql, p=(): captured.append((sql, p)) or [dict(row, is_lead=1)])
    investigator = Scope({"user_id": 7, "roles": ["Investigator"]})
    with app.test_request_context():
        gs.case_graph(investigator, "FX-2026-0002", "all")
        for node in ("case:2", "evidence:51", "hash:" + "a" * 64, "rule:3", "user:4", "exam:3", "report:1", "artifact:1"):
            gs.expand(investigator, node)
    for sql, params in captured:
        assert sql.count("%s") == len(params) and not re.search(r"%(?!s)", sql), sql[:120]
    # Anything that looks across cases (hash holders, rule matches, a person's cases) carries the case scope.
    for sql, _ in captured:
        if "IN (" in sql and ("current_hash_value" in sql or "a.sha256" in sql):
            assert "ci.user_id" in sql, sql[:120]


def test_template_and_script_agree():
    template = (ROOT / "app" / "templates" / "graph" / "index.html").read_text(encoding="utf-8")
    script = GRAPH_JS.read_text(encoding="utf-8")
    for element_id in re.findall(r'getElementById\("([^"]+)"\)', script):
        assert f'id="{element_id}"' in template, element_id
    assert "innerHTML" not in script.split("*/", 1)[1] and "eval(" not in script      # record text only via textContent


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js not installed")
def test_layout_and_merge_logic_in_node(tmp_path):
    test = tmp_path / "graph_test.js"
    test.write_text(f"""
const g = require({json.dumps(str(GRAPH_JS))});
const assert = require("assert");
function sample(n) {{
  const nodes = [{{id: "case:1", type: "case", label: "C"}}], edges = [];
  for (let i = 1; i <= n; i++) {{ nodes.push({{id: "evidence:" + i, type: "evidence", label: "E" + i}});
    edges.push({{source: "case:1", target: "evidence:" + i, kind: "recorded", label: "contains"}}); }}
  return {{nodes, edges}};
}}
const a = {{nodes: {{}}, edges: {{}}}}, b = {{nodes: {{}}, edges: {{}}}};
g.merge(a, sample(10)); g.layout(a); g.merge(b, sample(10)); g.layout(b);
assert.deepStrictEqual(Object.values(a.nodes).map(n => [n.x, n.y]), Object.values(b.nodes).map(n => [n.x, n.y]));
const before = JSON.stringify(Object.values(a.nodes).map(n => [n.x, n.y]));
const added = g.merge(a, {{nodes: [{{id: "exam:1", type: "exam", label: "X"}}, {{id: "case:1", type: "case", label: "dup"}}],
                          edges: [{{source: "exam:1", target: "evidence:1", kind: "recorded", label: "examined"}}]}});
assert.deepStrictEqual(added, ["exam:1"]);
g.layout(a, added);
assert.strictEqual(JSON.stringify(Object.values(a.nodes).filter(n => n.id !== "exam:1").map(n => [n.x, n.y])), before);
const pts = Object.values(a.nodes);
for (let i = 0; i < pts.length; i++) for (let j = i + 1; j < pts.length; j++)
  assert.ok(Math.hypot(pts[i].x - pts[j].x, pts[i].y - pts[j].y) > 20, "nodes overlap");
console.log("ok");
""", encoding="utf-8")
    result = subprocess.run(["node", str(test)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0 and "ok" in result.stdout, result.stderr
