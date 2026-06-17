"""UI1.26 — cursor-anchored progress / info readout (from UNVEIL/Cosmos).

Pins the UI1.26 deliverable: a small percent/status label that follows the
cursor during a long action (render / upload), built as vanilla JS position
tracking, and that disappears on completion.

What is asserted here:

  A. Source / wiring (always run)
     - the primitive (``MH.cursorReadout``) is defined exactly once, in the
       first-party progressive-enhancement kit (``static/js/ui-kit.js``);
     - the CSS for the chip lives in the motion layer (and so rides into
       BASE_CSS), is ``pointer-events:none`` so it never blocks a click, has
       the lane/medal accents, a pinned reduced-motion fallback, and is in the
       consolidated reduced-motion block;
     - the shared render controller (``MH.renderProgress``) spawns a cursor
       mirror, feeds it the live numeral + phase, dismisses it on
       complete()/stop(), and lets a caller opt out (``opts.cursor === false``);
     - the long "results from a link" ingest wires the readout through its real
       percent poll and dismisses it on done/error.

  B. Pages (always run)
     - the upload page (render + ingest) ships the kit and the chip CSS, and
       its inline URL-fetch script drives ``MH.cursorReadout``;
     - a render page (review) ships the controller + chip CSS.

  C. Behaviour (skipped where Node is unavailable)
     - the kit is syntactically valid;
     - a DOM-level drive of the primitive: it appends a chip, ``set()`` updates
       the percent (rounded + clamped 0–100) and the label independently,
       pointer-move positions it via a transform clamped to the viewport,
       ``done()`` removes it and unbinds the listener, and it is null-safe;
     - reduced motion: the chip is PINNED (no pointer listener) yet still shows,
       and ``done()`` removes it instantly;
     - integration: ``MH.renderProgress`` actually creates the chip in the DOM,
       its percent mirrors the giant numeral, its label mirrors the phase, and
       it is removed from the document on both complete() and stop().
"""
from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))

from mediahub.web import web as webmod  # noqa: E402

_NODE = shutil.which("node")
requires_node = pytest.mark.skipif(_NODE is None, reason="node not on PATH")


def _uikit_path() -> Path:
    return Path(webmod.__file__).resolve().parent / "static" / "js" / "ui-kit.js"


def _uikit() -> str:
    return _uikit_path().read_text(encoding="utf-8")


def _motion_css() -> str:
    from mediahub.web.theme_tokens import THEME_MOTION_CSS

    return THEME_MOTION_CSS


def _src() -> str:
    return Path(webmod.__file__).read_text(encoding="utf-8")


def _slice(src: str, marker: str, n: int = 3200) -> str:
    """A window of ``src`` starting at ``marker`` (good enough to scope a
    per-function/per-block assertion in the monolith)."""
    i = src.index(marker)
    return src[i : i + n]


# =========================================================================== #
# A. Source / wiring
# =========================================================================== #
def test_primitive_defined_once_in_uikit():
    js = _uikit()
    assert js.count("MH.cursorReadout = function") == 1, "primitive must be DRY"
    # It lives in the deferred, dependency-free kit (the behavioural half of
    # theme-motion.css), alongside the other imperative MH.* helpers.
    assert "window.MH = window.MH || {}" in js


def test_primitive_api_surface_and_safety():
    js = _slice(_uikit(), "MH.cursorReadout = function")
    # The controller exposes the documented imperative surface.
    for member in ("set:", "status:", "done:", "remove:"):
        assert member in js, f"missing controller member {member!r}"
    # Vanilla position tracking: it listens to pointermove and writes a
    # transform, the contract this roadmap item names ("vanilla JS position
    # tracking").
    assert 'addEventListener("pointermove"' in js
    assert "el.style.transform" in js
    assert "requestAnimationFrame(place)" in js
    # Disappears on completion AND tidies up after itself.
    assert "parentNode.removeChild(el)" in js
    assert 'removeEventListener("pointermove"' in js
    # Honours reduced motion (pins instead of chasing) and is null-safe when
    # there is no document/body to attach to.
    assert "REDUCE" in js and 'classList.add("is-pinned"' in js
    assert "!document.body" in js


