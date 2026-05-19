"""Stage A — token foundation tests.

These tests pin the contract of the Adaptive Theming Engine's token
foundation (Phase 1.6 Stage A):

  * the three-tier vocabulary is present
  * every tier-2 role token has a matching @property registration
  * initial-values are valid hex
  * legacy aliases resolve through to tier-2 tokens via the cascade
  * the prepended cascade order is preserved

The numeric pixel-parity check (i.e. ``--bg`` still resolves to
``#0A0B11``) is exercised in tests/test_responsive_meta.py via the
rendered HTML; here we work at the source-string level.
"""
from __future__ import annotations

import importlib
import re

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def theme_tokens_css() -> str:
    from mediahub.web.theme_tokens import THEME_TOKENS_CSS
    return THEME_TOKENS_CSS


@pytest.fixture(scope="module")
def base_css() -> str:
    import mediahub.web.web as wm
    importlib.reload(wm)
    return wm.BASE_CSS


# ---------------------------------------------------------------------------
# Module exposure
# ---------------------------------------------------------------------------


class TestModuleExposure:
    def test_module_imports(self):
        from mediahub.web.theme_tokens import THEME_TOKENS_CSS  # noqa: F401

    def test_css_is_non_empty_string(self, theme_tokens_css):
        assert isinstance(theme_tokens_css, str)
        assert len(theme_tokens_css) > 500

    def test_module_has_descriptive_marker(self, theme_tokens_css):
        # Make it cheap to grep for "what is this CSS" in browser devtools.
        assert "THEME TOKENS" in theme_tokens_css
        assert "Stage A" in theme_tokens_css


# ---------------------------------------------------------------------------
# Tier 1 — Primitives
# ---------------------------------------------------------------------------


_EXPECTED_BRAND_TONES = [0, 50, 100, 200, 300, 400, 500, 600, 700, 800, 900, 950, 1000]
_EXPECTED_TERTIARY_TONES = _EXPECTED_BRAND_TONES
_EXPECTED_NEUTRAL_TONES = [0, 50, 100, 200, 300, 400, 500, 600, 700, 750,
                           800, 850, 900, 950, 1000]


class TestTier1Primitives:
    @pytest.mark.parametrize("tone", _EXPECTED_BRAND_TONES)
    def test_brand_tone_defined(self, theme_tokens_css, tone):
        assert f"--mh-prim-brand-{tone}:" in theme_tokens_css

    @pytest.mark.parametrize("tone", _EXPECTED_TERTIARY_TONES)
    def test_tertiary_tone_defined(self, theme_tokens_css, tone):
        assert f"--mh-prim-tertiary-{tone}:" in theme_tokens_css

    @pytest.mark.parametrize("tone", _EXPECTED_NEUTRAL_TONES)
    def test_neutral_tone_defined(self, theme_tokens_css, tone):
        assert f"--mh-prim-neutral-{tone}:" in theme_tokens_css

    def test_status_anchors_defined(self, theme_tokens_css):
        for tok in (
            "--mh-prim-error-400",
            "--mh-prim-success-400",
            "--mh-prim-warning-400",
            "--mh-prim-info-400",
        ):
            assert f"{tok}:" in theme_tokens_css

    def test_primitives_are_hex_or_var(self, theme_tokens_css):
        # All --mh-prim-* values should be raw hex (the only place raw hex is
        # legitimate in the new vocabulary).
        for m in re.finditer(r"--mh-prim-[a-z0-9-]+:\s*([^;]+);", theme_tokens_css):
            value = m.group(1).strip()
            assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value) or \
                   re.fullmatch(r"#[0-9A-Fa-f]{3}", value), \
                   f"Primitive {m.group(0)!r} should be a hex literal, got {value!r}"


# ---------------------------------------------------------------------------
# Tier 2 — Semantic role tokens (~25 MD3-style)
# ---------------------------------------------------------------------------


# The canonical role tokens from the brief, plus the natural variants the
# implementation found necessary. Adding a new tier-2 token requires
# updating this list — that's deliberate friction.
_TIER2_ROLE_TOKENS = [
    # Surfaces
    "--mh-surface",
    "--mh-surface-deep",
    "--mh-surface-variant",
    "--mh-surface-container",
    "--mh-surface-container-high",
    # On-surface
    "--mh-on-surface",
    "--mh-on-surface-variant",
    "--mh-on-surface-muted",
    "--mh-on-surface-faint",
    # Primary
    "--mh-primary",
    "--mh-primary-hover",
    "--mh-primary-pressed",
    "--mh-on-primary",
    "--mh-primary-container",
    "--mh-on-primary-container",
    # Secondary
    "--mh-secondary",
    "--mh-on-secondary",
    # Tertiary
    "--mh-tertiary",
    "--mh-on-tertiary",
    "--mh-tertiary-container",
    "--mh-on-tertiary-container",
    # Outline
    "--mh-outline",
    "--mh-outline-variant",
    "--mh-outline-rule",
    # Status
    "--mh-error",
    "--mh-on-error",
    "--mh-success",
    "--mh-warning",
    "--mh-info",
    # Focus
    "--mh-focus",
    # Elevation (kept in this tier as composite shadow tokens)
    "--mh-elevation-1",
    "--mh-elevation-2",
    "--mh-elevation-3",
]


