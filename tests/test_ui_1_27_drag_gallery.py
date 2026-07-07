"""tests/test_ui_1_27_drag_gallery.py — UI 1.27 horizontal drag-scroll gallery.

Roadmap UI 1.27 (Phase 1 product polish, inspired by Fey + Sketch): a
mouse-draggable horizontal carousel for the Media Library and the landing
sample-output showcase. Vanilla-JS pointer-event drag on top of a plain
``overflow-x: auto`` scroll-snap row — no carousel library.

Four assertion layers, matching the house pattern (see
tests/test_u16_card_tilt.py + tests/test_hover_preview.py):

  1. CSS contract — the ``.mh-drag-scroll`` substrate in theme-motion.css:
       overflow-x + scroll-snap, the ``.is-dragging`` free-pan state (snap
       off, descendants inert), the honest ``.is-grabbable`` grab cursor, the
       gallery-card tokens, and the reduced-motion guard. No CDN.
  2. JS contract — ui-kit.js ``bindDragScroll``: registered in ``init``,
       touch left to native scroll, a movement threshold so real clicks stay
       clickable, the drag classes, pointer capture, and the trailing-click
       swallow. No external dependency.
  3. Server-side — the rendered markup on ``/`` (four sample-output cards,
       the four first-party sample SVGs, the section between the bento and
       the in-feed frames) and on ``/media-library`` (one filmstrip card per
       asset above the table; parsed metadata HTML-escaped; empty library →
       no gallery).
  4. Browser-side (Playwright, prebaked Chromium, auto-skips if absent):
       a real mouse drag pans the row and toggles ``.is-dragging`` /
       cursor; the grab cursor + hint appear only while the row overflows; a
       drag swallows its click while a plain click passes; touch is left to
       native scroll; the focused row scrolls by keyboard; and reduced-motion
       keeps the drag usable (only the smooth-scroll animation stands down).
"""
from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path

import pytest

from mediahub.web import web as webmod
from mediahub.web.theme_tokens import THEME_MOTION_CSS

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_UI_KIT_JS = _ROOT / "src" / "mediahub" / "web" / "static" / "js" / "ui-kit.js"
_SAMPLES_DIR = _ROOT / "src" / "mediahub" / "web" / "static" / "samples"

_SKIP_BROWSER = os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower() in (
    "1",
    "true",
    "yes",
)
from tests._pw_chromium import resolve_prebaked_chromium

_PINNED_CHROMIUM = resolve_prebaked_chromium()


def _playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401

        return True
    except ImportError:
        return False


def _chromium_available() -> bool:
    return _PINNED_CHROMIUM.is_file()


def _launch_browser():
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path=str(_PINNED_CHROMIUM),
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    return pw, browser


# ── fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def motion_css() -> str:
    return THEME_MOTION_CSS


@pytest.fixture(scope="module")
def kit_js() -> str:
    return _UI_KIT_JS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def drag_js(kit_js: str) -> str:
    """The body of ``bindDragScroll`` — sliced so each assertion is scoped to
    the new binder, not a coincidence elsewhere in the kit."""
    start = kit_js.index("function bindDragScroll(")
    end = kit_js.index("/* --- Scroll progress", start)
    return kit_js[start:end]


