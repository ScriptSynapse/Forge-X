/* FORGE-X dashboard charts.
   Each chart card fetches its data from a Flask JSON endpoint (backed by a
   MySQL query) and shows a loading, empty, error or ready state. A hidden
   table with the same numbers is filled in for screen-reader users. */
(function () {
  "use strict";

  var STATUS_COLORS = { "Open": "#1677FF", "In Progress": "#35BFFF", "On Hold": "#F4B740", "Closed": "#4A6380" };
  var PRIORITY_COLORS = { "Low": "#6E86A3", "Medium": "#42A5F5", "High": "#F4B740", "Critical": "#F05252" };
  var GRID = "#1A2E46";
  var TEXT = "#91A4BA";

  // Integrity bar segment widths (set from JS, so no inline styles are needed).
  document.querySelectorAll("[data-fx-width]").forEach(function (el) {
    el.style.width = Math.max(0, Math.min(100, parseFloat(el.getAttribute("data-fx-width")) || 0)) + "%";
  });

  function show(card, state) {
    card.querySelectorAll("[data-state]").forEach(function (el) {
      el.hidden = el.getAttribute("data-state") !== state;
    });
    var loading = card.querySelector('[data-state="loading"]');
    if (loading) { loading.setAttribute("aria-busy", state === "loading" ? "true" : "false"); }
  }

  function fillTable(card, labels, values) {
    var body = card.querySelector("[data-fx-table] tbody");
    if (!body) { return; }
    body.textContent = "";
    labels.forEach(function (label, i) {
      var row = document.createElement("tr");
      var th = document.createElement("th"); th.scope = "row"; th.textContent = label;
      var td = document.createElement("td"); td.textContent = String(values[i]);
      row.appendChild(th); row.appendChild(td); body.appendChild(row);
    });
  }

  function config(kind, data) {
    var integerTicks = { precision: 0, color: TEXT };
    if (kind === "doughnut") {
      return {
        type: "doughnut",
        data: { labels: data.labels, datasets: [{ data: data.values, borderWidth: 0,
          backgroundColor: data.labels.map(function (l) { return STATUS_COLORS[l] || "#4A6380"; }) }] },
        options: { cutout: "62%", plugins: { legend: { position: "right", labels: { color: "#C9D5E3", boxWidth: 12 } } } }
      };
    }
    if (kind === "bar-priority") {
      return {
        type: "bar",
        data: { labels: data.labels, datasets: [{ label: "Cases", data: data.values, borderRadius: 4,
          backgroundColor: data.labels.map(function (l) { return PRIORITY_COLORS[l] || "#42A5F5"; }) }] },
        options: { plugins: { legend: { display: false } },
          scales: { x: { grid: { display: false }, ticks: { color: TEXT } }, y: { beginAtZero: true, grid: { color: GRID }, ticks: integerTicks } } }
      };
    }
    if (kind === "bar-horizontal") {
      return {
        type: "bar",
        data: { labels: data.labels, datasets: [{ label: "Items", data: data.values, backgroundColor: "#1677FF", borderRadius: 3 }] },
        options: { indexAxis: "y", plugins: { legend: { display: false } },
          scales: { x: { beginAtZero: true, grid: { color: GRID }, ticks: integerTicks }, y: { grid: { display: false }, ticks: { color: TEXT } } } }
      };
    }
    return {
      type: "line",
      data: { labels: data.labels, datasets: [{ label: "Cases registered", data: data.values, tension: 0.25, fill: true,
        borderColor: "#1677FF", backgroundColor: "rgba(22,119,255,0.12)", pointBackgroundColor: "#07111F",
        pointBorderColor: "#35BFFF", pointRadius: 4 }] },
      options: { plugins: { legend: { display: false } },
        scales: { x: { grid: { display: false }, ticks: { color: TEXT } }, y: { beginAtZero: true, grid: { color: GRID }, ticks: integerTicks } } }
    };
  }

  function load(card) {
    var kind = card.getAttribute("data-fx-chart");
    var total = card.closest(".fx-chart-card").querySelector("[data-fx-total]");
    show(card, "loading");
    if (card._chart) { card._chart.destroy(); card._chart = null; }

    fetch(card.getAttribute("data-endpoint"), { headers: { "Accept": "application/json" }, credentials: "same-origin" })
      .then(function (response) {
        if (response.status === 401) { window.location.reload(); throw new Error("signed out"); }
        if (!response.ok) { throw new Error("HTTP " + response.status); }
        return response.json();
      })
      .then(function (data) {
        fillTable(card, data.labels, data.values);
        if (total) { total.textContent = data.total ? data.total + " total" : ""; }
        if (!data.total) { show(card, "empty"); return; }
        if (typeof window.Chart === "undefined") {
          card.querySelector("[data-fx-error-text]").textContent =
            "The chart library is missing. Run python tools\\fetch_vendor.py, then reload.";
          show(card, "error");
          return;
        }
        show(card, "ready");
        var canvas = card.querySelector("canvas");
        canvas.setAttribute("aria-label", data.labels.map(function (l, i) { return l + ": " + data.values[i]; }).join(", "));
        card._chart = new window.Chart(canvas, config(kind, data));
      })
      .catch(function (error) {
        if (error.message !== "signed out") { show(card, "error"); }
      });
  }

  if (typeof window.Chart !== "undefined") {
    window.Chart.defaults.color = TEXT;
    window.Chart.defaults.font.family = "'IBM Plex Sans', system-ui, sans-serif";
    window.Chart.defaults.maintainAspectRatio = false;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) { window.Chart.defaults.animation = false; }
  }

  document.querySelectorAll("[data-fx-chart]").forEach(function (card) {
    var retry = card.querySelector("[data-fx-retry]");
    if (retry) { retry.addEventListener("click", function () { load(card); }); }
    load(card);
  });
})();
