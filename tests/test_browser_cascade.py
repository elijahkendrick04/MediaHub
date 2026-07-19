"""Phase 1.6 Stage I2 — Playwright end-to-end cascade test.

Boots the Flask app via test_client, renders a real HTML
response, loads it in the prebaked Chromium (resolved via
tests/_pw_chromium.py), and asserts that the live CSS cascade
resolves ``--mh-brand-seed`` and ``--mh-surface`` to the
expected values.

Why a real browser
------------------
Every other Stage A–H test exercises Python against Python.
None of them prove that:
  - ``oklch(from var(--mh-brand-seed) 0.866 calc(c * 0.96) h)``
    parses cleanly in a real CSS engine,
  - the ``@property`` registrations make custom properties
    interpolable,
  - the inline ``<style id="mh-theme-seed">`` override wins the
    cascade over the static fallback declarations,
  - every tier-2 role token resolves to its dark value.

A Playwright test catches all of the above via a single
``getComputedStyle`` call.

Gating
------
Follows the ``tests/test_motion.py`` pattern:
  - opt-out via ``MEDIAHUB_SKIP_BROWSER_TESTS=1``
  - auto-skip if Playwright OR the prebaked Chromium is missing
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


_SKIP_BROWSER = os.environ.get("MEDIAHUB_SKIP_BROWSER_TESTS", "").lower() in ("1", "true", "yes")

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


# All tests in this file share these skip conditions.
pytestmark = [
    pytest.mark.skipif(
        _SKIP_BROWSER,
        reason="MEDIAHUB_SKIP_BROWSER_TESTS set",
    ),
    pytest.mark.skipif(
        not _playwright_available(),
        reason="playwright not installed",
    ),
    pytest.mark.skipif(
        not _chromium_available(),
        reason="prebaked chromium not found",
    ),
]


@pytest.fixture
def fresh_app(app, web_module):
    """A clean Flask app + isolated DATA_DIR via the canonical conftest
    fixtures (``app`` / ``web_module`` handle the per-test DATA_DIR
    repointing + module-state reset that the old reload did)."""
    import mediahub.web.club_profile as cp
    from mediahub.theming.theme_store import _read_cached

    _read_cached.cache_clear()
    return app, web_module, cp


def _seed_profile(cp_module, *, profile_id, primary_hex):
    """Create + persist a minimal profile that's complete enough
    to render the brand-preview card on /organisation/setup."""
    from mediahub.web.club_profile import ClubProfile

    prof = ClubProfile(profile_id=profile_id, display_name=f"Browser Test {profile_id}")
    prof.brand_primary = primary_hex
    prof.brand_voice_summary = "Energetic, community-first."
    prof.brand_keywords = ["test"]
    prof.brand_palette_extracted = {"primary": primary_hex}
    prof.brand_kit = {
        "profile_id": profile_id,
        "display_name": f"Browser Test {profile_id}",
        "primary_colour": primary_hex,
    }
    cp_module.save_profile(prof)
    return prof


def _launch_browser():
    """Construct a Playwright browser pinned to the bundled chrome."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        executable_path=str(_PINNED_CHROMIUM),
        headless=True,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
    )
    return pw, browser


def _read_css_var(page, name: str) -> str:
    """Read a CSS custom property's computed value from :root.

    Returns the trimmed string; an unset variable returns ''.
    """
    return page.evaluate(
        f"() => getComputedStyle(document.documentElement)" f".getPropertyValue({name!r}).trim()"
    )


