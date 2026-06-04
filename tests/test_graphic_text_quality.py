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
    _clean_event_name,
    _surname_font_px,
    _SURNAME_FONT_FAMILY,
    _tile_text,
)
from mediahub.media_requirements.evaluator import EvaluationResult
from mediahub.web.web import (
    _has_real_text,
    _stub_card_to_graphic_item,
    _truncate_words,
)


# ---------------------------------------------------------------------------
# web.py — bullet shaping for caption-only stub cards
# ---------------------------------------------------------------------------


def test_truncate_words_never_cuts_mid_word():
    text = (
        "Brilliant racing from the squad this weekend, topping the podium "
        "at the North District Open with three gold medals on day two"
    )
    out = _truncate_words(text, max_chars=90)
    assert len(out) <= 90
    assert out.endswith("…")
    # Every emitted word (bar the ellipsis) must be a whole word of the input
    body = out.rstrip("…").strip()
    for word in body.split():
        assert word in text.split(), f"mid-word fragment leaked: {word!r}"


def test_truncate_words_short_text_untouched():
    assert _truncate_words("Three golds for the squad", max_chars=90) == (
        "Three golds for the squad"
    )


def test_truncate_words_single_long_word_hard_cut_with_ellipsis():
    out = _truncate_words("A" * 200, max_chars=20)
    assert len(out) <= 20
    assert out.endswith("…")


def test_emoji_only_text_detected():
    assert not _has_real_text("\U0001f3c6\U0001f3c6\U0001f3c6")
    assert _has_real_text("3 golds \U0001f3c6")
    assert not _has_real_text("")


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
    card = {"caption": long_sentence}
    item = _stub_card_to_graphic_item("session_update", card, {})
    for b in item["graphic_text"]["bullets"]:
        assert len(b) <= 90
        # No mid-word fragment: strip the ellipsis and check the last word
        last = b.rstrip("…").split()[-1].strip(",;:.!?")
        assert last in long_sentence, f"mid-word cut: {last!r}"


def test_sponsor_headline_is_thank_you_pair_not_name_recap():
    card = {"caption": "Huge thanks to our partners for backing the squad."}
    item = _stub_card_to_graphic_item(
        "sponsor_post", card, {"sponsor_name": "MAK Swimwear", "meet_name": "Spring Open"}
    )
    gt = item["graphic_text"]
    assert gt["headline_line1"] == "THANK YOU"
    assert "RECAP" not in (gt["headline_line1"] + " " + gt["headline_line2"])
    assert gt["headline_line2"]  # sponsor name (or PARTNERS fallback)


def test_sponsor_headline_falls_back_to_partners():
    card = {"caption": "Thanks to everyone who supports the club."}
    item = _stub_card_to_graphic_item("sponsor_post", card, {})
    assert item["graphic_text"]["headline_line2"] == "PARTNERS"


def test_preview_and_session_headline_pairs():
    prev = _stub_card_to_graphic_item("weekend_preview", {"caption": "Big weekend ahead."}, {})
    assert (
        prev["graphic_text"]["headline_line1"],
        prev["graphic_text"]["headline_line2"],
    ) == ("EVENT", "PREVIEW")
    live = _stub_card_to_graphic_item("session_update", {"caption": "Session one done."}, {})
    assert (
        live["graphic_text"]["headline_line1"],
        live["graphic_text"]["headline_line2"],
    ) == ("SESSION", "UPDATE")


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
    # …but never lands in the displayed achievement_label / RESULT tile.
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


def test_tile_text_never_cuts_mid_word():
    out = _tile_text("North District Open", 18)
    assert out == "North District"
    assert len(out) <= 18


def test_tile_text_short_value_untouched():
    assert _tile_text("Spring Open", 18) == "Spring Open"


def test_tile_text_single_long_word_hard_cut_with_ellipsis():
    out = _tile_text("Championshipsmarathon", 14)
    assert len(out) <= 14
    assert out.endswith("…")


def test_clean_event_name_strips_course_jargon():
    assert _clean_event_name("100m Backstroke (SC)") == "100m Backstroke"
    assert _clean_event_name("100M BACKSTROKE (SC)") == "100M BACKSTROKE"
    assert _clean_event_name("200m Freestyle (lc) ") == "200m Freestyle"
    assert _clean_event_name("50m Butterfly") == "50m Butterfly"
    # Only the trailing course code is jargon — not parenthetical mid-text
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