@pytest.fixture
def client(tmp_path, monkeypatch):
    """Plain client for the public landing page (no org gate needed)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def media_app(tmp_path, monkeypatch):
    """A fresh app + one active profile + an empty, tmp-scoped media store
    (mirrors tests/test_hover_preview.py::hp_app)."""
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

    import mediahub.media_library.store as _mls

    _mls._default_store = _mls.MediaLibraryStore(db_path=tmp_path / "media_library.db")

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="club",
            display_name="Test Swimming Club",
            brand_voice_summary="Friendly and proud.",
        )
    )
    return app, tmp_path


def _seed_asset(tmp_path: Path, *, filename="p.jpg", athletes=None, venue="", atype="athlete_photo"):
    from mediahub.media_library.models import MediaAsset
    from mediahub.media_library.store import get_store

    asset_path = tmp_path / f"club_{filename}"
    asset_path.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00")
    return get_store().save(
        MediaAsset(
            id="",
            filename=filename,
            path=str(asset_path),
            type=atype,
            profile_id="club",
            permission_status="approved_by_club",
            approval_status="approved",
            linked_athlete_names=athletes if athletes is not None else ["Eira Hughes"],
            linked_venue=venue,
        )
    ).id


def _media_client(app):
    c = app.test_client()
    c.post("/api/organisation/active", data={"profile_id": "club"})
    return c


# ── 1. CSS contract — theme-motion.css ───────────────────────────────────────


class TestMotionCss:
    def test_substrate_is_overflow_scroll_with_snap(self, motion_css):
        block = re.search(r"\.mh-drag-scroll\s*\{(.*?)\}", motion_css, re.DOTALL)
        assert block, "no .mh-drag-scroll rule"
        body = block.group(1)
        assert "overflow-x: auto" in body, "row must be a native overflow-x scroller"
        assert "scroll-snap-type: x" in body, "cards must snap on the x axis"
        # An edge fade (mask) so cards dissolve at the rails (marquee parity).
        assert "mask-image:" in body and "linear-gradient(90deg" in body

    def test_children_are_snap_stops(self, motion_css):
        block = re.search(r"\.mh-drag-scroll\s*>\s*\*\s*\{(.*?)\}", motion_css, re.DOTALL)
        assert block, "no .mh-drag-scroll > * rule"
        body = block.group(1)
        assert "scroll-snap-align: start" in body
        assert "flex: 0 0 auto" in body, "cards must not shrink"

    def test_grabbable_is_the_only_grab_cursor(self, motion_css):
        # The grab cursor is gated on .is-grabbable (JS adds it only when the
        # row overflows) — never an always-on grab on a non-draggable row.
        assert re.search(r"\.mh-drag-scroll\.is-grabbable\s*\{\s*cursor:\s*grab", motion_css)
        # The base .mh-drag-scroll rule must NOT hardcode a grab cursor.
        base = re.search(r"\.mh-drag-scroll\s*\{(.*?)\}", motion_css, re.DOTALL).group(1)
        assert "cursor: grab" not in base

    def test_dragging_state_frees_the_pan(self, motion_css):
        block = re.search(r"\.mh-drag-scroll\.is-dragging\s*\{(.*?)\}", motion_css, re.DOTALL)
        assert block, "no .is-dragging rule"
        body = block.group(1)
        assert "cursor: grabbing" in body
        assert "scroll-snap-type: none" in body, "snap must release for a free pan"
        assert "scroll-behavior: auto" in body, "no smooth scroll fighting the drag"
        assert "user-select: none" in body

    def test_dragging_makes_descendants_inert(self, motion_css):
        assert re.search(
            r"\.mh-drag-scroll\.is-dragging\s*\*\s*\{\s*pointer-events:\s*none",
            motion_css,
        ), "a live drag must make children inert so it never fires a click"

    def test_gallery_card_tokens(self, motion_css):
        assert ".mh-ds-card {" in motion_css
        # Landing output cards match the designed 18:25 sample artwork (no crop).
        out = re.search(r"\.mh-ds-card--output\s*\{(.*?)\}", motion_css, re.DOTALL)
        assert out, "no .mh-ds-card--output rule"
        assert "--mh-ds-aspect: 18 / 25" in out.group(1)
        for part in (".mh-ds-card-cap .eyebrow", ".mh-ds-card-cap .title", ".mh-ds-card-cap .sub"):
            assert part in motion_css, f"missing caption part {part}"

    def test_hint_hidden_attr_wins_over_flex(self, motion_css):
        # The hint is display:inline-flex, so [hidden] needs an explicit
        # display:none to actually hide it.
        assert re.search(r"\.mh-ds-hint\[hidden\]\s*\{\s*display:\s*none", motion_css)

    def test_reduced_motion_stills_only_the_animation(self, motion_css):
        # Find the reduced-motion block and confirm the gallery's smooth scroll
        # is disabled there (drag itself — direct manipulation — is untouched).
        rm = re.search(
            r"@media \(prefers-reduced-motion: reduce\)\s*\{(.*)\}",
            motion_css,
            re.DOTALL,
        )
        assert rm, "no reduced-motion block"
        assert re.search(r"\.mh-drag-scroll\s*\{\s*scroll-behavior:\s*auto", rm.group(1))

    def test_no_cdn(self, motion_css):
        low = motion_css.lower()
        for bad in ("googleapis", "gstatic", "cdn.jsdelivr", "unpkg.com", "cdnjs."):
            assert bad not in low, f"motion CSS must stay first-party; found {bad!r}"


# ── 2. JS contract — ui-kit.js ───────────────────────────────────────────────


class TestKitJs:
    def test_binder_registered_in_init(self, kit_js):
        assert "function bindDragScroll(" in kit_js, "binder missing"
        assert 'each(root, ".mh-drag-scroll", bindDragScroll)' in kit_js, (
            "binder must be wired into init() so re-init picks up new HTML"
        )

    def test_touch_is_left_to_native_scroll(self, drag_js):
        assert 'ev.pointerType === "touch"' in drag_js, (
            "touch must keep native momentum scroll, not the mouse drag"
        )

    def test_primary_button_only(self, drag_js):
        assert "ev.button" in drag_js and "!== 0" in drag_js

    def test_movement_threshold_keeps_clicks_clickable(self, drag_js):
        assert "Math.abs(dx) < 4" in drag_js, (
            "a sub-threshold press must stay a click, not become a drag"
        )

    def test_overflow_gate_and_grabbable(self, drag_js):
        assert "scrollWidth" in drag_js and "clientWidth" in drag_js, (
            "drag + grab cursor must be gated on real overflow"
        )
        assert '"is-grabbable"' in drag_js
        assert '"is-dragging"' in drag_js

    def test_pointer_capture(self, drag_js):
        assert "setPointerCapture" in drag_js and "releasePointerCapture" in drag_js

    def test_trailing_click_swallowed_in_capture_phase(self, drag_js):
        # The post-drag click is suppressed with a capture-phase listener.
        assert '"click"' in drag_js
        assert "preventDefault" in drag_js and "stopPropagation" in drag_js
        assert ", true)" in drag_js, "click swallow must be a capture-phase listener"

    def test_no_external_dependency(self, kit_js):
        low = kit_js.lower()
        for bad in ("import ", "require(", "cdn.jsdelivr", "unpkg.com", "cdnjs.", "googleapis"):
            assert bad not in low, f"ui-kit.js must stay dependency-free; found {bad!r}"


# ── 4. Server-side — Media Library filmstrip ─────────────────────────────────


class TestMediaLibraryGallery:
    def test_gallery_renders_one_card_per_asset(self, media_app):
        app, tmp = media_app
        _seed_asset(tmp, filename="a.jpg", athletes=["Eira Hughes"])
        _seed_asset(tmp, filename="b.jpg", athletes=["Tom Davies"])
        _seed_asset(tmp, filename="c.jpg", athletes=[], venue="Welsh National Open")
        body = _media_client(app).get("/media-library").get_data(as_text=True)
        assert 'class="mh-drag-scroll"' in body
        assert 'aria-label="Media library photos' in body
        assert body.count('<figure class="mh-ds-card">') == 3, "one filmstrip card per asset"
        # caption surfaces the (prettified) type + the subject. Legacy
        # "athlete_photo" canonicalises to athlete_action on read.
        assert "athlete action" in body
        assert "Eira Hughes" in body and "Tom Davies" in body
        assert "Welsh National Open" in body  # falls back to venue when no athlete

    def test_gallery_sits_above_the_table(self, media_app):
        app, tmp = media_app
        _seed_asset(tmp, filename="a.jpg")
        body = _media_client(app).get("/media-library").get_data(as_text=True)
        assert body.find('class="mh-drag-scroll"') < body.find("<table"), (
            "the browse filmstrip should sit above the management table"
        )
        assert "<table" in body, "the detail table must remain"

    def test_card_metadata_is_html_escaped(self, media_app):
        app, tmp = media_app
        _seed_asset(tmp, filename="x.jpg", athletes=["<img src=x onerror=alert(1)>"], venue="")
        body = _media_client(app).get("/media-library").get_data(as_text=True)
        assert "<img src=x onerror" not in body, "stored-XSS via athlete name in a card"
        assert "&lt;img src=x onerror=alert(1)&gt;" in body, "name not escaped in the card"

    def test_empty_library_has_no_gallery(self, media_app):
        app, _ = media_app
        body = _media_client(app).get("/media-library").get_data(as_text=True)
        assert 'class="mh-drag-scroll"' not in body, "no gallery when there are no assets"
        # ...but the upload form + (empty) table still render.
        assert "Upload photos" in body and "<table" in body


# ── 5. Browser-side (Playwright) ─────────────────────────────────────────────


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="prebaked chromium not found")
class TestDragBrowser:
    """Drive the real ui-kit.js binder over the real CSS in Chromium. We mount
    the gallery (real classes) in a narrow harness so overflow is deterministic
    and the row is never below the fold — the *wiring* of these classes onto
    the live pages is proved by the server-side tests above."""

    @pytest.fixture(scope="class")
    def assets(self):
        # Full inlined CSS bundle (tokens + motion kit) lifted from a rendered
        # page, plus the real ui-kit.js source.
        webmod.app.config["TESTING"] = True
        body = webmod.app.test_client().get("/").get_data(as_text=True)
        css = "\n".join(re.findall(r"<style[^>]*>(.*?)</style>", body, re.DOTALL))
        assert ".mh-drag-scroll {" in css
        return css, _UI_KIT_JS.read_text(encoding="utf-8")

    @staticmethod
    def _harness(css: str, *, n: int = 8, width: int = 540) -> str:
        cards = "".join(
            f'<figure class="mh-ds-card" data-i="{i}">'
            f'<div class="mh-ds-card-media"></div>'
            f'<figcaption class="mh-ds-card-cap"><span class="title">Card {i}</span></figcaption>'
            f"</figure>"
            for i in range(n)
        )
        return (
            f'<!doctype html><html class="mh-js"><head><meta charset="utf-8">'
            f"<style>{css}</style></head><body>"
            f'<div style="width:{width}px;padding:30px">'
            f'<div class="mh-ds-gallery-wrap">'
            f'<div class="mh-drag-scroll" tabindex="0" role="group" aria-label="g">{cards}</div>'
            f'<p class="mh-ds-hint" hidden>drag</p>'
            f"</div></div></body></html>"
        )

    def _mount(self, browser, css, *, n=8, width=540, viewport=None, reduced=False):
        ctx = browser.new_context(
            viewport=viewport or {"width": 980, "height": 720},
            reduced_motion="reduce" if reduced else "no-preference",
        )
        page = ctx.new_page()
        page.set_content(self._harness(css, n=n, width=width))
        page.wait_for_load_state("domcontentloaded")
        page.add_script_tag(content=self._kit)  # defines MH + boots MH.ui.init
        return ctx, page

    def _drag(self, page, dx):
        loc = page.locator(".mh-drag-scroll").first
        loc.scroll_into_view_if_needed()
        box = loc.bounding_box()
        cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        page.mouse.move(cx, cy)
        page.mouse.down()
        page.mouse.move(cx + dx, cy, steps=8)
        mid = page.evaluate(
            "() => { var e=document.querySelector('.mh-drag-scroll');"
            " return {sl:e.scrollLeft, dragging:e.classList.contains('is-dragging'),"
            " cursor:getComputedStyle(e).cursor}; }"
        )
        page.mouse.up()
        return mid

    def test_drag_pans_the_overflowing_row(self, assets):
        css, self._kit = assets
        pw, browser = _launch_browser()
        try:
            ctx, page = self._mount(browser, css)
            state = page.evaluate(
                "() => { var e=document.querySelector('.mh-drag-scroll');"
                " return {over:e.scrollWidth - e.clientWidth,"
                " grab:e.classList.contains('is-grabbable'),"
                " cursor:getComputedStyle(e).cursor,"
                " hintHidden:document.querySelector('.mh-ds-hint').hidden}; }"
            )
            assert state["over"] > 0, "harness row must overflow"
            assert state["grab"] is True, "overflowing row must be grabbable"
            assert state["cursor"] == "grab"
            assert state["hintHidden"] is False, "hint must show on an overflowing row"

            mid = self._drag(page, -160)  # drag left → scroll right
            assert mid["dragging"] is True, "is-dragging must be set while panning"
            assert mid["cursor"] == "grabbing"
            assert mid["sl"] > 100, f"drag should pan the row (scrollLeft={mid['sl']})"

            after = page.evaluate(
                "() => document.querySelector('.mh-drag-scroll').classList.contains('is-dragging')"
            )
            assert after is False, "is-dragging must clear on release"
            # the hint is dismissed for good after the first drag
            assert page.evaluate("() => document.querySelector('.mh-ds-hint').hidden") is True
            ctx.close()
        finally:
            browser.close()
            pw.stop()

    def test_no_grab_or_drag_when_not_overflowing(self, assets):
        css, self._kit = assets
        pw, browser = _launch_browser()
        try:
            # Two cards in a wide harness → no overflow.
            ctx, page = self._mount(
                browser, css, n=2, width=1100, viewport={"width": 1240, "height": 700}
            )
            state = page.evaluate(
                "() => { var e=document.querySelector('.mh-drag-scroll');"
                " return {over:e.scrollWidth - e.clientWidth,"
                " grab:e.classList.contains('is-grabbable'),"
                " cursor:getComputedStyle(e).cursor,"
                " hintHidden:document.querySelector('.mh-ds-hint').hidden}; }"
            )
            assert state["over"] <= 2
            assert state["grab"] is False, "a fully-visible row must not claim to be grabbable"
            assert state["cursor"] != "grab"
            assert state["hintHidden"] is True, "no drag hint when there is nothing to drag"

            mid = self._drag(page, -160)
            assert mid["dragging"] is False, "a non-overflowing row must not start a drag"
            ctx.close()
        finally:
            browser.close()
            pw.stop()

    def test_drag_swallows_click_but_plain_click_passes(self, assets):
        css, self._kit = assets
        pw, browser = _launch_browser()
        try:
            ctx, page = self._mount(browser, css)
            page.evaluate(
                "() => { window.__clicks=0;"
                " document.querySelectorAll('.mh-ds-card').forEach("
                "c => c.addEventListener('click', () => window.__clicks++)); }"
            )
            loc = page.locator(".mh-drag-scroll").first
            loc.scroll_into_view_if_needed()
            box = loc.bounding_box()
            cx, cy = box["x"] + 120, box["y"] + box["height"] / 2

            # plain click (no movement) → registers
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.mouse.up()
            assert page.evaluate("() => window.__clicks") == 1, "a plain click must pass through"

            # drag past threshold → trailing click swallowed
            page.mouse.move(cx, cy)
            page.mouse.down()
            page.mouse.move(cx - 140, cy, steps=8)
            page.mouse.up()
            assert page.evaluate("() => window.__clicks") == 1, (
                "the click after a drag must be swallowed"
            )
            ctx.close()
        finally:
            browser.close()
            pw.stop()

    def test_touch_pointer_is_not_hijacked(self, assets):
        css, self._kit = assets
        pw, browser = _launch_browser()
        try:
            ctx, page = self._mount(browser, css)
            dragging = page.evaluate(
                """() => {
                  var e=document.querySelector('.mh-drag-scroll'); var r=e.getBoundingClientRect();
                  function pe(t,x){return new PointerEvent(t,{pointerType:'touch',pointerId:5,
                    clientX:x,clientY:r.top+20,bubbles:true,button:0});}
                  e.dispatchEvent(pe('pointerdown', r.left+200));
                  e.dispatchEvent(pe('pointermove', r.left+40));
                  var d=e.classList.contains('is-dragging');
                  e.dispatchEvent(pe('pointerup', r.left+40));
                  return d;
                }"""
            )
            assert dragging is False, "touch must keep native scroll, not the mouse drag"
            ctx.close()
        finally:
            browser.close()
            pw.stop()

    def test_focused_row_scrolls_by_keyboard(self, assets):
        css, self._kit = assets
        pw, browser = _launch_browser()
        try:
            ctx, page = self._mount(browser, css)
            page.locator(".mh-drag-scroll").first.scroll_into_view_if_needed()
            page.evaluate("() => document.querySelector('.mh-drag-scroll').focus()")
            sl0 = page.evaluate("() => document.querySelector('.mh-drag-scroll').scrollLeft")
            page.keyboard.press("ArrowRight")
            page.keyboard.press("ArrowRight")
            page.wait_for_timeout(150)
            sl1 = page.evaluate("() => document.querySelector('.mh-drag-scroll').scrollLeft")
            assert sl1 > sl0, f"arrow keys must scroll the focused row ({sl0} -> {sl1})"
            ctx.close()
        finally:
            browser.close()
            pw.stop()

    def test_reduced_motion_keeps_drag_but_stills_smooth_scroll(self, assets):
        css, self._kit = assets
        pw, browser = _launch_browser()
        try:
            ctx, page = self._mount(browser, css, reduced=True)
            behavior = page.evaluate(
                "() => getComputedStyle(document.querySelector('.mh-drag-scroll')).scrollBehavior"
            )
            assert behavior == "auto", "smooth scroll must stand down under reduced motion"
            mid = self._drag(page, -160)
            assert mid["dragging"] is True, "direct-manipulation drag must still work"
            assert mid["sl"] > 100, "reduced-motion users must still be able to pan"
            ctx.close()
        finally:
            browser.close()
            pw.stop()