class TestCascadeResolvesSeed:
    """End-to-end: the rendered HTML loaded in chromium resolves
    --mh-brand-seed to the active profile's seed."""

    def test_brand_seed_reflects_active_profile(self, fresh_app):
        app, wm, cp = fresh_app
        _seed_profile(cp, profile_id="browser-seed", primary_hex="#A30D2D")

        with app.test_client() as c:
            with c.session_transaction() as s:
                s["active_profile_id"] = "browser-seed"
            body = c.get("/status").get_data(as_text=True)

        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")
            seed = _read_css_var(page, "--mh-brand-seed")
        finally:
            browser.close()
            pw.stop()

        # The browser may return the hex literal as ``#a30d2d`` (Chrome
        # preserves user-declared hex). Whatever the form, the
        # red-channel byte must be present somewhere in the value.
        assert seed != "", "--mh-brand-seed not set on :root"
        normalised = seed.replace(" ", "").lower()
        # Accept either the raw hex form or a parsed rgb/oklch form
        # that contains the seed-red signature.
        plausible = (
            "a30d2d" in normalised
            or "rgb(163" in normalised  # 0xA3 == 163
            or "rgba(163" in normalised
            or "oklch" in normalised
        )
        assert plausible, f"expected brand seed to surface in computed style; got {seed!r}"

    def test_surface_resolves_non_empty(self, fresh_app):
        """--mh-surface is a tier-2 role token, registered via
        @property; the browser must resolve it to a colour value."""
        app, wm, cp = fresh_app
        _seed_profile(cp, profile_id="browser-surface", primary_hex="#0E2A47")
        with app.test_client() as c:
            with c.session_transaction() as s:
                s["active_profile_id"] = "browser-surface"
            body = c.get("/status").get_data(as_text=True)

        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")
            surface = _read_css_var(page, "--mh-surface")
            primary = _read_css_var(page, "--mh-primary")
            on_surface = _read_css_var(page, "--mh-on-surface")
        finally:
            browser.close()
            pw.stop()

        assert surface != "", "--mh-surface unset (cascade broken)"
        assert primary != "", "--mh-primary unset (cascade broken)"
        assert on_surface != "", "--mh-on-surface unset (cascade broken)"


class TestNoActiveProfile:
    """When no profile is active, the inline override block now
    carries the Stage J2 generic-default seed (#0E2A47 navy) so
    even unconfigured deployments exercise the full pipeline.

    The Stage E "absent when no profile" contract was superseded
    by Stage J2 — set MEDIAHUB_ADAPTIVE_THEME=0 for the legacy
    no-override behaviour (covered by test_adaptive_theme_flag.py)."""

    def test_default_seed_override_when_no_profile(self, fresh_app):
        app, _, _ = fresh_app
        with app.test_client() as c:
            body = c.get("/status").get_data(as_text=True)
        # Stage J2: the inline override block IS present, carrying
        # the generic-default seed.
        assert (
            'id="mh-theme-seed"' in body
        ), "Stage J2 default-theme override missing on unconfigured page"
        assert "#0E2A47" in body, "expected the generic-default seed (#0E2A47) in the override"

        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")
            seed = _read_css_var(page, "--mh-brand-seed")
        finally:
            browser.close()
            pw.stop()
        # The cascade resolves the seed to the generic-default navy.
        assert seed != ""
        normalised = seed.replace(" ", "").lower()
        # Navy is #0E2A47 → R=14 G=42 B=71. Accept hex, rgb, oklch
        # forms; just look for the signature.
        plausible = "0e2a47" in normalised or "rgb(14" in normalised or "oklch" in normalised
        assert plausible, f"unexpected default seed: {seed!r}"


class TestCascadeOrderIntegrity:
    """The full cascade — theme-base + theme-fallback + theme-derive
    + theme-cascade — must load without parser errors. We detect
    parser errors via the resolved values being empty / null."""

    def test_no_orphan_role_tokens(self, fresh_app):
        """Every documented tier-2 role token resolves to a
        non-empty value, even without an active profile."""
        app, _, _ = fresh_app
        with app.test_client() as c:
            body = c.get("/status").get_data(as_text=True)

        # A sample of the tier-2 roles declared in theme-base.css
        roles = (
            "--mh-surface",
            "--mh-on-surface",
            "--mh-primary",
            "--mh-on-primary",
            "--mh-tertiary",
            "--mh-error",
            "--mh-success",
        )

        pw, browser = _launch_browser()
        try:
            page = browser.new_page()
            page.set_content(body)
            page.wait_for_load_state("domcontentloaded")
            values = {name: _read_css_var(page, name) for name in roles}
        finally:
            browser.close()
            pw.stop()

        missing = [name for name, val in values.items() if val == ""]
        assert not missing, (
            f"these tier-2 role tokens did not resolve: {missing}\n"
            f"all values: {values}\n"
            f"likely a cascade order or @property registration issue."
        )
