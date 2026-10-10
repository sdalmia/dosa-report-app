(function () {
  var prefetched = new Map();

  function fetchText(url) {
    if (prefetched.has(url)) return prefetched.get(url);
    var pending = fetch(url, {
      credentials: "same-origin",
      headers: { Accept: "text/html" }
    }).then(function (response) {
      if (!response.ok) throw new Error("fragment");
      return response.text();
    });
    prefetched.set(url, pending);
    return pending;
  }

  function boot(root) {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll("[data-boot]").forEach(function (node) {
      var name = node.getAttribute("data-boot");
      var fn = window.lazyBoots && window.lazyBoots[name];
      if (!fn || node.getAttribute("data-booted") === "1") return;
      node.setAttribute("data-booted", "1");
      fn(node);
    });
    if (window.refreshLists) window.refreshLists();
  }

  function fill(section) {
    if (!section || section.getAttribute("data-loaded") === "1") return;
    var url = section.getAttribute("data-src");
    if (!url || section.getAttribute("data-loading") === "1") return;
    section.setAttribute("data-loading", "1");
    fetchText(url).then(function (html) {
      var holder = document.createElement("div");
      holder.innerHTML = html;
      var parent = section.parentNode;
      var nodes = Array.from(holder.childNodes);
      nodes.forEach(function (node) { parent.insertBefore(node, section); });
      section.remove();
      nodes.forEach(boot);
      revealHash();
    }).catch(function () {
      section.removeAttribute("data-loading");
      section.setAttribute("aria-busy", "false");
    });
  }

  function watch(section) {
    if (!("IntersectionObserver" in window)) {
      fill(section);
      return;
    }
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (!entry.isIntersecting) return;
        observer.disconnect();
        fill(section);
      });
    }, { rootMargin: "200px 0px" });
    observer.observe(section);
  }

  function prefetch(section) {
    var url = section.getAttribute("data-src");
    if (!url) return;
    var run = function () { fetchText(url).catch(function () { prefetched.delete(url); }); };
    if (window.requestIdleCallback) requestIdleCallback(run, { timeout: 1500 });
    else setTimeout(run, 400);
  }

  function scan() {
    document.querySelectorAll(".lazy-section[data-src]").forEach(function (section) {
      if (section.getAttribute("data-watched") === "1") return;
      section.setAttribute("data-watched", "1");
      if (section.tagName === "DETAILS") {
        section.addEventListener("toggle", function () {
          if (section.open) fill(section);
        });
      } else {
        watch(section);
      }
      if (section.getAttribute("data-prefetch") === "1") prefetch(section);
    });
    document.querySelectorAll("[data-boot]").forEach(function (node) {
      if (node.closest(".lazy-section")) return;
      if (!("IntersectionObserver" in window)) {
        boot(node.parentNode || document);
        return;
      }
      if (node.getAttribute("data-boot-watched") === "1") return;
      node.setAttribute("data-boot-watched", "1");
      var observer = new IntersectionObserver(function (entries) {
        entries.forEach(function (entry) {
          if (!entry.isIntersecting) return;
          observer.disconnect();
          var name = node.getAttribute("data-boot");
          var fn = window.lazyBoots && window.lazyBoots[name];
          if (fn && node.getAttribute("data-booted") !== "1") {
            node.setAttribute("data-booted", "1");
            fn(node);
          }
        });
      }, { rootMargin: "200px 0px" });
      observer.observe(node);
    });
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("[data-more]");
    if (!button) return;
    event.preventDefault();
    var url = button.getAttribute("data-more");
    button.disabled = true;
    fetchText(url).then(function (html) {
      var row = button.closest("tr");
      var tableBody = row && (button.closest("tbody") || button.closest("table"));
      var nodes;
      if (tableBody) {
        var table = document.createElement("table");
        table.innerHTML = "<tbody>" + html + "</tbody>";
        nodes = Array.from(table.querySelector("tbody").childNodes);
        nodes.forEach(function (node) { tableBody.insertBefore(node, row); });
        row.remove();
        boot(tableBody);
      } else {
        var holder = document.createElement("div");
        holder.innerHTML = html;
        var parent = button.parentNode;
        nodes = Array.from(holder.childNodes);
        nodes.forEach(function (node) { parent.insertBefore(node, button); });
        button.remove();
        boot(parent);
      }
    }).catch(function () {
      button.disabled = false;
    });
  });

  function pendingSections() {
    return Array.from(document.querySelectorAll(".lazy-section[data-src]"));
  }

  function revealHash() {
    if (!location.hash) return;
    var target = document.querySelector(location.hash);
    if (target) target.scrollIntoView();
  }

  document.addEventListener("click", function (event) {
    var link = event.target.closest("a[href^='#']");
    if (!link) return;
    var id = link.getAttribute("href");
    if (!id || id === "#") return;
    if (document.querySelector(id)) return;
    if (!pendingSections().length) return;
    event.preventDefault();
    var left = pendingSections();
    var pending = left.map(function (section) {
      return fetchText(section.getAttribute("data-src")).then(function (html) {
        if (!section.isConnected) return;
        var holder = document.createElement("div");
        holder.innerHTML = html;
        var parent = section.parentNode;
        Array.from(holder.childNodes).forEach(function (node) { parent.insertBefore(node, section); });
        section.remove();
        boot(parent);
      });
    });
    Promise.all(pending).then(function () {
      history.pushState(null, "", id);
      var target = document.querySelector(id);
      if (target) target.scrollIntoView();
    });
  });

  window.lazyScan = scan;
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", scan);
  else scan();
  window.addEventListener("hashchange", revealHash);
})();
