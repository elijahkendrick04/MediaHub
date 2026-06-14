/* =====================================================================
   MediaHub UI kit — progressive-enhancement behaviours for theme-motion.css
   ---------------------------------------------------------------------
   First-party, dependency-free (no React / Framer / CDN). Re-implements the
   interactive half of the borrowed effects (Aceternity UI) as vanilla JS.

   Contract with theme-motion.css:
     pointer effects  -> write --mh-x / --mh-y (0–100%) on the element
     tilt             -> write --mh-rx / --mh-ry (deg)
     reveal / text    -> toggle .is-in (shared Phase-10 reveal class)
     scroll progress  -> write --mh-progress (0–1)
     tabs             -> write --mh-ind-x / --mh-ind-w on the .mh-tabs
     compare          -> write --mh-pos (%)

   Principles: every feature is wrapped so one failure can't break the page;
   continuous / pointer-driven motion is skipped under prefers-reduced-motion;
   everything is a no-op when its target elements are absent. Re-entrant:
   MH.ui.init(root) can be called again on dynamically-inserted HTML.
   ===================================================================== */
(function () {
  "use strict";
  var MH = (window.MH = window.MH || {});
  var REDUCE = false;
  try {
    REDUCE = window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (window.matchMedia) {
      window.matchMedia("(prefers-reduced-motion: reduce)")
        .addEventListener("change", function (e) { REDUCE = e.matches; });
    }
  } catch (e) { /* ancient engine — treat as no-reduce */ }

  function each(root, sel, fn) {
    var list;
    try { list = (root || document).querySelectorAll(sel); }
    catch (e) { return; }
    for (var i = 0; i < list.length; i++) {
      try { fn(list[i], i); } catch (e) { /* per-node isolation */ }
    }
  }
  function clamp(v, lo, hi) { return v < lo ? lo : v > hi ? hi : v; }
  function once(el, key) {
    if (el.getAttribute(key) === "1") return false;
    el.setAttribute(key, "1");
    return true;
  }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  /* --- Pointer position (spotlight / glow-border / glare / lens) -------- */
  function bindPointer(el) {
    if (!once(el, "data-mh-ptr")) return;
    var raf = 0, lastX = 50, lastY = 50;
    function apply() {
      raf = 0;
      el.style.setProperty("--mh-x", lastX + "%");
      el.style.setProperty("--mh-y", lastY + "%");
    }
    el.addEventListener("pointermove", function (ev) {
      var r = el.getBoundingClientRect();
      if (!r.width || !r.height) return;
      lastX = clamp(((ev.clientX - r.left) / r.width) * 100, 0, 100);
      lastY = clamp(((ev.clientY - r.top) / r.height) * 100, 0, 100);
      if (!raf) raf = requestAnimationFrame(apply);
    }, { passive: true });
  }

  /* --- Lens: a zoomed copy of the underlying image -------------------- */
  function bindLens(el) {
    if (!once(el, "data-mh-lens-init")) return;
    var img = el.querySelector("img");
    var src = el.getAttribute("data-mh-lens") || (img && (img.currentSrc || img.src));
    if (!src) return;
    var zoom = el.querySelector(".mh-lens__zoom");
    if (!zoom) {
      zoom = document.createElement("div");
      zoom.className = "mh-lens__zoom";
      el.appendChild(zoom);
    }
    zoom.style.backgroundImage = "url('" + src.replace(/'/g, "%27") + "')";
    bindPointer(el);
  }

  /* --- 3D tilt --------------------------------------------------------- */
  function bindTilt(el) {
    if (!once(el, "data-mh-tilt-init")) return;
    if (REDUCE) return;
    var max = parseFloat(getComputedStyle(el).getPropertyValue("--mh-tilt-max")) || 7;
    var raf = 0, rx = 0, ry = 0;
    function apply() { raf = 0; el.style.setProperty("--mh-rx", rx.toFixed(2) + "deg"); el.style.setProperty("--mh-ry", ry.toFixed(2) + "deg"); }
    el.addEventListener("pointermove", function (ev) {
      var r = el.getBoundingClientRect();
      if (!r.width || !r.height) return;
      var px = (ev.clientX - r.left) / r.width - 0.5;
      var py = (ev.clientY - r.top) / r.height - 0.5;
      ry = clamp(px * max * 2, -max, max);
      rx = clamp(-py * max * 2, -max, max);
      if (!raf) raf = requestAnimationFrame(apply);
    }, { passive: true });
    el.addEventListener("pointerleave", function () {
      el.style.setProperty("--mh-rx", "0deg");
      el.style.setProperty("--mh-ry", "0deg");
    });
  }

  /* --- Infinite marquee: clone children for a seamless -50% loop ------- */
  function bindMarquee(el) {
    if (!once(el, "data-mh-marquee-init")) return;
    var track = el.querySelector(".mh-marquee__track");
    if (!track || track.children.length === 0) return;
    var n = track.children.length;
    for (var i = 0; i < n; i++) {
      var c = track.children[i].cloneNode(true);
      c.setAttribute("aria-hidden", "true");
      track.appendChild(c);
    }
    var speed = parseFloat(el.getAttribute("data-mh-speed"));
    if (speed > 0) track.style.animationDuration = speed + "s";
  }

  /* --- Text-generate: wrap words, reveal on view ---------------------- */
  function splitWords(el) {
    if (!once(el, "data-mh-split")) return;
    var text = el.textContent.replace(/\s+/g, " ").trim();
    if (!text) return;
    var words = text.split(" ");
    el.textContent = "";
    for (var i = 0; i < words.length; i++) {
      var span = document.createElement("span");
      span.className = "mh-word";
      span.style.setProperty("--i", i);
      span.textContent = words[i];
      el.appendChild(span);
      if (i < words.length - 1) el.appendChild(document.createTextNode(" "));
    }
  }

  /* --- Text-generate (immediate): the "AI is writing" caption type-on ---
     Reveals an element's text word-by-word *right now* — for a read-only
     generated-caption preview that's already on screen (roadmap UI2.7), not a
     scroll heading. Differs from splitWords() in two ways that matter for a
     caption: it fires immediately (no IntersectionObserver), and it PRESERVES
     the original whitespace/newlines (splitWords collapses them, which would
     flatten a multi-line caption rendered under white-space:pre-wrap).
     The caption's editable textarea is never passed here — it stays plain.
     Re-building via textContent/createTextNode keeps it XSS-safe; CSS handles
     prefers-reduced-motion (words just appear, no animation). Fails safe: any
     error leaves the original text visible. Returns the element. */
  MH.typeOn = function (el) {
    if (!el) return el;
    // Already typed (e.g. a re-init pass) — just ensure it's revealed.
    if (el.getAttribute("data-mh-typed") === "1") { el.classList.add("is-in"); return el; }
    try {
      var text = el.textContent;
      el.setAttribute("data-mh-typed", "1");
      el.setAttribute("data-mh-split", "1"); // keep splitWords() off this node
      el.classList.add("mh-text-generate");
      if (!text || !text.trim()) { el.classList.add("is-in"); return el; }
      // Tokenise into words + whitespace runs; wrap words, keep spaces verbatim.
      var parts = text.split(/(\s+)/), wi = 0;
      el.textContent = "";
      for (var i = 0; i < parts.length; i++) {
        var part = parts[i];
        if (!part) continue;
        if (/^\s+$/.test(part)) {
          el.appendChild(document.createTextNode(part));
        } else {
          var span = document.createElement("span");
          span.className = "mh-word";
          span.style.setProperty("--i", wi++);
          span.textContent = part;
          el.appendChild(span);
        }
      }
      // Keep the whole reveal time-bounded regardless of caption length:
      // ~1.5s of stagger spread across the words, clamped to a readable 18–55ms.
      var stagger = wi > 1 ? clamp(Math.round(1500 / wi), 18, 55) : 55;
      el.style.setProperty("--mh-stagger", stagger + "ms");
      // The element is already on screen, so trigger the stagger immediately
      // (next frame, so the hidden initial state paints first). Under reduced
      // motion the CSS shows every word at once — adding .is-in is still safe.
      if (REDUCE) { el.classList.add("is-in"); return el; }
      requestAnimationFrame(function () { el.classList.add("is-in"); });
    } catch (e) {
      el.classList.add("is-in"); // fail safe — never hide the caption
    }
    return el;
  };

  /* --- Flapboard: split-flap settle to a target string ---------------- */
  var FLAP_GLYPHS = "0123456789:.";
  function runFlap(el) {
    if (!once(el, "data-mh-flap-run")) return;
    var target = el.getAttribute("data-mh-to");
    if (target == null) target = el.textContent;
    target = String(target);
    el.textContent = "";
    var flaps = [];
    for (var i = 0; i < target.length; i++) {
      var f = document.createElement("span");
      f.className = "mh-flap";
      f.textContent = target[i];
      el.appendChild(f);
      flaps.push(f);
    }
    if (REDUCE) return;
    flaps.forEach(function (f, idx) {
      var ch = f.textContent, ticks = 4 + idx;
      var k = 0;
      var iv = setInterval(function () {
        k++;
        f.classList.add("is-flipping");
        f.textContent = (k >= ticks) ? ch : FLAP_GLYPHS[(Math.random() * FLAP_GLYPHS.length) | 0];
        setTimeout(function () { f.classList.remove("is-flipping"); }, 80);
        if (k >= ticks) clearInterval(iv);
      }, 70);
    });
  }

  /* --- Text-scramble / decode (UI 1.21, Locomotive-style) -------------
     Each character flickers through a random glyph alphabet then settles to
     its final value, staggered left-to-right so the string "decodes" in.
     XSS-safe by construction: it only rewrites the .data of the element's
     existing text nodes — never innerHTML, never a node built from text — so
     embedded markup (<br>, <em>) survives untouched. The final text is
     already in the DOM, so no-JS and reduced-motion users simply read it
     (runScramble no-ops under reduce). Two ways to drive it:
       declarative  <h1 class="mh-scramble">…</h1>  decodes in once on reveal;
       imperative   MH.scrambleTo(el, "new text")    decodes to new text
                    (the processing screen's live "generating" stage label). */
  var SCRAMBLE_GLYPHS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789#%&*+/<>";
  function randGlyph() {
    return SCRAMBLE_GLYPHS.charAt((Math.random() * SCRAMBLE_GLYPHS.length) | 0);
  }
  function isWS(ch) {
    return ch === " " || ch === "\n" || ch === "\t" || ch === " ";
  }
  function runScramble(el) {
    if (!el) return;
    if (el.mhScrambleRaf) { cancelAnimationFrame(el.mhScrambleRaf); el.mhScrambleRaf = 0; }
    var finalText = el.textContent;
    // Reduced motion / nothing useful to do: leave the (already-final) text be.
    if (REDUCE || !finalText || finalText.length > 240) {
      el.classList.remove("is-scrambling");
      el.removeAttribute("aria-busy");
      el.removeAttribute("aria-label");
      return;
    }
    var nodes = [];
    try {
      var walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, null);
      var node;
      while ((node = walk.nextNode())) { if (node.nodeValue) nodes.push(node); }
    } catch (e) { return; }
    if (!nodes.length) return;

    // Per text node: a working char array + a settle-frame per character.
    // Whitespace settles at frame 0 so word gaps (and layout) never wobble.
    var plan = [], live = 0;
    for (var i = 0; i < nodes.length; i++) {
      var s = nodes[i].nodeValue, work = [], ends = [];
      for (var c = 0; c < s.length; c++) {
        if (isWS(s.charAt(c))) { work.push(s.charAt(c)); ends.push(0); }
        else { work.push(randGlyph()); ends.push(-1); live++; }
      }
      plan.push({ node: nodes[i], chars: s, work: work, ends: ends });
    }
    if (!live) return; // whitespace only — nothing to decode

    // Stagger the settle frames left-to-right with jitter (≈0.5–0.9s total).
    var MIN = 6, STEP = 1.15, JITTER = 9, k = 0;
    for (var p = 0; p < plan.length; p++) {
      var en = plan[p].ends;
      for (var q = 0; q < en.length; q++) {
        if (en[q] === -1) { en[q] = MIN + ((k * STEP) | 0) + ((Math.random() * JITTER) | 0); k++; }
      }
    }

    // Transient a11y name while the glyphs resolve; removed on settle so the
    // element's natural accessible name (which renders <br> as a pause) takes
    // back over once the real text is in place.
    el.setAttribute("aria-label", finalText);
    el.classList.add("is-scrambling");
    el.setAttribute("aria-busy", "true");
    var frame = 0;
    function tick() {
      var pending = 0;
      for (var pp = 0; pp < plan.length; pp++) {
        var row = plan[pp], changed = false;
        for (var qq = 0; qq < row.work.length; qq++) {
          if (frame >= row.ends[qq]) {
            if (row.work[qq] !== row.chars.charAt(qq)) { row.work[qq] = row.chars.charAt(qq); changed = true; }
          } else {
            pending++;
            if (Math.random() < 0.5) { row.work[qq] = randGlyph(); changed = true; }
          }
        }
        if (changed) row.node.nodeValue = row.work.join("");
      }
      if (!pending) { // everything locked in — restore the pristine text + clear state
        for (var f = 0; f < plan.length; f++) plan[f].node.nodeValue = plan[f].chars;
        el.classList.remove("is-scrambling");
        el.removeAttribute("aria-busy");
        el.removeAttribute("aria-label"); // natural accessible name takes over
        el.mhScrambleRaf = 0;
        return;
      }
      frame++;
      el.mhScrambleRaf = requestAnimationFrame(tick);
    }
    el.mhScrambleRaf = requestAnimationFrame(tick);
  }

  /* --- IntersectionObserver: reveal / text-generate / count / flap ---- */
  var io = null;
  function observe(el) {
    if (!io) {
      if (!("IntersectionObserver" in window)) { fire(el); return; }
      io = new IntersectionObserver(function (entries) {
        entries.forEach(function (en) {
          if (en.isIntersecting) { fire(en.target); io.unobserve(en.target); }
        });
      }, { rootMargin: "0px 0px -8% 0px", threshold: 0.15 });
    }
    io.observe(el);
  }
  function fire(el) {
    el.classList.add("is-in"); // align to the existing Phase-10 reveal convention
    if (el.classList.contains("mh-flapboard")) runFlap(el);
    // Decode-in once: the guard stops a re-observed node re-scrambling.
    if (el.classList.contains("mh-scramble") && once(el, "data-mh-scrambled")) runScramble(el);
  }

  /* --- Flip-words: cycle the active child ----------------------------- */
  function bindFlipWords(el) {
    if (!once(el, "data-mh-flip-init")) return;
    var words = el.querySelectorAll(".mh-fw");
    if (words.length < 2) { if (words[0]) words[0].classList.add("is-active"); return; }
    var i = 0;
    words[0].classList.add("is-active");
    if (REDUCE) return;
    var interval = parseInt(el.getAttribute("data-mh-interval") || "2200", 10);
    setInterval(function () {
      var cur = words[i];
      cur.classList.remove("is-active");
      cur.classList.add("is-leaving");
      setTimeout(function () { cur.classList.remove("is-leaving"); }, 260);
      i = (i + 1) % words.length;
      words[i].classList.add("is-active");
    }, interval);
  }

  /* --- Tabs: slide the indicator under the active tab ----------------- */
  function bindTabs(el) {
    if (!once(el, "data-mh-tabs-init")) return;
    var ind = el.querySelector(".mh-tabs__ind");
    if (!ind) { ind = document.createElement("span"); ind.className = "mh-tabs__ind"; el.appendChild(ind); }
    function move(tab) {
      if (!tab) return;
      el.style.setProperty("--mh-ind-x", (tab.offsetLeft) + "px");
      el.style.setProperty("--mh-ind-w", (tab.offsetWidth) + "px");
    }
    function active() { return el.querySelector("[aria-selected='true'], .is-active") || el.querySelector("[role='tab'], a, button"); }
    el.addEventListener("click", function (ev) {
      var tab = ev.target.closest("[role='tab'], a, button");
      if (!tab || !el.contains(tab)) return;
      var tabs = el.querySelectorAll("[role='tab'], a, button");
      for (var i = 0; i < tabs.length; i++) {
        tabs[i].classList.toggle("is-active", tabs[i] === tab);
        if (tabs[i].hasAttribute("aria-selected")) tabs[i].setAttribute("aria-selected", tabs[i] === tab ? "true" : "false");
      }
      move(tab);
      var panel = tab.getAttribute("data-mh-panel");
      if (panel) {
        each(document, "[data-mh-panel-id]", function (p) {
          p.hidden = (p.getAttribute("data-mh-panel-id") !== panel);
        });
      }
    });
    requestAnimationFrame(function () { move(active()); });
    window.addEventListener("resize", function () { move(active()); }, { passive: true });
  }

  /* --- Copy-to-clipboard for code blocks / switchers (UI 1.11) -------- */
  function copyText(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text);
    }
    // Legacy fallback: an off-screen textarea + execCommand('copy').
    return new Promise(function (resolve, reject) {
      try {
        var ta = document.createElement("textarea");
        ta.value = text;
        ta.setAttribute("readonly", "");
        ta.style.position = "absolute";
        ta.style.left = "-9999px";
        document.body.appendChild(ta);
        ta.select();
        var ok = document.execCommand("copy");
        document.body.removeChild(ta);
        if (ok) resolve(); else reject();
      } catch (e) { reject(e); }
    });
  }
  function bindCopy(btn) {
    if (!once(btn, "data-mh-copy-init")) return;
    btn.addEventListener("click", function () {
      var host = btn.closest(".mh-code");
      if (!host) return;
      var panel;
      if (host.classList.contains("mh-code-switcher")) {
        // Copy whichever language panel the (pure-CSS) tabs have selected.
        var radios = host.querySelectorAll(".mh-cs-radio"), idx = 0;
        for (var i = 0; i < radios.length; i++) { if (radios[i].checked) { idx = i; break; } }
        panel = host.querySelectorAll(".mh-cs-panel")[idx];
      } else {
        panel = host.querySelector(".mh-cs-panel");
      }
      if (!panel) return;
      var codeEl = panel.querySelector("code") || panel;
      var label = btn.querySelector(".mh-cs-copy-label");
      copyText(codeEl.textContent || "").then(function () {
        btn.classList.add("is-copied");
        btn.setAttribute("aria-label", "Copied to clipboard");
        if (label) {
          if (!label.getAttribute("data-mh-label")) label.setAttribute("data-mh-label", label.textContent);
          label.textContent = "Copied";
        }
        window.clearTimeout(btn._mhCopyT);
        btn._mhCopyT = window.setTimeout(function () {
          btn.classList.remove("is-copied");
          btn.setAttribute("aria-label", "Copy code to clipboard");
          if (label && label.getAttribute("data-mh-label")) label.textContent = label.getAttribute("data-mh-label");
        }, 1600);
      }).catch(function () { /* clipboard blocked — code stays selectable */ });
    });
  }

  /* --- Compare: before/after slider (pointer + keyboard) -------------- */
  function bindCompare(el) {
    if (!once(el, "data-mh-compare-init")) return;
    var handle = el.querySelector(".mh-compare__handle");
    var pos = parseFloat(el.getAttribute("data-mh-pos")) || 50;
    function set(p) { pos = clamp(p, 0, 100); el.style.setProperty("--mh-pos", pos + "%"); }
    set(pos);
    function fromEvent(ev) {
      var r = el.getBoundingClientRect();
      set(((ev.clientX - r.left) / r.width) * 100);
    }
    var dragging = false;
    el.addEventListener("pointerdown", function (ev) { dragging = true; el.setPointerCapture && el.setPointerCapture(ev.pointerId); fromEvent(ev); });
    el.addEventListener("pointermove", function (ev) { if (dragging) fromEvent(ev); }, { passive: true });
    el.addEventListener("pointerup", function () { dragging = false; });
    if (handle) {
      handle.setAttribute("tabindex", "0");
      handle.setAttribute("role", "slider");
      handle.setAttribute("aria-label", "Reveal comparison");
      handle.addEventListener("keydown", function (ev) {
        if (ev.key === "ArrowLeft") { set(pos - 4); ev.preventDefault(); }
        else if (ev.key === "ArrowRight") { set(pos + 4); ev.preventDefault(); }
      });
    }
  }

  /* --- Scroll progress (tracing beam) --------------------------------- */
  var beams = [];
  function bindBeam(el) {
    if (!once(el, "data-mh-beam-init")) return;
    beams.push(el);
  }
  function updateBeams() {
    var vh = window.innerHeight || document.documentElement.clientHeight;
    for (var i = 0; i < beams.length; i++) {
      var r = beams[i].getBoundingClientRect();
      var total = r.height + vh;
      var p = clamp((vh - r.top) / total, 0, 1);
      beams[i].style.setProperty("--mh-progress", p.toFixed(4));
    }
  }

  /* --- Vanish input: rotating placeholders ---------------------------- */
  function bindVanish(el) {
    if (!once(el, "data-mh-vanish-init")) return;
    var input = el.querySelector("input, textarea");
    var ph = el.querySelector(".mh-vanish__ph");
    var raw = el.getAttribute("data-mh-placeholders") || "";
    var list = raw.split("|").map(function (s) { return s.trim(); }).filter(Boolean);
    if (input) {
      input.addEventListener("input", function () { el.classList.toggle("is-typing", !!input.value); });
    }
    if (ph && list.length) {
      ph.textContent = list[0];
      if (!REDUCE && list.length > 1) {
        var i = 0;
        setInterval(function () {
          if (el.classList.contains("is-typing")) return;
          ph.classList.add("is-swapping");
          setTimeout(function () {
            i = (i + 1) % list.length;
            ph.textContent = list[i];
            ph.classList.remove("is-swapping");
          }, 200);
        }, 2800);
      }
    }
  }

  /* --- Multi-step loader API (driven by the processing-screen poller) -- */
  MH.steps = function (container, activeIndex) {
    if (typeof container === "string") container = document.querySelector(container);
    if (!container) return;
    var steps = container.querySelectorAll(".mh-steploader__step");
    for (var i = 0; i < steps.length; i++) {
      steps[i].setAttribute("data-state", i < activeIndex ? "done" : i === activeIndex ? "active" : "pending");
    }
  };
  MH.stepsComplete = function (container) {
    if (typeof container === "string") container = document.querySelector(container);
    if (!container) return;
    each(container, ".mh-steploader__step", function (s) { s.setAttribute("data-state", "done"); });
  };

  /* --- Stateful button helper ----------------------------------------- */
  MH.btnState = function (btn, state) {
    if (typeof btn === "string") btn = document.querySelector(btn);
    if (!btn) return;
    btn.setAttribute("data-mh-state", state || "idle");
  };

  /* --- Text-scramble API (UI 1.21) ------------------------------------- */
  // Decode the element's current text in place (re-runs cleanly).
  MH.scramble = function (el) {
    if (typeof el === "string") el = document.querySelector(el);
    runScramble(el);
  };
  // Decode *to* a new string — used by the processing poller as each pipeline
  // stage arrives. A no-op when the target text is unchanged, so polling the
  // same stage label never re-triggers the flicker.
  MH.scrambleTo = function (el, text) {
    if (typeof el === "string") el = document.querySelector(el);
    if (!el) return;
    text = String(text == null ? "" : text);
    if (el.getAttribute("data-mh-scramble-target") === text) return;
    el.setAttribute("data-mh-scramble-target", text);
    el.textContent = text; // final text first → correct with no JS / reduced motion
    runScramble(el);
  };

  /* --- Live multi-step loader rendered from a pipeline log array ------- */
  MH.renderLogSteps = function (container, log, status) {
    if (typeof container === "string") container = document.getElementById(container);
    if (!container || !log) return;
    var key = log.length + ":" + (status || "");
    if (container.getAttribute("data-mh-key") === key) return; // only redraw on change
    container.setAttribute("data-mh-key", key);
    var lines = log.slice(-6), html = "";
    for (var i = 0; i < lines.length; i++) {
      var isLast = i === lines.length - 1;
      var state = status === "done" ? "done"
        : status === "error" ? (isLast ? "error" : "done")
        : isLast ? "active" : "done";
      html += '<div class="mh-steploader__step" data-state="' + state + '">' +
              '<span class="mh-steploader__dot"></span>' +
              '<span class="mh-steploader__label">' + esc(lines[i]) + "</span></div>";
    }
    container.innerHTML = html;
  };

  /* --- Cursor-anchored progress / status readout (UI1.26) -------------
     A small "NN% · status" chip that follows the cursor during a long
     action (render / upload) and is removed on completion. Imperative —
     a long action creates one, feeds it progress, then dismisses it:

         var r = MH.cursorReadout({ label: 'Rendering reel', percent: 0 });
         r.set(42);                 // percent only (label unchanged)
         r.set(null, 'Encoding');   // label only (percent unchanged)
         r.set(80, 'Muxing audio'); // both
         r.done();                  // fade out + remove (disappears)

     Honours prefers-reduced-motion: instead of tracking the pointer (a
     continuous pointer-driven motion) the chip PINS to a fixed corner,
     so the readout still shows but nothing chases the cursor. It is
     pointer-events:none (CSS) so it can never intercept a click, and is
     fully isolated — a thrown error here never breaks the host action. */
  MH.cursorReadout = function (opts) {
    opts = opts || {};
    var noop = { set: function () {}, status: function () {}, done: function () {}, remove: function () {} };
    if (typeof document === "undefined" || !document.body) return noop;
    var el, pctEl, labEl;
    try {
      el = document.createElement("div");
      el.className = "mh-cursor-readout";
      if (opts.accent === "medal") el.setAttribute("data-accent", "medal");
      el.setAttribute("role", "status");
      el.setAttribute("aria-live", "polite");
      pctEl = document.createElement("span");
      pctEl.className = "mh-cursor-readout__pct display-num";
      labEl = document.createElement("span");
      labEl.className = "mh-cursor-readout__label";
      el.appendChild(pctEl);
      el.appendChild(labEl);
      document.body.appendChild(el);
    } catch (e) { return noop; }

    var pinned = REDUCE;            // reduced-motion: don't chase the pointer
    var x = 0, y = 0, tracking = false, raf = 0, removed = false;
    function place() {
      raf = 0;
      if (removed) return;
      var w = el.offsetWidth || 0, h = el.offsetHeight || 0;
      var vw = window.innerWidth || document.documentElement.clientWidth || 0;
      var vh = window.innerHeight || document.documentElement.clientHeight || 0;
      // Offset down-right of the cursor; clamp so it never spills off-screen.
      var px = clamp(x + 16, 8, Math.max(8, vw - w - 8));
      var py = clamp(y + 18, 8, Math.max(8, vh - h - 8));
      el.style.transform = "translate(" + px + "px," + py + "px)";
    }
    function onMove(ev) {
      x = ev.clientX; y = ev.clientY;
      if (!tracking) { tracking = true; el.classList.add("is-in"); }
      if (!raf) raf = requestAnimationFrame(place);
    }
    if (pinned) {
      el.classList.add("is-pinned", "is-in");
    } else {
      document.addEventListener("pointermove", onMove, { passive: true });
      // If the pointer never moves (e.g. keyboard-triggered action), still
      // reveal the readout after a beat, pinned to the corner.
      setTimeout(function () {
        if (!tracking && !removed) el.classList.add("is-pinned", "is-in");
      }, 450);
    }

    var lastPct = null;
    function fmtPct(p) {
      if (p == null || typeof p !== "number" || isNaN(p)) return null;
      return clamp(Math.round(p), 0, 100) + "%";
    }
    function set(pct, status) {
      if (removed) return;
      var s = fmtPct(pct);
      if (s != null) { lastPct = s; pctEl.textContent = s; pctEl.style.display = ""; }
      else if (lastPct == null) { pctEl.style.display = "none"; }
      if (status != null) labEl.textContent = String(status);
    }
    set(opts.percent, opts.label != null ? opts.label : opts.status);

    function cleanup() {
      if (!pinned) { try { document.removeEventListener("pointermove", onMove); } catch (e) {} }
    }
    return {
      set: set,
      status: function (text) { set(null, text); },
      done: function () {
        if (removed) return;
        removed = true; cleanup();
        var rm = function () { if (el && el.parentNode) el.parentNode.removeChild(el); };
        if (REDUCE) { rm(); return; }   // no exit animation under reduced motion
        el.classList.remove("is-in");
        el.classList.add("is-out");
        var fired = false;
        var go = function () { if (!fired) { fired = true; rm(); } };
        try { el.addEventListener("transitionend", go); } catch (e) {}
        setTimeout(go, 360);            // belt-and-braces if transitionend never fires
      },
      remove: function () {
        if (removed) return;
        removed = true; cleanup();
        if (el && el.parentNode) el.parentNode.removeChild(el);
      },
    };
  };

  /* --- Init / re-init ------------------------------------------------- */
  function init(root) {
    each(root, ".mh-spotlight-card, .mh-glow-border, .mh-glare", bindPointer);
    each(root, ".mh-lens", bindLens);
    each(root, ".mh-tilt", bindTilt);
    each(root, ".mh-marquee", bindMarquee);
    each(root, ".mh-text-generate", function (el) { splitWords(el); observe(el); });
    each(root, ".mh-highlight, .mh-flapboard, .mh-scramble", observe);
    each(root, ".mh-flip-words", bindFlipWords);
    each(root, ".mh-tabs", bindTabs);
    each(root, ".mh-cs-copy", bindCopy);
    each(root, ".mh-compare", bindCompare);
    each(root, ".mh-tracing-beam", bindBeam);
    each(root, ".mh-vanish", bindVanish);
    if (beams.length) updateBeams();
  }
  MH.ui = { init: init };

  function boot() {
    init(document);
    if (beams.length) {
      window.addEventListener("scroll", function () { requestAnimationFrame(updateBeams); }, { passive: true });
      window.addEventListener("resize", function () { requestAnimationFrame(updateBeams); }, { passive: true });
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();
})();
