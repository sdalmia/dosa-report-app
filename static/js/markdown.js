/* Small markdown renderer. The source is escaped before any tag is added. */
function renderMarkdown(src) {
  function escape(text) {
    return String(text || "").replace(/[&<>]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch];
    });
  }
  function inline(text) {
    return escape(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  }
  function cells(line) {
    var parts = String(line || "").replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|");
    return parts.map(function (cell) { return cell.trim(); });
  }
  function isRule(line) {
    return /^\s*\|?\s*:?-{3,}[\s|:-]*$/.test(line);
  }
  function isNumeric(cell) {
    var text = String(cell || "").replace(/\*\*/g, "").trim();
    if (!text) return false;
    if (/^(—|–|-)$/.test(text)) return true;
    return /^[-−]?(₹)?\s*\d/.test(text);
  }
  function headingText(line) {
    var trimmed = String(line || "").trim();
    var match = trimmed.match(/^\*\*(.+?)\*\*:?$/);
    if (!match) return "";
    if (trimmed !== "**" + match[1] + "**" && trimmed !== "**" + match[1] + ":**") return "";
    return match[1].replace(/:$/, "");
  }
  function item(line) {
    var match = /^(\s*)([-*]|\d+\.)\s+(.*)$/.exec(line);
    if (!match) return null;
    return { indent: match[1].length, ordered: /\d/.test(match[2]), text: match[3] };
  }

  var lines = String(src || "").replace(/\r\n/g, "\n").split("\n");
  var blocks = [];
  var i = 0;
  while (i < lines.length) {
    var line = lines[i];
    if (!line.trim()) {
      i += 1;
      continue;
    }
    if (line.trim().charAt(0) === "|" && i + 1 < lines.length && isRule(lines[i + 1])) {
      var headers = cells(line);
      i += 2;
      var rows = [];
      while (i < lines.length && lines[i].trim().charAt(0) === "|") {
        rows.push(cells(lines[i]));
        i += 1;
      }
      blocks.push({ type: "table", headers: headers, rows: rows });
      continue;
    }
    var listed = item(line);
    if (listed) {
      var items = [];
      var ordered = listed.ordered;
      while (i < lines.length && item(lines[i])) {
        items.push(item(lines[i]));
        i += 1;
      }
      blocks.push({ type: "list", ordered: ordered, items: items });
      continue;
    }
    var title = headingText(line);
    if (title) {
      blocks.push({ type: "heading", text: title });
      i += 1;
      continue;
    }
    blocks.push({ type: "p", text: line.trim() });
    i += 1;
  }

  var kept = [];
  blocks.forEach(function (block, index) {
    if (block.type !== "heading") {
      kept.push(block);
      return;
    }
    var next = blocks[index + 1];
    if (!next || next.type === "heading") return;
    kept.push(block);
  });

  var html = [];
  kept.forEach(function (block, index) {
    if (block.type === "heading") {
      html.push("<h3>" + inline(block.text) + "</h3>");
      return;
    }
    if (block.type === "p") {
      var cls = index === 0 ? "cc-lead" : "";
      if (/^Data:/.test(block.text)) cls = "cc-data-note";
      html.push("<p" + (cls ? ' class="' + cls + '"' : "") + ">" + inline(block.text) + "</p>");
      return;
    }
    if (block.type === "list") {
      var tag = block.ordered ? "ol" : "ul";
      var lis = block.items.map(function (entry) {
        var nested = entry.indent >= 2 ? ' class="cc-nested"' : "";
        return "<li" + nested + ">" + inline(entry.text) + "</li>";
      }).join("");
      html.push("<" + tag + ">" + lis + "</" + tag + ">");
      return;
    }
    var head = block.headers.map(function (cell) {
      var cls = isNumeric(cell) ? ' class="cc-num"' : "";
      return "<th" + cls + ">" + inline(cell) + "</th>";
    }).join("");
    var body = block.rows.map(function (row) {
      return "<tr>" + row.map(function (cell, col) {
        var numeric = isNumeric(cell) || isNumeric(block.headers[col] || "");
        return "<td" + (numeric ? ' class="cc-num"' : "") + ">" + inline(cell) + "</td>";
      }).join("") + "</tr>";
    }).join("");
    html.push('<figure class="cc-table-wrap"><div class="cc-table-scroll"><table class="cc-mini"><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table></div></figure>");
  });
  return html.join("");
}

if (typeof module !== "undefined" && module.exports) module.exports = { renderMarkdown: renderMarkdown };
if (typeof window !== "undefined") window.renderMarkdown = renderMarkdown;
