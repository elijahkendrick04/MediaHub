"""Text-quality regression tests for generated graphics.

Live-verified defects this file pins down:
- bullets hard-cut mid-word at 80 chars ("…topping the podium at the N")
- emoji-only sentences rendered as bullets ("🏆🏆🏆")
- stat tiles hard-cut mid-word ("North District Ope")
- the routing hook word ("SPONSOR") rendered as a stat-tile value ("RESULT")
- sponsor headline composed as "<SPONSOR NAME> RECAP"
- the giant surname watermark clipping mid-letter at the canvas edge
- "(SC)" / "(LC)" course jargon on public event names
"""

from __future__ import annotations

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate
from mediahub.graphic_renderer import autofit
from mediahub.graphic_renderer.render import (
    _SURNAME_FONT_FAMILY,
    _clean_event_name,
    _ellipsize,
    _surname_font_px,
)
from mediahub.media_requirements.evaluator import EvaluationResult
from mediahub.web.web import _stub_card_to_graphic_item


# ---------------------------------------------------------------------------
# web.py — bullet shaping for caption-only stub cards
# ---------------------------------------------------------------------------


def test_stub_card_filters_emoji_only_bullets():
    card = {"caption": "Three golds for the squad. \U0001f3c6\U0001f3c6\U0001f3c6. What a weekend."}
    item = _stub_card_to_graphic_item("session_update", card, {"meet_name": "Spring Open"})
    bullets = item["graphic_text"]["bullets"]
    assert bullets, "real sentences must survive"
    for b in bullets:
        assert any(ch.isalnum() for ch in b), f"emoji-only bullet leaked: {b!r}"


def test_stub_card_bullets_word_boundary_truncated():
    long_sentence = (
        "An absolutely outstanding set of swims from every single one of our "
        "athletes, topping the podium at the North District Open Championships."
    )
    card = {"caption": "Session one done. " + long_sentence}
    item = _stub_card_to_graphic_item("session_update", card, {})
    bullets = item["graphic_text"]["bullets"]
    assert bullets
    for b in bullets:
        assert len(b) <= 81  # 80-char budget + ellipsis
        # No mid-word fragment: strip the ellipsis and check the last word
        last = b.rstrip("…").split()[-1].strip(",;:.!?")
        assert last in card["caption"], f"mid-word cut: {last!r}"


def test_sponsor_headline_never_reads_as_recap():
    card = {"caption": "Huge thanks to our partners for backing the squad."}
    item = _stub_card_to_graphic_item(
        "sponsor_post", card, {"sponsor_name": "MAK Swimwear", "meet_name": "Spring Open"}
    )
    gt = item["graphic_text"]
    pair = gt["headline_line1"] + " " + gt["headline_line2"]
    assert "RECAP" not in pair
    # The honest sponsor framing must be present somewhere in the pair.
    assert "THANK YOU" in pair
    assert "MAK" in pair  # sponsor name leads the headline


def test_sponsor_headline_without_sponsor_name_still_honest():
    card = {"caption": "Thanks to everyone who supports the club."}
    item = _stub_card_to_graphic_item("sponsor_post", card, {})
    gt = item["graphic_text"]
    pair = (gt["headline_line1"] + " " + gt["headline_line2"]).strip()
    assert pair, "headline must not be blank"
    assert "RECAP" not in pair


def test_preview_and_session_headlines_labelled_honestly():
    prev = _stub_card_to_graphic_item(
        "weekend_preview", {"caption": "Big weekend ahead."}, {"meet_name": "Spring Open"}
    )
    pgt = prev["graphic_text"]
    p_pair = pgt["headline_line1"] + " " + pgt["headline_line2"]
    assert "PREVIEW" in p_pair
    assert "RECAP" not in p_pair

    live = _stub_card_to_graphic_item(
        "session_update", {"caption": "Session one done."}, {"meet_name": "Spring Open"}
    )
    lgt = live["graphic_text"]
    l_pair = lgt["headline_line1"] + " " + lgt["headline_line2"]
    assert "UPDATE" in l_pair
    assert "RECAP" not in l_pair


# ---------------------------------------------------------------------------
# Athlete spotlight — celebrate achievements, never the internal "approved" count
# ---------------------------------------------------------------------------


def _spotlight_item(fd_extra):
    fd = {"source": "athlete_spotlight", "swimmer_name": "Dylan Broom"}
    fd.update(fd_extra)
    card = {"caption": "A standout weekend for Dylan."}
    return _stub_card_to_graphic_item("free_text", card, fd)


def test_spotlight_stats_never_show_approved_workflow_count():
    item = _spotlight_item(
        {"n_approved": 5, "results_lines": "200m Freestyle (LC)\n100m Freestyle (LC)"}
    )
    stats = item["graphic_text"]["stats"]
    # The internal workflow word must never reach the celebratory graphic.
    assert "moments" not in stats
    for v in stats.values():
        assert "approved" not in str(v).lower()
    # With no medals/PBs in the data, fall back to a celebratory swim count.
    assert stats.get("swims") == "5"


def test_spotlight_stats_lead_with_medals_then_pbs():
    medals = _spotlight_item({"n_approved": 5, "n_pbs": 3, "n_medals": 2})["graphic_text"]["stats"]
    assert medals.get("medals") == "2"
    assert "swims" not in medals  # medals win the headline stat
    pbs = _spotlight_item({"n_approved": 4, "n_pbs": 3, "n_medals": 0})["graphic_text"]["stats"]
    assert pbs.get("pbs") == "3"
    assert "swims" not in pbs


