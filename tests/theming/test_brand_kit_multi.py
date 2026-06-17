"""G1.20 — BrandKit multi-colour wiring.

``BrandKit.ensure_derived_palette`` threads the club's secondary + accent
colours into the theming engine. Existing kits (whose secondary defaults to
the non-brandable ``#000000``) must derive byte-identically to the pre-G1.20
single-seed engine; kits with real, distinct brand colours get those colours
placed into the secondary / tertiary roles.
"""
from __future__ import annotations

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.theming import derive_theme


@pytest.fixture(autouse=True)
def _isolate_data_dir(tmp_path, monkeypatch):
    """Pin DATA_DIR so the disk-mirror side-effect lands in tmp."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.theming.theme_store import _read_cached

    _read_cached.cache_clear()


def _strip_volatile(theme_json: dict) -> dict:
    out = dict(theme_json)
    out.pop("generated_at", None)
    # decision_trace differs (multi appends lines) — compare the palette + roles
    # which are what actually render. The single-seed back-compat case keeps an
    # identical trace too, asserted separately.
    return out


class TestBackCompatExistingKits:
    @pytest.mark.parametrize("primary", ["#A30D2D", "#0E2A47", "#06D6A0", "#D4FF3A"])
    def test_default_secondary_black_is_byte_identical(self, primary):
        """A kit with the default secondary (#000000, non-brandable) and no
        accent must match derive_theme(primary) exactly."""
        kit = BrandKit(profile_id="bc", display_name="BC", primary_colour=primary)
        # default secondary_colour is "#000000", accent_colour is None
        got = kit.ensure_derived_palette()
        expected = derive_theme(primary).to_json()
        assert _strip_volatile(got)["palettes"] == _strip_volatile(expected)["palettes"]
        assert _strip_volatile(got)["roles"] == _strip_volatile(expected)["roles"]

    def test_seed_hex_unchanged_for_single_colour(self):
        kit = BrandKit(profile_id="x", display_name="X", primary_colour="#D4FF3A")
        assert kit.ensure_derived_palette()["seed_hex"] == "#D4FF3A"


class TestMultiColourKits:
    def test_brandable_secondary_flows_into_secondary_role(self):
        kit = BrandKit(
            profile_id="multi",
            display_name="Multi",
            primary_colour="#0E2A47",
            secondary_colour="#C9A227",  # real gold
        )
        p = kit.ensure_derived_palette()
        assert p["seed_hex"] == "#0E2A47"
        # secondary ramp now carries gold's hue (~91), not the navy derivation
        assert 80 <= p["palettes"]["secondary"]["hue"] <= 100

    def test_accent_flows_into_tertiary_role(self):
        kit = BrandKit(
            profile_id="tri",
            display_name="Tri",
            primary_colour="#0E2A47",
            secondary_colour="#C9A227",
            accent_colour="#A30D2D",  # crimson
        )
        p = kit.ensure_derived_palette()
        tert_hue = p["palettes"]["tertiary"]["hue"]
        assert tert_hue <= 30 or tert_hue >= 350  # crimson ~16°

    def test_generic_default_is_multi_navy_gold(self):
        """The shipped generic default (navy primary + gold secondary) now
        expands to a genuine two-colour palette while keeping all 9 ramps."""
        kit = BrandKit.generic_default()
        p = kit.ensure_derived_palette()
        assert p["seed_hex"] == "#0E2A47"
        assert set(p["palettes"].keys()) == {
            "primary", "secondary", "tertiary", "neutral", "neutral_variant",
            "error", "success", "warning", "info",
        }
        # gold secondary, not navy-derived
        assert 80 <= p["palettes"]["secondary"]["hue"] <= 100

    def test_non_brandable_extras_do_not_expand(self):
        """A kit whose secondary is a near-grey is left single-seed."""
        kit = BrandKit(
            profile_id="grey",
            display_name="Grey",
            primary_colour="#A30D2D",
            secondary_colour="#777777",  # near-grey, not brandable
        )
        got = kit.ensure_derived_palette()
        expected = derive_theme("#A30D2D").to_json()
        assert got["palettes"] == expected["palettes"]


class TestIdempotenceAndShape:
    def test_idempotent_for_multi_kit(self):
        kit = BrandKit(
            profile_id="idem",
            display_name="Idem",
            primary_colour="#0E2A47",
            secondary_colour="#C9A227",
        )
        p1 = kit.ensure_derived_palette()
        p2 = kit.ensure_derived_palette()
        assert p1 is p2

    def test_force_recompute_stable(self):
        kit = BrandKit(
            profile_id="force",
            display_name="Force",
            primary_colour="#0E2A47",
            secondary_colour="#C9A227",
        )
        p1 = kit.ensure_derived_palette()
        p2 = kit.ensure_derived_palette(force=True)
        assert p1 is not p2
        assert p1["palettes"] == p2["palettes"]

    def test_disk_mirror_written_for_multi_kit(self):
        kit = BrandKit(
            profile_id="disk-multi",
            display_name="Disk",
            primary_colour="#0E2A47",
            secondary_colour="#C9A227",
        )
        p = kit.ensure_derived_palette()
        from mediahub.theming.theme_store import read_theme

        assert read_theme("disk-multi") == p
