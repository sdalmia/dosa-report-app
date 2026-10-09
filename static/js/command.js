(function () {
  var root = document.documentElement;
  var toggle = document.getElementById("theme-toggle");
  var menu = document.getElementById("nav-menu");
  var drawer = document.getElementById("nav-drawer");

  function applyLabel() {
    if (!toggle) return;
    var dark = root.getAttribute("data-theme") === "dark";
    var compact = toggle.closest(".cc-header");
    if (compact) {
      toggle.innerHTML = dark
        ? '<i class="bi bi-sun" aria-hidden="true"></i>'
        : '<i class="bi bi-moon" aria-hidden="true"></i>';
    } else {
      toggle.textContent = dark ? "Light" : "Dark";
    }
    toggle.setAttribute("aria-label", dark ? "Switch to light theme" : "Switch to dark theme");
    var meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", dark ? "#12110e" : "#f7f6f3");
  }

  if (toggle) {
    toggle.addEventListener("click", function () {
      var next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";
      root.setAttribute("data-theme", next);
      root.setAttribute("data-bs-theme", next);
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
      document.body.classList.toggle("nav-open", open);
      if (open) {
        var field = drawer.querySelector(".cc-search-input");
        if (field) field.focus();
      }
    });
  }

  var searchRows = null;
  function ensureSearch() {
    if (searchRows) return Promise.resolve(searchRows);
    return fetch("/search.json", { credentials: "same-origin" })
      .then(function (response) { return response.ok ? response.json() : { results: [] }; })
      .then(function (payload) {
        searchRows = payload.results || [];
        return searchRows;
      })
      .catch(function () { searchRows = []; return searchRows; });
  }

  function paintResults(box, rows) {
    if (!box) return;
    if (!rows.length) {
      box.hidden = true;
      box.innerHTML = "";
      return;
    }
    box.hidden = false;
    box.innerHTML = rows.map(function (row) {
      var kind = row.kind || "";
      var label = row.label || "";
      var store = row.store || "";
      var extra = store && label.toLowerCase().indexOf(String(store).toLowerCase()) === -1 ? " · " + store : "";
      return '<a href="' + String(row.href || "#").replace(/"/g, "") + '"><span class="kind">' + kind + '</span><span>' + (label + extra).replace(/[&<>]/g, function (ch) {
        return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch];
      }) + "</span></a>";
    }).join("");
  }

  document.querySelectorAll(".cc-search").forEach(function (form) {
    var input = form.querySelector(".cc-search-input");
    var box = form.querySelector(".cc-search-results");
    if (!input || !box) return;
    form.addEventListener("submit", function (event) { event.preventDefault(); });
    input.addEventListener("input", function () {
      var query = input.value.trim().toLowerCase();
      if (query.length < 1) {
        box.hidden = true;
        box.innerHTML = "";
        return;
      }
      ensureSearch().then(function (rows) {
        var hits = rows.filter(function (row) {
          return ((row.label || "") + " " + (row.store || "") + " " + (row.kind || "")).toLowerCase().indexOf(query) !== -1;
        }).slice(0, 12);
        paintResults(box, hits);
      });
    });
  });

  document.querySelectorAll(".cc-filters").forEach(function (form) {
    var range = form.querySelector('select[name="cc_range"]');
    if (!range) return;
    range.addEventListener("change", function () {
      form.classList.toggle("is-custom", range.value === "custom");
    });
  });

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
