"""Pin the responsive-design contract.

These tests are the future-proofing layer: any future PR that drops a
critical token, removes a viewport tag, or weakens the modern responsive
features will fail CI.

Two surfaces are tested here:

1. ``responsive_guardrails.py`` — the additive CSS module. Each modern
   feature has a test so it can't be silently removed.
2. ``BASE_CSS`` in ``web.py`` — must still contain the original brand
   tokens *and* must have the guardrails appended.

Integration tests for the rendered HTML live in
``tests/test_responsive_meta.py``.
"""

from __future__ import annotations

import re

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def guardrails_css() -> str:
    from mediahub.web.responsive_guardrails import RESPONSIVE_GUARDRAILS_CSS

    return RESPONSIVE_GUARDRAILS_CSS


@pytest.fixture
def base_css(web_module) -> str:
    return web_module.BASE_CSS


# ---------------------------------------------------------------------------
# Module-level: the guardrails CSS contains the modern primitives
# ---------------------------------------------------------------------------


class TestModernViewportUnits:
    """dvh / svh / lvh were Baseline Widely Available in June 2025.
    They MUST be available behind an @supports gate so the app handles
    mobile address-bar collapse correctly."""

    def test_dvh_present(self, guardrails_css):
        assert "100dvh" in guardrails_css

    def test_svh_present(self, guardrails_css):
        assert "100svh" in guardrails_css

    def test_lvh_present(self, guardrails_css):
        assert "100lvh" in guardrails_css

    def test_dvh_behind_supports_gate(self, guardrails_css):
        # The Progressive-enhancement gate is mandatory so legacy engines
        # don't error out.
        assert "@supports (height: 100dvh)" in guardrails_css

    def test_viewport_height_tokens_defined(self, guardrails_css):
        for tok in ("--mh-vh-dynamic", "--mh-vh-small", "--mh-vh-large"):
            assert tok in guardrails_css, f"missing {tok}"


class TestTouchTargetCompliance:
    """WCAG 2.5.8 Target Size (Minimum) — Level AA, legally required under
    the European Accessibility Act since June 2025. Targets must be at
    least 24 CSS px on coarse pointers."""

    def test_touch_min_token_is_at_least_24px(self, guardrails_css):
        m = re.search(r"--mh-touch-min:\s*(\d+)px", guardrails_css)
        assert m is not None, "--mh-touch-min token missing"
        assert int(m.group(1)) >= 24, "touch target below WCAG 2.5.8 minimum"

    def test_touch_comfortable_token_is_at_least_44px(self, guardrails_css):
        m = re.search(r"--mh-touch-comfortable:\s*(\d+)px", guardrails_css)
        assert m is not None
        assert int(m.group(1)) >= 44, "comfortable touch target below WCAG 2.5.5 AAA"

    def test_touch_min_applied_on_coarse_pointer(self, guardrails_css):
        # The min-height rule must be inside the (pointer: coarse) media query
        # so it never affects desktop layouts.
        coarse_block = re.search(
            r"@media\s*\(pointer:\s*coarse\)\s*\{[^}]*?min-height:\s*var\(--mh-touch-min\)",
            guardrails_css,
            re.DOTALL,
        )
        assert coarse_block is not None, "touch-min rule not scoped to pointer:coarse"

    def test_text_inputs_get_comfortable_target_on_coarse_pointer(self, guardrails_css):
        # Mobile-parity fix: bare text fields / textarea / select must reach
        # the comfortable 44px target on phones — the button-only rule above
        # left typed fields rendering ~20px tall (audit found this on the
        # sponsor form). Scoped to coarse pointers so desktop is untouched.
        assert 'input:not([type="button"])' in guardrails_css
        assert "textarea," in guardrails_css
        # The comfortable-target rule for typed fields must live after the
        # pointer:coarse declaration and before the next top-level @media,
        # so it only ever applies to touch devices.
        coarse_at = guardrails_css.index("@media (pointer: coarse)")
        next_media = guardrails_css.index("@media", coarse_at + 1)
        block = guardrails_css[coarse_at:next_media]
        assert "min-height: var(--mh-touch-comfortable)" in block
        assert 'input:not([type="button"])' in block