class TestTier2RoleTokens:
    @pytest.mark.parametrize("token", _TIER2_ROLE_TOKENS)
    def test_role_token_defined(self, theme_tokens_css, token):
        assert f"{token}:" in theme_tokens_css

    def test_no_role_token_references_raw_hex(self, theme_tokens_css):
        """Tier-2 tokens must reference primitives, not raw hex.

        Exception: the outline + elevation tokens encode alpha-blended
        rgba values that are not yet expressible as a primitive
        reference (Stage C will introduce color-mix-based derivation).
        Those rgba values are allowed.
        """
        allowed_rgba_only = {
            "--mh-outline",
            "--mh-outline-variant",
            "--mh-outline-rule",
            "--mh-elevation-1",
            "--mh-elevation-2",
            "--mh-elevation-3",
        }
        for token in _TIER2_ROLE_TOKENS:
            if token in allowed_rgba_only:
                continue
            m = re.search(
                rf"{re.escape(token)}:\s*([^;]+);", theme_tokens_css
            )
            assert m, f"Could not find declaration for {token}"
            value = m.group(1).strip()
            # Must be a var(...) reference — no hex.
            assert value.startswith("var("), (
                f"{token} must reference a primitive via var(), got {value!r}"
            )
            assert not re.search(r"#[0-9A-Fa-f]{3,8}", value), (
                f"{token} must not contain raw hex, got {value!r}"
            )


# ---------------------------------------------------------------------------
# @property registrations
# ---------------------------------------------------------------------------


# Tokens that MUST be @property-registered for Stage E animation. Outline
# and elevation tokens are composite (rgba + shadow blur) so they don't
# fit syntax: "<color>" — they're excluded from the registration set.
_REGISTERED_TOKENS = [
    t for t in _TIER2_ROLE_TOKENS
    if not t.startswith("--mh-outline") and not t.startswith("--mh-elevation")
]


class TestPropertyRegistrations:
    @pytest.mark.parametrize("token", _REGISTERED_TOKENS)
    def test_property_block_present(self, theme_tokens_css, token):
        pattern = (
            rf"@property\s+{re.escape(token)}\s*\{{[^}}]*"
            rf"syntax:\s*\"<color>\"[^}}]*"
            rf"inherits:\s*true[^}}]*"
            rf"initial-value:\s*#[0-9A-Fa-f]+"
        )
        assert re.search(pattern, theme_tokens_css, re.DOTALL), (
            f"@property declaration for {token} missing or malformed"
        )

    def test_every_initial_value_is_valid_hex(self, theme_tokens_css):
        # Pull every initial-value from @property blocks and assert hex.
        for m in re.finditer(
            r"@property\s+--[\w-]+\s*\{[^}]*?initial-value:\s*([^;]+);",
            theme_tokens_css, re.DOTALL,
        ):
            value = m.group(1).strip()
            assert re.fullmatch(r"#[0-9A-Fa-f]{6}", value), (
                f"initial-value must be 6-digit hex, got {value!r}"
            )

    def test_initial_value_count_matches_registered_set(self, theme_tokens_css):
        # Belt-and-braces: number of @property declarations equals the set
        # we expect to register.
        declared = re.findall(
            r"@property\s+(--mh-[\w-]+)\s*\{", theme_tokens_css
        )
        # Allow ordering to vary; assert set equality.
        assert set(declared) == set(_REGISTERED_TOKENS), (
            f"@property declarations differ from expected set.\n"
            f"  Missing:    {set(_REGISTERED_TOKENS) - set(declared)}\n"
            f"  Unexpected: {set(declared) - set(_REGISTERED_TOKENS)}"
        )


# ---------------------------------------------------------------------------
# Legacy aliases & cascade integrity
# ---------------------------------------------------------------------------