def test_chip_css_in_motion_layer():
    css = _motion_css()
    for sel in (
        ".mh-cursor-readout",
        ".mh-cursor-readout__pct",
        ".mh-cursor-readout__label",
        ".mh-cursor-readout.is-in",
        ".mh-cursor-readout.is-pinned",
    ):
        assert sel in css, f"missing CSS rule {sel!r}"
    # Never intercepts a click underneath it.
    chip = css[css.index(".mh-cursor-readout {") :]
    assert "pointer-events: none" in chip[:600]
    # Brand accents (lane default + medal) come from tokens, not hardcodes.
    assert "color: var(--lane)" in css
    assert '.mh-cursor-readout[data-accent="medal"] .mh-cursor-readout__pct' in css
    assert "var(--medal)" in css
    # Reduced motion disables its fade in the consolidated block.
    rm = css[css.index("prefers-reduced-motion") :]
    assert ".mh-cursor-readout" in rm


def test_chip_css_rides_into_base_css():
    # theme-motion.css is concatenated into BASE_CSS, so every page gets it.
    assert ".mh-cursor-readout" in webmod.BASE_CSS
    assert ".mh-cursor-readout__pct" in webmod.BASE_CSS


def test_render_controller_spawns_and_dismisses_cursor():
    # Wide window: the controller's giant innerHTML string makes the function
    # long, and the second dismissal lives in stop() near its end.
    body = _slice(webmod._RENDER_PROGRESS_JS, "MH.renderProgress = function", n=6000)
    # Spawns a cursor mirror, opt-out aware, only if the kit is present.
    assert "MH.cursorReadout(" in body
    assert "opts.cursor !== false" in body
    # Feeds it the live numeral (only on integer change) and the phase label.
    assert "cursor.set(shown)" in body
    assert "cursor.status(label)" in body
    # Dismissed on BOTH terminal paths: natural completion and error-stop.
    assert body.count("cursor.done()") >= 2


def test_upload_ingest_wires_cursor():
    body = _slice(_src(), "var btn = document.getElementById('mh-url-fetch');")
    # Created when the fetch starts, fed the real percent, given the phase text,
    # and dismissed on every terminal branch (done, error, network catch).
    assert "MH.cursorReadout(" in body
    assert "cursor.set(p)" in body
    assert "cursor.status(" in body
    assert body.count("cursor.done()") >= 3


