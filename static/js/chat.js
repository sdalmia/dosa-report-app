(function () {
  var root = document.getElementById("chat");
  var log = document.getElementById("chat-log");
  var form = document.getElementById("chat-form");
  var input = document.getElementById("chat-input");
  var chips = document.getElementById("chat-chips");
  var mark = "";
  var brand = document.querySelector(".cc-brand img");
  if (brand) mark = brand.getAttribute("src") || "";
  if (!log || !form || !input) return;

  function escape(text) {
    return String(text || "").replace(/[&<>]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch];
    });
  }

  function settle(node) {
    if (node && node.scrollIntoView) node.scrollIntoView({ block: "nearest" });
  }

  function addUser(text) {
    var node = document.createElement("article");
    node.className = "cc-turn user";
    var line = document.createElement("p");
    line.textContent = text;
    node.appendChild(line);
    log.appendChild(node);
    settle(node);
    return node;
  }

  function addBot() {
    var node = document.createElement("article");
    node.className = "cc-turn bot is-streaming";
    node.innerHTML = '<img class="cc-mark" alt="" src="' + escape(mark) + '">'
      + '<div class="cc-turn-body"><p class="cc-answer"></p><span class="cc-shimmer" aria-hidden="true"></span></div>';
    log.appendChild(node);
    settle(node);
    return node;
  }

  function chart(spec) {
    var series = (spec && spec.series) || [];
    if (!series.length) return "";
    var max = 1;
    series.forEach(function (item) {
      max = Math.max(max, Math.abs(Number(item.value) || 0));
    });
    var rowH = 40;
    var top = 6;
    var height = top + series.length * rowH;
    var labelW = 108;
    var track = 250;
    var width = labelW + track + 78;
    var grids = [0.25, 0.5, 0.75, 1].map(function (part) {
      var x = labelW + track * part;
      return '<line class="cc-grid" x1="' + x + '" y1="2" x2="' + x + '" y2="' + (height - 2) + '"></line>';
    }).join("");
    var rows = series.map(function (item, index) {
      var value = Number(item.value) || 0;
      var barW = Math.max(6, (Math.abs(value) / max) * track);
      var y = top + index * rowH;
      var unit = spec.unit || "";
      var label = String(item.label || "");
      if (label.length > 16) label = label.slice(0, 15) + "…";
      return '<text class="cc-chart-label" x="0" y="' + (y + 18) + '">' + escape(label) + "</text>"
        + '<rect class="cc-bar" x="' + labelW + '" y="' + (y + 6) + '" width="' + barW.toFixed(1) + '" height="14" rx="7"></rect>'
        + '<text class="cc-chart-value" x="' + (labelW + barW + 8).toFixed(1) + '" y="' + (y + 18) + '">' + escape(value + unit) + "</text>";
    }).join("");
    return '<figure class="cc-chart"><figcaption>' + escape(spec.title || "") + "</figcaption>"
      + '<svg viewBox="0 0 ' + width + " " + height + '" role="img">' + grids + rows + "</svg></figure>";
  }

  function table(spec) {
    if (!spec || !spec.rows || !spec.rows.length) return "";
    var head = (spec.columns || []).map(function (column) {
      return "<th>" + escape(column) + "</th>";
    }).join("");
    var body = spec.rows.map(function (row, index) {
      var cells = row.map(function (cell) { return "<td>" + escape(cell) + "</td>"; }).join("");
      return '<tr class="' + (index >= 5 ? "cc-extra" : "") + '">' + cells + "</tr>";
    }).join("");
    var more = spec.rows.length > 5
      ? '<button type="button" class="cc-show-all">Show all</button>'
      : "";
    return '<figure class="cc-table-wrap"><figcaption>' + escape(spec.title || "") + "</figcaption>"
      + '<div class="cc-table-scroll"><table class="cc-mini"><thead><tr>' + head + "</tr></thead><tbody>"
      + body + "</tbody></table></div>" + more + "</figure>";
  }

  function followups(items) {
    if (!items || !items.length) return "";
    return '<div class="cc-follow">' + items.map(function (item) {
      return '<button type="button" class="cc-chip">' + escape(item) + "</button>";
    }).join("") + "</div>";
  }

  log.addEventListener("click", function (event) {
    var button = event.target.closest(".cc-show-all");
    if (!button) return;
    var wrap = button.closest(".cc-table-wrap");
    if (!wrap) return;
    wrap.classList.add("is-open");
    button.remove();
  });

  function ask(question) {
    var text = String(question || "").trim();
    if (!text) return;
    if (root) root.classList.add("is-chatting");
    if (chips) chips.hidden = true;
    var note = document.getElementById("chat-note");
    if (note) note.remove();
    addUser(text);
    var bot = addBot();
    var answer = bot.querySelector(".cc-answer");
    var body = bot.querySelector(".cc-turn-body");
    input.value = "";
    fetch("/dashboard/ask", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "Accept": "text/event-stream" },
      body: JSON.stringify({ question: text })
    }).then(function (response) {
      var reader = response.body.getReader();
      var decoder = new TextDecoder();
      var buffer = "";
      var spoken = "";
      function pump() {
        return reader.read().then(function (part) {
          if (part.done) return;
          buffer += decoder.decode(part.value, { stream: true });
          var chunks = buffer.split("\n\n");
          buffer = chunks.pop();
          chunks.forEach(function (chunk) {
            var line = chunk.replace(/^data:\s*/, "");
            if (!line) return;
            var payload = JSON.parse(line);
            if (payload.text) {
              spoken += payload.text;
              answer.textContent = spoken.trim();
              bot.classList.remove("is-streaming");
            }
            if (payload.done) {
              bot.classList.remove("is-streaming");
              var extra = "";
              if (payload.as_of) extra += '<p class="cc-asof">Data as of ' + escape(payload.as_of) + "</p>";
              if (payload.chart) extra += chart(payload.chart);
              if (payload.table) extra += table(payload.table);
              extra += followups(payload.followups);
              if (extra) body.insertAdjacentHTML("beforeend", extra);
              settle(bot);
            }
          });
          return pump();
        });
      }
      return pump();
    }).catch(function () {
      bot.classList.remove("is-streaming");
      answer.textContent = "That didn't go through. Try again.";
    });
  }

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    ask(input.value);
  });
  document.addEventListener("click", function (event) {
    var chip = event.target.closest(".cc-chip");
    if (!chip) return;
    ask(chip.textContent);
  });
})();