# Existing tokens that BASE_CSS defines and that the rest of the app
# uses. Stage A must preserve every one.
_LEGACY_ALIASES = [
    "--bg", "--bg-deep", "--bg-soft",
    "--surface", "--surface-2", "--surface-3",
    "--hairline", "--rule", "--chrome",
    "--ink", "--ink-dim", "--ink-muted", "--ink-faint",
    "--lane", "--lane-h", "--lane-deep", "--lane-ink", "--lane-glow",
    "--medal", "--medal-h", "--medal-deep", "--medal-ink", "--medal-glow",
    "--info", "--info-bg",
    "--good", "--good-bg", "--warn", "--warn-bg", "--bad", "--bad-bg",
    "--accent", "--accent-h", "--accent2", "--accent2-h", "--accent3",
    "--gold", "--gold-h",
    "--panel", "--panel2", "--panel-h",
    "--border", "--border-h",
    "--shadow", "--shadow-h", "--shadow-1", "--shadow-2", "--shadow-3",
]


class TestLegacyAliases:
    @pytest.mark.parametrize("alias", _LEGACY_ALIASES)
    def test_alias_still_defined_in_base_css(self, base_css, alias):
        # Must still be declared somewhere — either as the new var(--mh-*)
        # alias or as a raw value (glow tokens). Either way, the cascade
        # must see a declaration.
        assert f"{alias}:" in base_css, (
            f"Legacy alias {alias} disappeared — every old var() callsite "
            f"would break."
        )


class TestCascadeOrder:
    def test_theme_tokens_prepended(self, base_css, theme_tokens_css):
        """The cascade must start with theme_tokens so the tier-2 vocabulary
        is parsed BEFORE BASE_CSS's :root re-points the legacy aliases."""
        assert base_css.startswith(theme_tokens_css), (
            "THEME_TOKENS_CSS must be prepended to BASE_CSS."
        )

    def test_guardrails_appended_last(self, base_css):
        """The responsive guardrails must still sit at the end of the cascade."""
        from mediahub.web.responsive_guardrails import RESPONSIVE_GUARDRAILS_CSS
        assert base_css.endswith(RESPONSIVE_GUARDRAILS_CSS), (
            "RESPONSIVE_GUARDRAILS_CSS must remain at the end of BASE_CSS."
        )

    def test_no_circular_aliases_in_legacy_layer(self, base_css):
        """Walk the var(--…) graph from every legacy alias and assert each
        chain terminates in a tier-1 primitive or a raw value (no infinite
        loops, no dangling references)."""
        # Extract a {token: declaration} map for tokens declared inside :root
        # blocks of BASE_CSS. We don't need full CSS parsing — a regex catches
        # the patterns BASE_CSS actually uses.
        decls: dict[str, str] = {}
        for m in re.finditer(r"(--[\w-]+):\s*([^;]+);", base_css):
            name, value = m.group(1), m.group(2).strip()
            # Last declaration wins under cascade. Overwrite is fine.
            decls[name] = value

        def resolve(name: str, seen: set[str]) -> str:
            if name in seen:
                pytest.fail(f"Circular alias chain through {name}: {seen}")
            seen = seen | {name}
            value = decls.get(name)
            if value is None:
                return "<undefined>"
            # If the value is var(--other), follow.
            inner = re.fullmatch(r"var\((--[\w-]+)\)", value)
            if inner:
                return resolve(inner.group(1), seen)
            return value

        for alias in _LEGACY_ALIASES:
            resolved = resolve(alias, set())
            # We don't assert a specific value — just that resolution
            # terminates without a loop and the alias is defined.
            assert resolved != "<undefined>", (
                f"Legacy alias {alias} resolves to nothing"
            )


# ---------------------------------------------------------------------------
# F-string hardcode regression
# ---------------------------------------------------------------------------


class TestNoNewHardcodes:
    """The inventory script (scripts/inventory_colors.py) classifies every
    colour literal in web.py. This test bounds the hex-hardcode count
    inside inline templates so a future PR can't silently add new ones.
    """

    def test_inline_hex_count_within_budget(self):
        from pathlib import Path
        import sys
        repo_root = Path(__file__).resolve().parents[1]
        sys.path.insert(0, str(repo_root / "scripts"))
        try:
            import inventory_colors as inv
        finally:
            sys.path.pop(0)

        rows = inv.scan_file(repo_root / "src" / "mediahub" / "web" / "web.py")
        hex_kinds = {"hex3", "hex4", "hex6", "hex8"}
        inline_hex = [
            r for r in rows
            if r["kind"] in hex_kinds
            and r["classification"] in ("inline_fstring", "inline_html_style")
        ]
        # Budget: ≤ 20 hardcodes. Today's baseline is ~19 after Stage A — a
        # future PR can either reduce this number (good) or add a justified
        # row to the inventory and lift the budget here (deliberate).
        assert len(inline_hex) <= 20, (
            f"Too many hex hardcodes in inline templates: {len(inline_hex)}.\n"
            f"Run `python scripts/inventory_colors.py` and migrate offenders "
            f"to var(--mh-*) references."
        )
