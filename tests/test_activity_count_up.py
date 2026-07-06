"""tests/test_activity_count_up.py — /activity stat-card count-up rendering.

Guards the P3 defect where the "Failed" stat card (data-mh-count="1") rendered
"01" instead of "1" because the server template used :02d formatting and the
count-up animation JS did not apply thousands formatting.

Two layers of assertion:
  1. Server-side: the initial HTML text content equals Python's ':,' format
     (no leading zeros, commas for thousands).
  2. Browser-side (Playwright): after the 900 ms count-up animation settles,
     every .stat .v[data-mh-count] textContent still equals the ':,' value.

The Playwright test skips when Playwright or the pinned Chromium build is absent,
matching the pattern used in tests/test_browser_cascade.py.
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
    os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower()
    in ("1", "true", "yes")
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


# ── helpers ──────────────────────────────────────────────────────────────────

def _fmt(n: int) -> str:
    """Python ':,' thousands format — the canonical display value for every stat."""
    return f"{n:,}"


def _launch_browser():
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path=str(_PINNED_CHROMIUM),
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    return pw, browser


# ── fixture ──────────────────────────────────────────────────────────────────

@pytest.fixture
def activity_app(tmp_path, monkeypatch):
    """Minimal isolated Flask app seeded with 1 done run + 1 failed run."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "uploads_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)

    app = wm.create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True

    from mediahub.web.club_profile import ClubProfile, save_profile
    save_profile(ClubProfile(
        profile_id="test-org",
        display_name="Test Org",
        brand_voice_summary="Testing.",
    ))

    conn = wm._db()
    # Seed: 1 completed run + 1 failed run. Failed count = 1 (the single-digit
    # bug case: :02d rendered "01" instead of "1").
    for run_id, status, error in [
        ("run-done", "done", None),
        ("run-fail", "error", "Pipeline error"),
    ]:
        conn.execute(
            "INSERT INTO runs (id, created_at, finished_at, status, profile_id, "
            "meet_name, file_name, our_swims, n_cards, n_queue, n_achievements, error) "
            "VALUES (?, datetime('now'), datetime('now'), ?, 'test-org', "
            "'Test Meet', 'test.pdf', 1, 0, 0, 0, ?)",
            (run_id, status, error),
        )
    conn.commit()
    conn.close()

    return app, wm


# ── server-side assertion ─────────────────────────────────────────────────────

class TestStatCardServerRendering:
    """Initial HTML text must match ':,' formatting with no leading zeros."""

    def _get_activity(self, app, wm):
        with app.test_client() as c:
            with c.session_transaction() as s:
                s["active_profile_id"] = "test-org"
            return c.get("/activity").get_data(as_text=True)

    def test_failed_stat_no_leading_zero(self, activity_app):
        """data-mh-count="1" must render as ">1<" not ">01<"."""
        app, wm = activity_app
        body = self._get_activity(app, wm)
        assert 'data-mh-count="1">01<' not in body, (
            "Failed stat card has leading zero in initial HTML"
        )
        assert 'data-mh-count="1">1<' in body

    def test_completed_stat_no_leading_zero(self, activity_app):
        """Completed=1 must also render as "1" not "01"."""
        app, wm = activity_app
        body = self._get_activity(app, wm)
        # Completed is inside the "stat good" div with data-mh-count="1"
        assert '>01<' not in body, "A stat card has a leading-zero initial text"

    def test_all_stat_cards_use_comma_format(self, activity_app):
        """Every data-mh-count initial text must match int(target):, format."""
        import re
        app, wm = activity_app
        body = self._get_activity(app, wm)
        # Find all occurrences of data-mh-count="N">TEXT<
        for m in re.finditer(
            r'data-mh-count="(\d+)">([^<]+)<', body
        ):
            raw_target = int(m.group(1))
            displayed = m.group(2)
            expected = _fmt(raw_target)
            assert displayed == expected, (
                f"Stat card data-mh-count={raw_target!r} shows {displayed!r}, "
                f"expected {expected!r}"
            )


# ── browser-side assertion ────────────────────────────────────────────────────

@pytest.mark.skipif(_SKIP_BROWSER, reason="MEDIAHUB_SKIP_BROWSER_TESTS set")
@pytest.mark.skipif(not _playwright_available(), reason="playwright not installed")
@pytest.mark.skipif(not _chromium_available(), reason="prebaked chromium not found")
class TestStatCardCountUpBrowser:
    """After the 900 ms count-up animation, every stat card must display
    its ':,' formatted target value — not "01", not a mid-animation frame."""

    def test_count_up_settles_to_formatted_target(self, activity_app):
        app, wm = activity_app
        with app.test_client() as c:
            with c.session_transaction() as s:
                s["active_profile_id"] = "test-org"
            body = c.get("/activity").get_data(as_text=True)

        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")
            # Wait longer than the 900 ms animation duration.
            page.wait_for_timeout(1300)

            items = page.evaluate("""() => {
                function fmtN(n) {
                    // Mirrors the Python ':,' and JS _fmtN helper: thousands commas,
                    // no leading zeros.
                    var s = Math.round(n).toString();
                    return s.replace(/\\B(?=(\\d{3})+(?!\\d))/g, ',');
                }
                var els = document.querySelectorAll('.stat .v[data-mh-count]');
                return Array.from(els).map(function(el) {
                    var raw = el.getAttribute('data-mh-count');
                    return {
                        target: raw,
                        text: el.textContent.trim(),
                        expected: fmtN(parseFloat(raw))
                    };
                });
            }""")
        finally:
            browser.close()
            pw.stop()

        assert items, "No .stat .v[data-mh-count] elements found on /activity"
        for item in items:
            assert item["text"] == item["expected"], (
                f"Stat card data-mh-count={item['target']!r} rendered "
                f"{item['text']!r} after animation; expected {item['expected']!r}"
            )
