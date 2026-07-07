"""Stage G2 — motion (Remotion) reads brand colours, theme_store is a fallback.

Original Stage G2 design routed motion through MD3's dark scheme
tokens (dark.primary / dark.secondary_container / dark.tertiary).
End-to-end verification against the live deployment on 2026-05-19
proved that this produced low-contrast pink-on-pink output for a
#FFD86E / #A30D2D / #000000 BrandKit — MD3's tonal-palette generator
is designed for UI surface harmony, not full-bleed brand colour
fills. The static graphic renderer, which uses the BrandKit's flat
primary/secondary/accent directly, produced beautifully on-brand
output for the same card.

The new contract:
  * When BrandKit carries primary/secondary/accent colours, those
    win — motion stays visually aligned with the static graphic and
    the brand the user actually configured.
  * When BrandKit has no flat colours but the theme store does, the
    theme store fills in (so a brand kit derived only from a logo
    still produces output).
  * ``themeSource`` reports which source actually contributed the
    roles used — "brand-kit" when the BrandKit's flat fields supplied
    every sourced role, "theme-store" when the store supplied them
    all, and "mixed" when a partial kit was filled from the store.
"""
from __future__ import annotations

import pytest

from mediahub.visual.motion import _brand_to_dict


@pytest.fixture
def isolated_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.theming.theme_store import _read_cached
    _read_cached.cache_clear()
    return tmp_path


def _seed_theme(profile_id: str, primary_hex: str = "#A30D2D"):
    """Use the BrandKit hook to populate the theme store."""
    from mediahub.brand.kit import BrandKit
    kit = BrandKit(profile_id=profile_id, display_name=f"Test {profile_id}",
                   primary_colour=primary_hex)
    return kit.ensure_derived_palette()


class TestThemeStoreSource:
    def test_theme_store_fills_when_brand_kit_has_no_flat_colours(self, isolated_data_dir):
        """A brand_kit dict with only a profile_id (no flat colours)
        gets its palette from the theme store on disk."""
        theme = _seed_theme("motion-test", "#A30D2D")
        result = _brand_to_dict({"profile_id": "motion-test"})
        assert result["themeSource"] == "theme-store"
        assert result["primary"].upper() == theme["roles"]["dark"]["primary"].upper()

    def test_brand_kit_flat_colours_win_over_theme_store(self, isolated_data_dir):
        """The headline visual-quality fix: when BrandKit carries the
        original brand colours AND a theme is on disk, BrandKit wins
        so motion stays visually aligned with the static graphic.
        Pre-fix this combination produced pink-on-pink output."""
        _seed_theme("brand-wins", "#A30D2D")
        result = _brand_to_dict({
            "profile_id": "brand-wins",
            "primary_colour": "#FFD86E",
            "secondary_colour": "#A30D2D",
            "accent_colour": "#000000",
        })
        assert result["themeSource"] == "brand-kit"
        assert result["primary"].upper() == "#FFD86E"
        assert result["secondary"].upper() == "#A30D2D"
        assert result["accent"].upper() == "#000000"

    def test_legacy_fallback_when_no_theme(self, isolated_data_dir):
        """A brand_kit without a profile_id (or with a missing theme
        file) falls back to the BrandKit's flat primary_colour."""
        result = _brand_to_dict({"primary_colour": "#FF1234"})
        assert result["themeSource"] == "brand-kit"
        assert result["primary"] == "#FF1234"

    def test_unknown_profile_id_falls_back(self, isolated_data_dir):
        """A profile_id that doesn't resolve to a theme on disk falls
        back to the BrandKit's flat fields."""
        result = _brand_to_dict({
            "profile_id": "doesnt-exist",
            "primary_colour": "#FF1234",
        })
        assert result["themeSource"] == "brand-kit"
        assert result["primary"] == "#FF1234"

    def test_brand_kit_dataclass_input(self, isolated_data_dir):
        """A BrandKit dataclass carries flat colour fields, so when
        passed in directly its colours win even if a theme was
        seeded on disk. Its accent field defaults to None, so the
        seeded theme contributes the accent — an honest "mixed"."""
        from mediahub.brand.kit import BrandKit
        kit = BrandKit(profile_id="dc-test", display_name="DC",
                       primary_colour="#06D6A0")
        kit.ensure_derived_palette()
        result = _brand_to_dict(kit)
        assert result["themeSource"] == "mixed"
        assert result["primary"].upper() == "#06D6A0"

    def test_partial_kit_filled_from_store_is_mixed(self, isolated_data_dir):
        """An accent-only kit gets primary/secondary from the theme
        store; themeSource must say so instead of claiming brand-kit."""
        _seed_theme("mixed-test", "#A30D2D")
        result = _brand_to_dict({
            "profile_id": "mixed-test",
            "accent_colour": "#FFD86E",
        })
        assert result["themeSource"] == "mixed"
        assert result["accent"].upper() == "#FFD86E"


class TestSecondaryAccent:
    def test_secondary_from_dark_secondary_container(self, isolated_data_dir):
        """When BrandKit has no flat colours, theme_store provides
        the secondary."""
        theme = _seed_theme("sec-test", "#0E2A47")
        result = _brand_to_dict({"profile_id": "sec-test"})
        expected = theme["roles"]["dark"]["secondary_container"].upper()
        assert result["secondary"].upper() == expected

    def test_accent_from_dark_tertiary(self, isolated_data_dir):
        """When BrandKit has no flat colours, theme_store provides
        the accent."""
        theme = _seed_theme("acc-test", "#0E2A47")
        result = _brand_to_dict({"profile_id": "acc-test"})
        expected = theme["roles"]["dark"]["tertiary"].upper()
        assert result["accent"].upper() == expected


class TestShapeUnchanged:
    """The Remotion compositions expect a specific dict shape. Stage G
    must not break the keys they consume."""

    def test_required_keys_present(self, isolated_data_dir):
        _seed_theme("shape-test", "#0E2A47")
        result = _brand_to_dict({"profile_id": "shape-test"})
        for key in ("primary", "secondary", "accent", "displayName",
                    "shortName", "logoDataUri"):
            assert key in result

    def test_display_name_preserved(self, isolated_data_dir):
        from mediahub.brand.kit import BrandKit
        kit = BrandKit(profile_id="name-test", display_name="Custom Name",
                       short_name="CN", primary_colour="#0E2A47")
        kit.ensure_derived_palette()
        result = _brand_to_dict(kit)
        assert result["displayName"] == "Custom Name"
        assert result["shortName"] == "CN"
