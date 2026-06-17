"""U.6 — branded render/generation loading state (inspired by Lusion).

Pins the U.6 deliverable: the generic spinner on the long render/generation
waits is replaced by one reusable, brand-locked loading state — a large
editorial %-numeral (reusing the ``.display-num`` motif) over a minimal
progress bar.

What is asserted here:

  A. Source / wiring (always run)
     - the controller (``MH.renderProgress``) is defined exactly once, in
       <head> so every consumer (incl. on-load mhAutoGraphic) sees it;
     - the CSS for the giant-numeral loading state lives in BASE_CSS, with the
       medal accent and a reduced-motion guard;
     - the generic 24px panel spinner is gone from all six render/generation
       panels, each of which now drives ``MH.renderProgress``.

  B. Pages (always run)
     - review / pack / grouped-pack all ship the controller and wire the reel
       button through it.

  C. Behaviour (skipped where Node is unavailable)
     - the rendered JS is syntactically valid on every surface;
     - a DOM-level drive of the controller: the numeral counts up, is
       monotonic, the eased estimate NEVER reaches 100 on its own (honesty —
       only the real result snaps it to 100 via ``complete()``), a real
       progress floor lifts it monotonically, ``stop()`` freezes it, and the
       accent defaults to lane.
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

# The render/generation panels U.6 upgrades, by a unique fragment of each.
# generateReelBatch is the R1.15 multi-format batch panel — it follows the
# same shared-controller contract, so it joins the guarded set.
_RENDER_FUNCS = {
    "createGraphic": "function createGraphic(",
    "generateMotion": "function generateMotion(",
    "generateReel": "function generateReel(",
    "generateReelBatch": "function generateReelBatch(",
    "regenerateGraphic": "function regenerateGraphic(",
    "mhGen (draft panel)": "function mhGen(panel)",
    "generateReelGrouped": "function generateReelGrouped(",
}


def _src() -> str:
    return Path(webmod.__file__).read_text(encoding="utf-8")


def _func_body(src: str, start_marker: str) -> str:
    """Slice from a function's start marker to the next top-level ``function``
    (or ~6k chars). Good enough to scope per-function assertions."""
    i = src.index(start_marker)
    nxt = src.find("\nfunction ", i + 1)
    end = nxt if 0 < nxt - i < 8000 else i + 8000
    return src[i:end]


# =========================================================================== #
# A. Source / wiring
# =========================================================================== #
def test_controller_defined_once_and_in_head():
    src = _src()
    assert src.count("MH.renderProgress = function") == 1, "controller must be DRY"
    # Injected as a <head> script value, before any body consumer can run it.
    assert "{{ render_progress_js | safe }}" in src
    assert "render_progress_js=_RENDER_PROGRESS_JS" in src


def test_controller_is_self_contained_iife():
    js = webmod._RENDER_PROGRESS_JS
    # Lazily creates window.MH so it is order-independent vs the main framework.
    assert "window.MH = window.MH || {}" in js
    assert "if (MH.renderProgress) return" in js  # idempotent


def test_controller_markup_is_the_giant_numeral_motif():
    js = webmod._RENDER_PROGRESS_JS
    assert 'class="mh-render-prog-pct display-num"' in js  # reuses the motif
    assert "mh-render-prog-sign" in js  # the % glyph
    assert "mh-render-prog-bar" in js and "mh-render-prog-fill" in js
    # Accessibility: it is an announced progressbar with a live phase label.
    assert 'role="progressbar"' in js
    assert 'aria-valuemin="0"' in js and 'aria-valuemax="100"' in js
    assert "aria-valuenow" in js
    assert 'aria-live="polite"' in js


def test_controller_is_honest_never_claims_done_early():
    """The eased estimate must asymptote BELOW 100; only the real result
    (``complete``) reaches 100. This mirrors the no-fabrication rule: a
    progress bar that hits 100 before the artefact exists is a lie."""
    js = webmod._RENDER_PROGRESS_JS
    assert "var CEIL = 94" in js  # eased asymptote < 100
    assert "var CAP  = 97" in js  # real-floor ceiling < 100 while running
    # The only path to 100 is the finishing animation inside complete().
    assert "100 - finishFrom" in js
    assert "complete:" in js and "setProgress:" in js and "stop:" in js


def test_css_for_loading_state_in_base_css():
    css = webmod.BASE_CSS
    for sel in (
        ".mh-render-prog ",
        ".mh-render-prog-num",
        ".mh-render-prog-pct",
        ".mh-render-prog-sign",
        ".mh-render-prog-bar",
        ".mh-render-prog-fill",
        ".mh-render-prog-label",
        ".mh-render-prog-sub",
    ):
        assert sel in css, f"missing CSS rule {sel!r}"
    # Brand accents (lane default + medal) and a reduced-motion guard.
    assert '.mh-render-prog[data-accent="medal"] .mh-render-prog-pct' in css
    assert '.mh-render-prog[data-accent="medal"] .mh-render-prog-fill' in css
    assert "var(--lane)" in css and "var(--medal)" in css
    # The giant numeral is responsive (fluid clamp), not a fixed size.
    assert "clamp(56px" in css
    # Reduced-motion: the new component's animation/transition are disabled.
    rm = css[css.index("prefers-reduced-motion") :]
    assert ".mh-render-prog" in rm


def test_generic_panel_spinner_removed_from_render_panels():
    src = _src()
    # The 24px in-panel spinner markup is gone everywhere (all render panels).
    assert src.count("width:24px;height:24px;border:2px solid") == 0
    # Each upgraded panel now drives the shared controller and gates its result.
    # 7 = the original six U.6 panels + R1.15's generateReelBatch panel.
    assert src.count("MH.renderProgress(panel") == len(_RENDER_FUNCS)


@pytest.mark.parametrize("name,marker", list(_RENDER_FUNCS.items()))
def test_each_render_function_drives_the_controller(name, marker):
    body = _func_body(_src(), marker)
    assert "MH.renderProgress(" in body, f"{name} does not use the controller"
    assert "animation:spin 600ms" not in body, f"{name} still has the old spinner"
    # Honest terminal states: the loop is always either completed or stopped.
    assert "prog.complete(" in body, f"{name} never completes the controller"
    assert "prog.stop(" in body, f"{name} never stops on error"


def test_variant_batch_feeds_real_progress():
    """regenerateGraphic has a real done/total signal — it must feed it to the
    bar (setProgress), not just animate a time estimate."""
    body = _func_body(_src(), "function regenerateGraphic(")
    assert "prog.setProgress(" in body
    assert "prog.setPhase(" in body
    assert "done / total" in body  # the real fraction


# =========================================================================== #
# B. Pages
# =========================================================================== #
@pytest.fixture
def page_html(tmp_path, monkeypatch):
    """Render review / pack / grouped-pack for one owned run, returning their
    HTML. Modelled on tests/test_reel_job_async.py's app_env."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
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
            {
                "id": "swim-1",
                "swimmer_name": "Eira Hughes",
                "event": "100m Freestyle",
                "time": "59.80",
            }
        ],
    }
    (wm.RUNS_DIR / "r1.json").write_text(json.dumps(run), encoding="utf-8")

    out = {}
    with app.test_client() as c:
        c.post("/api/organisation/active", data={"profile_id": "alpha"})
        for url in ("/review/r1", "/pack/r1", "/pack/r1/grouped"):
            resp = c.get(url)
            assert resp.status_code == 200, f"{url} -> {resp.status_code}"
            out[url] = resp.get_data(as_text=True)
    return out


