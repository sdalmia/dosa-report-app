(function () {
  var root = document.documentElement;
  var toggle = document.getElementById("theme-toggle");
  var menu = document.getElementById("nav-menu");
  var drawer = document.getElementById("nav-drawer");

  function applyLabel() {
    if (!toggle) return;
    var dark = root.getAttribute("data-theme") !== "light";
    toggle.textContent = dark ? "Light" : "Dark";
    toggle.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", dark ? "#12110e" : "#f4f1ea");
  }

  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "light" ? "dark" : "light";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("dosa-theme", next); } catch (err) {}
      applyLabel();
      if (window.Plotly) {
        document.querySelectorAll(".js-plotly-plot").forEach(function (node) {
          window.Plotly.Plots.resize(node);
        });
      }
    });
  }
  applyLabel();

  if (menu && drawer) {
    menu.addEventListener("click", function () {
      var open = drawer.classList.toggle("is-open");
      menu.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  var sheet = document.getElementById("cal-sheet");
  if (sheet && window.matchMedia("(max-width: 767px)").matches) {
    document.querySelectorAll(".store-health .cal-cell:not(.pad)").forEach(function (cell) {
      cell.addEventListener("click", function (event) {
        var link = event.target.closest("a");
        if (link) event.preventDefault();
        var labels = {
          tier: "Tier",
          pred_low: "Low",
          pred_mid: "Mid",
          pred_high: "High",
          actual_gross: "Actual Gross",
          actual_net: "Actual Net",
          drivers: "Driver",
          weekday: "Weekday",
          variance_vs_mid: "Variance",
          variance_pct: "Variance %",
          status: "Status",
          notes: "Notes"
        };
        var lines = [];
        cell.querySelectorAll("[data-field]").forEach(function (node) {
          var field = node.getAttribute("data-field");
          var value = (node.textContent || "").trim();
          if (!value) return;
          var label = labels[field] || field;
          lines.push("<p><span class='muted'>" + label + "</span><br><b>" + value.replace(/[&<>]/g, function (ch) {
            return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch];
          }) + "</b></p>");
        });
        sheet.innerHTML = lines.join("") + "<button type='button' class='cc-icon-btn' id='cal-sheet-close'>Close</button>";
        sheet.hidden = false;
        var close = document.getElementById("cal-sheet-close");
        if (close) close.addEventListener("click", function () { sheet.hidden = true; });
      });
    });
  }

  window.addEventListener("resize", function () {
    if (!window.Plotly) return;
    document.querySelectorAll(".js-plotly-plot").forEach(function (node) {
      window.Plotly.Plots.resize(node);
    });
  });
})();
