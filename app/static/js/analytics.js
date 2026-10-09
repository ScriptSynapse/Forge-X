/* FORGE-X analytics charts. Each card fetches {labels, datasets:[{label, values}]}
   from /api/analytics/<chart> and draws it with Chart.js. A hidden table with
   the same numbers is filled in for screen-reader users. */
(function () {
  "use strict";
  var PALETTE = ["#1677FF", "#35BFFF", "#20C997", "#F4B740", "#F05252", "#91A4BA"];
  var STATUS = { "Verified": "#20C997", "Failed": "#F05252", "Integrity mismatch": "#F05252", "Pending": "#F4B740", "In Progress": "#35BFFF", "Under Review": "#A78BFA",
                 "Completed": "#20C997", "Cancelled": "#4A6380" };
  var GRID = "#1A2E46", TEXT = "#91A4BA";

  function show(card, state) {
    card.querySelectorAll("[data-state]").forEach(function (el) { el.hidden = el.getAttribute("data-state") !== state; });
  }

  function fillTable(card, data) {
    var table = card.querySelector("[data-fx-table]");
    var head = table.querySelector("thead"), body = table.querySelector("tbody");
    head.textContent = ""; body.textContent = "";
    var hr = document.createElement("tr");
    ["Category"].concat(data.datasets.map(function (d) { return d.label; })).forEach(function (t) {
      var th = document.createElement("th"); th.scope = "col"; th.textContent = t; hr.appendChild(th);
    });
    head.appendChild(hr);
    data.labels.forEach(function (label, i) {
      var tr = document.createElement("tr");
      var th = document.createElement("th"); th.scope = "row"; th.textContent = label; tr.appendChild(th);
      data.datasets.forEach(function (d) { var td = document.createElement("td"); td.textContent = String(d.values[i]); tr.appendChild(td); });
      body.appendChild(tr);
    });
  }

  function config(kind, data) {
    var horizontal = kind === "hbar" || kind === "hbar2" || kind === "stacked-h";
    var stacked = kind === "stacked" || kind === "stacked-h";
    var line = kind === "line";
    var datasets = data.datasets.map(function (d, i) {
      var color = STATUS[d.label] || PALETTE[i % PALETTE.length];
      return line
        ? { label: d.label, data: d.values, borderColor: color, backgroundColor: color, tension: 0.25, pointRadius: 3 }
        : { label: d.label, data: d.values, backgroundColor: color, borderRadius: 3 };
    });
    var valueAxis = { beginAtZero: true, stacked: stacked, grid: { color: GRID }, ticks: { color: TEXT, precision: 0 } };
    var categoryAxis = { stacked: stacked, grid: { display: false }, ticks: { color: TEXT } };
    return {
      type: line ? "line" : "bar",
      data: { labels: data.labels, datasets: datasets },
      options: {
        indexAxis: horizontal ? "y" : "x",
        plugins: { legend: { display: datasets.length > 1, labels: { color: "#C9D5E3", boxWidth: 12 } } },
        scales: horizontal ? { x: valueAxis, y: categoryAxis } : { x: categoryAxis, y: valueAxis }
      }
    };
  }

  function load(card) {
    var total = card.closest(".fx-chart-card").querySelector("[data-fx-total]");
    show(card, "loading");
    if (card._chart) { card._chart.destroy(); card._chart = null; }
    fetch(card.getAttribute("data-endpoint"), { headers: { "Accept": "application/json" }, credentials: "same-origin" })
      .then(function (r) {
        if (r.status === 401) { window.location.reload(); throw new Error("signed out"); }
        if (!r.ok) { throw new Error("HTTP " + r.status); }
        return r.json();
      })
      .then(function (data) {
        fillTable(card, data);
        if (total) { total.textContent = data.total ? data.total + " total" : ""; }
        if (!data.total || !data.labels.length) { show(card, "empty"); return; }
        if (typeof window.Chart === "undefined") {
          card.querySelector("[data-fx-error-text]").textContent = "The chart library is missing. Run python tools\\fetch_vendor.py, then reload.";
          show(card, "error"); return;
        }
        show(card, "ready");
        var canvas = card.querySelector("canvas");
        canvas.setAttribute("aria-label", data.labels.length + " categories; full numbers in the table below.");
        card._chart = new window.Chart(canvas, config(card.getAttribute("data-fx-analytics"), data));
      })
      .catch(function (e) { if (e.message !== "signed out") { show(card, "error"); } });
  }

  if (typeof window.Chart !== "undefined") {
    window.Chart.defaults.color = TEXT;
    window.Chart.defaults.font.family = "'IBM Plex Sans', system-ui, sans-serif";
    window.Chart.defaults.maintainAspectRatio = false;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { window.Chart.defaults.animation = false; }
  }
  document.querySelectorAll("[data-fx-analytics]").forEach(function (card) {
    var retry = card.querySelector("[data-fx-retry]");
    if (retry) { retry.addEventListener("click", function () { load(card); }); }
    load(card);
  });
})();