def test_every_render_page_ships_the_controller(page_html):
    for url, html in page_html.items():
        assert "MH.renderProgress = function" in html, f"{url} missing controller"
        # And the brand-locked loading CSS rode along in BASE_CSS.
        assert ".mh-render-prog-pct" in html, f"{url} missing loading CSS"


def test_grouped_pack_wires_reel_through_controller(page_html):
    # The grouped builder renders the meet-reel surface for this run — it must
    # kick the controller, not a bare spinner.
    grouped = page_html["/pack/r1/grouped"]
    assert "function generateReelGrouped(" in grouped
    assert "MH.renderProgress(panel" in grouped
    # No page in the flow paints the old 24px in-panel spinner any more.
    for url, html in page_html.items():
        assert (
            "width:24px;height:24px;border:2px solid" not in html
        ), f"{url} still paints the old panel spinner"


# =========================================================================== #
# C. Behaviour (Node)
# =========================================================================== #
def _node_check(js: str) -> tuple[int, str]:
    js = re.sub(r"</?script[^>]*>", "", js)
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
        f.write(js)
        path = f.name
    try:
        r = subprocess.run([_NODE, "--check", path], capture_output=True, text=True)
        return r.returncode, r.stderr
    finally:
        os.unlink(path)


@requires_node
def test_rendered_js_is_syntactically_valid():
    for name, js in (
        ("_RENDER_PROGRESS_JS", webmod._RENDER_PROGRESS_JS),
        ("_card_creative_js", webmod._card_creative_js()),
        ("_VISUAL_PANEL_JS", webmod._VISUAL_PANEL_JS),
    ):
        rc, err = _node_check(js)
        assert rc == 0, f"{name} has a JS syntax error:\n{err}"


