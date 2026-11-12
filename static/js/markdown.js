/* A small markdown renderer. Text is escaped first, so tags in the answer stay text. */
function renderMarkdown(src) {
  function escape(text) {
    return String(text || "").replace(/[&<>]/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch];
    });
  }
  function inline(text) {
    return escape(text).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  }
  var lines = String(src || "").replace(/\r\n/g, "\n").split("\n");
  var html = [];
  var i = 0;
  while (i < lines.length) {
    var line = lines[i];
    if (line.trim().charAt(0) === "|" && i + 1 < lines.length && /^\s*\|?\s*:?-{3,}/.test(lines[i + 1])) {
      var headers = line.split("|").map(function (cell) { return cell.trim(); }).filter(function (cell, index, all) {
        return cell !== "" || (index > 0 && index < all.length - 1);
      });
      i += 2;
      var rows = [];
      while (i < lines.length && lines[i].trim().charAt(0) === "|") {
        rows.push(lines[i].split("|").map(function (cell) { return cell.trim(); }).filter(function (cell, index, all) {
          return cell !== "" || (index > 0 && index < all.length - 1);
        }));
        i += 1;
      }
      var head = headers.map(function (cell) { return "<th>" + inline(cell) + "</th>"; }).join("");
      var body = rows.map(function (row) {
        return "<tr>" + row.map(function (cell) { return "<td>" + inline(cell) + "</td>"; }).join("") + "</tr>";
      }).join("");
      html.push('<figure class="cc-table-wrap"><div class="cc-table-scroll"><table class="cc-mini"><thead><tr>' + head + "</tr></thead><tbody>" + body + "</tbody></table></div></figure>");
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      var items = [];
      while (i < lines.length && /^\s*[-*]\s+/.test(lines[i])) {
        items.push("<li>" + inline(lines[i].replace(/^\s*[-*]\s+/, "")) + "</li>");
        i += 1;
      }
      html.push("<ul>" + items.join("") + "</ul>");
      continue;
    }
    if (line.trim()) html.push("<p>" + inline(line) + "</p>");
    i += 1;
  }
  return html.join("");
}

if (typeof module !== "undefined" && module.exports) module.exports = { renderMarkdown: renderMarkdown };
if (typeof window !== "undefined") window.renderMarkdown = renderMarkdown;
