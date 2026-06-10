"""Canva-informed graphics upgrade tests.

Pins the brand-fidelity + de-clutter fixes and the two new layout families:
- a PB keeps the club's real accent (no generic-cyan hijack) and shows no badge
- medal tiers still tint the accent (gold/silver/bronze) and badge
- the no-photo surname watermark fits the canvas (no "CARTER" -> "CART"/"ARTER")
- action_photo_hero / stat_line are registered + fillable end to end

All pure-function (no Playwright) so they run in any environment.
"""
from __future__ import annotations

from mediahub.graphic_renderer import autofit
from mediahub.graphic_renderer.render import (
    LAYOUTS_DIR,
    _FILLERS,
    _MEDAL_ACCENTS,
    _SURNAME_FONT_FAMILY,
    _common_replacements,
    _detect_medal_tier,
    _fill_action_photo_hero,
    _fill_stat_line,
    _mega_watermark_px,
)


class _Brief:
    def __init__(self, *, label="NEW PB", place="", accent="#E8B94E", primary="#0A2540"):
        self.palette = {"primary": primary, "secondary": "#0E1B2C", "accent": accent}
        self.text_layers = {
            "athlete_full_name": "Emma Carter",
            "athlete_first_name": "Emma",
            "athlete_surname": "Carter",
            "achievement_label": label,
            "event_name": "100m Freestyle",
            "result_value": "58.34",
            "meet_name": "County Championships",
            "club_full": "Riverside Swimming Club",
            "club_short": "RSC",
        }
        if place:
            self.text_layers["place"] = place
        self.confidence_label = label
        self.primary_hook = label
        self.inspiration_pattern_id = ""
        self.profile_id = "t"
        self.id = "b1"
        self.content_item_id = "c1"


class _Brand:
    profile_id = "t"
    display_name = "Riverside Swimming Club"
    short_name = "RSC"
    primary_colour = "#0A2540"
    secondary_colour = "#0E1B2C"
    accent_colour = "#E8B94E"


def _repl(brief):
    return _common_replacements(
        brief, 1080, 1350, _Brand(),
        athlete_data_uri=None, logo_block="", result_chip="", sponsor_block="",
    )


# --- brand fidelity: a PB keeps the club accent; medals still tint ----------


def test_pb_is_not_a_medal_tier():
    assert _detect_medal_tier(_Brief(label="NEW PB")) is None
    assert "pb" not in _MEDAL_ACCENTS  # the cyan PB override is gone


def test_pb_keeps_club_accent_not_cyan():
    repl = _repl(_Brief(label="NEW PB", accent="#E8B94E"))
    assert repl["ACCENT"].upper() == "#E8B94E"
    assert repl["ACCENT"].upper() != "#22D3EE"
    # No floating "NEW PB" badge to collide with the result chip / ribbon.
    assert repl["MEDAL_BADGE_BLOCK"] == ""


def test_gold_place_still_tints_accent_and_badges():
    repl = _repl(_Brief(label="GOLD", place="1"))
    assert repl["ACCENT"].upper() == _MEDAL_ACCENTS["gold"]["accent"].upper()
    assert "GOLD" in repl["MEDAL_BADGE_BLOCK"]


# --- no-photo surname watermark fits the canvas -----------------------------


def test_mega_watermark_fits_with_margin():
    width, cap = 1080, int(min(1080, 1350) * 0.78)
    for name in ("CARTER", "REEKIE-AYALA", "SNOWDON", "NG"):
        px = _mega_watermark_px(name, width, cap)
        assert px <= cap
        w = autofit.measure_line_px(
            name.upper(), px, font_family=_SURNAME_FONT_FAMILY, weight=900
        )
        # Centred watermark: must fit inside the ~84% target with headroom so a
        # real-Anton render never bleeds a letter off either edge.
        assert w <= width * 0.86, f"{name}: {w:.0f}px at {px}px exceeds safe width"


def test_mega_watermark_short_name_keeps_design_size():
    width, cap = 1080, 700
    assert _mega_watermark_px("NG", width, cap) == cap


# --- new families: fillable end to end --------------------------------------


def test_new_layout_templates_exist_and_are_registered():
    for fam in ("action_photo_hero", "stat_line"):
        assert (LAYOUTS_DIR / f"{fam}.html").is_file(), f"missing {fam}.html"
        assert fam in _FILLERS, f"{fam} not wired into _FILLERS"


def test_stat_line_filler_populates_hero_and_headline():
    base = _repl(_Brief())
    repl = _fill_stat_line(_Brief(), 1080, 1350, base)
    assert repl["HERO_VALUE"] == "58.34"
    assert "100m Freestyle" in repl["HERO_EVENT"]
    assert repl["HEADLINE_LINE1"]  # a hook landed on line one
    assert int(repl["HERO_FONT_SIZE"]) > 0
    assert "Emma Carter" in repl["SUPPORT_CELLS"]


def test_action_photo_hero_filler_sets_result_and_ribbon():
    base = _repl(_Brief())
    base["HERO_PHOTO_URI"] = "data:image/jpeg;base64,AAAA"
    repl = _fill_action_photo_hero(_Brief(), 1080, 1350, base)
    assert repl["RESULT_VALUE_RAW"] == "58.34"
    assert repl["ACHIEVEMENT_LABEL"]
    assert int(repl["RIBBON_FONT_SIZE"]) > 0


def test_new_families_registered_for_selection():
    # The random-pick family pool (_GENERIC_FAMILIES) went with the
    # enum-permutation engine (SEQ-3); selection now happens via the pattern
    # library (v1 path) and the v2 archetype registry.
    from mediahub.creative_brief.generator import _TEXT_LED_FAMILIES
    from mediahub.inspiration.pattern_library import PATTERNS

    fams = {p["family"] for p in PATTERNS}
    assert {"action_photo_hero", "stat_line"} <= fams
    assert "stat_line" in _TEXT_LED_FAMILIES