@requires_node
def test_grouped_page_inline_scripts_are_valid(page_html):
    """The grouped reel function lives in a Python f-string (doubled braces) —
    the highest-risk surface. Syntax-check every inline script it ships."""
    html = page_html["/pack/r1/grouped"]
    scripts = re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.DOTALL)
    assert scripts, "expected inline scripts on the grouped page"
    for i, s in enumerate(scripts):
        if not s.strip():
            continue
        rc, err = _node_check(s)
        assert rc == 0, f"grouped page script #{i} invalid:\n{err}"


# A self-contained Node harness: deterministic clock + rAF/timeout shims and a
# tiny DOM, then it drives MH.renderProgress and asserts its behaviour. Prints a
# sentinel on success; any failed assert exits non-zero.
_HARNESS = textwrap.dedent(
    r"""
    'use strict';
    const assert = require('assert');
    const fs = require('fs');

    let now = 0;
    Date.now = () => now;
    const rafQ = [];
    const timeoutQ = [];
    global.window = {};
    window.requestAnimationFrame = (cb) => { rafQ.push(cb); return rafQ.length; };
    global.setTimeout = (fn) => { timeoutQ.push(fn); return timeoutQ.length; };
    function step(ms){ now += ms; const q = rafQ.splice(0); q.forEach((cb) => cb(now)); }
    function flushTimeouts(){ const q = timeoutQ.splice(0); q.forEach((fn) => fn()); }

    function mkEl(){
      return { textContent: '', style: {}, _a: {},
        setAttribute(k, v){ this._a[k] = String(v); },
        getAttribute(k){ return this._a[k]; } };
    }
    function mkContainer(){
      const els = {};
      let html = '';
      return {
        get innerHTML(){ return html; },
        set innerHTML(v){ html = v; },
        querySelector(sel){ if (!els[sel]) els[sel] = mkEl(); return els[sel]; },
      };
    }

    eval(fs.readFileSync(process.argv[2], 'utf8'));
    assert(window.MH && typeof window.MH.renderProgress === 'function', 'renderProgress missing');

    // ---- markup: giant-numeral motif + a11y ----
    let c = mkContainer();
    let ctl = window.MH.renderProgress(c, { label: 'Rendering reel', sub: 'x', expectedMs: 60000, accent: 'medal' });
    assert(/data-accent="medal"/.test(c.innerHTML), 'medal accent');
    assert(/role="progressbar"/.test(c.innerHTML), 'progressbar');
    assert(/mh-render-prog-pct display-num/.test(c.innerHTML), 'display-num numeral');
    assert(/mh-render-prog-fill/.test(c.innerHTML), 'progress bar');
    assert(/aria-label="Rendering reel"/.test(c.innerHTML), 'aria-label');

    const num = () => parseInt(c.querySelector('.mh-render-prog-pct').textContent || '0', 10);
    const width = () => parseFloat(String(c.querySelector('.mh-render-prog-fill').style.width || '0'));
    const ariaNow = () => parseInt(c.querySelector('.mh-render-prog').getAttribute('aria-valuenow') || '0', 10);

    // ---- counts up, monotonic, honest asymptote ----
    step(0);
    let prev = num(), peak = 0;
    for (let i = 0; i < 200; i++) { step(1000); const n = num(); assert(n >= prev, 'numeral monotonic'); prev = n; peak = Math.max(peak, n); }
    assert(peak >= 50, 'climbed (peak=' + peak + ')');
    assert(peak < 100, 'eased estimate never reaches 100 (peak=' + peak + ')');
    assert(Math.abs(width() - num()) <= 1.5, 'bar tracks numeral');
    assert(Math.abs(ariaNow() - num()) <= 1, 'aria-valuenow tracks');

    // ---- real-progress floor, monotonic ----
    c = mkContainer(); ctl = window.MH.renderProgress(c, { expectedMs: 90000, accent: 'lane' });
    step(0);
    ctl.setProgress(60); step(100); assert(num() >= 60, 'floor lifts (=' + num() + ')');
    ctl.setProgress(30); step(100); assert(num() >= 60, 'floor monotonic (=' + num() + ')');
    ctl.setProgress(85); step(100); assert(num() >= 85, 'floor raised (=' + num() + ')');
    assert(num() < 100, 'below 100 before complete');

    // ---- complete() animates to exactly 100 and fires cb ----
    let done = false;
    ctl.complete(() => { done = true; });
    for (let i = 0; i < 16 && num() < 100; i++) step(80);
    assert(num() === 100, 'complete reaches 100 (=' + num() + ')');
    assert(width() === 100, 'bar full at complete');
    flushTimeouts();
    assert(done === true, 'complete callback fired');

    // ---- stop() freezes the numeral ----
    c = mkContainer(); ctl = window.MH.renderProgress(c, { expectedMs: 5000 });
    step(0); step(500);
    const frozen = num();
    ctl.stop();
    step(5000); step(5000);
    assert(num() === frozen, 'stop freezes (' + num() + ' vs ' + frozen + ')');

    // ---- accent defaults / null safety ----
    c = mkContainer(); window.MH.renderProgress(c, {});
    assert(/data-accent="lane"/.test(c.innerHTML), 'defaults to lane');
    c = mkContainer(); window.MH.renderProgress(c, { accent: 'banana' });
    assert(/data-accent="lane"/.test(c.innerHTML), 'unknown accent -> lane');
    assert(window.MH.renderProgress(null, {}) === null, 'null container safe');

    console.log('RENDER_PROGRESS_BEHAVIOUR_OK');
    """
)


@requires_node
def test_controller_behaviour_in_a_dom():
    with tempfile.TemporaryDirectory() as d:
        comp = Path(d) / "component.js"
        comp.write_text(webmod._RENDER_PROGRESS_JS, encoding="utf-8")
        harness = Path(d) / "harness.js"
        harness.write_text(_HARNESS, encoding="utf-8")
        r = subprocess.run([_NODE, str(harness), str(comp)], capture_output=True, text=True)
    assert r.returncode == 0, f"behaviour harness failed:\nSTDOUT:{r.stdout}\nSTDERR:{r.stderr}"
    assert "RENDER_PROGRESS_BEHAVIOUR_OK" in r.stdout
