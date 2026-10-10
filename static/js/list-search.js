(function () {
  var FILTER = "form.cc-filters, form.filters, form.mc-filters, form.pc-form";

  function fold(value) {
    return String(value || "").replace(/\s+/g, " ").trim().toLowerCase();
  }

  function isRow(el) {
    if (!el || el.nodeType !== 1) return false;
    if (el.matches(".list-search, .list-search-count, .list-search-empty, .league-split, .section-head, .heading-row, .empty, script, style, form, nav")) return false;
    if (/^H[1-6]$/.test(el.tagName) || el.tagName === "P") return false;
    return true;
  }

  function collectItems(list) {
    var marked = list.querySelectorAll("[data-list-item]");
    if (marked.length) return Array.from(marked);
    if (list.tagName === "TABLE") return Array.from(list.querySelectorAll("tbody > tr"));
    var direct = Array.from(list.children).filter(isRow);
    if (direct.length) return direct;
    return [];
  }

  function itemText(item) {
    var bits = [item.textContent || ""];
    var group = item.closest(".store-group, .flag-group, .owner-group");
    if (group && group !== item) {
      var heading = group.querySelector("h2, h3");
      if (heading && !item.contains(heading)) bits.push(heading.textContent || "");
    }
    if (item.getAttribute("title")) bits.push(item.getAttribute("title"));
    return fold(bits.join(" "));
  }

  function isHeading(el) {
    return el.matches("h2, h3, .league-split");
  }

  function syncHeadings(list, items) {
    var heads = Array.from(list.children).filter(isHeading);
    heads.forEach(function (head) {
      var node = head.nextElementSibling;
      var relevant = false;
      var visible = false;
      while (node && !isHeading(node)) {
        if (items.indexOf(node) !== -1) {
          relevant = true;
          if (!node.hidden) visible = true;
        } else {
          items.forEach(function (item) {
            if (node.contains(item)) {
              relevant = true;
              if (!item.hidden) visible = true;
            }
          });
        }
        node = node.nextElementSibling;
      }
      if (relevant) head.hidden = !visible;
    });
  }

  function syncGroups(list, items) {
    list.querySelectorAll(".flag-group, .owner-group, .store-group").forEach(function (group) {
      if (group === list) return;
      var inside = items.filter(function (item) { return group.contains(item); });
      if (!inside.length) return;
      group.hidden = inside.every(function (item) { return item.hidden; });
    });
  }

  function clearButton() {
    var button = document.createElement("button");
    button.type = "button";
    button.className = "list-search-clear";
    button.setAttribute("aria-label", "Clear search");
    button.hidden = true;
    button.textContent = "x";
    return button;
  }

  function buildBar() {
    var bar = document.createElement("div");
    bar.className = "list-search";
    bar.innerHTML = '<label class="list-search-label"><span class="list-search-name">Search</span><span class="list-search-field"><input type="search" class="list-search-input" placeholder="Search" autocomplete="off" enterkeyhint="search"></span></label>';
    bar.querySelector(".list-search-field").appendChild(clearButton());
    return bar;
  }

  function matchFilter(el) {
    if (el.matches && el.matches(FILTER)) return el;
    if (el.querySelector) {
      var inner = el.querySelector(FILTER);
      if (inner) return inner;
    }
    return null;
  }

  function closestFilter(list) {
    var node = list;
    while (node && node !== document.body) {
      var prev = node.previousElementSibling;
      while (prev) {
        var found = matchFilter(prev);
        if (found) return found;
        prev = prev.previousElementSibling;
      }
      node = node.parentElement;
    }
    node = list;
    while (node && node !== document.body) {
      var chip = node.previousElementSibling;
      while (chip) {
        if (chip.matches && chip.matches("nav.filters, .filters") && !chip.querySelector("input, select, textarea")) return chip;
        chip = chip.previousElementSibling;
      }
      node = node.parentElement;
    }
    return null;
  }

  function adopt(host) {
    var existing = host.querySelector("input.list-search-input, input[type='search'], input[name='q']");
    if (!existing) return null;
    existing.classList.add("list-search-input");
    var field = existing.closest(".list-search-field");
    if (!field) {
      field = document.createElement("span");
      field.className = "list-search-field";
      existing.parentNode.insertBefore(field, existing);
      field.appendChild(existing);
    }
    if (!field.querySelector(".list-search-clear")) field.appendChild(clearButton());
    var shell = existing.closest(".list-search") || existing.closest("label") || field;
    shell.classList.add("list-search");
    return existing;
  }

  function ensureInput(list) {
    var pointed = list.getAttribute("data-list-input");
    if (pointed) {
      var target = document.querySelector(pointed);
      if (!target) return null;
      target.classList.add("list-search-input");
      var field = target.closest(".list-search-field");
      if (!field) {
        field = document.createElement("span");
        field.className = "list-search-field";
        target.parentNode.insertBefore(field, target);
        field.appendChild(target);
      }
      if (!field.querySelector(".list-search-clear")) field.appendChild(clearButton());
      var shell = target.closest("label") || field.parentElement;
      if (shell) shell.classList.add("list-search");
      return target;
    }
    var host = closestFilter(list);
    if (host) {
      var adopted = adopt(host);
      if (adopted) return adopted;
      if (!host.querySelector(".list-search-input")) {
        var bar = buildBar();
        host.appendChild(bar);
        if (window.matchMedia("(max-width: 767px)").matches && host.matches("form, nav, .filters, .cc-filters")) {
          var spacer = document.createElement("div");
          spacer.className = "list-search-spacer";
          spacer.setAttribute("aria-hidden", "true");
          bar.after(spacer);
        }
      }
      return host.querySelector(".list-search-input");
    }
    var bar = buildBar();
    bar.classList.add("is-sticky");
    if (list.tagName === "TABLE" || list.tagName === "OL" || list.tagName === "UL") {
      list.parentNode.insertBefore(bar, list);
    } else {
      list.insertBefore(bar, list.firstChild);
    }
    return bar.querySelector(".list-search-input");
  }

  function place(list, node) {
    if (list.tagName === "TABLE" || list.tagName === "OL" || list.tagName === "UL") {
      list.parentNode.insertBefore(node, list);
      return;
    }
    var count = list.querySelector(":scope > .list-search-count");
    var sticky = list.querySelector(":scope > .list-search");
    var after = count || sticky;
    list.insertBefore(node, after ? after.nextSibling : list.firstChild);
  }

  function wireClear(input) {
    var button = input.parentElement && input.parentElement.querySelector(".list-search-clear");
    if (!button || button.getAttribute("data-wired") === "1") return;
    button.setAttribute("data-wired", "1");
    button.addEventListener("click", function () {
      input.value = "";
      input.focus();
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }

  function bind(list) {
    if (list.getAttribute("data-list-ready") === "1") return;
    var items = collectItems(list);
    if (!items.length) return;
    list.setAttribute("data-list-ready", "1");
    items.forEach(function (item) { item.setAttribute("data-list-text", itemText(item)); });
    var input = ensureInput(list);
    if (!input) return;
    var count = document.createElement("p");
    count.className = "list-search-count";
    count.setAttribute("aria-live", "polite");
    var empty = document.createElement("p");
    empty.className = "list-search-empty empty";
    empty.hidden = true;
    empty.textContent = "No matches";
    place(list, count);
    place(list, empty);

    function apply() {
      var query = fold(input.value);
      var shown = 0;
      items.forEach(function (item) {
        var match = !query || (item.getAttribute("data-list-text") || "").indexOf(query) !== -1;
        item.hidden = !match;
        if (match) shown += 1;
      });
      syncHeadings(list, items);
      syncGroups(list, items);
      count.textContent = shown + " of " + items.length;
      empty.hidden = shown !== 0;
      var button = input.parentElement && input.parentElement.querySelector(".list-search-clear");
      if (button) button.hidden = input.value.length === 0;
    }

    if (!input._listApply) {
      input._listApply = [];
      input.addEventListener("input", function () {
        input._listApply.forEach(function (fn) { fn(); });
      });
      input.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !input.name) event.preventDefault();
      });
      wireClear(input);
    }
    input._listApply.push(apply);
    apply();
  }

  document.querySelectorAll("[data-list]").forEach(bind);
})();
