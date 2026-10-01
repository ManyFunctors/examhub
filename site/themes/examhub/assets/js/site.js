/* ExamHub site behaviour. */
(function () {
  "use strict";

  var DAY = 86400000;

  function parseDate(iso) {
    if (!iso) return null;
    /* Timestamps are RFC 3339 with an offset. */
    var day = String(iso).split("T")[0];
    var p = day.split("-");
    if (p.length !== 3) return null;
    var d = new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]));
    return isNaN(d.getTime()) ? null : d;
  }

  function startOfToday() {
    var n = new Date();
    return new Date(n.getFullYear(), n.getMonth(), n.getDate());
  }

  /* Levenshtein distance, and a matcher built on it. */
  function levenshtein(a, b) {
    if (a === b) return 0;
    if (!a.length) return b.length;
    if (!b.length) return a.length;
    var prev = new Array(b.length + 1);
    var cur = new Array(b.length + 1);
    for (var j = 0; j <= b.length; j++) prev[j] = j;
    for (var i = 1; i <= a.length; i++) {
      cur[0] = i;
      var best = cur[0];
      for (var k = 1; k <= b.length; k++) {
        var cost = a.charCodeAt(i - 1) === b.charCodeAt(k - 1) ? 0 : 1;
        cur[k] = Math.min(cur[k - 1] + 1, prev[k] + 1, prev[k - 1] + cost);
        if (cur[k] < best) best = cur[k];
      }
      /* No cell beat the bound, so no later row can: stop early. */
      if (best > a.length + b.length) return best;
      var t = prev; prev = cur; cur = t;
    }
    return prev[b.length];
  }

  /* The slack a query of this length is allowed. */
  function tolerance(len) {
    if (len <= 2) return 0;
    if (len <= 4) return 1;
    if (len <= 9) return 2;
    return 3;
  }

  /* Score one candidate against the query. */
  function score(hay, needle) {
    if (!needle) return 0;

    var words = hay.split(/[^a-z0-9]+/);
    var w, n;

    /* A whole word matching the query outright -- "next" against the NExT card --
       beats "next" merely turning up inside a longer word somewhere else. */
    for (w = 0; w < words.length; w++) {
      if (words[w] === needle) return 1;
    }

    if (hay.indexOf(needle) > -1) return 2;

    /* Initials of leading words, so "upsc cde" and "ugc net" match. */
    var run = [];
    for (n = 0; n < words.length; n++) {
      run.push(words[n]);
      if (run.join(" ") === needle) return 3;
    }

    /* A prefix of any single word, so "ssc" finds a body wherever it sits. */
    for (w = 0; w < words.length; w++) {
      if (words[w] && words[w].indexOf(needle) === 0) return 3;
    }

    var allow = tolerance(needle.length);
    if (!allow) return -1;

    /* Approximate, against each word and against the whole string. */
    var best = allow + 1;
    for (w = 0; w < words.length; w++) {
      if (!words[w] || Math.abs(words[w].length - needle.length) > allow) continue;
      var d = levenshtein(words[w], needle);
      if (d < best) best = d;
    }
    if (Math.abs(hay.length - needle.length) <= allow) {
      var dh = levenshtein(hay, needle);
      if (dh < best) best = dh;
    }
    return best <= allow ? 4 : -1;
  }

  /* Split a query into the separate things the reader asked for. */
  function queryTerms(q) {
    var parts = String(q || "").toLowerCase().split(/[\s,;]+/);
    var out = [], seen = {};
    for (var i = 0; i < parts.length; i++) {
      var t = parts[i].replace(/^[.\-]+|[.\-]+$/g, "");
      if (t && !seen[t]) { seen[t] = 1; out.push(t); }
    }
    return out;
  }

  /* Score a candidate against a whole query, which may be several terms. */
  function scoreAny(hay, q) {
    var terms = queryTerms(q);
    if (!terms.length) return 0;
    if (terms.length === 1) return score(hay, terms[0]);
    var best = -1;
    for (var i = 0; i < terms.length; i++) {
      var s = score(hay, terms[i]);
      /* score() reports "no match" as -1 and a match as 1-4, and lower is better. */
      if (s < 0) continue;
      if (best === -1 || s < best) best = s;
    }
    return best;
  }

  function plural(n, word) {
    return n + " " + word + (n === 1 ? "" : "s");
  }

  /* ── Countdowns ─────────────────────────────────────────────────── */
  function dateFor(el) {
    var host = el.closest("[data-exam-date]");
    if (host) return host.getAttribute("data-exam-date");
    var own = el.getAttribute("data-exam-date");
    if (own) return own;
    var sib = el.parentElement && el.parentElement.querySelector("[data-exam-date]");
    return sib ? sib.getAttribute("data-exam-date") : null;
  }

  function updateCountdowns() {
    var today = startOfToday();
    var nodes = document.querySelectorAll("[data-countdown]");
    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var target = parseDate(dateFor(el));
      if (!target) {
        el.textContent = "";
        continue;
      }
      var diff = Math.round((target - today) / DAY);
      /* The same four phrases the freshness stamp uses, and the same case. */
      if (diff > 1) el.textContent = plural(diff, "Day") + " Left";
      else if (diff === 1) el.textContent = "Tomorrow";
      else if (diff === 0) el.textContent = "Today";
      else el.textContent = plural(Math.abs(diff), "Day") + " Ago";
    }
  }

  /* ── Freshness ──────────────────────────────────────────────────── */
  function updateFreshness() {
    var today = startOfToday();
    var nodes = document.querySelectorAll("[data-last-checked]");

    for (var i = 0; i < nodes.length; i++) {
      var el = nodes[i];
      var checked = parseDate(el.getAttribute("data-last-checked"));
      if (!checked) continue;
      var days = Math.round((today - checked) / DAY);

      /* Title case, and the words are passed in already capitalised rather than transformed
         afterwards. */
      var text =
        days <= 0 ? "Today" : days === 1 ? "Yesterday" : plural(days, "Day") + " Ago";

      var out = el.hasAttribute("data-freshness-text") ? el : el.querySelector("[data-freshness-text]");
      if (out) out.textContent = text;

      var staleAfter = Number(el.getAttribute("data-stale-after") || "14");
      if (days > staleAfter) {
        if (el.hasAttribute("data-freshness-text")) el.classList.add("is-stale");
        if (el.hasAttribute("data-freshness-dot") || el.classList.contains("freshness__dot")) {
          el.classList.add("is-stale");
        }
        /* The dot is a sibling of the <time>, so the rules above miss it. */
        var strip = el.closest(".freshness");
        if (strip) {
          var dot = strip.querySelector("[data-freshness-dot]");
          if (dot) dot.classList.add("is-stale");
        }
      }
    }
  }

  /* ── Theme: binary light/dark ────────────────────────────────────── */
  var STORE_KEY = "examhub-theme";

  function systemIsDark() {
    return !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }

  function storedMode() {
    try {
      var v = localStorage.getItem(STORE_KEY);
      return v === "light" || v === "dark" ? v : null;
    } catch (e) {
      return null;
    }
  }

  function store(mode) {
    try {
      localStorage.setItem(STORE_KEY, mode);
    } catch (e) {
    }
  }

  function applyTheme(mode) {
    var root = document.documentElement;
    root.classList.remove("light", "dark");
    if (mode === "light") root.classList.add("light");
    else if (mode === "dark") root.classList.add("dark");

    var btn = document.getElementById("theme-toggle");
    if (btn) {
      btn.setAttribute("data-mode", mode);
      btn.setAttribute("aria-checked", mode === "dark" ? "true" : "false");
      btn.setAttribute(
        "aria-label",
        mode === "dark" ? "Switch to Light Theme" : "Switch to Dark Theme"
      );
    }
  }

  /* Repaints the page under a cross-fade. */
  function switchTheme(mode) {
    var root = document.documentElement;

    if (typeof root.startViewTransition === "function") {
      root.startViewTransition(function () { applyTheme(mode); });
      return;
    }

    root.classList.add("theme-switching");
    applyTheme(mode);
    /* Drop the class once the fade ends. */
    window.setTimeout(function () {
      root.classList.remove("theme-switching");
    }, 200);
  }

  function initTheme() {
    /* Follow the OS until the user chooses; then the stored choice wins. */
    var mode = storedMode() || (systemIsDark() ? "dark" : "light");
    applyTheme(mode);

    var btn = document.getElementById("theme-toggle");
    if (!btn) return;

    btn.addEventListener("click", function () {
      var next = btn.getAttribute("data-mode") === "dark" ? "light" : "dark";
      store(next);
      switchTheme(next);
    });

    /* Until a choice is stored, keep following the OS if it flips. */
    if (window.matchMedia) {
      var mq = window.matchMedia("(prefers-color-scheme: dark)");
      var onChange = function () {
        if (!storedMode()) applyTheme(mq.matches ? "dark" : "light");
      };
      if (mq.addEventListener) mq.addEventListener("change", onChange);
      else if (mq.addListener) mq.addListener(onChange);
    }
  }

  /* ── Mobile navigation ──────────────────────────────────────────── */
  function initNav() {
    var toggle = document.getElementById("nav-toggle");
    var sidebar = document.getElementById("sidebar");
    var scrim = document.getElementById("scrim");
    var closeBtn = document.getElementById("sidebar-close");
    if (!toggle || !sidebar) return;

    function isDesktop() {
      return window.innerWidth >= 992;
    }

    function setOpen(open) {
      sidebar.classList.toggle("is-open", open);
      if (scrim) scrim.classList.toggle("is-open", open);
      toggle.classList.toggle("is-open", open);
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute("aria-label", open ? "Close Menu" : "Open Menu");
      document.body.classList.toggle("nav-open", open);
    }

    toggle.addEventListener("click", function () {
      setOpen(!sidebar.classList.contains("is-open"));
    });

    if (closeBtn) {
      closeBtn.addEventListener("click", function () {
        setOpen(false);
        toggle.focus();
      });
    }

    if (scrim) {
      scrim.addEventListener("click", function () {
        setOpen(false);
      });
    }

    /* Following a link inside the drawer should close it. */
    sidebar.addEventListener("click", function (e) {
      if (e.target.closest("a") && !isDesktop()) setOpen(false);
    });

    /* A day picked in the calendar closes the drawer on phones too. */
    document.addEventListener("examdates:pick", function () {
      if (!isDesktop()) setOpen(false);
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && sidebar.classList.contains("is-open")) {
        setOpen(false);
        toggle.focus();
      }
    });

    window.addEventListener("resize", function () {
      if (isDesktop()) setOpen(false);
    });
  }

  /* ── Search ─────────────────────────────────────────────────────── */
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function highlight(text, q) {
    var i = text.toLowerCase().indexOf(q);
    if (i < 0) return escapeHtml(text);
    return (
      escapeHtml(text.slice(0, i)) +
      "<mark>" + escapeHtml(text.slice(i, i + q.length)) + "</mark>" +
      escapeHtml(text.slice(i + q.length))
    );
  }

  /* ── Filter listboxes ────────────────────────────────────────────── */
  /* The one open list's place() function, or null. */
  var openListPlace = null;

  window.addEventListener("resize", function () {
    if (openListPlace) openListPlace();
  });

  function initListbox(wrap) {
    /* Two shapes of the same widget. */
    var btn = wrap.querySelector(".filters__select, .filters__combo");
    if (!btn) return null;
    var isCombo = btn.tagName === "INPUT";

    var list = document.getElementById(btn.getAttribute("aria-controls"));
    if (!list) return null;

    var options = Array.prototype.slice.call(list.querySelectorAll('[role="option"]'));
    if (!options.length) return null;

    var text = wrap.querySelector(".filters__select-text");
    /* The search field, present only on the two long pickers. */
    /* In combo mode the control itself is the search field. */
    var search = isCombo ? btn : wrap.querySelector(".filters__search");
    var shown = options.slice();
    var open = false;
    var live = -1;
    /* What the box said when the list last opened. */
    var committed = isCombo ? (btn.getAttribute("value") || "") : "";
    /* The chosen option's data-value (in combo mode, not the displayed text). */
    var current = isCombo ? "" : (btn.value || "");

    function applyFilter() {
      var q = search ? search.value.trim().toLowerCase() : "";
      if (q) {
        /* Scored and ordered, so the best match comes first. */
        var ranked = [];
        for (var n = 0; n < options.length; n++) {
          var r = scoreAny((options[n].textContent || "").toLowerCase(), q);
          if (r > 0) ranked.push({ o: options[n], s: r, i: n });
        }
        ranked.sort(function (a, b) { return a.s - b.s || a.i - b.i; });
        shown = ranked.map(function (r) { return r.o; });
      } else {
        shown = options.slice();
      }
      for (var m = 0; m < options.length; m++) {
        options[m].hidden = shown.indexOf(options[m]) === -1;
      }
      if (search && search.value.trim()) {
        var input = wrap.querySelector(".filters__listbox-count");
        if (input) input.textContent = shown.length + " of " + options.length;
      }
    }

    if (search) {
      search.addEventListener("input", function () {
        /* Typing opens the list. */
        if (!open) setOpen(true);
        else { applyFilter(); mark(0, true); }
      });

      search.addEventListener("keydown", function (e) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          if (!open) setOpen(true);
          else mark(Math.min(live + 1, shown.length - 1), true);
        } else if (e.key === "ArrowUp") {
          if (open) { e.preventDefault(); mark(Math.max(live - 1, 0), true); }
        } else if (e.key === "Enter") {
          /* Only swallow Enter when there is something to take. */
          if (open && live > -1 && shown[live]) { e.preventDefault(); choose(live); }
        } else if (e.key === "Escape") {
          if (!open) return;
          e.preventDefault();
          e.stopPropagation();
          /* Restore the committed choice, as Escape does on a select. */
          if (isCombo) search.value = committed;
          setOpen(false);
        }
      });
    }

    function selected() {
      for (var i = 0; i < options.length; i++) {
        if (options[i].getAttribute("aria-selected") === "true") return i;
      }
      return 0;
    }

    /* The single highlighted option, moved by arrows or pointer and announced. */
    function mark(i, scroll) {
      live = i;
      for (var n = 0; n < shown.length; n++) {
        shown[n].classList.toggle("is-active", n === i);
      }
      if (i < 0 || !shown[i]) {
        btn.removeAttribute("aria-activedescendant");
        return;
      }
      if (shown[i].id) {
        btn.setAttribute("aria-activedescendant", shown[i].id);
        /* Scroll just far enough to keep the active option in view. */
        if (scroll && list.scrollHeight > list.clientHeight) {
          var top = shown[i].offsetTop;
          var bottom = top + shown[i].offsetHeight;
          if (top < list.scrollTop) list.scrollTop = top;
          else if (bottom > list.scrollTop + list.clientHeight) {
            list.scrollTop = bottom - list.clientHeight;
          }
        }
      }
    }

    /* Where the open list goes. */

    function place() {
      if (!open) return;
      var body = list.closest(".filters__body");
      if (!body) return;
      var box = body.getBoundingClientRect();
      var anchor = btn.getBoundingClientRect();
      var s = list.style;
      var gap = 8;
      /* Reset first, so the list is measured in its final state. */
      s.top = "";
      s.maxHeight = "";

      var below = window.innerHeight - anchor.bottom - gap;
      var above = anchor.top - gap;
      /* Choose whether the list opens up or down, as an inline `top`. */
      var up = below < Math.min(above, 256) && above > below;

      s.left = (anchor.left - box.left) + "px";
      s.width = anchor.width + "px";
      s.top = (up ? anchor.top - box.top - gap - list.offsetHeight
                   : anchor.bottom - box.top + gap) + "px";
      s.maxHeight = Math.max(96, Math.min(266, up ? above : below)) + "px";
    }

    function setOpen(state) {
      open = state;
      list.hidden = !state;
      btn.setAttribute("aria-expanded", state ? "true" : "false");
      if (state) {
        /* Show before measuring: an unlaid-out list has height 0. */
        place();
        openListPlace = place;
      } else {
        list.style.top = "";
        list.style.left = "";
        list.style.width = "";
        list.style.maxHeight = "";
        openListPlace = null;
      }
      if (state && search) {
        applyFilter();
        /* Filtering changed the height, so measure again. */
        place();
        search.focus();
        /* Not .select(): keep a half-typed query when the list reopens. */
        try {
          var at = search.value.length;
          search.setSelectionRange(at, at);
        } catch (e) { /* not all input types support selection ranges */ }
      }
      mark(state ? selected() : -1);
    }

    /* Commits an option element, not an index. */
    function commit(opt, notify) {
      if (!opt) return;
      for (var n = 0; n < options.length; n++) {
        options[n].setAttribute("aria-selected", options[n] === opt ? "true" : "false");
      }
      current = opt.getAttribute("data-value") || "";
      btn.value = current;
      if (text) text.textContent = opt.textContent;
      if (isCombo) {
        btn.value = opt.getAttribute("data-label") || opt.textContent;
        committed = btn.value;
      } else if (search) {
        /* A two-part widget's typed query, separate from the value just chosen --
           in combo mode `search` is `btn` itself, so clearing it here would wipe
           the label this just set, and the box would always read its placeholder. */
        search.value = "";
      }
      applyFilter();
      setOpen(false);
      /* Fire a real change event so the form's handler applies it. */
      if (notify !== false) {
        btn.dispatchEvent(new Event("change", { bubbles: true }));
      }
    }

    /* Commits index into `shown`: only visible options can be picked. */
    function choose(i, notify) {
      commit(shown[i], notify);
    }

    /* Enter and Space arrive here as a click. */
    btn.addEventListener("click", function () {
      setOpen(!open);
    });

    btn.addEventListener("keydown", function (e) {
      var k = e.key;

      if (!open) {
        /* Like a select: arrows open the list on the current choice. */
        if (k === "ArrowDown" || k === "ArrowUp") {
          e.preventDefault();
          setOpen(true);
        } else if (k === "Home" || k === "End") {
          e.preventDefault();
          setOpen(true);
          mark(k === "Home" ? 0 : shown.length - 1, true);
        }
        return;
      }

      if (k === "ArrowDown") {
        e.preventDefault();
        mark(Math.min(live + 1, shown.length - 1), true);
      } else if (k === "ArrowUp") {
        e.preventDefault();
        mark(Math.max(live - 1, 0), true);
      } else if (k === "Home") {
        e.preventDefault();
        mark(0, true);
      } else if (k === "End") {
        e.preventDefault();
        mark(shown.length - 1, true);
      } else if (k === "Enter" || k === " ") {
        e.preventDefault();
        choose(live < 0 ? selected() : live);
      } else if (k === "Escape") {
        /* Closes and leaves the choice as it was, which is the whole
           point of Escape on a select. */
        e.preventDefault();
        setOpen(false);
      } else if (k === "Tab") {
        setOpen(false);
      }
    });

    list.addEventListener("click", function (e) {
      var opt = e.target.closest && e.target.closest('[role="option"]');
      if (!opt || !list.contains(opt)) return;
      choose(shown.indexOf(opt));
      /* Options aren't focusable, so return focus to the button. */
      btn.focus();
    });

    list.addEventListener("mousemove", function (e) {
      var opt = e.target.closest && e.target.closest('[role="option"]');
      if (opt && list.contains(opt)) mark(options.indexOf(opt));
    });

    document.addEventListener("click", function (e) {
      if (open && !wrap.contains(e.target)) {
        if (isCombo) search.value = committed;
        setOpen(false);
      }
    });

    return {
      button: btn,
      /* Back to "Any", which is options[0] by construction. */
      reset: function () { commit(options[0], false); },
      /* The value the filter needs, not the label shown. */
      value: function () { return current; }
    };
  }

  /* ── Exam list filters ────────────────────────────────────────────── */
  /* The Filters disclosure, which works before index.json arrives. */
  function initFilterBody() {
    /* The full hint doesn't fit a phone's search box; a shorter one does. */
    var q = document.getElementById("filter-q");
    if (q && window.matchMedia) {
      var full = q.placeholder, narrow = window.matchMedia("(max-width: 36rem)");
      var hint = function () { q.placeholder = narrow.matches ? "Search Exams" : full; };
      hint();
      if (narrow.addEventListener) narrow.addEventListener("change", hint);
    }
    var form = document.getElementById("exam-filters");
    var toggle = document.getElementById("filters-toggle");
    var body = document.getElementById("filters-body");
    var wrap = document.querySelector(".filters__body");
    if (!form) return;
    /* Touching the bar fetches the data it filters, if it isn't here yet. */
    form.addEventListener("focusin", ensureData);
    form.addEventListener("pointerdown", ensureData);

    /* The state lives on the form, not the body. */
    function setBodyOpen(open) {
      if (!toggle || !body || !wrap) return;
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      if (open) {
        body.removeAttribute("inert");
        form.removeAttribute("data-filters-closed");
      } else {
        body.setAttribute("inert", "");
        form.setAttribute("data-filters-closed", "");
      }
    }

    if (toggle && body && wrap) {
      setBodyOpen(toggle.getAttribute("aria-expanded") === "true");
      toggle.addEventListener("click", function () {
        setBodyOpen(toggle.getAttribute("aria-expanded") !== "true");
      });
    }
  }

  function initFilters(data) {
    var form = document.getElementById("exam-filters");
    var grid = document.getElementById("exam-grid");
    if (!form || !grid) return;

    /* One card per exam: the TBA and Completed sections repeat some of the month's cards. */
    var cards = grid ? Array.prototype.slice.call(grid.querySelectorAll('[data-section="month"] .card')) : [];
    if (!cards.length) cards = Array.prototype.slice.call(grid.querySelectorAll(".card"));
    if (!cards.length) return;
    var copiesOf = {};
    var monthHrefs = {};
    cards.forEach(function (c) { monthHrefs[c.getAttribute("href")] = 1; });
    grid.querySelectorAll('.bymonth__group:not([data-section="month"]) .card').forEach(function (c) {
      var h = c.getAttribute("href");
      if (monthHrefs[h]) {
        (copiesOf[h] || (copiesOf[h] = [])).push(c);
      } else {
        /* No month counterpart: a tracked exam with no cycle at all, never in that
           section. It gets no copy to stay in sync with -- it is its own item. */
        cards.push(c);
      }
    });

    var q = document.getElementById("filter-q");
    var cat = document.getElementById("filter-cat");
    var status = document.getElementById("filter-status");
    var kind = document.getElementById("filter-kind");
    var when = document.getElementById("filter-when");
    var confirmed = document.getElementById("filter-confirmed");
    var count = document.getElementById("filter-count");
    var reset = document.getElementById("filter-reset");
    var empty = document.getElementById("exam-grid-empty");

    /* The Exam and Body lists, filled before the pickers read their options. */
    function fill(listId, rows) {
      var list = document.getElementById(listId);
      if (!list) return;
      var frag = document.createDocumentFragment();
      rows.forEach(function (r, i) {
        var li = document.createElement("li");
        li.className = "filters__option";
        li.id = listId + "-o" + (i + 1);
        li.setAttribute("role", "option");
        li.setAttribute("data-value", r.v);
        li.setAttribute("data-label", r.v === r.l ? r.v : r.l);
        li.setAttribute("aria-selected", "false");
        li.textContent = r.text;
        frag.appendChild(li);
      });
      list.appendChild(frag);
    }
    fill("filter-exams-list", data.cards.map(function (c) { return { v: c.u, l: c.t, text: c.t }; }));
    var bodyCount = {};
    cards.forEach(function (c) {
      (c.getAttribute("data-f-body") || "").split("|").filter(Boolean).forEach(function (b) {
        bodyCount[b] = (bodyCount[b] || 0) + 1;
      });
    });
    fill("filter-body-list", Object.keys(bodyCount).sort().map(function (b) {
      return { v: b, l: b, text: b + " (" + bodyCount[b] + ")" };
    }));

    var picks = [];
    var wraps = Array.prototype.slice.call(form.querySelectorAll(".filters__pick"));
    for (var w = 0; w < wraps.length; w++) {
      var pick = initListbox(wraps[w]);
      if (pick) picks.push(pick);
    }

    /* The two long pickers, found by the id on their control. */
    var examPick = null, bodyPick = null;
    for (var pi = 0; pi < picks.length; pi++) {
      var id = picks[pi].button.id;
      if (id === "filter-exams") examPick = picks[pi];
      if (id === "filter-body") bodyPick = picks[pi];
    }

    /* The known_as entries, keyed by the record's URL, from index.json. */
    var aliasOf = data.aliases || {};

    /* One pass over the cards, capturing what filtering needs as plain fields. */
    var items = cards.map(function (el) {
      var pill = el.querySelector(".pill");
      var titleEl = el.querySelector(".card__title");
      return {
        el: el,
        /* Its position before search touches order, so a cleared search puts
           the month's date order (or the TBA list's) back exactly. */
        baseOrder: el.style.order || "",
        /* The printed title, for naming exams in the Dates view. */
        title: (titleEl ? titleEl.textContent : "") || "",
        text: [
          (el.querySelector(".card__title") || {}).textContent || "",
          el.getAttribute("data-f-body") || "",
          el.getAttribute("data-f-cat") || "",
          /* A longer name worth matching on but not worth printing as the title
             (a tracked card's full catalogue name; a future card's own aliases). */
          el.getAttribute("data-f-alt") || ""
        ].concat(aliasOf[el.getAttribute("href") || ""] || [])
          .join(" ").toLowerCase(),
        body: (el.getAttribute("data-f-body") || "").toLowerCase(),
        bodies: (el.getAttribute("data-f-body") || "").split("|").filter(Boolean),
        cats: (el.getAttribute("data-f-cat") || "").toLowerCase(),
        date: el.getAttribute("data-f-date") || "",
        /* The milestone kinds this record has, as an array. */
        kinds: (el.getAttribute("data-f-kinds") || "").split("|").filter(Boolean),
        provisional: el.getAttribute("data-f-prov") === "1",
        key: pill ? (pill.className.match(/pill--([a-z]+)/) || [])[1] || "" : ""
      };
    });

    function matches(it, needle, catV, statusV, kindV, horizon, needConfirmed) {
      /* The same matcher as the sidebar, so both boxes find the same records. */
      if (needle && scoreAny(it.text, needle) < 0) return false;
      if (catV && it.cats.indexOf(catV.toLowerCase()) === -1) return false;
      if (statusV && it.key !== statusV) return false;
      /* Membership, not equality: a record can have several kinds. */
      if (kindV && it.kinds.indexOf(kindV) === -1) return false;
      if (needConfirmed && it.provisional) return false;
      if (horizon) {
        /* An exam with no published date cannot satisfy a date filter. */
        if (!it.date) return false;
        var diff = (parseDate(it.date) - startOfToday()) / DAY;
        if (diff < 0 || diff > horizon) return false;
      }
      return true;
    }

    /* The chosen exams and bodies, as a Set of record URLs and a Set of body names. */
    function examSet() {
      var s = new Set();
      var v = examPick && examPick.value();
      if (v) s.add(v);
      return s;
    }

    function bodySet() {
      var s = new Set();
      var v = bodyPick && bodyPick.value();
      if (v) s.add(v);
      return s;
    }

    function apply() {
      var needle = (q && q.value || "").trim().toLowerCase();
      var catV = cat ? cat.value : "";
      var statusV = status ? status.value : "";
      var kindV = kind ? kind.value : "";
      var horizon = when && when.value ? Number(when.value) : 0;
      var needConfirmed = !!(confirmed && confirmed.checked);
      var examUrls = examSet();
      var bodyNames = bodySet();

      var shown = 0;
      var undated = [];
      for (var i = 0; i < items.length; i++) {
        var it = items[i];
        var ok = matches(it, needle, catV, statusV, kindV, horizon, needConfirmed);
        if (ok && examUrls.size && !examUrls.has(it.el.getAttribute("href") || "")) ok = false;
        if (ok && bodyNames.size) {
          var any = false;
          for (var b = 0; b < it.bodies.length; b++) {
            if (bodyNames.has(it.bodies[b])) { any = true; break; }
          }
          if (!any) ok = false;
        }
        /* A search term ranks its own matches (exact, then initials/prefix, then
           fuzzy) ahead of each other within whatever group the card is already
           in; with no term, the group's own order (date, or the TBA/Completed
           list's) is restored exactly. */
        if (needle) {
          it.el.style.order = ok ? String(scoreAny(it.text, needle)) : "9";
        } else if (it.el.style.order !== it.baseOrder) {
          it.el.style.order = it.baseOrder;
        }
        it.el.hidden = !ok;
        (copiesOf[it.el.getAttribute("href")] || []).forEach(function (c) { c.hidden = !ok; });
        if (ok) {
          shown++;
          /* The records this filter found that the Dates view cannot show. */
          if (!it.kinds.length) {
            undated.push({ t: it.title, u: it.el.getAttribute("href") || "" });
          }
        }
      }

      if (empty) empty.hidden = shown !== 0;

      /* Published for the Dates view, which cannot read the cards. */
      window.examFilters = {
        q: needle,
        cat: catV,
        status: statusV,
        /* The milestone kind. */
        kind: kindV,
        exams: Array.prototype.slice.call(examUrls),
        body: bodyNames.size ? Array.prototype.slice.call(bodyNames)[0] : "",
        /* How many records the filter found, and how many of those the Dates view has no way to
           draw. */
        shown: shown,
        undated: undated
      };
      if (window.examDatesRepaint) window.examDatesRepaint();
      var active = !!(needle || catV || statusV || kindV || horizon ||
        needConfirmed || examUrls.size || bodyNames.size);
      if (window.examGroupsRecount) window.examGroupsRecount(active);
      if (reset) reset.hidden = !active;
      document.documentElement.classList.toggle("is-filtering", !!active);

      /* The count, last, once `active` is known. */
      /* "Showing" is its own word so a phone can drop it and keep the number */
      if (count) {
        count.textContent = "";
        if (active) {
          var word = document.createElement("span");
          word.className = "filters__count-word";
          word.textContent = "Showing ";
          count.appendChild(word);
          count.appendChild(document.createTextNode(shown + (shown === 1 ? " Exam" : " Exams")));
        }
      }
    }

    function resetPicks() {
      for (var i = 0; i < picks.length; i++) picks[i].reset();
    }

    /* Typing in the two search fields is not a filter. */
    var searchFields = form.querySelectorAll(".filters__combo");
    for (var sf = 0; sf < searchFields.length; sf++) {
      searchFields[sf].addEventListener("input", function (e) {
        e.stopPropagation();
      });
    }

    form.addEventListener("input", apply);
    form.addEventListener("change", apply);
    form.addEventListener("reset", function () {
      /* The three choice filters are buttons, and a button is not a resettable element. */
      resetPicks();
      /* Re-apply after form.reset() returns, since the event fires first. */
      Promise.resolve().then(apply);
    });
    if (examPick) examPick.button.addEventListener("change", apply);
    if (bodyPick) bodyPick.button.addEventListener("change", apply);

    /* The search button and Enter both submit. count is role="status", so it
       announces the new total on its own; moving focus there too just yanked
       the highlight away from the field the reader was still typing in. */
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      apply();
    });

    document.addEventListener("click", function (e) {
      if (e.target.closest && e.target.closest("[data-filter-reset]")) {
        /* every reset goes all the way back to the opening view */
        if (window.examResetView) window.examResetView();
        else { form.reset(); apply(); }
      }
    });

    apply();
  }

  /* ── The month section of the grid ──────────────────────────────── */
  /* Both views show one month: the bar's, then TBA and Completed. The page arrives with its
     own month drawn; this keeps it right as the month, search and filters change. */
  function initByMonth(grid, data) {
    var label = document.getElementById("cal-month");
    var monthGroup = grid.querySelector('.bymonth__group[data-section="month"]');
    var note = grid.querySelector(".bymonth__none");
    if (!label || !monthGroup || !note) return;
    /* month -> { exam link -> its first date that month }; upcoming only, a past month shows all */
    var byMonth = {}, pastMonth = {}, now = new Date();
    var today = now.getFullYear() + "-" + String(now.getMonth() + 1).padStart(2, "0") + "-" + String(now.getDate()).padStart(2, "0");
    data.events.forEach(function (e, i) {
      var into = e.d < today ? pastMonth : byMonth;
      var m = into[e.d.slice(0, 7)] || (into[e.d.slice(0, 7)] = {});
      if (!(e.u in m)) m[e.u] = { i: i, e: e };
    });
    /* A card names its first date in the month, not its next date. */
    var MEANING = { registration_open: "registration", registration_deadline: "registration",
      correction_open: "correction", correction_deadline: "correction",
      exam_date: "exam_date", admit_card: "admit_card", city_intimation: "admit_card", result: "result" };
    function longDate(iso) {
      var p = iso.split("-");
      return p[0] + ", " + MONTHS[Number(p[1]) - 1] + " " + p[2];
    }
    function monthChip(card, e) {
      var own = card.querySelector(".card__status:not(.card__monthchip)");
      var chip = card.querySelector(".card__monthchip");
      if (!chip) {
        chip = document.createElement("span");
        if (own) own.parentNode.insertBefore(chip, own); else card.insertBefore(chip, card.firstChild);
      }
      chip.className = "card__status card__monthchip pill pill--upcoming pill--" + (MEANING[e.k] || "done");
      chip.textContent = (e.l || "Date") + " ";
      var d = document.createElement("span");
      d.className = "pill__date";
      d.textContent = longDate(e.d);
      chip.appendChild(d);
    }
    function applySync() {
      var t = label.textContent.trim().split(/\s+/), m = MONTHS.indexOf(t[0]);
      if (m < 0) return;
      var key = t[1] + "-" + String(m + 1).padStart(2, "0"), inMonth = (key < today.slice(0, 7) ? pastMonth : byMonth)[key] || {};
      monthGroup.querySelector(".bymonth__name").textContent = t[0] + " " + t[1];
      monthGroup.querySelectorAll(".card").forEach(function (card) {
        var r = inMonth[card.getAttribute("href")];
        card.classList.toggle("card--offmonth", r === undefined);
        card.style.order = r === undefined ? "" : r.i;
        if (r !== undefined) monthChip(card, r.e);
      });
      var shown = recount();
      note.querySelector(".bymonth__title").textContent = t[0] + " " + t[1];
      note.querySelector(".cal__none").textContent = key < today.slice(0, 7) ? "No dates this month." : "No upcoming dates this month.";
    }
    /* The swap is a show/hide on every card, which can't be transitioned; fade the
       section across it instead of applying it mid-paint. This matters most on the
       very first call: the page already painted its own month's cards before any
       script ran, and if a reload lands on a different saved month, this call is
       what swaps that whole set out -- without the fade, that read as a sudden pop.
       But most loads land back on the same month the server already drew (no pin, or
       a pin that matches today); that case has nothing to swap, so skip the fade
       outright instead of dipping the whole section to nothing and back for no
       visible change -- that read as its own, different flicker. */
    function sync() {
      var t = label.textContent.trim().split(/\s+/), m = MONTHS.indexOf(t[0]);
      var key = m < 0 ? null : t[1] + "-" + String(m + 1).padStart(2, "0");
      var calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      if (calm || key === grid.dataset.month) { applySync(); return; }
      monthGroup.classList.add("bymonth__group--switching");
      setTimeout(function () {
        applySync();
        requestAnimationFrame(function () {
          monthGroup.classList.remove("bymonth__group--switching");
        });
      }, 160);
    }
    /* The count in brackets is what the section shows now: month, search and filters. */
    var filtering = false;
    var tbaStatEl = document.querySelector('[data-stat="awaiting-date"] .stat__value');
    var calmMotion = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    /* The TBA badge and the stats-band figure both show this same count, but recount()
       is the only place that ever computes it -- so it is also the only place that ever
       writes either of them. Two separate call sites reading the DOM afterwards to decide
       how to animate a change could each catch a different, not-yet-settled value if a
       second recount() happened to land between the read and the write; writing here,
       once, from the number this call just computed, cannot race itself. */
    function setCount(el, n, render) {
      var from = Number(el.dataset.n || "0");
      el.dataset.n = n;
      if (!("animated" in el.dataset)) {
        el.dataset.animated = "1";
        render(n);
        return;
      }
      if (from === n || calmMotion) { render(n); return; }
      var start = null, dur = 600, settled = false;
      function tick(now) {
        if (settled) return;
        if (start === null) start = now;
        var p = Math.min(1, (now - start) / dur);
        render(Math.round(from + (n - from) * (1 - Math.pow(1 - p, 3))));
        if (p < 1) requestAnimationFrame(tick);
        else settled = true;
      }
      requestAnimationFrame(tick);
      /* A backgrounded tab, a throttled rAF, or any other reason the browser stops
         ticking leaves the figure wherever the last frame left it -- possibly still
         mid-count -- with nothing left to ever correct it, since nothing here reads
         the DOM back to check. This guarantees the true value lands regardless of
         whether animation frames kept coming. */
      setTimeout(function () { if (!settled) { settled = true; render(n); } }, dur + 100);
    }
    /* month changes recount without knowing the filters, so keep the last word on them */
    function recount(f) {
      if (f !== undefined) filtering = f;
      var shown = 0, total = 0;
      grid.querySelectorAll(".bymonth__group[data-section]").forEach(function (g) {
        var n = g.querySelectorAll(".card:not([hidden]):not(.card--offmonth)").length;
        total += n;
        var h = g.querySelector(".bymonth__title"), c = h.querySelector(".bymonth__count");
        if (!c) { c = document.createElement("span"); c.className = "bymonth__count"; h.appendChild(c); }
        setCount(c, n, function (shownN) {
          c.textContent = shownN ? "(" + shownN + (shownN === 1 ? " Exam)" : " Exams)") : "";
        });
        if (g.dataset.section === "~1tba" && tbaStatEl) {
          setCount(tbaStatEl, n, function (shownN) { tbaStatEl.textContent = String(shownN); });
        }
        /* a section the search empties is hidden, not left as a bare heading */
        if (g !== monthGroup) g.hidden = !n;
        /* a search opens folded sections it has matches in, once; clearing it folds them back */
        if (filtering && n && !g.open && !g.dataset.autoOpen) { g.dataset.autoOpen = "1"; g.open = true; }
        if (!filtering && g.dataset.autoOpen) { var was = g.dataset.autoOpen; delete g.dataset.autoOpen; if (was === "1") g.open = false; }
        if (g === monthGroup) shown = n;
      });
      monthGroup.classList.toggle("bymonth__group--off", !shown);
      /* the empty-month note is only for a site with nothing at all; a search that empties
         everything has its own message */
      note.hidden = total > 0 || filtering;
      return shown;
    }
    window.examGroupsRecount = recount;
    /* A reload comes back to the saved month. Land sync() on it directly: otherwise this
       first pass draws the page's own built month, and a moment later initDates() points
       the label at the saved month, which the observer below redraws to -- a visible jump. */
    var savedMonth = window.examPlace && window.examPlace.get("month");
    if (savedMonth && savedMonth.pinned) {
      label.textContent = MONTHS[savedMonth.m] + " " + savedMonth.y;
    }
    sync();
    new MutationObserver(sync).observe(label, { childList: true, characterData: true, subtree: true });
  }

  /* ── The rest of the data, fetched after first paint ──────────────── */
  /* The page carries its own month. index.json has every date, every record's card and the
     search aliases; switching months, searching and filtering wait for it. */
  var dataPromise = null;
  function ensureData() {
    if (dataPromise) return dataPromise;
    var grid = document.getElementById("exam-grid");
    var url = grid && grid.getAttribute("data-index");
    if (!url) return (dataPromise = Promise.resolve(null));
    dataPromise = fetch(url)
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) { hydrate(grid, data); return data; })
      .catch(function (err) {
        /* Say so, and let the next touch of the bar try again. */
        console.error("[examhub] could not load " + url + ":", err);
        dataPromise = null;
        return null;
      });
    return dataPromise;
  }

  function hydrate(grid, data) {
    /* initByMonth's own startup sync() calls recount() before this function has added a
       single off-month or tracked-stub card to the DOM, so that first count -- real,
       server-rendered exams only -- becomes the baseline every later recount() (inside
       initFilters, inside a month switch, ...) animates up from. Calling it here, before
       any of the appends below, is what makes the "jump" the stubs cause into a counted-up
       animation rather than a flash straight to the final number: recount() is the one
       place that ever draws these figures, so there is nothing left to race. */
    initByMonth(grid, data);
    /* Every record's card joins the month section, hidden until its month is shown. */
    var into = grid.querySelector('.bymonth__group[data-section="month"] .card-grid');
    if (into) {
      var have = {}, elsewhere = {};
      into.querySelectorAll(".card").forEach(function (c) { have[c.getAttribute("href")] = 1; });
      grid.querySelectorAll('.bymonth__group:not([data-section="month"]) .card').forEach(function (c) {
        elsewhere[c.getAttribute("href")] = c;
      });
      var tmp = document.createElement("div"), frag = document.createDocumentFragment();
      data.cards.forEach(function (c) {
        if (have[c.u]) return;
        /* TBA and Completed cards are on the page already; the rest come as markup */
        var el = null;
        if (elsewhere[c.u]) el = elsewhere[c.u].cloneNode(true);
        else if (c.h) { tmp.innerHTML = c.h; el = tmp.firstElementChild; }
        if (!el) return;
        el.classList.add("card--offmonth");
        frag.appendChild(el);
      });
      into.appendChild(frag);
    }
    /* Catalogue exams with no live cycle (examhub_pipeline tracked): hundreds of them, so
       they are never server-rendered (see home.data.json) -- added here, into the always-
       present TBA group, instead. */
    var tbaGrid = grid.querySelector('.bymonth__group[data-section="~1tba"] .card-grid');
    if (tbaGrid && data.tracked && data.tracked.length) {
      var tbaTmp = document.createElement("div"), tbaFrag = document.createDocumentFragment();
      data.tracked.forEach(function (c) {
        tbaTmp.innerHTML = c.h;
        if (tbaTmp.firstElementChild) tbaFrag.appendChild(tbaTmp.firstElementChild);
      });
      tbaGrid.appendChild(tbaFrag);
    }
    initFilters(data);
    initDates(data);
    updateCountdowns();
    updateFreshness();
    /* A saved month other than this page's changes the page's height; settle the scroll again. */
    var m = window.examPlace && window.examPlace.get("month");
    if (m && m.pinned && window.examRestoreScroll) window.examRestoreScroll();
  }

  /* ── Calendar ───────────────────────────────────────────────────── */
  var MONTHS = ["January", "February", "March", "April", "May", "June",
                "July", "August", "September", "October", "November", "December"];
  /* The five words, read out of the Kind filter's own options. */
  function readKinds() {
    /* Labels and order, from one walk. */
    var order = [];
    var labels = {};
    var opts = document.querySelectorAll("#filter-kind-list .filters__option");
    for (var i = 0; i < opts.length; i++) {
      var v = opts[i].getAttribute("data-value");
      if (!v) continue;
      order.push(v);
      labels[v] = opts[i].getAttribute("data-label") || opts[i].textContent || v;
    }
    return { order: order, labels: labels };
  }
  var KINDS = readKinds();
  var KIND_LABEL = KINDS.labels;
  /* A rank per kind, for sorting. */
  var KIND_RANK = {};
  for (var ki = 0; ki < KINDS.order.length; ki++) KIND_RANK[KINDS.order[ki]] = ki;
  var MAX_PER_DAY = 3;

  /* The Dates view: a day-grouped list of every date. */
  function initDates(data) {
    var root = document.getElementById("dates");
    if (!root) return;
    if (!data || !data.events || !data.events.length) return;

    /* The stepper is links to the month pages until now; as buttons it switches in place. */
    function asButton(a) {
      if (!a || a.tagName !== "A") return a;
      var b = document.createElement("button");
      b.type = "button";
      for (var n = 0; n < a.attributes.length; n++) {
        var at = a.attributes[n];
        if (at.name !== "href" && at.name !== "aria-disabled") b.setAttribute(at.name, at.value);
      }
      while (a.firstChild) b.appendChild(a.firstChild);
      a.parentNode.replaceChild(b, a);
      return b;
    }
    asButton(document.getElementById("cal-prev"));
    asButton(document.getElementById("cal-next"));

    var events = data.events;
    var monthEl = document.getElementById("cal-month");
    var flyout = document.getElementById("cal-flyout");
    var flyBody = document.getElementById("cal-fly-body");
    var flyYears = document.getElementById("cal-years");
    var flyCaption = document.getElementById("cal-fly-caption");
    var resetBtn = document.getElementById("cal-reset");
    var monthWrap = monthEl && monthEl.closest(".cal__picker");
    var listEl = document.getElementById("cal-list");
    var listHead = document.getElementById("cal-list-heading");
    var prev = document.getElementById("cal-prev");
    var next = document.getElementById("cal-next");
    var nav = document.querySelector(".cal__nav");

    /* An ISO day string, zero padded. */
    function iso(y, m, d) {
      return y + "-" + ("0" + (m + 1)).slice(-2) + "-" + ("0" + d).slice(-2);
    }

    var todayKey = iso(startOfToday().getFullYear(), startOfToday().getMonth(),
                       startOfToday().getDate());

    var today = startOfToday();
    /* The month this page is for: the opening month on home, its own on a month page. */
    var grid = document.getElementById("exam-grid");
    var startParts = String((grid && grid.getAttribute("data-month")) || data.start.slice(0, 7)).split("-");
    var view = {
      y: startParts.length === 2 ? Number(startParts[0]) : today.getFullYear(),
      m: startParts.length === 2 ? Number(startParts[1]) - 1 : today.getMonth()
    };

    /* The one day being shown, as an ISO key, or "" for the whole month. */
    var day = "";

    /* Whether the reader picked a month by hand. */ 
    var monthPinned = false;

    /* The month this view opened on, kept so Reset has something to return to. */
    var opening = { y: view.y, m: view.m };

    /* A reload comes back to the month and day the reader was on. */
    var savedMonth = window.examPlace && window.examPlace.get("month");
    if (savedMonth && savedMonth.pinned) {
      view.y = savedMonth.y; view.m = savedMonth.m;
      monthPinned = true; day = savedMonth.day || "";
    }

    /* Is the month narrowing the list right now? */
    function monthInForce() {
      return monthPinned || !!day || !narrowed();
    }

    /* The months that have something in them, oldest first. */
    var monthKeys = (function () {
      var seen = {};
      var out = [];
      for (var n = 0; n < events.length; n++) {
        var k = events[n].d.slice(0, 7);
        if (!seen[k]) { seen[k] = 1; out.push(k); }
      }
      return out.sort();
    })();

    /* The first and last months that have dates. */
    var monthFirst = monthKeys[0];
    var monthLast = monthKeys[monthKeys.length - 1];

    /* The same filters the card grid reads, so both views agree. */
    function passes(e) {
      var f = window.examFilters || {};
      if (f.body && ("|" + (e.b || "") + "|").indexOf("|" + f.body + "|") === -1) return false;
      if (f.cat && ("|" + (e.c || "") + "|").indexOf("|" + f.cat + "|") === -1) return false;

      /* The free-text query. */
      if (f.q) {
        if (scoreAny(((e.t || "") + " " + (e.l || "") + " " + (e.b || "") +
                      " " + (e.c || "") + " " + (e.q || "")).toLowerCase(),
                     f.q) < 0) return false;
      }
      if (f.exams && f.exams.length) {
        var ok = false;
        for (var n = 0; n < f.exams.length; n++) {
          if (e.u === f.exams[n]) { ok = true; break; }
        }
        if (!ok) return false;
      }
      return true;
    }

    /* Whether the reader has narrowed the set with the filter bar. */
    function narrowed() {
      var f = window.examFilters || {};
      return !!(f.q || f.cat || f.body || f.kind ||
        (f.exams && f.exams.length > 0));
    }

    /* A full date in the site's format. */
    function longDay(key) {
      var d = new Date(Number(key.slice(0, 4)), Number(key.slice(5, 7)) - 1, Number(key.slice(8, 10)));
      return ("0" + d.getDate()).slice(-2) + " " + MONTHS[d.getMonth()] + " " + d.getFullYear();
    }

    function matchesFilters(e) {
      /* The kind comes from the shared filter, not from a control of this view's own. */
      var k = (window.examFilters || {}).kind || "";
      if (k && e.k !== k) return false;
      return passes(e);
    }

    /* Every milestone the filters allow in a month, or in all of them. */
    function rowsFor(ym) {
      return events.filter(function (e) {
        if (ym && e.d.slice(0, 7) !== ym) return false;
        return matchesFilters(e);
      });
    }

    /* The flyout: a month grid. */

    var flyMonths = monthKeys;          /* "YYYY-MM", oldest first */
    var flyAt = { y: view.y, m: view.m };  /* the month being viewed */
    var flyFocusDay = 1;                /* roving tabindex, per render */

    function monthKeyOf(y, m) {
      return y + "-" + ("0" + (m + 1)).slice(-2);
    }

    function flyLabelFor(y, m) {
      return MONTHS[m] + " " + y;
    }

    /* Only years with data, so the year row is a few buttons. */
    /* The year row is the year being looked at with one either side. */
    function buildFlyYears() {
      if (!flyYears) return;
      flyYears.textContent = "";
      var at = flyAt && flyAt.y ? flyAt.y : new Date().getFullYear();
      for (var y = at - 1; y <= at + 1; y++) {
        var b = document.createElement("button");
        b.type = "button";
        b.className = "cal__flyyear";
        b.setAttribute("data-year", String(y));
        b.textContent = String(y);
        flyYears.appendChild(b);
      }
    }

    function markFlyYears() {
      if (!flyYears) return;
      buildFlyYears();
      var bs = flyYears.querySelectorAll(".cal__flyyear");
      for (var n = 0; n < bs.length; n++) {
        var on = bs[n].getAttribute("data-year") === String(flyAt.y);
        bs[n].setAttribute("aria-pressed", on ? "true" : "false");
        bs[n].classList.toggle("cal__flyyear--on", on);
      }
    }

    /* The grid for the month being looked at. */
    function renderFlyout() {
      if (!flyBody) return;
      var y = flyAt.y, m = flyAt.m;
      var key = monthKeyOf(y, m);
      var rows = rowsFor(key);
      var here = flyMonths.indexOf(key) > -1;
      var byDay = {};
      for (var n = 0; n < rows.length; n++) {
        byDay[rows[n].d] = (byDay[rows[n].d] || 0) + 1;
      }

      if (flyCaption) {
        /* Visible now, and it is the only thing on screen naming the month the grid is showing. */
        flyCaption.textContent = here
          ? flyLabelFor(y, m) + " \u2014 " + rows.length +
            (rows.length === 1 ? " date." : " dates.")
          : "Nothing is dated in " + flyLabelFor(y, m) + ".";
      }
      markFlyYears();

      /* Monday-first: Sunday (0) goes in the last column. */
      var first = new Date(y, m, 1);
      var lead = (first.getDay() + 6) % 7;
      var days = new Date(y, m + 1, 0).getDate();
      var cells = lead + days;
      var weeks = Math.ceil(cells / 7);
      var today = startOfToday();
      var todayKey = today.getFullYear() + "-" +
        ("0" + (today.getMonth() + 1)).slice(-2) + "-" +
        ("0" + today.getDate()).slice(-2);

      flyBody.textContent = "";
      for (var w = 0; w < weeks; w++) {
        var tr = document.createElement("tr");
        for (var c = 0; c < 7; c++) {
          var idx = w * 7 + c - lead;
          var td = document.createElement("td");
          if (idx < 0 || idx >= days) {
            td.className = "cal__flycell cal__flycell--void";
            tr.appendChild(td);
            continue;
          }
          var dnum = idx + 1;
          var dkey = key + "-" + ("0" + dnum).slice(-2);
          var count = byDay[dkey] || 0;
          td.className = "cal__flycell";
          if (count) td.className += " cal__flycell--has";

          var b = document.createElement("button");
          b.type = "button";
          b.className = "cal__flyday";
          b.setAttribute("data-day", dkey);
          b.setAttribute("data-month", key);
          /* The name says what pressing it does and carries the visible number whole inside it. */
          b.setAttribute("aria-label", dnum + " " + MONTHS[m] + " " + y +
            (count ? ", " + count + (count === 1 ? " date" : " dates") : ", nothing dated"));
          if (dkey === todayKey) b.setAttribute("aria-current", "date");
          if (day && dkey === day) b.setAttribute("aria-pressed", "true");
          b.tabIndex = -1;
          b.textContent = String(dnum);
          if (count) {
            var dot = document.createElement("span");
            dot.className = "cal__flydot";
            dot.setAttribute("aria-hidden", "true");
            b.appendChild(dot);
          }
          td.appendChild(b);
          tr.appendChild(td);
        }
        flyBody.appendChild(tr);
      }

      /* One tabbable day, and it is today if the grid is showing this
         month, else the first day. */
      var tabs = flyBody.querySelectorAll(".cal__flyday");
      var pick = null;
      for (var t = 0; t < tabs.length; t++) {
        if (tabs[t].getAttribute("aria-current") === "date") { pick = tabs[t]; break; }
      }
      if (!pick && tabs.length) pick = tabs[0];
      if (pick) pick.tabIndex = 0;
    }

    function closeFlyout(focusBtn) {
      if (!flyout) return;
      flyout.hidden = true;
      monthEl.setAttribute("aria-expanded", "false");
      if (focusBtn) monthEl.focus();
    }

    function openFlyout() {
      if (!flyout) return;
      /* Open on the month in force, or keep the one being viewed. */
      if (flyout.hidden) {
        if (monthInForce()) { flyAt.y = view.y; flyAt.m = view.m; }
      }
      flyout.hidden = false;
      monthEl.setAttribute("aria-expanded", "true");
      renderFlyout();
      var on = flyBody.querySelector('[tabindex="0"]');
      if (on) on.focus();
    }

    function toggleFlyout() {
      if (!flyout) return;
      if (flyout.hidden) openFlyout();
      else closeFlyout(true);
    }

    /* The one place that sets the month: a flyout day, the stepper, or Reset. */
    function setMonth(ym) {
      monthPinned = true;
      view.y = Number(ym.slice(0, 4));
      view.m = Number(ym.slice(5, 7)) - 1;
      if (day) {
        day = "";
      }
      render();
    }

    /* Reset: back to the opening month, no pinned day, no hand-picked month. */
    /* Reset means the page as it first opens: no search or filters, the opening month, no
       picked day, at the top. Grid or List stays as it is. */
    function resetView(e) {
      var form = document.getElementById("exam-filters");
      if (form) form.reset();
      monthPinned = false;
      day = "";
      view.y = opening.y;
      view.m = opening.m;
      render();
      var calm = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      window.scrollTo({ top: 0, behavior: calm ? "auto" : "smooth" });
      if (e && e.currentTarget === resetBtn) monthEl.focus();
    }
    window.examResetView = resetView;

    /* How close is close enough to be red. */
    var URGENT_DAYS = 7;

    function isUrgent(e) {
      if (!e.d) return false;
      var then = new Date(Number(e.d.slice(0, 4)), Number(e.d.slice(5, 7)) - 1,
                          Number(e.d.slice(8, 10)));
      var days = Math.round((then - startOfToday()) / 86400000);
      return days >= 0 && days <= URGENT_DAYS;
    }

    function eventChip(e) {
      var a = document.createElement("a");
      a.className = "cal__event cal__event--" + e.k + (e.p ? " cal__event--prov" : "") +
        (isUrgent(e) ? " cal__event--urgent" : "");
      a.href = e.u;

      var k = document.createElement("span");
      k.className = "cal__event-kind";
      /* The milestone's own name, not the kind's. */
      k.textContent = e.l || KIND_LABEL[e.k] || e.k;
      a.appendChild(k);

      /* Kind first, so source and visual order match. */
      var t = document.createElement("span");
      t.className = "cal__event-title";
      t.textContent = e.t;
      a.appendChild(t);

      return a;
    }

    function measurePillWidth() { measureListPills(); }

    function render() {
      var y = view.y, m = view.m;
      var monthKey = y + "-" + ("0" + (m + 1)).slice(-2);

      /* The stepper's two ends, from the render rather than the click. */
      if (prev) prev.disabled = monthKey <= monthFirst;
      if (next) next.disabled = monthKey >= monthLast;

      /* Today, as the same YYYY-MM-DD key the rows are keyed by. */
      var today = startOfToday();
      var todayKey = today.getFullYear() + "-" +
        ("0" + (today.getMonth() + 1)).slice(-2) + "-" +
        ("0" + today.getDate()).slice(-2);

      /* rowsFor(null) returns every month. */
      var lens = monthInForce();
      var monthItems = rowsFor(lens ? monthKey : null);
      /* Past dates fold into an "Earlier" section; a past month or pinned day shows everything. */
      var pastItems = [];
      if (day) {
        monthItems = monthItems.filter(function (e) { return e.d === day; });
      } else if (!lens || monthKey >= todayKey.slice(0, 7)) {
        /* "Earlier" holds only this month's dates before today; older months' dates stay off the list */
        pastItems = monthItems.filter(function (e) { return e.d < todayKey && e.d.slice(0, 7) === todayKey.slice(0, 7); });
        monthItems = monthItems.filter(function (e) { return e.d >= todayKey; });
      }

      if (monthEl) {
        /* "All dates" is not a control anybody chooses any more. */
        monthEl.textContent = lens ? MONTHS[m] + " " + y : "All Dates";
        if (!flyout.hidden) renderFlyout();
      }
      if (resetBtn) {
        /* Is there anything here to undo? */
        var away = view.y !== opening.y || view.m !== opening.m || day || narrowed();
        resetBtn.disabled = !away;
      }

      /* Four headings, because the question being answered is four questions. */
      if (listHead) {
        var examsOnly = window.examFilters && window.examFilters.exams &&
          window.examFilters.exams.length > 0;
        listHead.textContent = day
          ? "Everything on " + longDay(day) + " (" + monthItems.length + ")"
          : !lens
            ? examsOnly
              ? "All Dates for the Selected Exams (" + monthItems.length + ")"
              : "All Dates Matching the Filters (" + monthItems.length + ")"
            : "Everything in " + MONTHS[m] + " " + y +
              (monthItems.length ? " (" + monthItems.length + ")" : "");
      }

      listEl.textContent = "";
      /* Sections as the grid has them: a heading that folds its rows away. */
      var closedSections = window.examListClosed ||
        (window.examListClosed = (window.examPlace && window.examPlace.get("listClosed")) || {});
      function openSection(title, count, unit) {
        var cell = document.createElement("li");
        cell.className = "cal__list-section";
        var det = document.createElement("details");
        det.className = "bymonth__group";
        var key = title === "Dates to Be Announced" ? "~1tba" : title === "Completed" ? "~2done" :
                  title.indexOf("Earlier") === 0 ? "~0past" : "month";
        det.setAttribute("data-section", key);
        /* TBA and Completed start folded; the month starts open */
        det.open = title in closedSections ? !closedSections[title] : key === "month";
        /* a search opens folded sections it has matches in, without remembering it */
        var auto = !det.open && count > 0 && narrowed();
        if (auto) det.open = true;
        det.addEventListener("toggle", function () {
          if (auto) { auto = false; return; }
          closedSections[title] = !det.open;
          if (window.examPlace) window.examPlace.set("listClosed", closedSections);
        });
        var sum = document.createElement("summary");
        sum.className = "bymonth__summary";
        var h = document.createElement("h2");
        h.className = "bymonth__title";
        h.textContent = title;
        /* the count, shown beside the heading */
        if (count) {
          var n = document.createElement("span");
          n.className = "bymonth__count";
          n.textContent = "(" + count + " " + unit + (count === 1 ? "" : "s") + ")";
          h.appendChild(n);
        }
        sum.appendChild(h);
        det.appendChild(sum);
        var ul = document.createElement("ul");
        ul.className = "cal__list-rows";
        det.appendChild(ul);
        cell.appendChild(det);
        listEl.appendChild(cell);
        return ul;
      }
      /* Earlier dates come first, folded; the month's own days follow. */
      var pastRows = pastItems.length
        ? openSection(lens ? "Earlier in " + MONTHS[view.m] : "Earlier Dates", pastItems.length, "Date")
        : null;
      /* Across all months (a search), each month gets its own section and its own count. */
      var spread = !lens && !day && monthItems.length > 0;
      var byMon = {}, monKeys = [];
      if (spread) monthItems.forEach(function (e) {
        var k = e.d.slice(0, 7);
        if (!byMon[k]) { byMon[k] = []; monKeys.push(k); }
        byMon[k].push(e);
      });
      function monTitle(k) { return MONTHS[Number(k.slice(5, 7)) - 1] + " " + k.slice(0, 4); }
      var monthRows = spread
        ? openSection(monTitle(monKeys[0]), byMon[monKeys[0]].length, "Date")
        : openSection(lens || day ? MONTHS[view.m] + " " + view.y : "Upcoming Dates", monthItems.length, "Date");
      /* A day picked from the calendar always shows open. */
      if (day) monthRows.parentNode.open = true;

      /* Matches with no date to place. */
      var fNow = window.examFilters || {};
      var undated = fNow.undated || [];

      if (!monthItems.length) {
        var none = document.createElement("li");
        none.className = "cal__none";
        /* Four empties, and they are not the same emptiness. */ 
        none.textContent = day
          ? "Nothing on the site is dated " + longDay(day) + "."
          : pastItems.length
            ? "No upcoming dates here; earlier ones are above."
          : narrowed() ? "No Exams Match These Filters." : "Nothing is dated this month.";
        monthRows.appendChild(none);
      }

      /* A day block: big number, weekday under it, full date as its name. */
      function dateBlock(dt, extra) {
        var p = document.createElement("p");
        p.className = "cal__list-date" + (extra ? " " + extra : "");
        var full = dt.getFullYear() + ", " + MONTHS[dt.getMonth()] + " " + ("0" + dt.getDate()).slice(-2);
        p.setAttribute("title", full);
        var num = document.createElement("span");
        num.className = "cal__list-dnum";
        num.textContent = ("0" + dt.getDate()).slice(-2);
        var wk = document.createElement("span");
        wk.className = "cal__list-dwk";
        wk.textContent = dt.toLocaleDateString("en-GB", { weekday: "short" });
        var sr = document.createElement("span");
        sr.className = "sr-only";
        sr.textContent = full;
        p.appendChild(num); p.appendChild(wk); p.appendChild(sr);
        return p;
      }
      /* Day groups for a list of dated rows. */
      function renderDays(items, into) {
        var byDay = {};
        for (var n = 0; n < items.length; n++) {
          (byDay[items[n].d] = byDay[items[n].d] || []).push(items[n]);
        }
        Object.keys(byDay).sort().forEach(function (key) {
          var li = document.createElement("li");
          li.className = "cal__list-day";
          /* Today is marked on the group, not the heading. */
          if (key === todayKey) li.setAttribute("aria-current", "date");
          var d = new Date(Number(key.slice(0, 4)), Number(key.slice(5, 7)) - 1, Number(key.slice(8, 10)));
          li.appendChild(dateBlock(d));
          var ul = document.createElement("ul");
          /* Order a day's milestones by when they happen. */
          byDay[key].slice().sort(function (a, b) {
            var ra = KIND_RANK[a.k], rb = KIND_RANK[b.k];
            /* An unranked kind goes last, not first, and the two of them
               keep the order they arrived in. */
            if (ra === undefined) ra = KINDS.order.length;
            if (rb === undefined) rb = KINDS.order.length;
            return ra - rb;
          }).forEach(function (e) {
            var item = document.createElement("li");
            item.appendChild(eventChip(e));
            ul.appendChild(item);
          });
          li.appendChild(ul);
          into.appendChild(li);
        });
      }
      if (spread) {
        renderDays(byMon[monKeys[0]], monthRows);
        for (var mk = 1; mk < monKeys.length; mk++) {
          renderDays(byMon[monKeys[mk]], openSection(monTitle(monKeys[mk]), byMon[monKeys[mk]].length, "Date"));
        }
      } else renderDays(monthItems, monthRows);
      if (pastRows) renderDays(pastItems, pastRows);

      /* Matches with no date, in the site's usual chip and wording. */ 
      /* "Dates to Be Announced" and "Completed", as in the grid. */
      function section(title, items) {
        if (!items.length) return;
        var ul = openSection(title, items.length, "Exam");
        ul.classList.add("cal__undated-list");
        /* No date yet: a grey "?" block stands in the day column. */
        if (title === "Dates to Be Announced") {
          var tba = document.createElement("li");
          tba.className = "cal__list-day cal__list-day--tba";
          var q = document.createElement("p");
          q.className = "cal__list-date cal__list-date--tba";
          q.setAttribute("title", "Date to be announced");
          q.innerHTML = '<span class="cal__list-dnum" aria-hidden="true">?</span>' +
            '<span class="sr-only">Date to be announced</span>';
          var rows = document.createElement("ul");
          tba.appendChild(q); tba.appendChild(rows);
          ul.appendChild(tba);
          ul = rows;
        }
        for (var i = 0; i < items.length; i++) {
          var li = document.createElement("li");
          var a = document.createElement("a");
          a.className = "cal__undated-link cal__list-row";
          a.href = items[i].u;
          var chip = document.createElement("span");
          chip.className = "pill pill--upcoming pill--done cal__list-chip";
          chip.textContent = title;
          a.appendChild(chip);
          var nm = document.createElement("span");
          nm.className = "cal__list-name";
          nm.textContent = items[i].t;
          a.appendChild(nm);
          li.appendChild(a);
          ul.appendChild(li);
        }
      }
      section("Dates to Be Announced", undated);
      var done = [];
      var groups = document.querySelectorAll("#exam-grid .bymonth__group");
      for (var g = 0; g < groups.length; g++) {
        var gt = groups[g].querySelector(".bymonth__title");
        if (!gt || groups[g].getAttribute("data-section") !== "~2done") continue;
        var cards = groups[g].querySelectorAll(".card");
        for (var c = 0; c < cards.length; c++) {
          if (cards[c].hidden) continue;
          var ct = cards[c].querySelector(".card__title");
          done.push({ u: cards[c].getAttribute("href"), t: (ct || cards[c]).textContent.trim() });
        }
      }
      section("Completed", done);

      /* An empty month hides while anything else is listed; its note is for when nothing is. */
      if (!monthItems.length && !day && (pastItems.length || undated.length || done.length)) {
        monthRows.parentNode.parentNode.hidden = true;
      }

      /* Last: needs the rows to exist. */
      measurePillWidth();
      if (window.examPlace) {
        window.examPlace.set("month", { y: view.y, m: view.m, pinned: monthPinned, day: day });
      }
    }

    /* Stepping a month is a change of which month is painted, nothing more. */
    function step(n) {
      /* The stepper always steps. */
      var m = view.m + n;
      var y = view.y + Math.floor(m / 12);
      var mm = ((m % 12) + 12) % 12;
      var k = y + "-" + ("0" + (mm + 1)).slice(-2);
      if (k < monthFirst) k = monthFirst;
      else if (k > monthLast) k = monthLast;
      view.y = Number(k.slice(0, 4));
      view.m = Number(k.slice(5, 7)) - 1;
      monthPinned = true;
      if (day) {
        day = "";
      }
      /* keep an open calendar grid in step with the month */
      if (flyout && !flyout.hidden) { flyAt.y = view.y; flyAt.m = view.m; }
      render();
      if (flyout && !flyout.hidden) renderFlyout();
    }

    if (prev) prev.addEventListener("click", function () { step(-1); });
    if (next) next.addEventListener("click", function () { step(1); });
    if (nav) {
      nav.addEventListener("keydown", function (e) {
        if (e.key === "ArrowLeft") { step(-1); }
        else if (e.key === "ArrowRight") { step(1); }
      });
    }

    /* The calendar grid, opened from the month name. */
    if (monthEl && flyout) {
      buildFlyYears();

      monthEl.addEventListener("click", toggleFlyout);
      monthEl.addEventListener("keydown", function (e) {
        if (e.key === "ArrowDown" || e.key === "Enter" || e.key === " ") {
          if (flyout.hidden) { e.preventDefault(); openFlyout(); }
        }
      });

      if (resetBtn) resetBtn.addEventListener("click", resetView);

      /* A day in the grid selects its month. */
      flyBody.addEventListener("click", function (e) {
        var b = e.target.closest && e.target.closest(".cal__flyday");
        if (!b) return;
        /* A picked day closes the grid and shows that day in the List view. */
        closeFlyout(false);
        document.dispatchEvent(new CustomEvent("examdates:pick", {
          detail: { date: b.getAttribute("data-day") }
        }));
      });

      /* Arrows move by day inside the grid. */
      flyBody.addEventListener("keydown", function (e) {
        var b = e.target.closest && e.target.closest(".cal__flyday");
        if (!b) return;
        var key = e.key;
        if (key === "Escape" || key === "Tab") {
          e.preventDefault();
          closeFlyout(true);
          return;
        }
        var all = flyBody.querySelectorAll(".cal__flyday");
        var i = all.indexOf(b);
        var step = 0;
        if (key === "ArrowRight") step = 1;
        else if (key === "ArrowLeft") step = -1;
        else if (key === "ArrowDown") step = 7;
        else if (key === "ArrowUp") step = -7;
        else if (key === "Home") { step = -(i % 7); }
        else if (key === "End") { step = 6 - (i % 7); }
        else if (key === "PageUp" || key === "PageDown") {
          e.preventDefault();
          /* Page keys step the year. */
          stepFlyYear(key === "PageUp" ? -1 : 1);
          return;
        } else return;
        e.preventDefault();
        var to = i + step;
        if (to < 0) return;
        if (to >= all.length) return;
        all[i].tabIndex = -1;
        all[to].tabIndex = 0;
        all[to].focus();
      });

      /* Show a year in the grid, landing on the month that makes sense. */
      function goFlyYear(y) {
        /* Same month, other year; the grid and page follow. */
        setMonth(monthKeyOf(y, flyAt.m));
        flyAt.y = y;
        renderFlyout();
      }

      /* A year either side, among the years that have anything in them. */
      function stepFlyYear(n) {
        var years = [];
        for (var yi = 0; yi < flyMonths.length; yi++) {
          var yy = flyMonths[yi].slice(0, 4);
          if (years.indexOf(yy) === -1) years.push(yy);
        }
        var at = years.indexOf(String(flyAt.y));
        if (at < 0) return;
        var to = at + n;
        if (to < 0 || to >= years.length) return;
        goFlyYear(Number(years[to]));
        var on = flyBody.querySelector('[tabindex="0"]');
        if (on) on.focus();
      }

      /* The header steppers browse the grid without selecting. */
      if (flyYears) flyYears.addEventListener("click", function (e) {
        var b = e.target.closest && e.target.closest(".cal__flyyear");
        if (!b) return;
        goFlyYear(Number(b.getAttribute("data-year")));
      });

      /* Click outside closes, the same rule the filter bar's pickers use. */
      document.addEventListener("click", function (e) {
        if (flyout.hidden) return;
        if (monthWrap && monthWrap.contains(e.target)) return;
        if (e.target.closest && e.target.closest(".navgroup__month")) return;
        /* a year button is rebuilt by the click that pressed it. */
        if (!document.documentElement.contains(e.target)) return;
        closeFlyout(false);
      });
    }

    /* One way in and two callers: a day pressed in the calendar, and the button above. */
    function pick(key) {
      day = (key && key === day) ? "" : key;

      /* The month moves to the day's. */
      if (day) {
        var d = new Date(Number(day.slice(0, 4)), Number(day.slice(5, 7)) - 1, Number(day.slice(8, 10)));
        view.y = d.getFullYear();
        view.m = d.getMonth();
      }

      render();

      /* A pinned day moves focus to the heading. */
      if (day && listHead) listHead.focus();
    }

    /* The one hook between the calendar and this view. */
    document.addEventListener("examdates:pick", function (e) {
      pick((e.detail || {}).date || "");
    });

    /* The filter bar repaints through this, so the picker's counts go with it. */
    window.examDatesRepaint = function () {
      renderFlyout();
      render();
    };
    buildFlyYears();
    renderFlyout();
    render();
  }

  /* ── The kind legend ───────────────────────────────────────────────── */
  function initCalKey() {
    var btn = document.getElementById("cal-key-toggle");
    var pop = document.getElementById("cal-key-pop");
    if (!btn || !pop) return;

    var open = false;

    /* Under the button, flipping above it when the bar is near the foot of the window. */
    function place() {
      if (!open) return;
      var wrap = btn.parentNode;
      if (!wrap) return;
      var a = wrap.getBoundingClientRect();
      var gap = 8;
      var pad = 8;
      var w = pop.offsetWidth;
      var h = pop.offsetHeight;

      var below = window.innerHeight - a.bottom - gap;
      var above = a.top - gap;
      var up = below < h && above > below;

      var vTop = up ? above - h : a.bottom + gap;
      /* Right edges aligned with the button's. */
      var vLeft = a.right - w;
      var min = pad;
      var max = window.innerWidth - pad - w;

      if (max < min) {
        /* Narrower than the popover: pin it to the left margin. */
        vLeft = min;
      } else if (vLeft < min) {
        /* Right alignment doesn't fit here. */
        vLeft = (window.innerWidth - w) / 2;
      }

      if (vLeft > max) vLeft = max;

      /* Which way it came from, so the rise or the fall in the keyframes points at the button. */
      pop.setAttribute("data-up", up ? "true" : "false");

      pop.style.top = (vTop - a.top) + "px";
      pop.style.left = (vLeft - a.left) + "px";
    }

    function setOpen(state) {
      open = state;
      pop.hidden = !state;
      btn.setAttribute("aria-expanded", state ? "true" : "false");
      if (state) {
        place();
        openListPlace = place;
      } else {
        openListPlace = null;
      }
    }

    btn.addEventListener("click", function () { setOpen(!open); });

    document.addEventListener("click", function (e) {
      if (open && !btn.contains(e.target) && !pop.contains(e.target)) setOpen(false);
    });

    document.addEventListener("keydown", function (e) {
      if (e.key !== "Escape" || !open) return;
      e.stopPropagation();
      setOpen(false);
      /* Escape closes and leaves the focus where a closed disclosure should leave it. */
      btn.focus();
    });
  }

  /* One width for every chip in the day list: the widest one actually in it. Also run on the
     server-drawn list before the data arrives, so the column doesn't jump. */
  function measureListPills() {
    var listEl = document.getElementById("cal-list");
    if (!listEl || !listEl.getClientRects().length) return;
    var pills = listEl.querySelectorAll(".cal__event-kind, .cal__list-chip");
    var widest = 0;
    /* Measure the chips at their own width, not the last month's. */
    var was = listEl.style.getPropertyValue("--pill-w");
    listEl.style.setProperty("--pill-w", "max-content");
    for (var p = 0; p < pills.length; p++) {
      var w = pills[p].getBoundingClientRect().width;
      if (w > widest) widest = w;
    }
    if (widest > 0) listEl.style.setProperty("--pill-w", Math.ceil(widest) + "px");
    else if (was) listEl.style.setProperty("--pill-w", was); else listEl.style.removeProperty("--pill-w");
  }

  /* The Exams / Dates switch. */
  function initViews() {
    var wrap = document.getElementById("views");
    if (!wrap) return;
    var tabs = wrap.querySelectorAll(".views__tab");

    var VIEW_KEY = "examhub-view";

    function show(name) {
      wrap.setAttribute("data-view", name);
      /* Remembered, so a reload comes back to the same view. */
      try { localStorage.setItem(VIEW_KEY, name); } catch (e) { }
      for (var i = 0; i < tabs.length; i++) {
        var on = tabs[i].getAttribute("data-view") === name;
        tabs[i].setAttribute("aria-selected", on ? "true" : "false");
        tabs[i].classList.toggle("is-on", on);
        var panel = document.getElementById(tabs[i].getAttribute("aria-controls"));
        if (panel) panel.hidden = !on;
      }
      /* The day list is sized and counted by script, so it is only worth
         painting once it is on screen. */
      if (window.examDatesRepaint) window.examDatesRepaint();
      else if (name === "dates") measureListPills();
    }

    for (var i = 0; i < tabs.length; i++) {
      (function (tab) {
        tab.addEventListener("click", function () { show(tab.getAttribute("data-view")); });
      })(tabs[i]);
    }

    /* A picked day switches to the List view. */
    document.addEventListener("examdates:pick", function () {
      show("dates");
    });

    wrap.addEventListener("keydown", function (e) {
      if (e.key !== "ArrowRight" && e.key !== "ArrowLeft") return;
      var cur = wrap.getAttribute("data-view");
      var other = cur === "exams" ? tabs[1] : tabs[0];
      if (!other) return;
      e.preventDefault();
      show(other.getAttribute("data-view"));
      other.focus();
    });

    var saved = null;
    try { saved = localStorage.getItem(VIEW_KEY); } catch (e) { }
    show(saved === "dates" ? "dates" : "exams");
    /* The head script's stand-in is done once the real view is painted. */
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { document.documentElement.removeAttribute("data-start-view"); });
    });
  }

  /* ── Boot ───────────────────────────────────────────────────────── */
  /* Fold the Key Dates schedule by width (the one layout decision made in script). */
  var KEYDATES_FOLD_MAX = 900;
  function initKeyDates() {
    var boxes = document.querySelectorAll(".keydates");
    if (!boxes.length) return;

    /* Once the reader has touched one, it is theirs and the width stops mattering. */
    function setFold(d) {
      for (var i = 0; i < boxes.length; i++) {
        if (d.open) boxes[i].setAttribute("open", "");
        else boxes[i].removeAttribute("open");
      }
    }

    function foldForWidth() {
      setFold({
        open: window.innerWidth > KEYDATES_FOLD_MAX
      });
    }

    foldForWidth();

    var touched = false;
    for (var i = 0; i < boxes.length; i++) {
      boxes[i].addEventListener("toggle", function () {
        touched = true;
      });
    }

    var pending;
    window.addEventListener("resize", function () {
      if (touched) return;
      clearTimeout(pending);
      /* Trailing debounce: resize fires many times during a drag. */
      pending = setTimeout(foldForWidth, 150);
    });
  }

  /* ── Saved place: a reload comes back as the reader left the page ── */
  var PLACE_KEY = "examhub-place:" + location.pathname;
  var place = (function () {
    try { return JSON.parse(localStorage.getItem(PLACE_KEY)) || {}; } catch (e) { return {}; }
  })();
  var placeTimer = null;
  function savePlace() {
    clearTimeout(placeTimer);
    placeTimer = setTimeout(function () {
      try { localStorage.setItem(PLACE_KEY, JSON.stringify(place)); } catch (e) { }
    }, 200);
  }
  window.examPlace = { get: function (k) { return place[k]; },
                       set: function (k, v) { place[k] = v; savePlace(); } };

  /* A name for a <details> that survives a rebuild of the page. */
  function detailsKey(d) {
    if (d.id) return "#" + d.id;
    if (d.getAttribute("data-section")) return "s:" + d.getAttribute("data-section");
    var host = d.parentNode && d.parentNode.closest("[id]");
    var all = (host || document).querySelectorAll("details");
    return (host ? "#" + host.id : "") + ">" + Array.prototype.indexOf.call(all, d);
  }

  /* Open and folded sections, and where both scrollers were. */
  function initPlace() {
    var open = place.open || (place.open = {});
    var boxes = document.querySelectorAll("details");
    /* Restoring saved state below flips .open on sections already painted the other
       way; without this guard the chevron plays its rotate transition as if the
       reader had just clicked it. */
    document.documentElement.classList.add("js-restoring-place");
    for (var i = 0; i < boxes.length; i++) {
      (function (d) {
        /* The day list's sections are keyed by title in examListClosed. */
        if (d.closest("#cal-list")) return;
        var k = detailsKey(d);
        if (k in open) d.open = open[k];
        d.addEventListener("toggle", function () {
          /* a section a search opened isn't the reader's choice; don't save it */
          if (d.dataset.autoOpen) { if (!d.open) d.dataset.autoOpen = "closed"; return; }
          open[k] = d.open; savePlace();
        });
      })(boxes[i]);
    }
    requestAnimationFrame(function () {
      requestAnimationFrame(function () { document.documentElement.classList.remove("js-restoring-place"); });
    });

    if ("scrollRestoration" in history) history.scrollRestoration = "manual";
    var side = document.querySelector(".sidebar__upcoming .sidebar__list");
    function restoreScroll() {
      if (place.y) window.scrollTo({ top: place.y, behavior: "instant" });
      if (side && place.side) side.scrollTop = place.side;
    }
    restoreScroll();
    window.examRestoreScroll = restoreScroll;
    /* Late layout (fonts, the day list) can move things; settle once more on load. */
    if (document.readyState !== "complete") window.addEventListener("load", restoreScroll, { once: true });
    window.addEventListener("scroll", function () { place.y = Math.round(window.scrollY); savePlace(); }, { passive: true });
    if (side) side.addEventListener("scroll", function () { place.side = Math.round(side.scrollTop); savePlace(); }, { passive: true });
    window.addEventListener("pagehide", function () {
      try { localStorage.setItem(PLACE_KEY, JSON.stringify(place)); } catch (e) { }
    });
  }

  /* Phones: the search docks into the top bar once it scrolls under it, and undocks on the way back. */
  function initDock() {
    var head = document.querySelector(".filters__head");
    var anchor = document.querySelector(".browse__bar > .cal__keywrap");
    var bar = document.querySelector(".site-header");
    var form = document.getElementById("exam-filters");
    if (!head || !anchor || !bar || !form || !window.matchMedia) return;
    var phone = window.matchMedia("(max-width: 36rem)");
    var docked = false, ticking = false;
    function set(on) {
      if (on === docked) return;
      docked = on;
      head.classList.toggle("is-docked", on);
      document.documentElement.classList.toggle("search-docked", on);
    }
    /* the legend stays in the page, so its edge says when the search row has gone under the bar */
    function check() {
      ticking = false;
      set(phone.matches && anchor.getBoundingClientRect().bottom < bar.getBoundingClientRect().bottom);
    }
    window.addEventListener("scroll", function () {
      if (!ticking) { ticking = true; requestAnimationFrame(check); }
    }, { passive: true });
    if (phone.addEventListener) phone.addEventListener("change", check);
    function calm() { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; }
    /* typing while docked brings the top of the results up under the bar, once the typing pauses */
    var q = document.getElementById("filter-q"), wait = 0;
    if (q) q.addEventListener("input", function () {
      if (!docked) return;
      clearTimeout(wait);
      wait = setTimeout(function () {
        var panel = document.querySelector(".views__panel:not([hidden])");
        if (panel && panel.getBoundingClientRect().top < bar.getBoundingClientRect().bottom) {
          panel.scrollIntoView({ behavior: calm() ? "auto" : "smooth", block: "start" });
        }
      }, 250);
    });
    /* the filters open in the page, so a docked Filters button takes you back to them */
    var toggle = document.getElementById("filters-toggle");
    if (toggle) toggle.addEventListener("click", function () {
      if (!docked) return;
      form.scrollIntoView({ behavior: calm() ? "auto" : "smooth", block: "start" });
    });
    check();
  }

  function init() {
    initTheme();
    initNav();
    initFilterBody();
    initDock();
    initViews();
    initCalKey();
    initKeyDates();
    initPlace();
    updateCountdowns();
    updateFreshness();

    /* The other months and the search index: straight away if the saved place needs them,
       else once the page is idle. */
    if (document.getElementById("exam-grid")) {
      var saved = window.examPlace && window.examPlace.get("month");
      if (saved && saved.pinned) ensureData();
      else if (window.requestIdleCallback) requestIdleCallback(ensureData, { timeout: 3000 });
      else setTimeout(ensureData, 500);
      /* The stepper and the calendar are links until then; touching them fetches it too. */
      var bar = document.querySelector(".navgroup");
      if (bar) { bar.addEventListener("pointerdown", ensureData); bar.addEventListener("focusin", ensureData); }
    }

    /* Hand the root scroller back to the stylesheet. */
    function releaseScrollBehavior() {
      document.documentElement.style.removeProperty("scroll-behavior");
    }
    if (document.readyState === "complete") releaseScrollBehavior();
    else window.addEventListener("load", releaseScrollBehavior, { once: true });
  }

  /* Boot without depending on DOMContentLoaded. */
  var booted = false;
  function boot() {
    if (booted) return;
    booted = true;
    init();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  }
  boot();
})();
