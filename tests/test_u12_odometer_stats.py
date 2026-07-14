"""tests/test_u12_odometer_stats.py — U.12 animated count-up stat numerals.

U.12 turns the landing-hero meta tallies (organisations / results processed / moments
detected) into odometer numerals: zero-padded digit reels that roll upward on
page load + scroll-into-view, inspired by Max Yinger (yinger.dev).

Three layers of assertion, mirroring tests/test_activity_count_up.py:
  1. Server HTML — the meta numerals are `data-mh-odometer` elements with the
     padded value as text, role="img" + aria-label for assistive tech, and the
     third figure sourced from the REAL engine output (SUM(n_achievements)),
     NOT the legacy ~0 n_cards column.
  2. Static assets — the animateOdometer renderer ships in the page JS and the
     reel CSS ships in theme-components.css.
  3. Browser (Playwright) — the reels roll on load, roll on scroll-into-view,
     snap (no roll) under prefers-reduced-motion, land EXACTLY on the padded
     target, expose the clean aria value, and clip to a single digit (the
     ghosting-regression guard). Skips when Playwright / the pinned Chromium
     build is absent, matching tests/test_browser_cascade.py.
"""
from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SKIP_BROWSER = (
    os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower()
    in ("1", "true", "yes")
)
from tests._pw_chromium import resolve_prebaked_chromium

_PINNED_CHROMIUM = resolve_prebaked_chromium()
_THEME_CSS = _ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "theme-components.css"


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


# Expected zero-padded display strings for the seeded fixture.
EXP_ORGS = "02"     # 2 organisations, pad 2
EXP_RUNS = "005"    # 5 runs, pad 3 (single significant digit + leading zeros)
EXP_MOMENTS = "1234"  # 1234 moments, pad 3 expanded to 4 digits


# ── fixture ──────────────────────────────────────────────────────────────────

@pytest.fixture
def home_app(tmp_path, monkeypatch):
    """Isolated Flask app: 2 orgs, 5 runs, SUM(n_achievements) = 1234."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile
    for pid in ("org-a", "org-b"):  # 2 organisations -> "02"
        save_profile(ClubProfile(
            profile_id=pid,
            display_name=pid.upper(),
            brand_voice_summary="Testing.",
        ))

    conn = wm._db()
    # 5 runs whose n_standout (the deduped standout-swim figure the hero now
    # sums) totals 1234. n_cards stays 0 on purpose — the hero must NOT read
    # from it (it would render a falsehood).
    seeds = [
        ("r1", 1230),
        ("r2", 1),
        ("r3", 1),
        ("r4", 1),
        ("r5", 1),
    ]
    for run_id, ach in seeds:
        conn.execute(
            "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
            "meet_name, file_name, our_swims, n_cards, n_queue, n_achievements, "
            "n_standout, error) "
            "VALUES (?, datetime('now'), datetime('now'), 'done', 'org-a', "
            "'Test Meet', 'test.pdf', 1, 0, 0, ?, ?, NULL)",
            (run_id, ach, ach),
        )
    conn.commit()
    conn.close()
    return app, wm


def _get_home(app) -> str:
    with app.test_client() as c:
        return c.get("/").get_data(as_text=True)


# ── server-side: markup ───────────────────────────────────────────────────────

class TestOdometerServerMarkup:
    def test_three_odometers_rendered(self, home_app):
        app, _ = home_app
        body = _get_home(app)
        # Three live tallies become odometers (the JS reference adds one more
        # occurrence of the bare attribute string, so count the opening tags).
        assert body.count('class="mh-odo"') == 3

    def test_orgs_odometer_padded_and_labelled(self, home_app):
        app, _ = home_app
        body = _get_home(app)
        assert 'data-mh-count="2"' in body
        assert 'data-mh-count-pad="2"' in body
        # Padded text content + clean aria-label + role for assistive tech.
        assert f'aria-label="2" data-mh-count="2" data-mh-odometer data-mh-count-pad="2">{EXP_ORGS}</b>' in body
        assert 'role="img"' in body

    def test_runs_odometer_padded(self, home_app):
        app, _ = home_app
        body = _get_home(app)
        assert f'data-mh-count="5" data-mh-odometer data-mh-count-pad="3">{EXP_RUNS}</b>' in body
        assert "results processed" in body

    def test_moments_uses_standout_swims_not_cards(self, home_app):
        """The third figure is SUM(n_standout)=1234 — the deduped standout-swim
        count, never the ~0 n_cards and never the inflated raw detections."""
        app, _ = home_app
        body = _get_home(app)
        assert f'data-mh-count="1234" data-mh-odometer data-mh-count-pad="3">{EXP_MOMENTS}</b>' in body
        assert "standout swims found" in body
        assert "moments detected" not in body
        # The honest source means the figure is NOT 0 even though n_cards is 0.
        assert 'aria-label="1,234"' in body  # comma-grouped clean value

    def test_padded_text_matches_count(self, home_app):
        """Every odometer's text must equal value zero-padded to its pad width."""
        app, _ = home_app
        body = _get_home(app)
        found = re.findall(
            r'data-mh-count="(\d+)" data-mh-odometer data-mh-count-pad="(\d+)">([^<]+)<',
            body,
        )
        assert found, "no odometer elements parsed from home page"
        for raw, pad, shown in found:
            expected = f"{int(raw):0{int(pad)}d}"
            assert shown == expected, (
                f"odometer count={raw} pad={pad} shows {shown!r}, expected {expected!r}"
            )