class TestFluidTypography:
    """Six steps of fluid type built with clamp(rem, rem+vw, rem)."""

    @pytest.mark.parametrize("step", range(6))
    def test_each_step_uses_clamp(self, guardrails_css, step):
        m = re.search(rf"--mh-fluid-step-{step}:\s*clamp\(([^)]+)\)", guardrails_css)
        assert m is not None, f"step {step} missing or not using clamp()"

    @pytest.mark.parametrize("step", range(6))
    def test_each_step_uses_rem_floor(self, guardrails_css, step):
        """WCAG 1.4.4: clamp() floors and ceilings must use rem so user
        zoom still works. px floors break text resize."""
        m = re.search(rf"--mh-fluid-step-{step}:\s*clamp\(([^,]+),", guardrails_css)
        assert m is not None
        floor = m.group(1).strip()
        assert "rem" in floor, f"step {step} floor `{floor}` must use rem, not px"

    @pytest.mark.parametrize("step", range(6))
    def test_each_step_under_2_5x_ratio(self, guardrails_css, step):
        """Utopia's 2.5× rule for accessibility: ceiling / floor ≤ 2.5
        so users at 200% zoom still get readable text."""
        m = re.search(
            rf"--mh-fluid-step-{step}:\s*clamp\(([\d.]+)rem,[^,]+,\s*([\d.]+)rem\)",
            guardrails_css,
        )
        assert m is not None
        floor, ceiling = float(m.group(1)), float(m.group(2))
        ratio = ceiling / floor
        assert ratio <= 2.5, f"step {step} ratio {ratio:.2f} exceeds WCAG-safe 2.5× max"


class TestSafeAreaInsets:
    """Notch / Dynamic Island / foldable hardware support."""

    def test_safe_area_tokens_defined(self, guardrails_css):
        for tok in (
            "--mh-safe-top",
            "--mh-safe-right",
            "--mh-safe-bottom",
            "--mh-safe-left",
        ):
            assert tok in guardrails_css, f"missing {tok}"

    def test_safe_area_uses_env_with_fallback(self, guardrails_css):
        # env(safe-area-inset-*, 0px) — the 0px fallback makes it safe on
        # devices that don't report insets.
        assert "env(safe-area-inset-left,   0px)" in guardrails_css
        assert "env(safe-area-inset-right,  0px)" in guardrails_css

    def test_body_padding_uses_max_for_safety(self, guardrails_css):
        # max(0px, env(...)) is the canonical pattern that's safe on
        # every device because it never goes negative.
        assert "max(0px, env(safe-area-inset-left))" in guardrails_css
        assert "max(0px, env(safe-area-inset-right))" in guardrails_css

    def test_safe_area_behind_supports_gate(self, guardrails_css):
        assert "@supports (padding: max(0px))" in guardrails_css


class TestUserPreferenceMediaQueries:
    """The three legally and ergonomically important preference queries."""

    def test_prefers_reduced_motion_preserved(self, base_css):
        # Pre-existing rule from BASE_CSS — guard against accidental removal.
        assert "prefers-reduced-motion: reduce" in base_css

    def test_prefers_contrast_more(self, guardrails_css):
        assert "@media (prefers-contrast: more)" in guardrails_css

    def test_forced_colors_active(self, guardrails_css):
        assert "@media (forced-colors: active)" in guardrails_css

    def test_color_scheme_pinned_dark(self, guardrails_css):
        # MediaHub is dark-only: color-scheme is pinned to dark and there
        # is no prefers-color-scheme light/dark switching.
        assert "color-scheme: dark;" in guardrails_css
        assert "prefers-color-scheme" not in guardrails_css


class TestContainerQueries:
    """Component-level responsiveness — the 2026 default for cards."""

    def test_container_type_inline_size_used(self, guardrails_css):
        assert "container-type: inline-size" in guardrails_css

    def test_container_query_at_rule_used(self, guardrails_css):
        assert "@container" in guardrails_css

    def test_container_utility_classes_present(self, guardrails_css):
        for cls in (
            ".mh-container ",
            ".mh-container-card ",
            ".mh-container-panel",
            ".mh-card-responsive",
        ):
            assert cls in guardrails_css, f"missing utility class {cls!r}"


class TestDefensiveCSS:
    """Defensive patterns that prevent layout breakage from future updates."""

    def test_overflow_wrap_on_text_elements(self, guardrails_css):
        # overflow-wrap: anywhere prevents long words / URLs from breaking
        # the layout on narrow viewports.
        assert "overflow-wrap: anywhere" in guardrails_css

    def test_text_wrap_balance_on_headings(self, guardrails_css):
        # text-wrap: balance is a low-risk visual polish that improves
        # heading legibility.
        assert "text-wrap: balance" in guardrails_css
        assert "@supports (text-wrap: balance)" in guardrails_css

    def test_text_wrap_pretty_on_body(self, guardrails_css):
        assert "text-wrap: pretty" in guardrails_css

    def test_media_defensive_defaults(self, guardrails_css):
        # img, video, etc. should never overflow their container.
        # The canonical defensive defaults from Andy Bell's modern reset.
        assert (
            re.search(
                r"img,\s*picture,\s*video,\s*canvas,\s*svg",
                guardrails_css,
            )
            is not None
        )
        assert "max-width: 100%" in guardrails_css

    def test_flex_grid_children_min_width_zero(self, guardrails_css):
        # min-width: 0 on flex/grid children stops them from forcing
        # horizontal scroll when they have intrinsic min-content.
        assert "min-width: 0" in guardrails_css


