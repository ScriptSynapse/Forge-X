/* FORGE-X relationship graph (FORGE-X 2.0 Phase 8).
 *
 * Dependency-free SVG graph. Works under the strict Content-Security-Policy:
 * no inline styles or handlers, and record text is always inserted with
 * textContent (never innerHTML). Two parts:
 *   1. pure logic (merge, deterministic force layout), exported for Node tests
 *   2. the browser UI (render, zoom/pan, select, expand, filter, search, list)
 */
(function (root) {
  "use strict";

  // ---------------------------------------------------------------- pure logic
  function rng(seed) {                       // small deterministic generator (mulberry32)
    var a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      var t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function hashString(s) {
    var h = 2166136261;
    for (var i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }

  function edgeKey(e) { return e.source + "|" + e.target + "|" + e.kind; }

  /* Merge a server response into the state. Returns the ids of new nodes. */
  function merge(state, data) {
    var added = [];
    (data.nodes || []).forEach(function (n) {
      if (!state.nodes[n.id]) { state.nodes[n.id] = Object.assign({}, n); added.push(n.id); }
    });
    (data.edges || []).forEach(function (e) {
      if (state.nodes[e.source] && state.nodes[e.target]) state.edges[edgeKey(e)] = Object.assign({}, e);
    });
    state.truncated = state.truncated || !!data.truncated;
    return added;
  }

  /* Force-directed layout (Fruchterman-Reingold). Only nodes in `movable`
   * move; existing nodes keep their places so expanding doesn't reshuffle the
   * picture. New nodes start next to an already-placed neighbour.
   * Deterministic: the same data always gives the same layout. */
  function layout(state, movable, options) {
    options = options || {};
    var ids = Object.keys(state.nodes).sort();
    var move = {};
    (movable || ids).forEach(function (id) { move[id] = true; });
    var edges = Object.keys(state.edges).map(function (k) { return state.edges[k]; });
    var neighbours = {};
    edges.forEach(function (e) {
      (neighbours[e.source] = neighbours[e.source] || []).push(e.target);
      (neighbours[e.target] = neighbours[e.target] || []).push(e.source);
    });
    var size = options.size || Math.max(600, Math.sqrt(ids.length) * 170);
    ids.forEach(function (id) {
      var n = state.nodes[id];
      if (typeof n.x === "number" && !(options.reset && move[id])) return;
      var r = rng(hashString(id));
      var anchor = (neighbours[id] || []).map(function (o) { return state.nodes[o]; })
        .filter(function (o) { return o && typeof o.x === "number"; })[0];
      var cx = anchor ? anchor.x : 0, cy = anchor ? anchor.y : 0, spread = anchor ? 90 : size / 2;
      n.x = cx + (r() - 0.5) * spread;
      n.y = cy + (r() - 0.5) * spread;
    });
    var k = Math.sqrt((size * size) / Math.max(ids.length, 1)) * 0.75;
    var iterations = options.iterations || 220;
    var temperature = size / 8;
    for (var it = 0; it < iterations; it++) {
      var disp = {};
      ids.forEach(function (id) { disp[id] = { x: 0, y: 0 }; });
      for (var i = 0; i < ids.length; i++) {
        for (var j = i + 1; j < ids.length; j++) {
          var a = state.nodes[ids[i]], b = state.nodes[ids[j]];
          var dx = a.x - b.x, dy = a.y - b.y;
          var d = Math.sqrt(dx * dx + dy * dy) || 0.01;
          var f = (k * k) / d;
          disp[ids[i]].x += (dx / d) * f; disp[ids[i]].y += (dy / d) * f;
          disp[ids[j]].x -= (dx / d) * f; disp[ids[j]].y -= (dy / d) * f;
        }
      }
      edges.forEach(function (e) {
        var a = state.nodes[e.source], b = state.nodes[e.target];
        var dx = a.x - b.x, dy = a.y - b.y;
        var d = Math.sqrt(dx * dx + dy * dy) || 0.01;
        var f = (d * d) / k;
        disp[e.source].x -= (dx / d) * f; disp[e.source].y -= (dy / d) * f;
        disp[e.target].x += (dx / d) * f; disp[e.target].y += (dy / d) * f;
      });
      ids.forEach(function (id) {
        if (!move[id]) return;
        var n = state.nodes[id], d = disp[id];
        var len = Math.sqrt(d.x * d.x + d.y * d.y) || 0.01;
        n.x += (d.x / len) * Math.min(len, temperature);
        n.y += (d.y / len) * Math.min(len, temperature);
      });
      temperature *= 0.97;
    }
    return state;
  }

  function bounds(state, visible) {
    var xs = [], ys = [];
    Object.keys(state.nodes).forEach(function (id) {
      if (visible && !visible(id)) return;
      xs.push(state.nodes[id].x); ys.push(state.nodes[id].y);
    });
    if (!xs.length) return { x: -100, y: -100, w: 200, h: 200 };
    var minX = Math.min.apply(null, xs), maxX = Math.max.apply(null, xs);
    var minY = Math.min.apply(null, ys), maxY = Math.max.apply(null, ys);
    return { x: minX - 80, y: minY - 60, w: (maxX - minX) + 160, h: (maxY - minY) + 120 };
  }

  var logic = { merge: merge, layout: layout, bounds: bounds, edgeKey: edgeKey };
  if (typeof module !== "undefined" && module.exports) { module.exports = logic; return; }
  root.FxGraphLogic = logic;

  // ---------------------------------------------------------------- browser UI
  var SVG = "http://www.w3.org/2000/svg";
  var TYPE_LABEL = { "case": "Case", evidence: "Evidence", exam: "Examination", report: "Report", user: "Investigator",
                     artifact: "Artifact", hash: "SHA-256", rule: "YARA rule" };
  var RADIUS = { "case": 20, evidence: 14, exam: 13, report: 13, user: 12, artifact: 10, hash: 9, rule: 12 };

  function el(name, attrs, parent) {
    var node = document.createElementNS(SVG, name);
    Object.keys(attrs || {}).forEach(function (k) { node.setAttribute(k, attrs[k]); });
    if (parent) parent.appendChild(node);
    return node;
  }

  function html(tag, cls, text, parent) {
    var node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined && text !== null) node.textContent = text;
    if (parent) parent.appendChild(node);
    return node;
  }

  function start(container) {
    var svg = container.querySelector("svg.fx-graph-canvas");
    var viewport = el("g", { "class": "fx-graph-viewport" }, svg);
    var edgeLayer = el("g", { "class": "fx-graph-edges" }, viewport);
    var nodeLayer = el("g", { "class": "fx-graph-nodes" }, viewport);
    var panel = document.getElementById("fx-graph-panel");
    var status = document.getElementById("fx-graph-status");
    var listBody = document.getElementById("fx-graph-list-body");
    var search = document.getElementById("fx-graph-search");
    var hashMode = container.getAttribute("data-hash-mode");
    var state = { nodes: {}, edges: {}, truncated: false };
    var view = { x: 0, y: 0, scale: 1 };
    var hiddenTypes = {}, hiddenKinds = {};
    var selected = null;

    function say(message) { status.textContent = message; }

    function visible(id) {
      var n = state.nodes[id];
      return n && !hiddenTypes[n.type];
    }

    function apply() { viewport.setAttribute("transform", "translate(" + view.x + "," + view.y + ") scale(" + view.scale + ")"); }

    function fit() {
      var rect = svg.getBoundingClientRect(), b = bounds(state, visible);
      view.scale = Math.max(0.2, Math.min(2, Math.min(rect.width / b.w, rect.height / b.h)));
      view.x = rect.width / 2 - (b.x + b.w / 2) * view.scale;
      view.y = rect.height / 2 - (b.y + b.h / 2) * view.scale;
      apply();
    }

    function zoom(factor, cx, cy) {
      var rect = svg.getBoundingClientRect();
      if (cx === undefined) { cx = rect.width / 2; cy = rect.height / 2; }
      var next = Math.max(0.15, Math.min(4, view.scale * factor));
      view.x = cx - (cx - view.x) * (next / view.scale);
      view.y = cy - (cy - view.y) * (next / view.scale);
      view.scale = next;
      apply();
    }

    function draw() {
      while (edgeLayer.firstChild) edgeLayer.removeChild(edgeLayer.firstChild);
      while (nodeLayer.firstChild) nodeLayer.removeChild(nodeLayer.firstChild);
      Object.keys(state.edges).forEach(function (key) {
        var e = state.edges[key];
        if (!visible(e.source) || !visible(e.target) || hiddenKinds[e.kind]) return;
        var a = state.nodes[e.source], b = state.nodes[e.target];
        var line = el("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, "class": "fx-edge k-" + e.kind }, edgeLayer);
        el("title", {}, line).textContent = a.label + " — " + e.label + " — " + b.label;
      });
      Object.keys(state.nodes).sort().forEach(function (id) {
        if (!visible(id)) return;
        var n = state.nodes[id];
        var group = el("g", { "class": "fx-node t-" + n.type + (id === selected ? " is-selected" : ""),
                              transform: "translate(" + n.x + "," + n.y + ")", tabindex: "0", role: "button",
                              "aria-label": TYPE_LABEL[n.type] + " " + n.label, "data-id": id }, nodeLayer);
        el("circle", { r: RADIUS[n.type] || 12 }, group);
        el("text", { y: (RADIUS[n.type] || 12) + 14, "text-anchor": "middle" }, group).textContent = n.label;
        if (n.integrity === "Failed") el("circle", { r: 5, cx: 10, cy: -10, "class": "fx-node-alert" }, group);
      });
      highlight();
      renderList();
      var shown = Object.keys(state.nodes).filter(visible).length;
      say(shown + " nodes, " + edgeLayer.childNodes.length + " links shown" +
          (state.truncated ? ". The graph reached its limit; some records are not shown. Use filters or expand single nodes." : "."));
    }

    function highlight() {
      var term = (search.value || "").trim().toLowerCase();
      Array.prototype.forEach.call(nodeLayer.childNodes, function (g) {
        var n = state.nodes[g.getAttribute("data-id")];
        var match = term && (n.label + " " + n.sub).toLowerCase().indexOf(term) >= 0;
        g.classList.toggle("is-match", !!match);
        g.classList.toggle("is-dimmed", !!term && !match);
      });
    }

    function renderList() {
      while (listBody.firstChild) listBody.removeChild(listBody.firstChild);
      Object.keys(state.edges).sort().forEach(function (key) {
        var e = state.edges[key];
        if (!visible(e.source) || !visible(e.target) || hiddenKinds[e.kind]) return;
        var row = html("tr", null, null, listBody);
        html("td", null, TYPE_LABEL[state.nodes[e.source].type] + " " + state.nodes[e.source].label, row);
        html("td", null, e.label, row);
        html("td", null, TYPE_LABEL[state.nodes[e.target].type] + " " + state.nodes[e.target].label, row);
        html("td", "fx-muted", { recorded: "Recorded link", result: "Scan result", identity: "Identical hash" }[e.kind], row);
      });
    }

    function select(id) {
      selected = id;
      var n = state.nodes[id];
      while (panel.firstChild) panel.removeChild(panel.firstChild);
      html("p", "fx-graph-type", TYPE_LABEL[n.type], panel);
      html("h3", "fx-graph-title", n.label, panel);
      if (n.sub) html("p", "fx-muted small", n.sub, panel);
      if (n.type === "hash") html("p", "small", "Items linked to this SHA-256 have identical content. That alone says nothing about intent.", panel);
      if (n.integrity) html("p", "small", "Integrity: " + n.integrity, panel);
      var count = Object.keys(state.edges).filter(function (k) {
        return state.edges[k].source === id || state.edges[k].target === id;
      }).length;
      html("p", "fx-muted small", count + " link" + (count === 1 ? "" : "s") + " shown", panel);
      var actions = html("div", "d-flex flex-wrap gap-2", null, panel);
      var expandButton = html("button", "fx-btn fx-btn-secondary fx-btn-sm", "Expand", actions);
      expandButton.type = "button";
      expandButton.addEventListener("click", function () { expand(id); });
      if (n.url) {
        var link = html("a", "fx-btn fx-btn-ghost fx-btn-sm", "Open record", actions);
        link.href = n.url;
      }
      draw();
    }

    function load(url, focusId) {
      say("Loading…");
      return fetch(url, { credentials: "same-origin", headers: { Accept: "application/json" } })
        .then(function (r) { return r.json().then(function (body) { return { ok: r.ok, body: body }; }); })
        .then(function (res) {
          if (!res.ok) { say(res.body.error || "Couldn't load the graph."); return; }
          var first = !Object.keys(state.nodes).length;
          var added = merge(state, res.body);
          layout(state, first ? null : added);
          draw();
          if (first) fit();
          if (focusId && state.nodes[focusId]) select(focusId);
          if (!first) say(added.length + " new node" + (added.length === 1 ? "" : "s") + " added. " + status.textContent);
        })
        .catch(function () { say("Couldn't load the graph. Check your connection and try again."); });
    }

    function expand(id) {
      load(container.getAttribute("data-expand-url") + "?node=" + encodeURIComponent(id) +
           "&hashes=" + encodeURIComponent(hashMode), id);
    }

    // interactions
    var drag = null;
    svg.addEventListener("pointerdown", function (ev) {
      if (ev.target.closest && ev.target.closest(".fx-node")) return;
      drag = { x: ev.clientX - view.x, y: ev.clientY - view.y };
      svg.setPointerCapture(ev.pointerId);
    });
    svg.addEventListener("pointermove", function (ev) {
      if (!drag) return;
      view.x = ev.clientX - drag.x; view.y = ev.clientY - drag.y; apply();
    });
    svg.addEventListener("pointerup", function () { drag = null; });
    svg.addEventListener("wheel", function (ev) {
      ev.preventDefault();
      var rect = svg.getBoundingClientRect();
      zoom(ev.deltaY < 0 ? 1.15 : 1 / 1.15, ev.clientX - rect.left, ev.clientY - rect.top);
    }, { passive: false });
    nodeLayer.addEventListener("click", function (ev) {
      var g = ev.target.closest(".fx-node");
      if (g) select(g.getAttribute("data-id"));
    });
    nodeLayer.addEventListener("dblclick", function (ev) {
      var g = ev.target.closest(".fx-node");
      if (g) expand(g.getAttribute("data-id"));
    });
    nodeLayer.addEventListener("keydown", function (ev) {
      var g = ev.target.closest(".fx-node");
      if (!g) return;
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); select(g.getAttribute("data-id")); }
      if (ev.key === "e" || ev.key === "E") { ev.preventDefault(); expand(g.getAttribute("data-id")); }
    });
    container.addEventListener("keydown", function (ev) {
      if (ev.target.tagName === "INPUT") return;
      var step = 60;
      if (ev.key === "+" || ev.key === "=") zoom(1.2);
      else if (ev.key === "-") zoom(1 / 1.2);
      else if (ev.key === "0") fit();
      else if (ev.key === "ArrowLeft") { view.x += step; apply(); }
      else if (ev.key === "ArrowRight") { view.x -= step; apply(); }
      else if (ev.key === "ArrowUp") { view.y += step; apply(); }
      else if (ev.key === "ArrowDown") { view.y -= step; apply(); }
      else return;
      ev.preventDefault();
    });
    container.querySelectorAll("[data-graph-zoom]").forEach(function (b) {
      b.addEventListener("click", function () {
        var how = b.getAttribute("data-graph-zoom");
        if (how === "fit") fit(); else zoom(how === "in" ? 1.25 : 0.8);
      });
    });
    container.querySelectorAll("input[data-graph-type]").forEach(function (box) {
      box.addEventListener("change", function () { hiddenTypes[box.getAttribute("data-graph-type")] = !box.checked; draw(); });
    });
    container.querySelectorAll("input[data-graph-kind]").forEach(function (box) {
      box.addEventListener("change", function () { hiddenKinds[box.getAttribute("data-graph-kind")] = !box.checked; draw(); });
    });
    search.addEventListener("input", highlight);
    search.addEventListener("keydown", function (ev) {
      if (ev.key !== "Enter") return;
      ev.preventDefault();
      var hit = nodeLayer.querySelector(".fx-node.is-match");
      if (!hit) { say("No node matches \u201c" + search.value + "\u201d."); return; }
      var n = state.nodes[hit.getAttribute("data-id")], rect = svg.getBoundingClientRect();
      view.x = rect.width / 2 - n.x * view.scale; view.y = rect.height / 2 - n.y * view.scale; apply();
      select(n.id);
      var again = nodeLayer.querySelector('[data-id="' + CSS.escape(n.id) + '"]');
      if (again) again.focus();
    });

    load(container.getAttribute("data-case-url") + "?hashes=" + encodeURIComponent(hashMode),
         container.getAttribute("data-focus"));
  }

  document.addEventListener("DOMContentLoaded", function () {
    var container = document.getElementById("fx-graph");
    if (container) start(container);
  });
})(this);
