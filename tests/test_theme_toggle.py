"""UI 1.23 — Light/dark theme toggle.

Pins the contract of the in-app theme toggle and the Stage D light
palette it unlocks:

  * A no-FOUC boot script applies the saved preference (read from
    ``localStorage['mh-theme']``) BEFORE the stylesheet paints.
  * A 3-way segmented control (Light · System · Dark) renders in the
    masthead with an accessible radiogroup structure.
  * The toggle behaviour persists the choice and forces / clears
    ``color-scheme`` on ``<html>``.
  * The default is dark-first but OS-aware (``color-scheme: dark light``).
  * The light palette is real (surface / text roles differ light vs
    dark) AND meets WCAG AA contrast on the paper page and white cards.
  * Dark mode does not move a pixel (the dark branch of every surface /
    text role still maps to its original Stage A primitive).
"""
from __future__ import annotations

import importlib
import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fresh_app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.web as wm
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture(scope="module")
def status_html() -> str:
    import mediahub.web.web as wm
    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        return c.get("/status").get_data(as_text=True)


@pytest.fixture(scope="module")
def base_css() -> str:
    from mediahub.web.theme_tokens import THEME_BASE_CSS
    return THEME_BASE_CSS


@pytest.fixture(scope="module")
def guardrails_css() -> str:
    from mediahub.web.responsive_guardrails import RESPONSIVE_GUARDRAILS_CSS
    return RESPONSIVE_GUARDRAILS_CSS


# ---------------------------------------------------------------------------
# Boot script — applied before paint (no flash of the wrong theme)
# ---------------------------------------------------------------------------


class TestBootScript:
    def test_boot_script_reads_persisted_preference(self, status_html):
        assert "localStorage.getItem('mh-theme')" in status_html

    def test_boot_script_sets_data_theme(self, status_html):
        assert "setAttribute('data-theme'" in status_html

    def test_boot_script_forces_color_scheme_for_explicit_choice(self, status_html):
        # The explicit light/dark choice is forced via an inline
        # color-scheme on <html> (beats the stylesheet's OS default).
        assert "colorScheme = pref" in status_html

    def test_boot_runs_before_stylesheet_no_fouc(self, status_html):
        """The boot <script> MUST appear before the inline <style> that
        carries BASE_CSS, otherwise the page paints dark then snaps to
        light on load (a flash). We assert source order."""
        boot = status_html.find("localStorage.getItem('mh-theme')")
        style = status_html.find("<style>")
        assert boot != -1 and style != -1
        assert boot < style, "theme boot script must precede the <style> block"


# ---------------------------------------------------------------------------
# The control itself
# ---------------------------------------------------------------------------


class TestToggleControl:
    def test_radiogroup_present(self, status_html):
        assert 'class="mh-theme-toggle"' in status_html
        assert 'role="radiogroup"' in status_html

    @pytest.mark.parametrize("value", ["light", "system", "dark"])
    def test_three_segments(self, status_html, value):
        assert f'data-theme-value="{value}"' in status_html

    def test_segments_are_accessible_radios(self, status_html):
        # Each segment is a radio with a discrete label so screen-reader
        # users can tell the options apart.
        assert status_html.count('role="radio"') >= 3
        for label in ("Light theme", "Dark theme"):
            assert label in status_html

    def test_toggle_css_shipped(self, status_html):
        assert ".mh-theme-toggle" in status_html
        # The active segment lights up via the data-theme attribute.
        assert 'html[data-theme="light"]' in status_html


# ---------------------------------------------------------------------------
# Persistence behaviour
# ---------------------------------------------------------------------------


class TestToggleBehaviour:
    def test_persists_choice(self, status_html):
        assert "localStorage.setItem('mh-theme'" in status_html

    def test_system_clears_forced_scheme(self, status_html):
        # Choosing System removes the inline override so the OS decides.
        assert "removeProperty('color-scheme')" in status_html

    def test_keyboard_radiogroup_pattern(self, status_html):
        # Arrow-key navigation across the segments (WAI-ARIA radiogroup).
        assert "ArrowRight" in status_html and "ArrowLeft" in status_html


# ---------------------------------------------------------------------------
# Default = dark-first but OS-aware
# ---------------------------------------------------------------------------