class TestFormFactorBreakpoints:
    """Guards for emerging form factors beyond the standard phone/tablet/desktop."""

    def test_smartwatch_breakpoint_present(self, guardrails_css):
        assert "@media (max-width: 320px)" in guardrails_css

    def test_ultrawide_breakpoint_present(self, guardrails_css):
        assert "@media (min-width: 1920px)" in guardrails_css

    def test_tv_breakpoint_present(self, guardrails_css):
        assert "@media (min-width: 2400px)" in guardrails_css


class TestProgressiveEnhancementGates:
    """Modern features must be behind @supports so they degrade gracefully."""

    @pytest.mark.parametrize(
        "feature_query",
        [
            "@supports (height: 100dvh)",
            "@supports (text-wrap: balance)",
            "@supports (text-wrap: pretty)",
            "@supports (padding: max(0px))",
            "@supports (text-size-adjust: 100%)",
            "@supports (scrollbar-gutter: stable)",
            "@supports (color-scheme: dark)",
            "@supports selector(:focus-visible)",
        ],
    )
    def test_feature_gated_with_supports(self, guardrails_css, feature_query):
        assert feature_query in guardrails_css, f"missing @supports gate for: {feature_query}"


class TestPrintStylesheet:
    """Users should be able to print or save-as-PDF cleanly."""

    def test_print_media_block(self, guardrails_css):
        assert "@media print" in guardrails_css

    def test_print_hides_chrome(self, guardrails_css):
        for sel in (".topnav", ".mh-footer", "#mh-loader", "#mh-toast-container"):
            assert sel in guardrails_css


# ---------------------------------------------------------------------------
# Existing BASE_CSS contract — protect the brand tokens from regression
# ---------------------------------------------------------------------------


class TestExistingBrandTokensPreserved:
    """The brand colour palette is design contract. These tests fail
    loudly if a future PR accidentally drops one of them."""

    @pytest.mark.parametrize(
        "token",
        [
            # Surfaces
            "--bg:",
            "--bg-deep:",
            "--surface:",
            "--surface-2:",
            "--surface-3:",
            # Ink
            "--ink:",
            "--ink-dim:",
            "--ink-muted:",
            "--ink-faint:",
            # Signature accents — must never disappear
            "--lane:",
            "--lane-h:",
            "--lane-deep:",
            "--lane-ink:",
            "--medal:",
            "--medal-h:",
            "--medal-deep:",
            "--medal-ink:",
            # Semantic colours
            "--good:",
            "--warn:",
            "--bad:",
            "--info:",
            # Type stacks
            "--font-display:",
            "--font-serif:",
            "--font-body:",
            "--font-mono:",
            # Spacing scale
            "--sp-1:",
            "--sp-4:",
            "--sp-7:",
            "--sp-10:",
            # Radii
            "--radius:",
            "--radius-pill:",
            # Shadows
            "--shadow-1:",
            "--shadow-2:",
            "--shadow-3:",
            # Legacy aliases that downstream rules depend on
            "--accent:",
            "--panel:",
            "--border:",
        ],
    )
    def test_token_present(self, base_css, token):
        assert token in base_css, f"critical brand token {token!r} missing"

    def test_existing_breakpoints_preserved(self, base_css):
        # These were the original responsive breakpoints — the guardrails
        # layer ADDS new ones (320, 1920, 2400) and must never remove them.
        for bp in ("max-width: 860px", "max-width: 720px", "max-width: 480px", "min-width: 760px"):
            assert bp in base_css, f"original breakpoint {bp!r} removed"


class TestGuardrailsAppendedLast:
    """The guardrails CSS must come AFTER the original BASE_CSS in the
    cascade so it can supply user-preference fallbacks without being
    overridden by less-specific original rules."""

    def test_marker_is_after_root_block(self, base_css):
        root_pos = base_css.find(":root {")
        guard_pos = base_css.find("RESPONSIVE GUARDRAILS")
        assert root_pos >= 0 and guard_pos >= 0
        assert guard_pos > root_pos, "guardrails must come after original :root"

    def test_marker_is_after_reduced_motion(self, base_css):
        # Original prefers-reduced-motion rule must come before the
        # guardrails marker — otherwise something has reordered BASE_CSS.
        rm_pos = base_css.find("prefers-reduced-motion: reduce")
        guard_pos = base_css.find("RESPONSIVE GUARDRAILS")
        assert rm_pos >= 0 and guard_pos >= 0
        assert guard_pos > rm_pos