def test_spotlight_headline_is_the_name_not_redundant_spotlight():
    gt = _spotlight_item({"n_approved": 2})["graphic_text"]
    # The eyebrow already says ATHLETE SPOTLIGHT; the headline is the athlete's
    # name split first-over-surname, not a second "SPOTLIGHT" line colliding
    # with it.
    assert gt["headline_line1"] == "DYLAN"
    assert gt["headline_line2"] == "BROOM"
    assert "SPOTLIGHT" not in (gt["headline_line1"] + " " + gt["headline_line2"])


# ---------------------------------------------------------------------------
# generator.py — routing hook words must not land in achievement_label
# ---------------------------------------------------------------------------


def _eval(layout="text_led_recap", confidence_label="RECAP"):
    return EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout=layout,
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label=confidence_label,
        explain="ok",
    )


def _brand():
    return BrandKit(
        profile_id="test",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )


def test_achievement_label_not_set_to_sponsor_hook():
    card = {"caption": "Huge thanks to our partners."}
    item = _stub_card_to_graphic_item(
        "sponsor_post", card, {"sponsor_name": "MAK Swimwear", "meet_name": "Spring Open"}
    )
    brief = generate(item, _eval(), _brand(), profile_id="test", meet_name="Spring Open")
    # The hook still routes layout selection…
    assert brief.primary_hook == "SPONSOR"
    # …but never lands in the displayed achievement_label / ribbon text.
    assert (
        brief.text_layers.get("achievement_label", "")
        not in (
            "SPONSOR",
            "PREVIEW",
            "LIVE",
            "HIGHLIGHT",
        )
        or brief.text_layers.get("achievement_label", "") == ""
    )
    assert brief.text_layers.get("achievement_label", "") != "SPONSOR"


# ---------------------------------------------------------------------------
# render.py — stat tiles, event names, surname autofit
# ---------------------------------------------------------------------------


def test_ellipsize_never_cuts_mid_word():
    out = _ellipsize("North District Open", 18)
    assert len(out) <= 18
    body = out.rstrip("…").strip()
    for word in body.split():
        assert word in "North District Open".split(), f"mid-word fragment leaked: {word!r}"


def test_ellipsize_short_value_untouched():
    assert _ellipsize("Spring Open", 18) == "Spring Open"


def test_ellipsize_single_long_word_hard_cut_with_ellipsis():
    out = _ellipsize("Championshipsmarathon", 14)
    assert len(out) <= 14
    assert out.endswith("…")


def test_clean_event_name_strips_course_jargon():
    assert _clean_event_name("100m Backstroke (SC)") == "100m Backstroke"
    assert _clean_event_name("100M BACKSTROKE (SC)") == "100M BACKSTROKE"
    assert _clean_event_name("200m Freestyle (lc) ") == "200m Freestyle"
    assert _clean_event_name("50m Butterfly") == "50m Butterfly"
    assert _clean_event_name("") == ""


def test_surname_font_fits_canvas_width():
    width, height = 1080, 1350
    for surname in ("SNOWDON", "REEKIE-AYALA", "SCOTT", "NG"):
        px = _surname_font_px(surname, width, height, int(height * 0.30))
        assert px >= int(height * 0.12) or px >= 8
        assert px <= int(height * 0.30)
        rendered_w = autofit.measure_line_px(
            surname.upper(), px, font_family=_SURNAME_FONT_FAMILY, weight=900
        )
        # Must span no more than the canvas (the fill fits to 96% width)
        assert (
            rendered_w <= width
        ), f"{surname}: {rendered_w:.0f}px at {px}px exceeds {width}px canvas"


def test_surname_font_short_name_keeps_design_size():
    width, height = 1080, 1350
    base = int(height * 0.30)
    # A short surname comfortably fits at the design cap — keep the drama.
    assert _surname_font_px("NG", width, height, base) == base


# ---------------------------------------------------------------------------
# render.py — weekend-numbers stat tiles never fabricate filler
# ---------------------------------------------------------------------------


class _TilesBrief:
    def __init__(self, layers):
        self.text_layers = layers


def _tile_values(repl):
    import re as _re

    return _re.findall(r'class="num"[^>]*>([^<]*)<', repl["STAT_TILES"])


def test_weekend_numbers_never_pads_fabricated_tiles():
    from mediahub.graphic_renderer.render import _fill_weekend_numbers

    brief = _TilesBrief({"result_value": "58.34", "meet_name": "Spring Open"})
    repl = _fill_weekend_numbers(brief, 1080, 1350, {})
    values = _tile_values(repl)
    # Only real/derived cells — no "24 HOURS" / "✓ COMPLETE" / "★ HIGHLIGHT".
    for fabricated in ("✓", "★", "24"):
        assert fabricated not in values, f"fabricated filler tile leaked: {fabricated!r}"
    assert "HOURS" not in repl["STAT_TILES"]
    assert "HIGHLIGHT" not in repl["STAT_TILES"]
    assert "58.34" in values


def test_weekend_numbers_grid_sizes_to_actual_count():
    from mediahub.graphic_renderer.render import _fill_weekend_numbers

    brief = _TilesBrief({"result_value": "58.34"})
    repl = _fill_weekend_numbers(brief, 1080, 1350, {})
    assert repl["STAT_TILES"].count("stat-tile") == 1


def test_weekend_numbers_real_stats_untouched():
    from mediahub.graphic_renderer.render import _fill_weekend_numbers

    brief = _TilesBrief({"stat_pbs": "7", "stat_medals": "3"})
    repl = _fill_weekend_numbers(brief, 1080, 1350, {})
    values = _tile_values(repl)
    assert values == ["7", "3"]