class TestOdometerServerEdges:
    def test_singular_labels(self, tmp_path, monkeypatch):
        """1 org / 1 run / 1 moment use singular nouns."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
        monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
        for sub in ("runs_v4", "uploads_v4", "club_profiles"):
            (tmp_path / sub).mkdir(parents=True, exist_ok=True)
        import mediahub.web.club_profile as cp
        import mediahub.web.web as wm
        importlib.reload(cp)
        importlib.reload(wm)
        app = wm.create_app()
        app.config["TESTING"] = True
        from mediahub.web.club_profile import ClubProfile, save_profile
        save_profile(ClubProfile(profile_id="solo", display_name="Solo", brand_voice_summary="x"))
        conn = wm._db()
        conn.execute(
            "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
            "meet_name, file_name, our_swims, n_cards, n_queue, n_achievements, "
            "n_standout, error) "
            "VALUES ('r1', datetime('now'), datetime('now'), 'done', 'solo', "
            "'M', 'f.pdf', 1, 0, 0, 1, 1, NULL)"
        )
        conn.commit()
        conn.close()
        body = _get_home(app)
        # Target the exact meta spans (the word "organisations" also appears in
        # the demo line, so assert against the "</b> <noun></span>" fragment).
        assert '<b class="mh-odo"' in body  # an odometer rendered
        assert "</b> organisation</span>" in body
        assert "</b> organisations</span>" not in body
        assert "</b> result processed</span>" in body
        assert "</b> standout swim found</span>" in body
        assert "</b> standout swims found</span>" not in body

    def test_fresh_deployment_hides_odometers(self, tmp_path, monkeypatch):
        """No orgs + no runs -> no odometers, and the page still renders."""
        monkeypatch.setenv("DATA_DIR", str(tmp_path))
        monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
        monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
        monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
        for sub in ("runs_v4", "uploads_v4", "club_profiles"):
            (tmp_path / sub).mkdir(parents=True, exist_ok=True)
        import mediahub.web.club_profile as cp
        import mediahub.web.web as wm
        importlib.reload(cp)
        importlib.reload(wm)
        app = wm.create_app()
        app.config["TESTING"] = True
        with app.test_client() as c:
            resp = c.get("/")
        body = resp.get_data(as_text=True)
        assert resp.status_code == 200
        # The renderer JS always ships the attribute name; assert no odometer
        # ELEMENT was rendered into the meta line.
        assert '<b class="mh-odo"' not in body


# ── static assets: JS + CSS ───────────────────────────────────────────────────

class TestOdometerAssetsPresent:
    def test_renderer_js_in_page(self, home_app):
        app, _ = home_app
        body = _get_home(app)
        # The odometer renderer and its reduced-motion gate ship inline.
        assert "function animateOdometer" in body
        assert "data-mh-odometer" in body
        assert "mh-odo--live" in body
        assert "prefersReduced" in body
        # Idempotency guard so the reveal observer + safety net don't double-fire.
        assert "_mhCounted" in body

    def test_reel_css_present(self):
        css = _THEME_CSS.read_text(encoding="utf-8")
        for cls in (".mh-odo--live", ".mh-odo-col", ".mh-odo-clip",
                    ".mh-odo-strip", ".mh-odo-d"):
            assert cls in css, f"missing odometer rule {cls}"
        # The clip must hide overflow (only one digit visible) and the column
        # must collapse to a single line (the ghosting fix).
        assert "overflow: hidden" in css


# ── browser-side: animation behaviour ─────────────────────────────────────────

@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="prebaked chromium not found")
class TestOdometerBrowser:
    # Reading the landed digit from each reel's inline transform needs no CSS,
    # but we inject theme-components.css so the clip/layout matches production
    # (and so the ghosting guard is meaningful).
    _READ = """() => [...document.querySelectorAll('.mh-odo--live')].map(o => ({
        digits: [...o.querySelectorAll('.mh-odo-strip')].map(s => {
            const m = (s.style.transform || '').match(/translateY\\(\\s*(-?[\\d.]+)em/);
            const off = m ? Math.round(-parseFloat(m[1])) : 0;
            return ((off % 10) + 10) % 10;
        }).join(''),
        aria: o.getAttribute('aria-label'),
        count: o.getAttribute('data-mh-count'),
    }))"""

    def _body_and_css(self, app):
        return _get_home(app), _THEME_CSS.read_text(encoding="utf-8")

    def test_rolls_and_settles_on_load(self, home_app):
        app, _ = home_app
        body, css = self._body_and_css(app)
        pw, browser = _launch_browser()
        try:
            # Tall viewport so the meta is in view on load (counts up immediately).
            page = browser.new_page(viewport={"width": 1280, "height": 2200})
            page.set_content(body)
            page.add_style_tag(content=css)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(80)
            mid = page.evaluate(
                "() => [...document.querySelectorAll('.mh-odo-strip')].map(s => s.style.transform)"
            )
            page.wait_for_timeout(1700)
            settled = page.evaluate(self._READ)
            final = page.evaluate(
                "() => [...document.querySelectorAll('.mh-odo-strip')].map(s => s.style.transform)"
            )
        finally:
            browser.close()
            pw.stop()

        # It genuinely rolled: a mid-animation frame differs from the final one.
        assert mid != final, "odometer did not animate (mid == final transforms)"
        by_count = {item["count"]: item for item in settled}
        assert by_count["2"]["digits"] == EXP_ORGS
        assert by_count["5"]["digits"] == EXP_RUNS
        assert by_count["1234"]["digits"] == EXP_MOMENTS
        # Clean (unpadded, comma-grouped) accessible value.
        assert by_count["1234"]["aria"] == "1,234"

    def test_animates_on_scroll_into_view(self, home_app):
        app, _ = home_app
        body, css = self._body_and_css(app)
        pw, browser = _launch_browser()
        try:
            # Short viewport: the meta starts below the fold, so nothing rolls
            # until it is scrolled into view (the IntersectionObserver path).
            page = browser.new_page(viewport={"width": 1280, "height": 600})
            page.set_content(body)
            page.add_style_tag(content=css)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(300)
            before = page.evaluate("() => document.querySelectorAll('.mh-odo--live').length")
            page.evaluate("() => document.querySelector('[data-mh-odometer]').scrollIntoView()")
            page.wait_for_timeout(1700)
            settled = page.evaluate(self._READ)
        finally:
            browser.close()
            pw.stop()

        assert before == 0, "odometer animated before being scrolled into view"
        by_count = {item["count"]: item for item in settled}
        assert by_count["2"]["digits"] == EXP_ORGS
        assert by_count["5"]["digits"] == EXP_RUNS
        assert by_count["1234"]["digits"] == EXP_MOMENTS

    def test_reduced_motion_snaps_without_rolling(self, home_app):
        app, _ = home_app
        body, css = self._body_and_css(app)
        pw, browser = _launch_browser()
        try:
            ctx = browser.new_context(
                reduced_motion="reduce", viewport={"width": 1280, "height": 2200}
            )
            page = ctx.new_page()
            page.set_content(body)
            page.add_style_tag(content=css)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(150)  # far less than the 1100ms roll
            settled = page.evaluate(self._READ)
        finally:
            browser.close()
            pw.stop()

        by_count = {item["count"]: item for item in settled}
        # Values are correct immediately — no roll, just placement.
        assert by_count["2"]["digits"] == EXP_ORGS
        assert by_count["5"]["digits"] == EXP_RUNS
        assert by_count["1234"]["digits"] == EXP_MOMENTS

    def test_clip_shows_single_digit(self, home_app):
        """Ghosting guard: each column box clips to exactly one digit cell."""
        app, _ = home_app
        body, css = self._body_and_css(app)
        pw, browser = _launch_browser()
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 2200})
            page.set_content(body)
            page.add_style_tag(content=css)
            page.wait_for_load_state("domcontentloaded")
            page.wait_for_timeout(1700)
            dims = page.evaluate(
                """() => {
                    const col = document.querySelector('.mh-odo-col');
                    const cell = col.querySelector('.mh-odo-d');
                    return {
                        col: col.getBoundingClientRect().height,
                        cell: cell.getBoundingClientRect().height,
                    };
                }"""
            )
        finally:
            browser.close()
            pw.stop()
        # The clip (== column height) must not exceed one digit cell, else a
        # sliver of the neighbouring digit bleeds through.
        assert abs(dims["col"] - dims["cell"]) <= 1.0, (
            f"column ({dims['col']}px) taller than one digit cell ({dims['cell']}px) "
            "— neighbouring digit would ghost through"
        )
