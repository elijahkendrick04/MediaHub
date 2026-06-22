"""Email & newsletter composer (roadmap 1.17) — build 1: the email palette."""

from __future__ import annotations

import pytest

from mediahub.email_design.theme import EMAIL_FONT_STACK, email_palette


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def test_default_palette_is_complete_and_hex():
    pal = email_palette(None, None)
    for key in ("bg", "panel", "ink", "muted", "border", "brand", "on_brand", "accent", "on_accent", "surface"):
        assert key in pal, key
        assert isinstance(pal[key], str) and pal[key].startswith("#")
        assert len(pal[key]) == 7  # #rrggbb


def test_manual_palette_wins_over_extracted_and_legacy():
    profile = {
        "profile_id": "club-a",
        "brand_palette_manual": {"primary": "#123456", "secondary": "#abcdef"},
        "brand_palette_extracted": {"primary": "#000000"},
        "brand_primary": "#ffffff",
    }
    pal = email_palette(profile, None)
    assert pal["brand"] == "#123456"
    assert pal["accent"] == "#abcdef"


def test_extracted_used_when_no_manual():
    profile = {"brand_palette_extracted": {"primary": "#0d6efd"}}
    assert email_palette(profile, None)["brand"] == "#0d6efd"


def test_legacy_field_used_as_late_fallback():
    profile = {"brand_primary": "#a30d2d", "brand_secondary": "#ffd700"}
    pal = email_palette(profile, None)
    assert pal["brand"] == "#a30d2d"
    assert pal["accent"] == "#ffd700"


def test_explicit_accent_slot_overrides_secondary():
    profile = {
        "brand_palette_manual": {"primary": "#101010", "secondary": "#202020", "accent": "#ff8800"},
    }
    assert email_palette(profile, None)["accent"] == "#ff8800"


def test_on_colours_are_legible():
    # a dark brand should get light ink; a light brand should get dark ink
    dark = email_palette({"brand_primary": "#0a2540"}, None)
    light = email_palette({"brand_primary": "#ffe14d"}, None)
    # crude luminance check: on_brand contrasts the brand
    assert dark["on_brand"].lower() != dark["brand"].lower()
    assert light["on_brand"].lower() != light["brand"].lower()
    # the dark navy gets a light ink, the bright yellow gets a dark ink
    assert dark["on_brand"].lower() in ("#ffffff", "#f5f2e8")
    assert light["on_brand"].lower() not in ("#ffffff", "#f5f2e8")


def test_surface_is_a_light_tint_of_brand():
    pal = email_palette({"brand_primary": "#0a2540"}, None)
    # surface is brand blended 90% toward white → much lighter than brand
    assert pal["surface"] != pal["brand"]
    # near-white-ish (each channel high)
    r = int(pal["surface"][1:3], 16)
    assert r > 200


def test_garbage_hex_falls_back_to_default():
    pal = email_palette({"brand_primary": "not-a-colour"}, None)
    assert pal["brand"] == "#0a2540"  # house default navy


def test_font_stack_has_no_remote_webfont():
    # email uses the device system stack — no Google Fonts / @import / link
    assert "googleapis" not in EMAIL_FONT_STACK
    assert "gstatic" not in EMAIL_FONT_STACK
    assert "@import" not in EMAIL_FONT_STACK
    assert "-apple-system" in EMAIL_FONT_STACK


def test_brand_kit_colour_used_when_no_profile_palette():
    class _Kit:
        primary_colour = "#336699"
        secondary_colour = "#cc9933"

    pal = email_palette(None, _Kit())
    assert pal["brand"] == "#336699"
    assert pal["accent"] == "#cc9933"
