(function () {
  "use strict";

  var ANCHORS = window.LD.presentation.anchors;
  var ROWS = window.LD.presentation.rows;
  var NARROW = window.matchMedia("(max-width: 62rem)");

  /* --- files that arrive as rows rather than markup ------------------------ */

  var KINDS = { c: "context", a: "add", d: "del", h: "hunk", m: "message" };
  var SIGNS = { add: "+", del: "-" };

  function cell(cls, text) {
    var td = document.createElement("td");
    td.className = cls;
    if (text) td.textContent = text;
    return td;
  }

  // A collapsed file ships as data: 145 bytes of table scaffolding per line is
  // not worth spending on something folded shut. Build it the first time it is
  // opened, or the first time a reference points into it.
  function fill(block) {
    var key = block.dataset.ldLazy;
    if (!key) return false;
    var data = ROWS[key];
    delete block.dataset.ldLazy;
    if (!data) return false;

    var body = block.querySelector("table.ld-diff tbody");
    if (!body) return false;
    var html = [];
    data.rows.forEach(function (r, i) {
      var section = data.sections[i];
      if (section) html.push(section);
      var kind = KINDS[r[0]] || "context";
      var tr = document.createElement("tr");
      tr.id = key + "-r" + i;
      tr.className = "ld-row ld-" + kind + (r[4] ? " ld-marked" : "");
      if (r[4]) tr.dataset.ldNotes = r[4];
      if (kind === "hunk" || kind === "message") {
        tr.appendChild(cell("ld-no", ""));
        tr.appendChild(cell("ld-no", ""));
        tr.appendChild(cell("ld-text", r[3]));
      } else {
        tr.appendChild(cell("ld-no", r[1] ? String(r[1]) : ""));
        tr.appendChild(cell("ld-no", r[2] ? String(r[2]) : ""));
        var td = cell("ld-text", "");
        var sign = document.createElement("span");
        sign.className = "ld-sign";
        sign.textContent = SIGNS[kind] || " ";
        td.appendChild(sign);
        td.appendChild(document.createTextNode(r[3]));
        tr.appendChild(td);
      }
      html.push(tr.outerHTML);
    });
    body.innerHTML = html.join("");
    return true;
  }

  function fillFor(id) {
    // `id` may name a row inside a file that has not been built yet.
    var key = /^(f\d+)/.exec(id);
    if (!key) return;
    var block = document.querySelector('[data-ld-lazy="' + key[1] + '"]');
    if (block) fill(block);
  }

  function rowIndex(note) {
    var m = /-r(\d+)$/.exec(note.dataset.ldRow || "");
    return m ? parseInt(m[1], 10) : 0;
  }

  function rowsFor(targetId) {
    var a = ANCHORS[targetId];
    if (!a) return [];
    fillFor(a.body);
    var out = [];
    for (var i = a.start; i <= a.end; i++) {
      var el = document.getElementById(a.body + "-r" + i);
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
    fillFor(targetId);
    var rows = rowsFor(targetId);
    var el = document.getElementById(targetId);
    var focus = rows[0] || el;
    if (!focus) return;

    var block = focus.closest("details.ld-fileblock");
    if (block && !block.open) {
      block.open = true;
      placeNotes();
    }
    var msg = focus.closest(".ld-msg");
    if (msg && focus.classList.contains("ld-elided")) openMessage(msg, true);
    // Centre a line, but put the top of anything taller than the window at the
    // top: centring a section that is longer than the viewport lands the reader
    // in the middle of it, which is nowhere in particular.
    var tall = focus.getBoundingClientRect().height > window.innerHeight * 0.8;
    focus.scrollIntoView({ block: tall ? "start" : "center" });

    document.querySelectorAll(".ld-flash").forEach(function (n) {
      n.classList.remove("ld-flash");
    });
    // Flashing something taller than the window tints the whole screen, which
    // points at nothing. Landing at its top is the cue.
    var flash = rows.length ? rows : el && !tall ? [el] : [];
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

  function openMessage(msg, open) {
    msg.classList.toggle("is-open", open);
    var btn = msg.querySelector(".ld-msg-more");
    if (btn) {
      btn.setAttribute("aria-expanded", String(open));
      btn.textContent = open ? "show less" : btn.dataset.ldLabel;
    }
  }

  document.querySelectorAll(".ld-msg-more").forEach(function (btn) {
    btn.dataset.ldLabel = btn.textContent;
  });

  document.addEventListener("click", function (ev) {
    var more = ev.target.closest(".ld-msg-more");
    if (more) {
      ev.preventDefault();
      var msg = more.closest(".ld-msg");
      openMessage(msg, !msg.classList.contains("is-open"));
      return;
    }
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
      if (ev.target.open) fill(ev.target);
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
    // The title attribute is kept for accessibility; suppress
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
    var files = document.querySelectorAll(".ld-file, .ld-thread");
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

  /* --- the map: which layer the reader is in ------------------------------- */

  function trackMap() {
    var blocks = document.querySelectorAll(".ld-map-box");
    if (!blocks.length || !("IntersectionObserver" in window)) return;
    // The full-size map and the postage stamp share layer ids; mark both.
    var byId = {};
    blocks.forEach(function (b) { (byId[b.dataset.ldLayer] = byId[b.dataset.ldLayer] || []).push(b); });
    var seen = new Set();
    var obs = new IntersectionObserver(
      function (entries) {
        entries.forEach(function (e) {
          if (e.isIntersecting) seen.add(e.target.id);
          else seen.delete(e.target.id);
        });
        var current = null;
        Object.keys(byId).forEach(function (id) {
          if (seen.has(id) && current === null) current = id;
        });
        Object.keys(byId).forEach(function (id) {
          byId[id].forEach(function (b) { b.classList.toggle("ld-current", id === current); });
        });
      },
      { rootMargin: "-5% 0px -60% 0px" }
    );
    Object.keys(byId).forEach(function (id) {
      var el = document.getElementById(id);
      if (el) obs.observe(el);
    });
  }

  /* --- the data block, for page scripts and the console -------------------- */

  window.LD.anchors = ANCHORS;
  window.LD.reveal = reveal;

  /* --- boot ---------------------------------------------------------------- */

  function boot() {
    placeNotes();
    trackToc();
    trackMap();
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
