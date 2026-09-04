(function () {
  "use strict";

  var ANCHORS = window.LD_ANCHORS || {};
  var NARROW = window.matchMedia("(max-width: 62rem)");

  function rowIndex(note) {
    var m = /-r(\d+)$/.exec(note.dataset.ldRow || "");
    return m ? parseInt(m[1], 10) : 0;
  }

  function rowsFor(targetId) {
    var a = ANCHORS[targetId];
    if (!a) return [];
    var out = [];
    for (var i = a.start; i <= a.end; i++) {
      var el = document.getElementById("f" + a.file + "-r" + i);
      if (el) out.push(el);
    }
    return out;
  }

  /* --- sidenote placement -------------------------------------------------- */

  function placeNotes() {
    var wide = !NARROW.matches;
    document.querySelectorAll(".ld-file").forEach(function (file) {
      var gutter = file.querySelector(".ld-gutter");
      if (!gutter) return;
      var notes = Array.prototype.slice.call(file.querySelectorAll(".ld-note"));
      if (!notes.length) return;

      if (!wide) {
        // Narrow: fold each note into the table, just below the line it is
        // about, rather than stacking them all after the diff.
        notes.forEach(function (note) {
          var row = document.getElementById(note.dataset.ldRow);
          if (!row) return;
          var host = note.parentElement;
          if (host && host.classList.contains("ld-noterow-cell")) return;
          var tr = document.createElement("tr");
          tr.className = "ld-noterow";
          var td = document.createElement("td");
          td.className = "ld-noterow-cell";
          td.colSpan = 3;
          td.appendChild(note);
          tr.appendChild(td);
          row.after(tr);
          note.style.top = "";
        });
        gutter.style.minHeight = "";
        return;
      }

      // Wide: notes belong in the margin. Undo any inline folding.
      notes.forEach(function (note) {
        var cell = note.parentElement;
        if (cell && cell.classList.contains("ld-noterow-cell")) {
          gutter.appendChild(note);
          var tr = cell.parentElement;
          if (tr) tr.remove();
        }
      });
      // Place in anchor order, so the push-down below never runs backwards.
      notes.sort(function (a, b) { return rowIndex(a) - rowIndex(b); });
      notes.forEach(function (n) { gutter.appendChild(n); });
      var gTop = gutter.getBoundingClientRect().top;
      var floor = 0;
      notes.forEach(function (note) {
        var row = document.getElementById(note.dataset.ldRow);
        if (!row) return;
        var want = row.getBoundingClientRect().top - gTop;
        var top = Math.max(want, floor);
        note.style.top = top + "px";
        floor = top + note.offsetHeight + 12;
      });
      // Keep the gutter tall enough that stacked notes are not clipped.
      gutter.style.minHeight = floor + "px";
    });
  }

  var raf = null;
  function schedulePlace() {
    // requestAnimationFrame does not fire while the document is hidden, which
    // would leave notes unplaced in a background tab until it is next shown.
    if (document.hidden) {
      placeNotes();
      return;
    }
    if (raf) cancelAnimationFrame(raf);
    raf = requestAnimationFrame(function () { raf = null; placeNotes(); });
  }
  document.addEventListener("visibilitychange", schedulePlace);
  window.ldPlaceNotes = placeNotes;

  /* --- navigation ---------------------------------------------------------- */

  function reveal(targetId) {
    var rows = rowsFor(targetId);
    var el = document.getElementById(targetId);
    var focus = rows[0] || el;
    if (!focus) return;

    var block = focus.closest("details.ld-fileblock");
    if (block && !block.open) {
      block.open = true;
      placeNotes();
    }
    focus.scrollIntoView({ behavior: "smooth", block: "center" });

    document.querySelectorAll(".ld-flash").forEach(function (n) {
      n.classList.remove("ld-flash");
    });
    var flash = rows.length ? rows : el ? [el] : [];
    flash.forEach(function (n) {
      n.classList.remove("ld-flash");
      void n.offsetWidth;
      n.classList.add("ld-flash");
    });
    if (el && el.classList.contains("ld-note")) {
      document.querySelectorAll(".ld-note-active").forEach(function (n) {
        n.classList.remove("ld-note-active");
      });
      el.classList.add("ld-note-active");
    }
  }

  document.addEventListener("click", function (ev) {
    var jump = ev.target.closest("[data-ld-target]");
    if (jump && !jump.classList.contains("ld-quote-btn")) {
      ev.preventDefault();
      var id = jump.dataset.ldTarget;
      history.replaceState(null, "", "#" + id);
      reveal(id);
      return;
    }
    var btn = ev.target.closest(".ld-quote-btn");
    if (btn) {
      ev.preventDefault();
      var body = btn.nextElementSibling;
      if (!body) return;
      var open = body.hasAttribute("hidden");
      body.toggleAttribute("hidden", !open);
      btn.setAttribute("aria-expanded", String(open));
      schedulePlace();
    }
  });

  document.addEventListener("toggle", function (ev) {
    if (ev.target.classList && ev.target.classList.contains("ld-fileblock")) {
      schedulePlace();
    }
  }, true);

  /* --- hovering a marked line highlights its notes -------------------------- */

  document.addEventListener("mouseover", function (ev) {
    var row = ev.target.closest && ev.target.closest(".ld-marked");
    if (!row) return;
    document.querySelectorAll(".ld-note-active").forEach(function (n) {
      n.classList.remove("ld-note-active");
    });
    (row.dataset.ldNotes || "").split(",").forEach(function (id) {
      var n = document.getElementById(id);
      if (n) n.classList.add("ld-note-active");
    });
  });

  /* --- category flags: hover shows the item being cited ---------------------- */

  var tip = null;
  function hideTip() {
    if (tip) { tip.remove(); tip = null; }
    document.querySelectorAll(".ld-flag-active").forEach(function (n) {
      n.classList.remove("ld-flag-active");
    });
  }
  function showTip(flag) {
    hideTip();
    var item = document.getElementById(flag.dataset.ldTarget);
    if (!item) return;
    var body = item.cloneNode(true);
    body.querySelectorAll(".ld-cat-badge, .ld-cat-where").forEach(function (n) { n.remove(); });
    body.removeAttribute("id");
    tip = document.createElement("div");
    tip.className = "ld-cat-tip";
    tip.style.cssText = flag.style.cssText;
    var head = document.createElement("div");
    head.className = "ld-cat-tip-head";
    head.textContent = (flag.getAttribute("title") || "").split(":")[0];
    tip.appendChild(head);
    var content = document.createElement("div");
    content.innerHTML = body.innerHTML;
    tip.appendChild(content);
    document.body.appendChild(tip);
    var r = flag.getBoundingClientRect();
    var left = r.left + window.scrollX;
    var maxLeft = window.scrollX + document.documentElement.clientWidth - tip.offsetWidth - 12;
    tip.style.left = Math.max(window.scrollX + 8, Math.min(left, maxLeft)) + "px";
    tip.style.top = (r.bottom + window.scrollY + 8) + "px";
    flag.classList.add("ld-flag-active");
    // The title attribute is kept for accessibility and no-JS readers; suppress
    // the browser's own tooltip while ours is showing.
    flag.dataset.ldTitle = flag.getAttribute("title");
    flag.removeAttribute("title");
  }
  document.addEventListener("mouseover", function (ev) {
    var flag = ev.target.closest && ev.target.closest(".ld-cat-flag");
    if (flag) showTip(flag);
  });
  document.addEventListener("mouseout", function (ev) {
    var flag = ev.target.closest && ev.target.closest(".ld-cat-flag");
    if (!flag) return;
    if (flag.dataset.ldTitle) {
      flag.setAttribute("title", flag.dataset.ldTitle);
      delete flag.dataset.ldTitle;
    }
    hideTip();
  });
  document.addEventListener("scroll", hideTip, true);

  /* --- table of contents current-file tracking ------------------------------ */

  function trackToc() {
    var files = document.querySelectorAll(".ld-file");
    if (!files.length || !("IntersectionObserver" in window)) return;
    var links = {};
    document.querySelectorAll(".ld-toc-file > a").forEach(function (a) {
      links[a.dataset.ldTarget] = a.parentElement;
    });
    var seen = new Set();
    var obs = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) seen.add(e.target.id);
          else seen.delete(e.target.id);
        });
        Object.keys(links).forEach(function (id) {
          links[id].classList.toggle("ld-current", seen.has(id));
        });
      },
      { rootMargin: "-10% 0px -70% 0px" }
    );
    files.forEach(function (f) { obs.observe(f); });
  }

  /* --- boot ---------------------------------------------------------------- */

  function boot() {
    placeNotes();
    trackToc();
    if (location.hash.length > 1) reveal(location.hash.slice(1));
  }

  window.addEventListener("resize", schedulePlace);
  window.addEventListener("hashchange", function () {
    if (location.hash.length > 1) reveal(location.hash.slice(1));
  });
  if (document.fonts && document.fonts.ready) {
    document.fonts.ready.then(schedulePlace);
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
