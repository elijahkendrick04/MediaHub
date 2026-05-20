"""Stage G2 — motion (Remotion) reads from the theme store.

When a brand_kit input carries a profile_id that resolves to an
on-disk theme JSON, _brand_to_dict() should pick the DARK scheme's
primary / secondary_container / tertiary roles. Falls back to the
legacy primary_colour fields when no theme is on disk.
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
    def test_brand_to_dict_uses_theme_store(self, isolated_data_dir):
        theme = _seed_theme("motion-test", "#A30D2D")
        result = _brand_to_dict({"profile_id": "motion-test"})
        # themeSource flag should announce it came from theme-store.
        assert result["themeSource"] == "theme-store"
        # Primary should be the DARK scheme primary, not the legacy hex.
        assert result["primary"].upper() == theme["roles"]["dark"]["primary"].upper()

    def test_dark_scheme_for_video_grade_saturation(self, isolated_data_dir):
        """The motion renderer specifically uses the DARK scheme
        (lighter, more saturated brand tone)."""
        theme = _seed_theme("dark-scheme", "#0E2A47")
        result = _brand_to_dict({"profile_id": "dark-scheme"})
        assert result["primary"].upper() == theme["roles"]["dark"]["primary"].upper()
        # Sanity: dark.primary ≠ light.primary for this seed
        assert theme["roles"]["dark"]["primary"] != theme["roles"]["light"]["primary"]

    def test_legacy_fallback_when_no_theme(self, isolated_data_dir):
        """A brand_kit without a profile_id (or with a missing theme
        file) falls back to the legacy primary_colour."""
        result = _brand_to_dict({"primary_colour": "#FF1234"})
        assert result["themeSource"] == "brand-kit"
        assert result["primary"] == "#FF1234"

    def test_unknown_profile_id_falls_back(self, isolated_data_dir):
        """A profile_id that doesn't resolve to a theme on disk falls
        back to the legacy path."""
        result = _brand_to_dict({
            "profile_id": "doesnt-exist",
            "primary_colour": "#FF1234",
        })
        assert result["themeSource"] == "brand-kit"
        assert result["primary"] == "#FF1234"

    def test_brand_kit_dataclass_input(self, isolated_data_dir):
        """A dataclass BrandKit is accepted, and its CONFIRMED primary
        wins over the theme store. CLAUDE.md requires motion to read the
        same BrandKit palette as the static renderer so a card's reel
        aligns with its still — the MD3 theme store only fills roles the
        BrandKit left unset."""
        from mediahub.brand.kit import BrandKit
        kit = BrandKit(profile_id="dc-test", display_name="DC",
                       primary_colour="#06D6A0")
        kit.ensure_derived_palette()
        result = _brand_to_dict(kit)
        # Confirmed brand primary is preserved exactly, not tone-shifted.
        assert result["primary"] == "#06D6A0"
        assert result["themeSource"] == "brand-kit"


class TestSecondaryAccent:
    def test_secondary_from_dark_secondary_container(self, isolated_data_dir):
        theme = _seed_theme("sec-test", "#0E2A47")
        result = _brand_to_dict({"profile_id": "sec-test"})
        expected = theme["roles"]["dark"]["secondary_container"].upper()
        assert result["secondary"].upper() == expected

    def test_accent_from_dark_tertiary(self, isolated_data_dir):
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