# =========================================================================== #
# B. Pages
# =========================================================================== #
@pytest.fixture
def page_html(tmp_path, monkeypatch):
    """Render the upload page (render + ingest surface) and a review page for
    one owned run. Modelled on tests/test_u6_render_progress.py::page_html."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.setenv("MEDIAHUB_RESULTS_FETCH_ENABLED", "1")
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="alpha", display_name="Alpha SC"))
    run = {
        "run_id": "r1",
        "profile_id": "alpha",
        "meet_name": "Test Open",
        "meet": {"name": "Test Open"},
        "recognition_report": {
            "ranked_achievements": [
                {
                    "id": "swim-1",
                    "rank": 1,
                    "priority": 0.9,
                    "achievement": {
                        "swim_id": "swim-1",
                        "swimmer_name": "Eira Hughes",
                        "event": "100m Freestyle",
                        "time": "59.80",
                    },
                }
            ]
        },
        "cards": [
            {"id": "swim-1", "swimmer_name": "Eira Hughes", "event": "100m Freestyle", "time": "59.80"}
        ],
    }
    (wm.RUNS_DIR / "r1.json").write_text(json.dumps(run), encoding="utf-8")

    out = {}
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "alpha"})
        for url in ("/upload", "/review/r1"):
            resp = c.get(url)
            assert resp.status_code == 200, f"{url} -> {resp.status_code}"
            out[url] = resp.get_data(as_text=True)
    return out


def test_pages_ship_kit_and_chip_css(page_html):
    for url, html in page_html.items():
        assert "js/ui-kit.js" in html, f"{url} does not load the kit"
        assert ".mh-cursor-readout" in html, f"{url} missing chip CSS"


def test_upload_page_drives_cursor_through_ingest(page_html):
    html = page_html["/upload"]
    assert "mh-url-fetch" in html
    # The inline URL-fetch script references the primitive.
    assert "MH.cursorReadout" in html


def test_review_page_ships_controller(page_html):
    html = page_html["/review/r1"]
    assert "MH.renderProgress = function" in html
    assert ".mh-cursor-readout__pct" in html


# =========================================================================== #
# C. Behaviour (Node)
# =========================================================================== #
# A self-contained DOM + clock shim shared by the harnesses below. It models
# just enough of the document/window the kit touches: a fake element tree with
# classList/attrs/children, document-level pointer listeners, a deterministic
# rAF/timeout queue and clock, and a viewport. ``REDUCE`` is read from argv so
# one harness file exercises both motion modes.
_PREAMBLE = textwrap.dedent(
    r"""
    'use strict';
    const assert = require('assert');
    const fs = require('fs');

    const REDUCE = process.argv[3] === '1';
    let now = 0;
    const rafQ = [];
    const timeoutQ = [];

    function mkEl(tag){
      const el = {
        tagName: tag, _cls: {}, _a: {}, style: {}, children: [], parentNode: null,
        _listeners: {}, textContent: '', offsetWidth: 80, offsetHeight: 24,
        classList: {
          add(){ for (let i=0;i<arguments.length;i++) el._cls[arguments[i]] = true; },
          remove(){ for (let i=0;i<arguments.length;i++) delete el._cls[arguments[i]]; },
          contains(c){ return !!el._cls[c]; },
          toggle(c,f){ if (f === undefined) f = !el._cls[c]; if (f) el._cls[c] = true; else delete el._cls[c]; return f; },
        },
        setAttribute(k,v){ el._a[k] = String(v); },
        getAttribute(k){ return el._a[k] !== undefined ? el._a[k] : null; },
        hasAttribute(k){ return el._a[k] !== undefined; },
        appendChild(c){ c.parentNode = el; el.children.push(c); return c; },
        removeChild(c){ const i = el.children.indexOf(c); if (i >= 0) el.children.splice(i,1); c.parentNode = null; return c; },
        addEventListener(t,fn){ (el._listeners[t] = el._listeners[t] || []).push(fn); },
        removeEventListener(t,fn){ const a = el._listeners[t]; if (a){ const i = a.indexOf(fn); if (i>=0) a.splice(i,1); } },
        querySelector(){ return null; },
        querySelectorAll(){ return []; },
      };
      Object.defineProperty(el, 'className', {
        get(){ return Object.keys(el._cls).join(' '); },
        set(v){ el._cls = {}; String(v).split(/\s+/).forEach(function(c){ if (c) el._cls[c] = true; }); },
      });
      return el;
    }

    const body = mkEl('body');
    const docListeners = {};
    global.document = {
      body: body,
      readyState: 'complete',
      documentElement: { classList: { add(){}, remove(){}, contains(){ return false; } }, clientWidth: 1200, clientHeight: 800 },
      createElement(tag){ return mkEl(tag); },
      querySelector(){ return null; },
      querySelectorAll(){ return []; },
      getElementById(){ return null; },
      addEventListener(t,fn){ (docListeners[t] = docListeners[t] || []).push(fn); },
      removeEventListener(t,fn){ const a = docListeners[t]; if (a){ const i = a.indexOf(fn); if (i>=0) a.splice(i,1); } },
    };

    global.window = global;
    window.innerWidth = 1200;
    window.innerHeight = 800;
    Date.now = () => now;
    window.requestAnimationFrame = (cb) => { rafQ.push(cb); return rafQ.length; };
    global.setTimeout = (fn) => { timeoutQ.push(fn); return timeoutQ.length; };
    window.matchMedia = (q) => ({ matches: REDUCE, media: q, addEventListener(){}, removeEventListener(){}, addListener(){}, removeListener(){} });

    function step(ms){ now += (ms || 0); const q = rafQ.splice(0); q.forEach((cb) => cb(now)); }
    function flushTimeouts(){ const q = timeoutQ.splice(0); q.forEach((fn) => fn()); }
    function pointerCount(){ return (docListeners['pointermove'] || []).length; }
    function fireMove(x,y){ (docListeners['pointermove'] || []).slice().forEach((fn) => fn({ clientX: x, clientY: y })); }
    function mkContainer(){
      const els = {}; let html = '';
      return {
        get innerHTML(){ return html; },
        set innerHTML(v){ html = v; },
        querySelector(sel){ if (!els[sel]) els[sel] = mkEl('span'); return els[sel]; },
      };
    }
    """
)

# Drives MH.cursorReadout directly. argv[2] = ui-kit.js, argv[3] = REDUCE flag.
_CURSOR_HARNESS = _PREAMBLE + textwrap.dedent(
    r"""
    eval(fs.readFileSync(process.argv[2], 'utf8'));
    assert(window.MH && typeof window.MH.cursorReadout === 'function', 'cursorReadout missing');

    // ---- creates the chip with the giant-numeral motif + a11y ----
    const r = window.MH.cursorReadout({ label: 'Rendering reel', percent: 0, accent: 'medal' });
    assert(body.children.length === 1, 'chip appended to <body>');
    const el = body.children[0];
    assert(/mh-cursor-readout/.test(el.className), 'has the chip class');
    assert(el.getAttribute('data-accent') === 'medal', 'medal accent attr');
    assert(el.getAttribute('role') === 'status', 'role=status');
    assert(el.children.length === 2, 'pct + label spans');
    const pct = el.children[0], lab = el.children[1];
    assert(/mh-cursor-readout__pct/.test(pct.className), 'pct span class');
    assert(/display-num/.test(pct.className), 'reuses the display-num motif');
    assert(pct.textContent === '0%', 'initial percent shown (=' + pct.textContent + ')');
    assert(lab.textContent === 'Rendering reel', 'initial label shown');

    // ---- set(): percent + label are independent; rounded and clamped 0..100 ----
    r.set(42);
    assert(pct.textContent === '42%', 'percent updates (=' + pct.textContent + ')');
    assert(lab.textContent === 'Rendering reel', 'label unchanged when status omitted');
    r.set(58.7); assert(pct.textContent === '59%', 'rounds (=' + pct.textContent + ')');
    r.set(250);  assert(pct.textContent === '100%', 'clamps high (=' + pct.textContent + ')');
    r.set(-10);  assert(pct.textContent === '0%', 'clamps low (=' + pct.textContent + ')');
    r.set(null, 'Muxing audio');
    assert(lab.textContent === 'Muxing audio', 'label updates');
    assert(pct.textContent === '0%', 'percent unchanged when null');
    r.status('Encoding');
    assert(lab.textContent === 'Encoding', 'status() updates the label');

    if (!REDUCE) {
      // ---- pointer tracking: one listener, transform written, clamped ----
      assert(pointerCount() === 1, 'exactly one pointermove listener');
      fireMove(100, 120); step();
      assert(/translate\(/.test(el.style.transform || ''), 'transform written on move');
      assert(el._cls['is-in'], 'revealed on first move');
      fireMove(5000, 5000); step();
      const m = String(el.style.transform).match(/translate\(([\d.]+)px,\s*([\d.]+)px\)/);
      assert(m, 'transform parses (' + el.style.transform + ')');
      assert(parseFloat(m[1]) <= 1112.5, 'x clamped into viewport (=' + m[1] + ')');
      assert(parseFloat(m[2]) <= 768.5, 'y clamped into viewport (=' + m[2] + ')');

      // ---- done(): fades, then removes element + unbinds listener ----
      r.done();
      flushTimeouts();
      assert(body.children.length === 0, 'removed from <body> after done()');
      assert(pointerCount() === 0, 'pointermove listener cleaned up');
      // idempotent + safe after removal
      r.done(); r.set(50); r.status('x');

      // ---- null-safe with no body to attach to ----
      const saved = document.body; document.body = null;
      const r2 = window.MH.cursorReadout({ label: 'x', percent: 1 });
      r2.set(5); r2.status('y'); r2.done(); r2.remove();   // must not throw
      document.body = saved;

      console.log('CURSOR_READOUT_OK');
    } else {
      // ---- reduced motion: pinned, no pointer listener, still updates ----
      assert(el._cls['is-pinned'], 'pinned under reduced motion');
      assert(el._cls['is-in'], 'shown under reduced motion');
      assert(pointerCount() === 0, 'no pointermove listener under reduced motion');
      r.set(30);
      assert(pct.textContent === '30%', 'still updates under reduced motion');
      r.done();
      assert(body.children.length === 0, 'removed instantly under reduced motion (no timer)');
      console.log('CURSOR_READOUT_REDUCED_OK');
    }
    """
)

# Drives the renderProgress <-> cursorReadout integration. argv[2] = ui-kit.js,
# argv[3] = _RENDER_PROGRESS_JS (REDUCE stays off so the chip tracks the pointer).
_INTEGRATION_HARNESS = _PREAMBLE + textwrap.dedent(
    r"""
    eval(fs.readFileSync(process.argv[2], 'utf8'));   // ui-kit.js -> MH.cursorReadout
    eval(fs.readFileSync(process.argv[3], 'utf8'));   // render-progress -> MH.renderProgress
    assert(typeof window.MH.cursorReadout === 'function', 'cursorReadout present');
    assert(typeof window.MH.renderProgress === 'function', 'renderProgress present');

    // renderProgress must spawn the cursor chip in the DOM.
    const container = mkContainer();
    const ctl = window.MH.renderProgress(container, { label: 'Producing your reel', expectedMs: 60000, accent: 'medal' });
    assert(body.children.length === 1, 'renderProgress spawned a cursor chip');
    const el = body.children[0];
    assert(/mh-cursor-readout/.test(el.className), 'chip class');
    assert(el.getAttribute('data-accent') === 'medal', 'accent forwarded to the chip');
    assert(el.children[1].textContent === 'Producing your reel', 'phase mirrored to chip label');

    // Drive the eased estimate; the chip percent mirrors the giant numeral.
    step(0);
    for (let i = 0; i < 40; i++) step(1000);
    const numText = container.querySelector('.mh-render-prog-pct').textContent;
    assert(parseInt(numText, 10) > 0, 'numeral climbed (=' + numText + ')');
    assert(el.children[0].textContent === numText + '%', 'chip mirrors numeral (' + el.children[0].textContent + ' vs ' + numText + ')');

    // A phase change propagates to the chip.
    ctl.setPhase('Encoding', null);
    assert(el.children[1].textContent === 'Encoding', 'setPhase mirrored to chip');

    // complete() -> the chip is removed from the document.
    ctl.complete();
    for (let i = 0; i < 16 && body.children.length; i++) step(80);
    flushTimeouts();
    assert(body.children.length === 0, 'chip removed on complete()');

    // stop() (error path) also removes the chip.
    const c2 = mkContainer();
    const ctl2 = window.MH.renderProgress(c2, { label: 'x', expectedMs: 5000 });
    assert(body.children.length === 1, 'second chip spawned');
    ctl2.stop();
    flushTimeouts();
    assert(body.children.length === 0, 'chip removed on stop()');

    // opt-out: no chip when opts.cursor === false.
    const c3 = mkContainer();
    window.MH.renderProgress(c3, { label: 'x', cursor: false });
    assert(body.children.length === 0, 'no chip when cursor:false');

    console.log('CURSOR_INTEGRATION_OK');
    """
)


def _strip_scripts(js: str) -> str:
    return re.sub(r"</?script[^>]*>", "", js)


@requires_node
def test_kit_is_syntactically_valid():
    rc = subprocess.run([_NODE, "--check", str(_uikit_path())], capture_output=True, text=True)
    assert rc.returncode == 0, f"ui-kit.js has a JS syntax error:\n{rc.stderr}"


@requires_node
def test_cursor_readout_behaviour():
    with tempfile.TemporaryDirectory() as d:
        harness = Path(d) / "harness.js"
        harness.write_text(_CURSOR_HARNESS, encoding="utf-8")
        r = subprocess.run(
            [_NODE, str(harness), str(_uikit_path()), "0"], capture_output=True, text=True
        )
    assert r.returncode == 0, f"behaviour harness failed:\nSTDOUT:{r.stdout}\nSTDERR:{r.stderr}"
    assert "CURSOR_READOUT_OK" in r.stdout


@requires_node
def test_cursor_readout_reduced_motion():
    with tempfile.TemporaryDirectory() as d:
        harness = Path(d) / "harness.js"
        harness.write_text(_CURSOR_HARNESS, encoding="utf-8")
        r = subprocess.run(
            [_NODE, str(harness), str(_uikit_path()), "1"], capture_output=True, text=True
        )
    assert r.returncode == 0, f"reduced-motion harness failed:\nSTDOUT:{r.stdout}\nSTDERR:{r.stderr}"
    assert "CURSOR_READOUT_REDUCED_OK" in r.stdout


@requires_node
def test_render_progress_cursor_integration_behaviour():
    with tempfile.TemporaryDirectory() as d:
        harness = Path(d) / "harness.js"
        harness.write_text(_INTEGRATION_HARNESS, encoding="utf-8")
        rp = Path(d) / "render_progress.js"
        rp.write_text(_strip_scripts(webmod._RENDER_PROGRESS_JS), encoding="utf-8")
        r = subprocess.run(
            [_NODE, str(harness), str(_uikit_path()), str(rp)], capture_output=True, text=True
        )
    assert r.returncode == 0, f"integration harness failed:\nSTDOUT:{r.stdout}\nSTDERR:{r.stderr}"
    assert "CURSOR_INTEGRATION_OK" in r.stdout
