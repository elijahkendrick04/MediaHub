"""Tests for BrandKit.ensure_derived_palette (B3)."""
from __future__ import annotations

import pytest

from mediahub.brand.kit import BrandKit


class TestBrandKitDerivedPaletteField:
    def test_default_kit_has_no_derived_palette(self):
        kit = BrandKit.generic_default()
        assert kit.derived_palette is None

    def test_ensure_populates_derived_palette(self):
        kit = BrandKit.generic_default()
        p = kit.ensure_derived_palette()
        assert kit.derived_palette is p
        assert isinstance(p, dict)

    def test_ensure_returns_dtcg_shape(self):
        kit = BrandKit.generic_default()
        p = kit.ensure_derived_palette()
        # Required keys per ThemeJSON TypedDict.
        for key in ("schema_version", "seed_hex", "seed_hct", "palettes",
                    "roles", "quality", "decision_trace", "was_repaired",
                    "generated_at"):
            assert key in p, f"missing {key}"

    def test_palettes_contains_all_nine(self):
        kit = BrandKit.generic_default()
        p = kit.ensure_derived_palette()
        assert set(p["palettes"].keys()) == {
            "primary", "secondary", "tertiary", "neutral", "neutral_variant",
            "error", "success", "warning", "info",
        }

    def test_roles_contains_light_and_dark(self):
        kit = BrandKit.generic_default()
        p = kit.ensure_derived_palette()
        assert set(p["roles"].keys()) == {"light", "dark"}
        for scheme in p["roles"].values():
            assert "primary" in scheme
            assert "on_primary" in scheme
            assert "surface" in scheme

    def test_seed_hex_matches_input(self):
        kit = BrandKit(profile_id="x", display_name="X", primary_colour="#D4FF3A")
        p = kit.ensure_derived_palette()
        assert p["seed_hex"] == "#D4FF3A"


class TestIdempotence:
    def test_second_call_returns_same_object_unless_forced(self):
        kit = BrandKit.generic_default()
        p1 = kit.ensure_derived_palette()
        p2 = kit.ensure_derived_palette()
        assert p1 is p2

    def test_force_recomputes(self):
        kit = BrandKit.generic_default()
        p1 = kit.ensure_derived_palette()
        p2 = kit.ensure_derived_palette(force=True)
        # Object may not be the same, but content equal.
        assert p1 is not p2
        assert p1["seed_hex"] == p2["seed_hex"]
        assert p1["palettes"] == p2["palettes"]


class TestRoundTrip:
    def test_to_dict_includes_derived_palette(self):
        kit = BrandKit.generic_default()
        kit.ensure_derived_palette()
        d = kit.to_dict()
        assert "derived_palette" in d
        assert d["derived_palette"] is not None

    def test_from_dict_restores_derived_palette(self):
        kit1 = BrandKit.generic_default()
        kit1.ensure_derived_palette()
        kit2 = BrandKit.from_dict(kit1.to_dict())
        assert kit2.derived_palette is not None
        assert kit2.derived_palette["seed_hex"] == kit1.derived_palette["seed_hex"]
        assert kit2.derived_palette["palettes"] == kit1.derived_palette["palettes"]

    def test_old_profile_without_derived_palette_still_loads(self):
        """A profile JSON serialised before Stage B (no derived_palette
        key) must load cleanly through from_dict."""
        old_dict = {
            "profile_id": "legacy",
            "display_name": "Legacy Club",
            "primary_colour": "#A30D2D",
            "secondary_colour": "#000000",
            "accent_colour": None,
            "logo_svg": None,
            "governing_body": None,
            "short_name": "Legacy",
        }
        kit = BrandKit.from_dict(old_dict)
        assert kit.derived_palette is None   # default for missing key

    def test_unknown_keys_still_ignored(self):
        """from_dict ignores unknown keys — that contract must hold."""
        d = {
            "profile_id": "x",
            "display_name": "X",
            "future_field_not_yet_defined": "ignore me",
        }
        kit = BrandKit.from_dict(d)
        assert kit.profile_id == "x"


class TestDeterminism:
    def test_same_kit_same_palette(self):
        k1 = BrandKit(profile_id="x", display_name="X", primary_colour="#06D6A0")
        k2 = BrandKit(profile_id="y", display_name="Y", primary_colour="#06D6A0")
        p1 = k1.ensure_derived_palette()
        p2 = k2.ensure_derived_palette()
        # Same seed → same palettes.
        assert p1["palettes"] == p2["palettes"]
        assert p1["roles"] == p2["roles"]


class TestSourceFallback:
    def test_uses_safe_primary_when_no_logo(self):
        kit = BrandKit(profile_id="x", display_name="X", primary_colour="#06D6A0")
        p = kit.ensure_derived_palette()
        assert p["seed_hex"] == "#06D6A0"
        assert p["seed_source"] == "hex"

    def test_invalid_primary_falls_back_to_safe_primary(self):
        kit = BrandKit(profile_id="x", display_name="X", primary_colour="not a hex")
        p = kit.ensure_derived_palette()
        # safe_primary returns the BrandKit-class default for invalid input
        assert p["seed_hex"] in ("#A30D2D", "#0E2A47")
