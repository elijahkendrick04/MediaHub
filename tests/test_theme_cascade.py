"""Stage E — cascade-animation CSS contract tests.

Pins the contract of ``theme-cascade.css``: the @view-transition
rule for cross-document crossfade, the :root seed transition for
in-page interpolation, and the prefers-reduced-motion overrides
for both.

See ``docs/stage_e_looks_right_cascade_plan.md`` for the full
architecture.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def cascade_css() -> str:
    from mediahub.web.theme_tokens import THEME_CASCADE_CSS
    return THEME_CASCADE_CSS


@pytest.fixture(scope="module")
def assembled_css() -> str:
    from mediahub.web.theme_tokens import THEME_TOKENS_CSS
    return THEME_TOKENS_CSS


@pytest.fixture(scope="module")
def static_theme_dir() -> Path:
    from mediahub.web.theme_tokens import STATIC_THEME_DIR
    return STATIC_THEME_DIR


# ---------------------------------------------------------------------------
# File on disk
# ---------------------------------------------------------------------------


class TestFileOnDisk:
    def test_cascade_file_exists(self, static_theme_dir):
        path = static_theme_dir / "theme-cascade.css"
        assert path.is_file(), f"missing {path}"

    def test_cascade_file_nonempty(self, static_theme_dir):
        path = static_theme_dir / "theme-cascade.css"
        assert path.stat().st_size > 500, "theme-cascade.css suspiciously small"

    def test_cascade_module_constant_loaded(self, cascade_css):
        assert isinstance(cascade_css, str)
        assert len(cascade_css) > 500

    def test_cascade_in_assembled_concat(self, assembled_css, cascade_css):
        assert cascade_css in assembled_css, (
            "THEME_CASCADE_CSS not present in THEME_TOKENS_CSS — loader broken"
        )


# ---------------------------------------------------------------------------
# E2 — @view-transition { navigation: auto }
# ---------------------------------------------------------------------------


class TestViewTransitionRule:
    def test_view_transition_rule_present(self, cascade_css):
        assert "@view-transition" in cascade_css

    def test_navigation_auto_present(self, cascade_css):
        # The rule must declare navigation: auto for cross-doc crossfade.
        pattern = re.compile(
            r"@view-transition\s*\{[^}]*navigation:\s*auto",
            re.DOTALL,
        )
        assert pattern.search(cascade_css), (
            "@view-transition rule missing `navigation: auto;`"
        )


# ---------------------------------------------------------------------------
# E3 — :root { transition: --mh-brand-seed ... }
# ---------------------------------------------------------------------------


class TestRootSeedTransition:
    def test_root_transition_declared(self, cascade_css):
        # The :root selector must carry a transition that names
        # --mh-brand-seed.
        pattern = re.compile(
            r":root\s*\{[^}]*transition:[^;}]*--mh-brand-seed",
            re.DOTALL,
        )
        assert pattern.search(cascade_css), (
            "missing :root { transition: --mh-brand-seed ...; }"
        )

    def test_transition_duration_is_600ms(self, cascade_css):
        # The duration on the brand seed transition must be 600ms.
        pattern = re.compile(
            r"--mh-brand-seed\s+600ms",
        )
        assert pattern.search(cascade_css), (
            "--mh-brand-seed transition duration not 600ms"
        )

    def test_transition_uses_cubic_bezier(self, cascade_css):
        # The roadmap's specific easing curve.
        assert "cubic-bezier(0.2, 0.7, 0.2, 1)" in cascade_css, (
            "missing the documented cubic-bezier easing curve"
        )

    def test_tertiary_seed_also_transitions(self, cascade_css):
        # Tertiary follows the same animation so a brand change
        # ripples through the medal gold too.
        pattern = re.compile(r"--mh-tertiary-seed\s+600ms")
        assert pattern.search(cascade_css), (
            "tertiary seed should also transition for in-lockstep movement"
        )


# ---------------------------------------------------------------------------
# E4 — prefers-reduced-motion: reduce overrides
# ---------------------------------------------------------------------------


class TestReducedMotion:
    def test_media_block_present(self, cascade_css):
        assert "@media (prefers-reduced-motion: reduce)" in cascade_css

    def test_root_transition_disabled(self, cascade_css):
        # Inside the reduce media query, :root transition must be none.
        # Use DOTALL to span newlines inside the media block.
        pattern = re.compile(
            r"@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{"
            r"[^}]*:root\s*\{[^}]*transition:\s*none",
            re.DOTALL,
        )
        assert pattern.search(cascade_css), (
            "reduced-motion block missing :root { transition: none; }"
        )

    def test_view_transition_pseudos_disabled(self, cascade_css):
        # The view-transition pseudo-elements have their own animation
        # rule the global :root transition rule cannot reach. Stage E
        # explicitly disables them inside reduced-motion.
        assert "::view-transition-group(*)" in cascade_css
        assert "::view-transition-old(root)" in cascade_css
        assert "::view-transition-new(root)" in cascade_css


# ---------------------------------------------------------------------------
# Cascade integrity
# ---------------------------------------------------------------------------


class TestCascadeOrder:
    def test_cascade_css_last_in_assembled(self, assembled_css, cascade_css):
        """theme-cascade.css must sit LAST in the assembled cascade so
        its rules apply regardless of which @supports branch resolved
        the tier-1 primitives."""
        assert assembled_css.endswith(cascade_css) or \
               assembled_css.endswith(cascade_css + "\n"), (
            "theme-cascade.css not at the end of the assembled cascade"
        )

    def test_braces_balanced(self, cascade_css):
        opens = cascade_css.count("{")
        closes = cascade_css.count("}")
        assert opens == closes, f"unbalanced braces: {opens} vs {closes}"
