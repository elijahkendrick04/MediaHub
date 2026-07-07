"""tests/test_hover_preview.py — U.14 cursor-following hover preview.

Roadmap U.14 (Phase 1 product polish, inspired by Christopher Ireland +
SuperHi): hovering an item in the Media library or the Create list spawns a
floating thumbnail that trails the cursor and cross-dissolves to the next
item's preview. JS + absolute positioning, no external dependency.

Two assertion layers, matching the house pattern (see
tests/test_activity_count_up.py + tests/test_browser_cascade.py):

  1. Server-side — the markup + inlined CSS/JS contract:
       • the shared follower JS/CSS ships in _layout on every page, gated on
         fine-pointer + non-reduced-motion + non-touch;
       • Media-library rows carry .mh-hp + a <template class="mh-hp-tpl">
         holding the full photo and an (escaped) caption;
       • Create tiles that are *live* carry .mh-hp + an output-frame poster;
         coming-soon tiles do not;
       • parsed asset metadata is HTML-escaped (no stored-XSS via a name).

  2. Browser-side (Playwright, prebaked Chromium, auto-skips if absent):
       • hovering a row shows the follower, with the hovered item's photo in
         the front layer; sweeping to the next row cross-dissolves (the other
         layer takes over) — both layers end up populated;
       • moving off every host hides the follower;
       • a Create tile shows its poster;
       • prefers-reduced-motion suppresses the follower entirely (never built).
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SKIP_BROWSER = (
    os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower() in ("1", "true", "yes")
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


# ── fixture ────────────────────────────────────────────────────────────────


@pytest.fixture
def hp_app(tmp_path, monkeypatch):
    """A fresh Flask app + one active profile (org gate off — these tests are
    about the preview UI, not the gate)."""
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

    # The media store is a module-level singleton (store._default_store) bound
    # to the DATA_DIR present when it was first built — it does NOT pick up the
    # per-test monkeypatched DATA_DIR on reload, so assets leak between tests.
    # Bind a fresh, empty store to this test's tmp dir so emptiness / counts
    # are deterministic. Both the page (_v8_get_media_store) and _seed_asset
    # resolve through this same get_store() singleton.
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


def _seed_asset(
    tmp_path: Path,
    *,
    profile_id: str = "club",
    filename: str = "p.jpg",
    athletes=None,
    venue: str = "",
) -> str:
    """Persist a real asset file + a media_library row; return its id."""
    from mediahub.media_library.models import MediaAsset
    from mediahub.media_library.store import get_store

    asset_path = tmp_path / f"{profile_id}_{filename}"
    asset_path.write_bytes(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00")
    saved = get_store().save(
        MediaAsset(
            id="",
            filename=filename,
            path=str(asset_path),
            type="athlete_photo",
            profile_id=profile_id,
            permission_status="approved_by_club",
            approval_status="approved",
            linked_athlete_names=athletes if athletes is not None else ["Eira Hughes"],
            linked_venue=venue,
        )
    )
    return saved.id


def _client(app):
    c = app.test_client()
    c.post("/api/organisation/active", data={"profile_id": "club"})
    return c


# ── 1. Server-side: shared follower JS + CSS in the layout ───────────────────


class TestLayoutFollowerContract:
    """The follower JS/CSS ships inline in _layout on every page, with the
    accessibility gates the roadmap (and our house rules) require."""

    def _any_page(self, app) -> str:
        return _client(app).get("/make").get_data(as_text=True)

    def test_js_module_present_and_inline(self, hp_app):
        app, _ = hp_app
        body = self._any_page(app)
        assert "Cursor-following hover preview" in body, "U.14 JS module missing"
        # No external dependency — the roadmap requires "no external dep".
        for cdn in ("cdn.jsdelivr", "unpkg.com", "cdnjs.", "googleapis"):
            assert cdn not in body, f"U.14 must add no external dep; found {cdn!r}"

    def test_js_gates_on_fine_pointer_and_motion(self, hp_app):
        app, _ = hp_app
        body = self._any_page(app)
        assert "(hover: hover) and (pointer: fine)" in body, (
            "follower must only run on hover-capable, fine-pointer devices"
        )
        assert "prefers-reduced-motion: reduce" in body, (
            "follower must bail under prefers-reduced-motion"
        )
        assert "template.mh-hp-tpl" in body, "JS must read the host's <template>"
        assert "aria-hidden" in body  # the follower wrapper is decorative

    def test_css_present(self, hp_app):
        app, _ = hp_app
        body = self._any_page(app)
        for sel in (
            ".mh-hover-preview",
            ".mh-hp-frame",
            ".mh-hp-layer",
            ".mh-hp-img",
            ".mh-hp-poster",
        ):
            assert sel in body, f"missing CSS for {sel}"
        assert "pointer-events: none" in body  # never eats clicks
        # touch + forced-colors belt-and-braces hide rules
        assert "@media (hover: none)" in body or "(pointer: coarse)" in body


# ── 2. Server-side: Media library rows ───────────────────────────────────────


class TestMediaLibraryRows:
    def test_row_carries_preview_template(self, hp_app):
        app, tmp = hp_app
        aid = _seed_asset(tmp, athletes=["Eira Hughes"])
        body = _client(app).get("/media-library").get_data(as_text=True)
        # Prefix match: the row leads with the mh-hp preview-host class but UI 1.9
        # appends mh-asset-row + data-asset-id for multi-select. Don't re-tighten
        # to the exact `mh-hp">` form — that drops the bulk-select hooks.
        assert '<tr class="mh-hp' in body, "asset row must be a preview host"
        assert '<template class="mh-hp-tpl">' in body
        assert '<img class="mh-hp-img"' in body
        # the floating frame shows the SAME asset's full image
        file_url = f"/api/media-library/file/{aid}"
        assert body.count(file_url) >= 2, (
            "both the 60px chip and the full preview should point at the asset"
        )
        # caption surfaces the athlete + type
        assert "Eira Hughes" in body
        # Legacy "athlete_photo" canonicalises to athlete_action on read
        # (media_library.models.LEGACY_TYPE_ALIASES), then prettifies.
        assert "athlete action" in body

    def test_metadata_is_html_escaped(self, hp_app):
        """A malicious athlete name / venue must never reach the page raw —
        not in the table cells, not in the preview caption."""
        app, tmp = hp_app
        payload = "<img src=x onerror=alert(1)>"
        _seed_asset(tmp, athletes=[payload], venue="<b>boom</b>")
        body = _client(app).get("/media-library").get_data(as_text=True)
        # The dangerous part is the live tag/attribute — the payload must never
        # appear with a real "<" (it would execute). Escaped to inert text
        # (&lt;img ...&gt;) it is harmless, so assert on the raw-tag form.
        assert "<img src=x onerror" not in body, "stored-XSS: name rendered raw"
        assert "<b>boom</b>" not in body, "stored-XSS: venue rendered raw"
        assert "&lt;img src=x onerror=alert(1)&gt;" in body, "name not escaped"

    def test_empty_library_has_no_preview_host(self, hp_app):
        app, _ = hp_app
        body = _client(app).get("/media-library").get_data(as_text=True)
        assert '<tr class="mh-hp' not in body
        # ...but the shared follower JS/CSS still ships (no JS error surface)
        assert ".mh-hover-preview" in body


# ── 3. Server-side: Create list tiles ────────────────────────────────────────


class TestCreateTiles:
    def test_live_tiles_have_poster_preview(self, hp_app):
        app, _ = hp_app
        body = _client(app).get("/make").get_data(as_text=True)
        import re

        live_anchors = re.findall(r'<a [^>]*class="mh-template[^"]*\bmh-hp\b', body)
        assert live_anchors, "no live Create tile carries the .mh-hp host class"
        posters = re.findall(r'<div class="mh-hp-poster">', body)
        # exactly one poster per live tile
        assert len(posters) == len(live_anchors), (
            f"{len(posters)} posters for {len(live_anchors)} live tiles — "
            "every live tile should get exactly one preview poster"
        )

    def test_poster_shows_format_and_dimensions(self, hp_app):
        app, _ = hp_app
        body = _client(app).get("/make").get_data(as_text=True)
        assert "mh-hp-poster-eyebrow" in body
        assert "mh-hp-poster-title" in body
        assert "mh-hp-poster-dims" in body
        # canonical output dimensions only (honest, fact-based)
        import re

        dims = set(re.findall(r'mh-hp-poster-dims">([^<]+)<', body))
        assert dims, "poster carries no dimensions"
        allowed = {"1080×1920", "1080×1350", "1080×1080", "Ready to post"}
        assert dims <= allowed, f"unexpected poster dims: {dims - allowed}"

    def test_coming_soon_tiles_have_no_preview(self, hp_app):
        """Disabled / coming-soon tiles are not actionable items, so they get
        no follower (the preview means 'something you can make now')."""
        app, _ = hp_app
        body = _client(app).get("/make").get_data(as_text=True)
        import re

        for m in re.finditer(r'<a [^>]*class="(mh-template[^"]*)"', body):
            cls = m.group(1)
            if "is-disabled" in cls:
                assert "mh-hp" not in cls, (
                    f"a disabled tile got a preview host: {cls!r}"
                )


# ── 4. Browser-side (Playwright) ─────────────────────────────────────────────


@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="prebaked chromium not found")
class TestFollowerBrowser:
    """End-to-end: the follower actually appears, tracks, cross-dissolves and
    hides in a real CSS/JS engine."""

    def _media_html(self, app, tmp) -> str:
        _seed_asset(tmp, filename="a.jpg", athletes=["Alpha One"])
        _seed_asset(tmp, filename="b.jpg", athletes=["Beta Two"])
        return _client(app).get("/media-library").get_data(as_text=True)

    @staticmethod
    def _fine_pointer(page) -> bool:
        return bool(
            page.evaluate(
                "() => matchMedia('(hover: hover)').matches "
                "&& matchMedia('(pointer: fine)').matches"
            )
        )

    @staticmethod
    def _point_at(page, locator):
        """Move the real pointer to an element's centre. We drive the cursor
        directly (not Playwright's .hover(), which scroll-into-views and so
        fires our scroll→hide) — using a tall viewport keeps targets on-screen,
        and scroll_into_view_if_needed is a no-op safety for anything below it
        (its scroll lands before the show, so it never hides the follower)."""
        locator.scroll_into_view_if_needed()
        page.wait_for_timeout(120)
        bb = locator.bounding_box()
        page.mouse.move(bb["x"] + bb["width"] / 2, bb["y"] + bb["height"] / 2)

    @staticmethod
    def _visible(page) -> bool:
        return bool(
            page.evaluate(
                "() => { const w=document.querySelector('.mh-hover-preview');"
                " return !!w && w.classList.contains('is-visible'); }"
            )
        )

    @staticmethod
    def _front_src(page):
        return page.evaluate(
            "() => { const e=document.querySelector('.mh-hp-layer.is-front img.mh-hp-img');"
            " return e ? e.getAttribute('src') : null; }"
        )

    def test_hover_shows_and_tracks_then_hides(self, hp_app):
        app, tmp = hp_app
        body = self._media_html(app, tmp)
        pw, browser = _launch_browser()
        try:
            # Tall viewport so both rows are on-screen (no scroll → no
            # scroll-driven hide while we drive the cursor by coordinates).
            page = browser.new_page(viewport={"width": 1280, "height": 1800})
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")
            if not self._fine_pointer(page):
                pytest.skip("headless env reports coarse pointer")

            rows = page.locator("tr.mh-hp")
            assert rows.count() == 2

            # full-image src of each row's <template> (read inside the inert
            # fragment, which normal locators can't reach)
            tpl_srcs = page.evaluate(
                """() => Array.from(document.querySelectorAll('tr.mh-hp')).map(tr => {
                    const t = tr.querySelector('template.mh-hp-tpl');
                    const img = t && t.content.querySelector('img.mh-hp-img');
                    return img ? img.getAttribute('src') : null;
                })"""
            )
            assert all(tpl_srcs), "each row must hold a preview image"

            # point at row 0 → follower visible, front layer holds row-0 photo
            self._point_at(page, rows.nth(0))
            page.wait_for_timeout(450)
            assert self._visible(page), "follower not visible after hovering a row"
            assert self._front_src(page) == tpl_srcs[0], (
                "front layer must show the hovered row's photo"
            )

            # follower is positioned (transform set away from the origin)
            transform = page.evaluate(
                "() => getComputedStyle(document.querySelector('.mh-hover-preview')).transform"
            )
            assert transform and transform != "none", "follower not positioned"

            # sweep to row 1 → cross-dissolve: other layer takes over with row-1
            self._point_at(page, rows.nth(1))
            page.wait_for_timeout(450)
            assert self._front_src(page) == tpl_srcs[1], (
                "cross-dissolve did not load the next photo"
            )
            # both layers now populated (proves two-layer dissolve, not reuse)
            populated = page.evaluate(
                "() => document.querySelectorAll('.mh-hp-layer img.mh-hp-img').length"
            )
            assert populated == 2, "cross-dissolve should populate both layers"

            # move off every host (top-left corner, no .mh-hp) → follower hides
            page.mouse.move(2, 2)
            page.wait_for_timeout(250)
            assert not self._visible(page), (
                "follower should hide once the pointer leaves all hosts"
            )
        finally:
            browser.close()
            pw.stop()

    def test_create_tile_shows_poster(self, hp_app):
        app, _ = hp_app
        body = _client(app).get("/make").get_data(as_text=True)
        pw, browser = _launch_browser()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 1800})
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")
            if not self._fine_pointer(page):
                pytest.skip("headless env reports coarse pointer")

            self._point_at(page, page.locator("a.mh-template.mh-hp").first)
            page.wait_for_timeout(450)
            assert self._visible(page), "follower not visible after hovering a Create tile"
            has_poster = page.evaluate(
                "() => !!document.querySelector('.mh-hp-layer.is-front .mh-hp-poster')"
            )
            assert has_poster, "live tile preview should render the output poster"
        finally:
            browser.close()
            pw.stop()

    def test_reduced_motion_suppresses_follower(self, hp_app):
        app, tmp = hp_app
        body = self._media_html(app, tmp)
        pw, browser = _launch_browser()
        try:
            ctx = browser.new_context(
                viewport={"width": 1280, "height": 900}, reduced_motion="reduce"
            )
            page = ctx.new_page()
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")
            page.locator("tr.mh-hp").nth(0).hover()
            page.wait_for_timeout(300)
            # The JS bails before building anything under reduced motion.
            assert page.evaluate(
                "() => document.querySelector('.mh-hover-preview') === null"
            ), "reduced-motion users must never get the cursor follower"
            ctx.close()
        finally:
            browser.close()
            pw.stop()
