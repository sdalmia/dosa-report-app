(function () {
  var log = document.getElementById("chat-log");
  var form = document.getElementById("chat-form");
  var input = document.getElementById("chat-input");
  var chips = document.getElementById("chat-chips");
  if (!log || !form || !input) return;

  function escape(text) {
    return String(text || "").replace(/[&<>]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch];
    });
  }

  function addBubble(kind) {
    var node = document.createElement("article");
    node.className = "cc-bubble " + kind;
    log.appendChild(node);
    log.scrollTop = log.scrollHeight;
    return node;
  }

  function chart(spec) {
    var series = (spec && spec.series) || [];
    if (!series.length) return "";
    var max = 1;
    series.forEach(function (item) { max = Math.max(max, Math.abs(Number(item.value) || 0)); });
    var height = series.length * 32 + 8;
    var rows = series.map(function (item, index) {
      var value = Number(item.value) || 0;
      var width = Math.max(2, (Math.abs(value) / max) * 150);
      var y = 8 + index * 32;
      var unit = spec.unit || "";
      return '<text x="0" y="' + (y + 14) + '" class="cc-chart-label">' + escape(item.label) + '</text>'
        + '<rect class="cc-bar" x="108" y="' + y + '" width="' + width + '" height="16" rx="4"></rect>'
        + '<text x="' + (114 + width) + '" y="' + (y + 13) + '" class="cc-chart-value">' + escape(value + unit) + '</text>';
    }).join("");
    return '<figure class="cc-chart"><figcaption>' + escape(spec.title || "") + '</figcaption>'
      + '<svg viewBox="0 0 320 ' + height + '" role="img">' + rows + '</svg></figure>';
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
    return '<figure class="cc-table-wrap"><figcaption>' + escape(spec.title || "") + '</figcaption>'
      + '<div class="cc-table-scroll"><table class="cc-mini"><thead><tr>' + head + '</tr></thead><tbody>'
      + body + '</tbody></table></div>' + more + '</figure>';
  }

  function followups(items) {
    if (!items || !items.length) return "";
    return '<div class="cc-follow">' + items.map(function (item) {
      return '<button type="button" class="cc-chip">' + escape(item) + '</button>';
    }).join("") + '</div>';
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
    if (chips) chips.hidden = true;
    var note = document.getElementById("chat-note");
    if (note) note.remove();
    addBubble("user").textContent = text;
    var bot = addBubble("bot");
    bot.textContent = "…";
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
      bot.textContent = "";
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
              bot.textContent = spoken.trim();
            }
            if (payload.done) {
              var extra = "";
              if (payload.as_of) extra += '<p class="cc-asof">Data as of ' + escape(payload.as_of) + '</p>';
              if (payload.chart) extra += chart(payload.chart);
              if (payload.table) extra += table(payload.table);
              extra += followups(payload.followups);
              if (extra) bot.insertAdjacentHTML("beforeend", extra);
            }
          });
          log.scrollTop = log.scrollHeight;
          return pump();
        });
      }
      return pump();
    }).catch(function () {
      bot.textContent = "That didn't go through. Try again.";
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
