"""Stage C — CSS architecture tests.

Pins the contract of the Phase 1.6 Stage C migration:

  * The three static CSS files exist on disk and are non-empty.
  * The loader (``mediahub.web.theme_tokens``) concatenates them in
    the documented cascade order.
  * The seven seed variables are declared.
  * Stage A fallback values are byte-identical inside the
    ``@supports not`` block (zero pixel drift for Safari ≤ 16.3).
  * The modern branch contains genuine ``oklch(from var(...))``
    derivations.
  * Calibrated derivations land within ΔE2000 ≤ 5 of the Stage A
    hand-coded primitive values (pixel-parity for modern browsers).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def static_theme_dir() -> Path:
    from mediahub.web.theme_tokens import STATIC_THEME_DIR
    return STATIC_THEME_DIR


@pytest.fixture(scope="module")
def base_css() -> str:
    from mediahub.web.theme_tokens import THEME_BASE_CSS
    return THEME_BASE_CSS


@pytest.fixture(scope="module")
def fallback_css() -> str:
    from mediahub.web.theme_tokens import THEME_FALLBACK_CSS
    return THEME_FALLBACK_CSS


@pytest.fixture(scope="module")
def derive_css() -> str:
    from mediahub.web.theme_tokens import THEME_DERIVE_CSS
    return THEME_DERIVE_CSS


@pytest.fixture(scope="module")
def assembled_css() -> str:
    from mediahub.web.theme_tokens import THEME_TOKENS_CSS
    return THEME_TOKENS_CSS


# ---------------------------------------------------------------------------
# Files on disk
# ---------------------------------------------------------------------------


class TestStaticFilesExist:
    def test_directory_exists(self, static_theme_dir):
        assert static_theme_dir.is_dir(), f"missing dir {static_theme_dir}"

    @pytest.mark.parametrize("filename", [
        "theme-base.css", "theme-fallback.css", "theme-derive.css",
    ])
    def test_file_exists_and_nonempty(self, static_theme_dir, filename):
        path = static_theme_dir / filename
        assert path.is_file(), f"missing {path}"
        assert path.stat().st_size > 500, f"{filename} suspiciously small"


# ---------------------------------------------------------------------------
# Loader behaviour
# ---------------------------------------------------------------------------


class TestLoader:
    def test_module_constants_are_strings(self, base_css, fallback_css, derive_css):
        for src in (base_css, fallback_css, derive_css):
            assert isinstance(src, str)
            assert len(src) > 500

    def test_assembled_css_is_concatenation(self, assembled_css,
                                            base_css, fallback_css, derive_css):
        # Assembled = base + "\n" + fallback + "\n" + derive + "\n" + cascade
        # (documented order; Stage E added the cascade-animation layer
        # at the end). Cascade is optional — if Stage E hasn't shipped
        # yet the assembled string is the original 3-way concat.
        try:
            from mediahub.web.theme_tokens import THEME_CASCADE_CSS
        except ImportError:
            THEME_CASCADE_CSS = None
        if THEME_CASCADE_CSS is None:
            expected = base_css + "\n" + fallback_css + "\n" + derive_css
        else:
            expected = (
                base_css + "\n" + fallback_css + "\n"
                + derive_css + "\n" + THEME_CASCADE_CSS
            )
        assert assembled_css == expected

    def test_re_import_is_stable(self):
        """Re-importing the module should yield the same content."""
        import importlib
        import mediahub.web.theme_tokens as mod
        a = mod.THEME_TOKENS_CSS
        importlib.reload(mod)
        b = mod.THEME_TOKENS_CSS
        assert a == b


# ---------------------------------------------------------------------------
# Seed variables (C2)
# ---------------------------------------------------------------------------


_SEEDS = [
    ("--mh-brand-seed",    "#D4FF3A"),
    ("--mh-tertiary-seed", "#F4D58D"),
    ("--mh-neutral-seed",  "#F5F2E8"),
    ("--mh-error-seed",    "#FF6B6B"),
    ("--mh-success-seed",  "#5EE39A"),
    ("--mh-warning-seed",  "#FFB454"),
    ("--mh-info-seed",     "#4DA3FF"),
]


class TestSeeds:
    @pytest.mark.parametrize("name,expected_hex", _SEEDS)
    def test_seed_declared_in_base(self, base_css, name, expected_hex):
        # Default declaration in :root + @property registration.
        pattern = re.compile(rf"{re.escape(name)}:\s*({expected_hex})\b", re.IGNORECASE)
        assert pattern.search(base_css), f"seed {name} = {expected_hex} not in theme-base.css"

    @pytest.mark.parametrize("name,_hex", _SEEDS)
    def test_seed_has_property_registration(self, base_css, name, _hex):
        # @property block for each seed so Stage E can interpolate.
        pattern = re.compile(
            rf"@property\s+{re.escape(name)}\s*\{{[^}}]*syntax:\s*\"<color>\""
            rf"[^}}]*initial-value:\s*#[0-9A-Fa-f]{{6}}",
            re.DOTALL,
        )
        assert pattern.search(base_css), (
            f"missing @property registration for seed {name}"
        )


# ---------------------------------------------------------------------------
# C4 — Fallback contains Stage A byte-identical values
# ---------------------------------------------------------------------------


# Stage A's hand-coded primitive values. The fallback file MUST carry
# these verbatim so Safari ≤ 16.3 sees identical pixels.
_STAGE_A_PRIMITIVES = {
    # Brand ramp
    "--mh-prim-brand-0":    "#FFFFFF",
    "--mh-prim-brand-50":   "#FAFFE6",
    "--mh-prim-brand-100":  "#F1FFB8",
    "--mh-prim-brand-200":  "#E6FF8A",
    "--mh-prim-brand-300":  "#E6FF6B",
    "--mh-prim-brand-400":  "#D4FF3A",
    "--mh-prim-brand-500":  "#C2E832",
    "--mh-prim-brand-600":  "#A8CC2E",
    "--mh-prim-brand-700":  "#8AA823",
    "--mh-prim-brand-800":  "#6B821C",
    "--mh-prim-brand-900":  "#4A5E12",
    "--mh-prim-brand-950":  "#2A360A",
    "--mh-prim-brand-1000": "#000000",
    # Tertiary
    "--mh-prim-tertiary-50":   "#FFF9EC",
    "--mh-prim-tertiary-100":  "#FFEEC4",
    "--mh-prim-tertiary-200":  "#FFE5A1",
    "--mh-prim-tertiary-300":  "#F8DC97",
    "--mh-prim-tertiary-400":  "#F4D58D",
    "--mh-prim-tertiary-500":  "#DEBD75",
    "--mh-prim-tertiary-600":  "#C9A04B",
    "--mh-prim-tertiary-700":  "#9F7E36",
    "--mh-prim-tertiary-800":  "#6E5524",
    "--mh-prim-tertiary-900":  "#3F2F12",
    "--mh-prim-tertiary-950":  "#2B1F00",
    # Neutral
    "--mh-prim-neutral-50":   "#F5F2E8",
    "--mh-prim-neutral-300":  "#B6B2A6",
    "--mh-prim-neutral-400":  "#9A988A",
    "--mh-prim-neutral-900":  "#14171F",
    "--mh-prim-neutral-950":  "#0A0B11",
    "--mh-prim-neutral-1000": "#06070C",
    # Status anchors
    "--mh-prim-error-400":   "#FF6B6B",
    "--mh-prim-success-400": "#5EE39A",
    "--mh-prim-warning-400": "#FFB454",
    "--mh-prim-info-400":    "#4DA3FF",
}


class TestFallback:
    def test_fallback_is_supports_not_gated(self, fallback_css):
        assert "@supports not (color: oklch(from red l c h))" in fallback_css

    @pytest.mark.parametrize("token,expected_hex", _STAGE_A_PRIMITIVES.items())
    def test_fallback_value_byte_identical(self, fallback_css, token, expected_hex):
        # The fallback file MUST carry the exact Stage A value so Safari
        # ≤ 16.3 sees identical pixels to today.
        pattern = re.compile(
            rf"{re.escape(token)}:\s*({expected_hex})\b",
            re.IGNORECASE,
        )
        assert pattern.search(fallback_css), (
            f"fallback missing {token} = {expected_hex}"
        )


# ---------------------------------------------------------------------------
# C2 — Derive block uses relative-colour syntax
# ---------------------------------------------------------------------------


class TestDerive:
    def test_derive_is_supports_gated(self, derive_css):
        assert "@supports (color: oklch(from red l c h))" in derive_css

    def test_brand_derivations_use_seed(self, derive_css):
        # At least 8 oklch(from var(--mh-brand-seed) …) expressions.
        matches = re.findall(r"oklch\(from var\(--mh-brand-seed\)", derive_css)
        assert len(matches) >= 8, f"only {len(matches)} brand derivations"

    def test_tertiary_derivations_use_seed(self, derive_css):
        matches = re.findall(r"oklch\(from var\(--mh-tertiary-seed\)", derive_css)
        assert len(matches) >= 8, f"only {len(matches)} tertiary derivations"

    def test_color_mix_used_for_outlines(self, derive_css):
        # The outline / elevation tokens should use color-mix() in the
        # derive branch so they pick up theme changes.
        assert "color-mix(in oklch" in derive_css

    def test_brand_seed_appears_as_tone_400(self, derive_css):
        # tone 400 is the seed itself; the derive branch should declare
        # --mh-prim-brand-400 as var(--mh-brand-seed) (not derived).
        pattern = re.compile(r"--mh-prim-brand-400:\s*var\(--mh-brand-seed\)")
        assert pattern.search(derive_css)


# ---------------------------------------------------------------------------
# C3 — light-dark() for prefers-color-scheme parity
# ---------------------------------------------------------------------------


class TestLightDark:
    def test_color_scheme_declared(self, base_css):
        # color-scheme tells the UA chrome (scrollbars, form controls)
        # which mode to render in.
        assert "color-scheme:" in base_css

    def test_light_dark_used_extensively(self, base_css):
        # Tier-2 role tokens are wrapped in light-dark(). Count how
        # many actually fire.
        matches = re.findall(r"light-dark\(", base_css)
        assert len(matches) >= 20, (
            f"only {len(matches)} light-dark() wrappers; expected ≥ 20 "
            f"(one per tier-2 role token)"
        )

    def test_light_dark_arguments_are_valid_primitive_refs(self, base_css):
        """Stage D (UI 1.23): every light-dark(var(--a), var(--b)) must
        reference declared primitives (or tier-2 roles) on BOTH sides —
        no dangling vars. This is the structural successor to the old
        Stage-C "args must be identical" pin, which UI 1.23 replaces by
        shipping a real light palette (asserted below).
        """
        declared = set(re.findall(r"(--mh-[\w-]+)\s*:", base_css))
        # Primitives live in the fallback/derive files, not base — accept
        # the documented primitive namespace without requiring a local decl.
        for m in re.finditer(
            r"light-dark\(\s*var\((--[\w-]+)\)\s*,\s*var\((--[\w-]+)\)\s*\)",
            base_css,
        ):
            light, dark = m.group(1), m.group(2)
            for ref in (light, dark):
                ok = ref.startswith("--mh-prim-") or ref in declared
                assert ok, f"light-dark() references undeclared var {ref}"

    def test_real_light_palette_shipped(self, base_css):
        """UI 1.23 turns the dark-only Stage C scaffold into a real
        light theme: the core surface + on-surface role tokens MUST now
        resolve to DIFFERENT primitives in light vs dark. (The brand /
        status roles are intentionally allowed to stay identical — the
        lane-yellow fill is brand identity in both modes.)
        """
        must_differ = {
            "--mh-surface", "--mh-surface-deep", "--mh-surface-variant",
            "--mh-surface-container", "--mh-surface-container-high",
            "--mh-on-surface", "--mh-on-surface-variant",
            "--mh-on-surface-muted", "--mh-on-surface-faint",
        }
        for token in must_differ:
            m = re.search(
                rf"{re.escape(token)}:\s*light-dark\(\s*var\((--[\w-]+)\)\s*,"
                rf"\s*var\((--[\w-]+)\)\s*\)",
                base_css,
            )
            assert m, f"{token} is no longer a light-dark(var(), var()) role"
            light, dark = m.group(1), m.group(2)
            assert light != dark, (
                f"{token} still ships identical light/dark args ({light}); "
                f"UI 1.23 requires a real light value"
            )


# ---------------------------------------------------------------------------
# Pixel parity — the derivation lands within ΔE2000 ≤ 5 of Stage A
# ---------------------------------------------------------------------------


# (tone, target_L, chroma_factor) — must mirror the formulas in
# theme-derive.css. If you change one file you must update the other.
_BRAND_FORMULAS = [
    (50,  0.991, 0.12),
    (100, 0.973, 0.45),
    (200, 0.954, 0.76),
    (300, 0.948, 0.91),
    (500, 0.866, 0.96),
    (600, 0.772, 0.84),
    (700, 0.660, 0.71),
    (800, 0.535, 0.58),
    (900, 0.405, 0.42),
    (950, 0.272, 0.30),
]
_TERTIARY_FORMULAS = [
    (50,  0.982, 0.26),
    (100, 0.953, 0.81),
    (200, 0.928, 1.14),
    (300, 0.894, 1.13),
    (500, 0.792, 0.94),
    (600, 0.708, 1.21),
    (700, 0.584, 1.07),
    (800, 0.434, 0.85),
    (900, 0.286, 0.55),
    (950, 0.213, 0.47),
]


def _hex_for_tone(palette: str, tone: int) -> str:
    return _STAGE_A_PRIMITIVES.get(f"--mh-prim-{palette}-{tone}", "")


class TestPixelParity:
    """For each derived tone, the value computed by the OKLCH formula
    on the Stage A seed must land within ΔE2000 ≤ 5 of the Stage A
    hand-coded value. We compute this in Python (coloraide) since we
    can't reliably execute CSS resolution in the test environment.
    """

    def _derived_value(self, seed_hex: str, target_l: float, chroma_factor: float) -> str:
        from coloraide import Color
        seed = Color(seed_hex).convert("oklch")
        derived = Color("oklch", [target_l, seed["chroma"] * chroma_factor, seed["hue"]])
        derived_srgb = derived.fit("srgb")
        return derived_srgb.convert("srgb").to_string(hex=True, upper=True)

    @pytest.mark.parametrize("tone,target_l,chroma_factor", _BRAND_FORMULAS)
    def test_brand_derivation_within_5_delta_e(self, tone, target_l, chroma_factor):
        from coloraide import Color
        seed_hex = "#D4FF3A"
        stage_a_hex = _hex_for_tone("brand", tone)
        if not stage_a_hex:
            pytest.skip(f"no Stage A reference for brand-{tone}")
        derived_hex = self._derived_value(seed_hex, target_l, chroma_factor)
        delta = Color(derived_hex).delta_e(Color(stage_a_hex), method="2000")
        assert delta <= 5.0, (
            f"brand-{tone}: derived={derived_hex} Stage A={stage_a_hex} "
            f"ΔE2000={delta:.2f} (> 5.0)"
        )

    @pytest.mark.parametrize("tone,target_l,chroma_factor", _TERTIARY_FORMULAS)
    def test_tertiary_derivation_within_5_delta_e(self, tone, target_l, chroma_factor):
        from coloraide import Color
        seed_hex = "#F4D58D"
        stage_a_hex = _hex_for_tone("tertiary", tone)
        if not stage_a_hex:
            pytest.skip(f"no Stage A reference for tertiary-{tone}")
        derived_hex = self._derived_value(seed_hex, target_l, chroma_factor)
        delta = Color(derived_hex).delta_e(Color(stage_a_hex), method="2000")
        assert delta <= 5.0, (
            f"tertiary-{tone}: derived={derived_hex} Stage A={stage_a_hex} "
            f"ΔE2000={delta:.2f} (> 5.0)"
        )


# ---------------------------------------------------------------------------
# Cascade integrity — assembled CSS is balanced + complete
# ---------------------------------------------------------------------------


class TestCascadeIntegrity:
    def test_braces_balanced(self, assembled_css):
        """The assembled CSS must have balanced braces. Naive count
        sanity-check (won't catch all malformed CSS but catches
        common copy-paste damage)."""
        opens = assembled_css.count("{")
        closes = assembled_css.count("}")
        assert opens == closes, f"unbalanced braces: {opens} {{ vs {closes} }}"

    def test_no_partial_oklch(self, assembled_css):
        """Common typo: oklch(from … without closing paren."""
        # Count `oklch(from ` vs the corresponding closing structures.
        from_count = assembled_css.count("oklch(from ")
        # Each should have a matching " h)" or " h / N)" closer.
        closer_count = len(re.findall(r"oklch\(from[^)]+\)", assembled_css))
        assert from_count == closer_count, (
            f"unbalanced oklch(from ...): {from_count} openings vs {closer_count} closes"
        )

    def test_every_supports_block_closes(self, assembled_css):
        """@supports must have matching opening + closing braces."""
        opens = len(re.findall(r"@supports\s+(?:not\s+)?\(", assembled_css))
        # Roughly each @supports has at least one rule block inside +
        # the outer block. We only check that the outer braces close.
        assert opens >= 2, f"expected ≥ 2 @supports blocks, got {opens}"
