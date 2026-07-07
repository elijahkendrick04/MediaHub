"""Pinning test for the PAR-7 ``stat_stack_sidebar`` v2 archetype.

Guards that the new archetype is registered in the Tier-A library, obeys the
slot convention (no hex literals, only allow-listed placeholders, brand colour
via ``--mh-*`` roles), collapses its optional emphasis chip when no hero stat is
supplied, and assembles into clean HTML through the real ``render_brief`` path
(Playwright stubbed) — i.e. it actually picks up the injected brand-role and
autofit tokens like every other v2 archetype.
"""

from __future__ import annotations

import re

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate as gen_brief
from mediahub.graphic_renderer import archetypes
from mediahub.media_requirements.evaluator import EvaluationResult

NAME = "stat_stack_sidebar"

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
    # M11 — secondary-stat chip row (collapses to "" when undirected).
    "STAT_CHIPS",
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


def test_optional_hero_chip_collapses_when_empty():
    # the emphasis chip must hide itself when no hero stat is supplied, so an
    # empty slot never leaves a dangling label on the rail.
    assert ".ss__hero:has(.ss__chip-val:empty)" in _raw()


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
    b.layout_template = NAME  # force this archetype regardless of seed mapping
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
        "--mh-fit-surname-px:",
        "--mh-fit-result-px:",
        "--mh-photo-pos:",
    ):
        assert token in html, f"missing {token}"
    assert "Manchester Open" in html  # real content reached the rail