class TestDefaultColorScheme:
    def test_color_scheme_meta_supports_both(self, status_html):
        assert '<meta name="color-scheme" content="dark light"' in status_html

    def test_guardrails_default_is_dark_first_os_aware(self, guardrails_css):
        # `dark light` → no OS preference resolves to dark (dark-first);
        # an OS set to light gets the light branch of every token.
        assert "color-scheme: dark light;" in guardrails_css

    def test_guardrails_keeps_os_preference_queries(self, guardrails_css):
        assert "@media (prefers-color-scheme: light)" in guardrails_css
        assert "@media (prefers-color-scheme: dark)" in guardrails_css


# ---------------------------------------------------------------------------
# The light palette is real AND meets WCAG AA contrast
# ---------------------------------------------------------------------------


def _wcag_contrast(hex_a: str, hex_b: str) -> float:
    """WCAG 2.1 contrast ratio between two 6-digit hex colours."""
    def lin(c: float) -> float:
        c = c / 255.0
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    def lum(h: str) -> float:
        h = h.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)

    la, lb = lum(hex_a), lum(hex_b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


@pytest.fixture(scope="module")
def primitives() -> dict[str, str]:
    """The hand-coded neutral primitive hexes (byte-identical fallback)."""
    from mediahub.web.theme_tokens import THEME_FALLBACK_CSS
    out: dict[str, str] = {}
    for m in re.finditer(r"(--mh-prim-neutral-\d+):\s*(#[0-9A-Fa-f]{6})", THEME_FALLBACK_CSS):
        out[m.group(1)] = m.group(2)
    return out


def _role_branches(base_css: str, token: str) -> tuple[str, str]:
    """Return (light_primitive, dark_primitive) for a light-dark() role."""
    m = re.search(
        rf"{re.escape(token)}:\s*light-dark\(\s*var\((--[\w-]+)\)\s*,\s*var\((--[\w-]+)\)\s*\)",
        base_css,
    )
    assert m, f"{token} is not a light-dark(var(), var()) role"
    return m.group(1), m.group(2)


class TestLightPaletteContrast:
    # (text role, surface role, min ratio). Page = --mh-surface (paper),
    # cards = --mh-surface-variant (white). Body copy needs AA (4.5);
    # faint/decorative needs AA-large (3.0).
    CASES = [
        ("--mh-on-surface",         "--mh-surface",         7.0),
        ("--mh-on-surface-variant", "--mh-surface",         4.5),
        ("--mh-on-surface-muted",   "--mh-surface",         4.5),
        ("--mh-on-surface-faint",   "--mh-surface",         3.0),
        ("--mh-on-surface",         "--mh-surface-variant", 7.0),
        ("--mh-on-surface-muted",   "--mh-surface-variant", 4.5),
    ]

    @pytest.mark.parametrize("text_role,surface_role,min_ratio", CASES)
    def test_light_text_on_light_surface(
        self, base_css, primitives, text_role, surface_role, min_ratio
    ):
        text_light = _role_branches(base_css, text_role)[0]
        surf_light = _role_branches(base_css, surface_role)[0]
        text_hex = primitives[text_light]
        surf_hex = primitives[surf_light]
        ratio = _wcag_contrast(text_hex, surf_hex)
        assert ratio >= min_ratio, (
            f"light {text_role} ({text_hex}) on {surface_role} ({surf_hex}) "
            f"is {ratio:.2f}:1 — below the {min_ratio}:1 floor"
        )


# ---------------------------------------------------------------------------
# Dark mode must not move a pixel
# ---------------------------------------------------------------------------


class TestDarkModeUnchanged:
    # The Stage C dark mapping — the dark branch must still equal these.
    DARK_MAP = {
        "--mh-surface": "--mh-prim-neutral-950",
        "--mh-surface-deep": "--mh-prim-neutral-1000",
        "--mh-surface-variant": "--mh-prim-neutral-900",
        "--mh-surface-container": "--mh-prim-neutral-850",
        "--mh-surface-container-high": "--mh-prim-neutral-800",
        "--mh-on-surface": "--mh-prim-neutral-50",
        "--mh-on-surface-variant": "--mh-prim-neutral-300",
        "--mh-on-surface-muted": "--mh-prim-neutral-400",
        "--mh-on-surface-faint": "--mh-prim-neutral-600",
    }

    @pytest.mark.parametrize("token,expected_dark", list(DARK_MAP.items()))
    def test_dark_branch_is_original_primitive(self, base_css, token, expected_dark):
        _light, dark = _role_branches(base_css, token)
        assert dark == expected_dark, (
            f"{token} dark branch changed to {dark}; UI 1.23 must keep dark "
            f"mode byte-identical ({expected_dark})"
        )
