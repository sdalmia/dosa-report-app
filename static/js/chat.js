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

  function calendar(spec) {
    var days = (spec && spec.days) || [];
    if (!days.length) return "";
    var cells = days.map(function (day) {
      var gap = day.gap;
      var tone = gap == null ? "" : (gap < -10 ? " is-down" : (gap > 10 ? " is-up" : ""));
      var gapText = gap == null ? "no actual" : (gap > 0 ? "+" : "") + gap + "%";
      return '<div class="cc-day' + tone + '"><b>' + escape(String(day.date || "").slice(8)) + " " + escape(day.weekday || "") + "</b>"
        + "<span>pred " + escape(day.pred == null ? "" : String(day.pred)) + "</span>"
        + "<span>" + escape(gapText) + "</span>"
        + (day.tier ? "<i>" + escape(day.tier) + "</i>" : "")
        + "</div>";
    }).join("");
    return '<figure class="cc-cal"><figcaption>' + escape(spec.title || "Sales calendar") + "</figcaption><div class=\"cc-cal-grid\">" + cells + "</div></figure>";
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

  function thumb(rating, label, turned) {
    return '<button type="button" class="cc-thumb' + (turned ? " is-down" : "") + '" data-rating="' + rating + '" aria-label="' + label + '">'
      + '<svg viewBox="0 0 24 24" width="16" height="16" aria-hidden="true"><path d="M14 9V5a3 3 0 0 0-3-3L7 11v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"></path></svg></button>';
  }

  function rateControls(question, topic, asOf, askId) {
    var box = document.createElement("div");
    box.className = "cc-rate";
    box.dataset.question = question || "";
    box.dataset.topic = topic || "";
    box.dataset.asof = asOf || "";
    box.dataset.askId = askId || "";
    box.innerHTML = thumb("up", "Helpful", false) + thumb("down", "Not helpful", true)
      + '<form class="cc-note" hidden><input maxlength="160" placeholder="What was off?" aria-label="Note"><button type="submit">Send</button></form>';
    return box;
  }

  function sendRating(box, rating, note) {
    fetch("/dashboard/feedback", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        ask_id: box.dataset.askId,
        question: box.dataset.question,
        topic: box.dataset.topic,
        data_as_of: box.dataset.asof,
        rating: rating,
        note: note || ""
      })
    }).catch(function () {});
  }

  function actions(payload, source) {
    var row = '<div class="cc-actions">'
      + '<button type="button" class="cc-act" data-act="pdf">Download PDF</button>';
    if (payload.table) row += '<button type="button" class="cc-act" data-act="xlsx">Download Excel</button>';
    if (payload.chart || payload.calendar) row += '<button type="button" class="cc-act" data-act="png">Download image</button>';
    row += '<button type="button" class="cc-act" data-act="share">Share</button>';
    row += '<button type="button" class="cc-act" data-act="thread">Download conversation</button>';
    if (payload.cos) {
      var label = payload.cos.connected ? "Send to Chief of Staff" : "Send to Chief of Staff isn't connected yet";
      row += '<button type="button" class="cc-act" data-act="cos">' + label + "</button>";
    }
    row += "</div>";
    return row;
  }

  function postFile(kind, question, answer, table, chart) {
    var columns = (table && table.columns) || ["Answer"];
    var rows = (table && table.rows) || [[answer]];
    fetch("/api/chat/export", {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        format: kind,
        title: question || "Dosa Coffee Wizard",
        columns: columns,
        rows: rows,
        series: chart && chart.series,
        notes: ["Copied from the Wizard answer."]
      })
    }).then(function (response) { return response.blob(); }).then(function (blob) {
      var link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = kind === "xlsx" ? "wizard.xlsx" : (kind === "png" ? "wizard.png" : "wizard.pdf");
      link.click();
    }).catch(function () {});
  }

  log.addEventListener("click", function (event) {
    var act = event.target.closest(".cc-act");
    if (!act) return;
    var turn = act.closest(".cc-turn");
    var question = turn ? turn.dataset.question || "" : "";
    var answer = turn ? (turn.querySelector(".cc-answer") || {}).textContent || "" : "";
    var kind = act.getAttribute("data-act");
    if (kind === "share") {
      var days = window.prompt("Link expires in how many days? 1, 7, or 30", "7");
      fetch("/api/chat/share", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question: question, answer: answer, days: Number(days || 7), public: false })
      }).then(function (response) { return response.json(); }).then(function (body) {
        var url = location.origin + (body.url || "");
        if (navigator.share) {
          navigator.share({ title: "Dosa Coffee Wizard", text: question, url: url }).catch(function () {});
        } else if (navigator.clipboard) {
          navigator.clipboard.writeText(url);
        }
      }).catch(function () {});
      return;
    }
    if (kind === "thread") {
      var turns = [];
      log.querySelectorAll(".cc-turn").forEach(function (node) {
        var body = node.querySelector(".cc-answer, p");
        turns.push([(node.classList.contains("user") ? "You" : "Wizard"), body ? body.textContent : ""]);
      });
      postFile("pdf", "Conversation", "", { columns: ["Who", "Text"], rows: turns }, null);
      return;
    }
    if (kind === "cos") {
      var requestText = window.prompt("Request for Chief of Staff", question);
      if (!requestText) return;
      fetch("/api/chat/cos", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ request: requestText, excerpt: answer.slice(0, 400) })
      }).then(function (response) { return response.json(); }).then(function (body) {
        act.textContent = body.connected ? ("Sent: " + (body.status || "")) : "Send to Chief of Staff isn't connected yet";
      }).catch(function () {});
      return;
    }
    postFile(kind, question, answer, null, null);
  });

  function followups(items) {
    if (!items || !items.length) return "";
    return '<div class="cc-follow">' + items.map(function (item) {
      return '<button type="button" class="cc-chip">' + escape(item) + "</button>";
    }).join("") + "</div>";
  }

  log.addEventListener("click", function (event) {
    var thumb = event.target.closest(".cc-thumb");
    if (thumb) {
      var box = thumb.closest(".cc-rate");
      var rating = thumb.getAttribute("data-rating");
      box.querySelectorAll(".cc-thumb").forEach(function (node) { node.classList.remove("is-on"); });
      thumb.classList.add("is-on");
      var form = box.querySelector(".cc-note");
      if (rating === "down") {
        form.hidden = false;
        var field = form.querySelector("input");
        if (field) field.focus();
      } else {
        form.hidden = true;
        sendRating(box, "up", "");
      }
      return;
    }
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
    bot.dataset.question = text;
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
              var source = payload.markdown || spoken;
              if (window.renderMarkdown) answer.innerHTML = window.renderMarkdown(source);
              var extra = "";
              if (payload.as_of) extra += '<p class="cc-asof">Data as of ' + escape(payload.as_of) + "</p>";
              if (payload.chart) extra += chart(payload.chart);
              if (payload.calendar) extra += calendar(payload.calendar);
              if (payload.table) extra += table(payload.table);
              extra += followups(payload.followups);
              extra += actions(payload, source);
              if (extra) body.insertAdjacentHTML("beforeend", extra);
              body.appendChild(rateControls(
                bot.dataset.question || "",
                payload.topic || "",
                payload.as_of || "",
                payload.ask_id || ""
              ));
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

  log.addEventListener("submit", function (event) {
    var noteForm = event.target.closest(".cc-note");
    if (!noteForm) return;
    event.preventDefault();
    var box = noteForm.closest(".cc-rate");
    var field = noteForm.querySelector("input");
    sendRating(box, "down", field ? field.value : "");
    noteForm.hidden = true;
  });

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    ask(input.value);
  });
  var preset = new URLSearchParams(window.location.search).get("ask");
  if (preset) ask(preset);

  var sheet = document.getElementById("insight-sheet");
  var sheetBody = document.getElementById("insight-sheet-body");
  var sheetTitle = document.getElementById("insight-sheet-title");
  var sheetOpen = false;
  var sheetPushed = false;
  var sheetDetail = null;

  function paintSheet(detail) {
    sheetDetail = detail;
    if (sheetTitle) sheetTitle.textContent = detail.title || "";
    if (!sheetBody) return;
    sheetBody.innerHTML = detail.kind === "licences" ? licenceSheet(detail) : salesSheet(detail);
    var actions = document.getElementById("insight-sheet-actions");
    if (actions) actions.innerHTML = sheetActions(detail);
  }

  function salesSheet(detail) {
    var facts = (detail.facts || []).map(function (line) {
      return "<li>" + escape(line) + "</li>";
    }).join("");
    var dayRows = (detail.days || []).map(function (day) {
      return "<tr><th>" + escape(day.day) + "</th><td>" + escape(day.this_gross) + "</td><td>" + escape(day.prior_gross) + "</td><td>" + escape(day.change) + "</td></tr>";
    }).join("");
    var total = detail.total || {};
    var billRows = (detail.days || []).map(function (day) {
      return "<tr><th>" + escape(day.day) + "</th><td>" + escape(day.this_bills) + "</td><td>" + escape(day.prior_bills) + "</td><td>" + escape(day.this_apb) + "</td><td>" + escape(day.prior_apb) + "</td></tr>";
    }).join("");
    var channelRows = ((detail.channels && detail.channels.rows) || []).map(function (row) {
      return "<tr><th>" + escape(row.name) + "</th><td>" + escape(row.this) + "</td><td>" + escape(row.prior) + "</td><td>" + escape(row.change) + "</td></tr>";
    }).join("");
    return "<p class=\"cc-sheet-lead\">" + escape(detail.headline || "") + "</p>"
      + "<ul class=\"cc-sheet-facts\">" + facts + "</ul>"
      + "<h3>Daily gross</h3>"
      + "<p class=\"cc-sheet-legend\"><span><i class=\"is-now\"></i>This week</span><span><i class=\"is-then\"></i>Week before</span></p>"
      + chartSvg(detail.chart)
      + "<h3>By day</h3>"
      + "<table class=\"cc-sheet-table\"><thead><tr><th>Day</th><th>This week</th><th>Week before</th><th>Change</th></tr></thead><tbody>"
      + dayRows
      + "<tr class=\"is-total\"><th>" + escape(total.day || "Total") + "</th><td>" + escape(total.this_gross || "") + "</td><td>" + escape(total.prior_gross || "") + "</td><td>" + escape(total.change || "") + "</td></tr>"
      + "</tbody></table>"
      + "<details class=\"cc-sheet-more\"><summary>Bills and average bill</summary>"
      + "<table class=\"cc-sheet-table\"><thead><tr><th>Day</th><th>Bills</th><th>Bills before</th><th>Avg bill</th><th>Before</th></tr></thead><tbody>"
      + billRows
      + "<tr class=\"is-total\"><th>Total</th><td>" + escape(total.this_bills || "") + "</td><td>" + escape(total.prior_bills || "") + "</td><td>" + escape(total.this_apb || "") + "</td><td>" + escape(total.prior_apb || "") + "</td></tr>"
      + "</tbody></table></details>"
      + "<h3>By channel</h3>"
      + "<table class=\"cc-sheet-table\"><thead><tr><th></th><th>This week</th><th>Week before</th><th>Change</th></tr></thead><tbody>"
      + channelRows + "</tbody></table>"
      + "<details class=\"cc-sheet-more\"><summary>About this data</summary><p>" + escape(detail.about || "") + "</p></details>";
  }

  function licenceSheet(detail) {
    var notes = (detail.notes || []).map(function (line) {
      return "<li>" + escape(line) + "</li>";
    }).join("");
    var items = (detail.rows || []).map(function (row) {
      return "<li><strong>" + escape(row.store) + "</strong><span>"
        + escape(row.type) + " · " + escape(row.expiry) + " · " + escape(row.when) + "</span></li>";
    }).join("");
    return "<p class=\"cc-sheet-kicker\">" + escape(detail.window || "") + "</p>"
      + "<p class=\"cc-sheet-lead\">" + escape(detail.headline || "") + "</p>"
      + "<ul class=\"cc-sheet-notes\">" + notes + "</ul>"
      + "<ul class=\"cc-sheet-list\">" + items + "</ul>";
  }

  function sheetActions(detail) {
    var image = detail.download && detail.download.series
      ? "<button type=\"button\" data-sheet-act=\"png\">Image</button>" : "";
    return "<button type=\"button\" class=\"is-primary\" data-ask=\"" + escape(detail.question || "") + "\">Ask the Wizard why</button>"
      + "<button type=\"button\" data-sheet-act=\"pdf\">PDF</button>"
      + "<button type=\"button\" data-sheet-act=\"xlsx\">Excel</button>"
      + image
      + "<button type=\"button\" data-sheet-act=\"share\">Share</button>";
  }

  function chartSvg(chart) {
    var now = (chart && chart.this_week) || [];
    var prior = (chart && chart.prior_week) || [];
    if (!now.length) return "";
    var max = 1;
    now.concat(prior).forEach(function (item) {
      max = Math.max(max, Math.abs(Number(item && item.value) || 0));
    });
    var width = 320;
    var height = 128;
    var pad = 16;
    var group = (width - pad) / now.length;
    var bars = now.map(function (item, index) {
      var then = prior[index] || {};
      var nowH = ((Number(item.value) || 0) / max) * 96;
      var thenH = ((Number(then.value) || 0) / max) * 96;
      var x = pad / 2 + index * group;
      var label = String(item.label || "").split(" ")[1] || "";
      return "<rect class=\"is-then\" x=\"" + x.toFixed(1) + "\" y=\"" + (104 - thenH).toFixed(1) + "\" width=\"8\" height=\"" + Math.max(thenH, 1).toFixed(1) + "\"></rect>"
        + "<rect class=\"is-now\" x=\"" + (x + 10).toFixed(1) + "\" y=\"" + (104 - nowH).toFixed(1) + "\" width=\"8\" height=\"" + Math.max(nowH, 1).toFixed(1) + "\"></rect>"
        + "<text x=\"" + (x + 8).toFixed(1) + "\" y=\"122\" text-anchor=\"middle\" fill=\"currentColor\" font-size=\"10\">" + escape(label) + "</text>";
    }).join("");
    return "<svg class=\"cc-sheet-chart\" viewBox=\"0 0 " + width + " " + height + "\" role=\"img\" aria-label=\"Daily gross, this week and the week before\">" + bars + "</svg>";
  }

  function showSheet(detail, pushed) {
    paintSheet(detail);
    if (!sheet) return;
    sheet.hidden = false;
    sheetOpen = true;
    document.body.classList.add("cc-sheet-open");
    var close = sheet.querySelector(".cc-sheet-x");
    if (close) close.focus();
    if (pushed) {
      var url = new URL(window.location.href);
      url.searchParams.set("insight", detail.id || "");
      history.pushState({ insight: detail.id }, "", url);
      sheetPushed = true;
    }
  }

  function closeSheet(fromPop) {
    if (!sheetOpen) return;
    sheetOpen = false;
    if (sheet) sheet.hidden = true;
    document.body.classList.remove("cc-sheet-open");
    if (!fromPop && sheetPushed) {
      sheetPushed = false;
      history.back();
    }
  }

  function openInsight(id) {
    if (!id) return;
    showSheet({ title: "Opening…", kind: "sales", notes: [], days: [], channels: { rows: [] }, download: {} }, false);
    fetch("/api/chat/insights/" + encodeURIComponent(id) + "/details", { credentials: "same-origin" })
      .then(function (response) {
        if (!response.ok) throw new Error("missing");
        return response.json();
      })
      .then(function (detail) { showSheet(detail, true); })
      .catch(function () {
        if (sheetBody) sheetBody.innerHTML = "<p class=\"cc-sheet-lead\">That detail is not in the file.</p>";
      });
  }

  if (window.INSIGHT_OPEN) showSheet(window.INSIGHT_OPEN, false);

  document.addEventListener("click", function (event) {
    var closer = event.target.closest("[data-close]");
    if (closer && sheet && sheet.contains(closer)) {
      closeSheet(false);
      return;
    }
    var act = event.target.closest("[data-sheet-act]");
    if (act && sheetDetail) {
      var kind = act.getAttribute("data-sheet-act");
      var file = sheetDetail.download || {};
      if (kind === "share") {
        var days = window.prompt("Link expires in how many days? 1, 7, or 30", "7");
        fetch("/api/chat/share", {
          method: "POST",
          credentials: "same-origin",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            question: sheetDetail.question || "",
            answer: sheetDetail.share_text || "",
            days: Number(days || 7),
            public: false
          })
        }).then(function (response) { return response.json(); }).then(function (body) {
          var url = location.origin + (body.url || "");
          if (navigator.share) {
            navigator.share({ title: sheetDetail.title || "Dosa Coffee Wizard", text: sheetDetail.headline || "", url: url }).catch(function () {});
          } else if (navigator.clipboard) {
            navigator.clipboard.writeText(url);
          }
        }).catch(function () {});
        return;
      }
      postFile(kind, sheetDetail.title || "Dosa Coffee Wizard", sheetDetail.share_text || "", {
        columns: file.columns,
        rows: file.rows
      }, kind === "png" ? { series: file.series || [] } : null);
      return;
    }
    var askBtn = event.target.closest("[data-ask]");
    if (askBtn) {
      closeSheet(false);
      ask(askBtn.getAttribute("data-ask"));
      return;
    }
    var insight = event.target.closest(".cc-insight");
    if (insight) {
      openInsight(insight.getAttribute("data-id"));
      return;
    }
    var chip = event.target.closest(".cc-chip");
    if (!chip) return;
    ask(chip.getAttribute("data-q") || chip.textContent);
  });
  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape") closeSheet(false);
  });
  window.addEventListener("popstate", function () {
    if (sheetOpen) closeSheet(true);
    sheetPushed = false;
  });
})();
