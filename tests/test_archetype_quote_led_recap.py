"""Pinning test for the PAR-7 ``quote_led_recap`` v2 archetype.

Guards that the new archetype is registered in the Tier-A library, obeys the
slot convention (no hex literals, only allow-listed placeholders, brand colour
via ``--mh-*`` roles), collapses its optional slots (achievement kicker / hero
stat) when their value is empty, wraps its hero text so a long/space-less name
can never clip, carries the editorial pull-quote structural furniture (left
quote-bar + hanging quote glyph + em-dash attribution rule), and assembles into
clean HTML through the real ``render_brief`` path (Playwright stubbed) — i.e. it
actually picks up the injected brand-role and autofit tokens like every other v2
archetype. Also pins that adding this archetype keeps a representative seeds-0..9
pack at saturated archetype-diversity while growing the library past the prior
10-archetype high-water mark (the targeted §8C structural-distinctiveness axis).
"""

from __future__ import annotations

import re

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate as gen_brief
from mediahub.graphic_renderer import archetypes
from mediahub.media_requirements.evaluator import EvaluationResult
from mediahub.quality import variant_metrics as VM

NAME = "quote_led_recap"

_ALLOWED = {
    "ATHLETE_FULL_NAME",
    "ATHLETE_FIRST_NAME",
    "ATHLETE_SURNAME_DISPLAY",
    "EVENT_NAME",
    "RESULT_VALUE",
    "ACHIEVEMENT_LABEL",
    "MEET_NAME",
    "CLUB_FULL",
    "HERO_STAT",
    "LOGO_BLOCK",
    "ATHLETE_IMG_BLOCK",
    "ACCENT_DECORATION",
    "SPONSOR_BLOCK",
    "WIDTH",
    "HEIGHT",
    "BASE_CSS",
}


def _raw():
    return (archetypes.V2_DIR / f"{NAME}.html").read_text(encoding="utf-8")


def test_registered_in_library():
    assert NAME in archetypes.list_archetypes()


def test_has_authoring_notes():
    assert (archetypes.V2_DIR / f"{NAME}.notes.md").exists()


def test_follows_slot_convention():
    raw = _raw()
    assert "{{BASE_CSS}}" in raw
    assert re.search(r"#[0-9a-fA-F]{3,6}\b", raw) is None, "hex colour literal present"
    assert "var(--mh-" in raw
    for ph in set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", raw)):
        assert ph in _ALLOWED, f"unknown placeholder {ph}"


def test_optional_slots_collapse_when_empty():
    raw = _raw()
    # achievement kicker and the hero-stat margin note collapse when empty so an
    # absent value never leaves a dangling label.
    assert ".ql__kicker:empty" in raw
    assert ".ql__hero:empty" in raw


def test_hero_text_wraps_not_clips():
    raw = _raw()
    assert raw.count("overflow-wrap: anywhere") >= 2


def test_carries_pull_quote_furniture():
    raw = _raw()
    # left quote-bar, the hanging quote glyph and the em-dash attribution line
    # are the structural signature that makes this read as an editorial recap.
    assert 'class="ql__bar"' in raw
    assert 'class="ql__quote"' in raw
    assert 'class="ql__attrib"' in raw
    assert "&ldquo;" in raw  # hanging open-quote glyph
    assert "&mdash;" in raw  # em-dash attribution


def _brand():
    return BrandKit(
        profile_id="t",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )


def _ev():
    return EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout="individual_hero",
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )


def _brief():
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }
    b = gen_brief(
        item,
        _ev(),
        _brand(),
        profile_id="t",
        meet_name="Manchester Open",
        venue_name="Manchester Aquatics Centre",
        variation_seed=0,
    )
    b.layout_template = NAME
    return b


def test_assembles_clean_html(monkeypatch, tmp_path):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    import mediahub.graphic_renderer.render as R

    captured = {}

    def _fake_png(html, output_path, size):
        captured["html"] = html
        from pathlib import Path

        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    R.render_brief(_brief(), output_dir=tmp_path, size=(1080, 1350))
    html = captured["html"]
    assert "{{" not in html and "}}" not in html
    assert ":root{" in html
    for token in (
        "--mh-primary:",
        "--mh-accent:",
        "--mh-surface:",
        "--mh-on-surface:",
        "--mh-fit-mega-name-px:",
        "--mh-fit-result-px:",
    ):
        assert token in html, f"missing {token}"
    assert "Manchester Open" in html


def test_grows_library_past_prior_mark():
    names = archetypes.list_archetypes()
    assert NAME in names
    # prior high-water mark was a 10-archetype library; this addition grows it.
    assert len(names) >= 11, f"expected >= 11 archetypes, got {len(names)}"
    # a representative seeds-0..9 pack stays at saturated archetype-diversity.
    pack = [archetypes.pick_archetype(s) for s in range(10)]
    div = VM.archetype_diversity(pack)
    assert div >= 0.9, f"expected pack diversity >= 0.9, got {div}"
