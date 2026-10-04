/* FORGE-X shared behaviour. No inline scripts are used anywhere (the
   Content Security Policy forbids them), so pages opt in with data-* attributes. */
(function () {
  "use strict";

  // Show/hide password: <button data-fx-toggle-password="input-id">Show</button>
  document.querySelectorAll("[data-fx-toggle-password]").forEach(function (button) {
    var input = document.getElementById(button.getAttribute("data-fx-toggle-password"));
    if (!input) { return; }
    button.setAttribute("aria-pressed", "false");
    button.addEventListener("click", function () {
      var show = input.type === "password";
      input.type = show ? "text" : "password";
      button.textContent = show ? "Hide" : "Show";
      button.setAttribute("aria-pressed", show ? "true" : "false");
      button.setAttribute("aria-label", show ? "Hide password" : "Show password");
    });
  });

  // Confirm before a destructive or irreversible action: <form data-fx-confirm="Close this case?">
  document.querySelectorAll("form[data-fx-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-fx-confirm"))) { event.preventDefault(); }
    });
  });

  // Prevent double submission and show a loading state: <form data-fx-busy="Saving…">
  document.querySelectorAll("form[data-fx-busy]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (event.defaultPrevented) { return; }
      var button = form.querySelector("button[type=submit]");
      if (!button) { return; }
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      button.innerHTML = '<span class="fx-spinner" aria-hidden="true"></span>';
      button.appendChild(document.createTextNode(" " + form.getAttribute("data-fx-busy")));
    });
  });
})();
