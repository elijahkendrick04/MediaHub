"""Pinning + integration test for the PAR-7 ``relay_collage`` v2 archetype (G1.2).

Guards that the multi-athlete collage archetype is registered, obeys the slot
convention (no hex literals, only allow-listed placeholders, brand colour via
``--mh-*`` roles), ships the ``RC:STAGE`` markers and a single-photo / painted
fallback so it never looks broken, and — the point of the feature — that the
``relay_collage`` sprint hook composites 2-4 resolved cutouts into the stage
through the *real* ``render_brief`` path (Playwright stubbed). Also pins the
hook's no-op guards and the motion-scene parity file.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from PIL import Image

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import generate as gen_brief
from mediahub.graphic_renderer import archetypes
from mediahub.graphic_renderer.sprint_hooks import RenderHookCtx
from mediahub.graphic_renderer.sprint_hooks import relay_collage as hook
from mediahub.media_requirements.evaluator import EvaluationResult

NAME = "relay_collage"

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


def _raw() -> str:
    return (archetypes.V2_DIR / f"{NAME}.html").read_text(encoding="utf-8")


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
        suggested_layout=NAME,
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="GOLD",
        explain="ok",
    )


def _brief():
    item = {
        "id": "ci-1",
        "post_angle": "relay_highlight",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "4x100m Freestyle Relay",
            "result_time": "3:42.18",
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
    b.sourced_asset_ids = []
    return b


def _png(path: Path, colour=(220, 40, 40, 255)) -> str:
    """A tiny RGBA cutout (transparent canvas, one opaque blob)."""
    img = Image.new("RGBA", (60, 90), (0, 0, 0, 0))
    img.paste(Image.new("RGBA", (30, 60), colour), (15, 20))
    img.save(path)
    return str(path)


# --------------------------------------------------------------------------- #
# Registry + authoring convention
# --------------------------------------------------------------------------- #


def test_registered_in_library():
    assert NAME in archetypes.list_archetypes()


def test_has_authoring_notes_with_when_clause():
    notes = archetypes.V2_DIR / f"{NAME}.notes.md"
    assert notes.exists()
    text = notes.read_text(encoding="utf-8")
    assert len(text.strip()) > 200
    assert "When the director should pick it" in text
    # The director catalog line extracts cleanly (PAR-7).
    assert len(archetypes.director_note(NAME)) >= 60


def test_follows_slot_convention():
    raw = _raw()
    assert "{{BASE_CSS}}" in raw
    assert "var(--mh-" in raw
    # No hex colour literal anywhere — brand colour only via --mh-* roles.
    assert re.search(r"#[0-9a-fA-F]{3,6}\b", raw) is None
    # Every placeholder is on the allow-list.
    for ph in set(re.findall(r"\{\{([A-Z0-9_]+)\}\}", raw)):
        assert ph in _ALLOWED, f"unknown placeholder {ph}"


def test_ships_stage_markers_and_furniture():
    raw = _raw()
    # The hook's injection anchor wraps the single-photo fallback.
    assert "<!--RC:STAGE-->" in raw and "<!--/RC:STAGE-->" in raw
    assert "{{ATHLETE_IMG_BLOCK}}" in raw
    # Three-deck structural furniture: stage / name band / data panel.
    for token in ("rc__stage", "rc__backdrop", "rc__band", "rc__surname", "rc__data", "rc__result"):
        assert token in raw, f"missing {token}"


def test_optional_slots_collapse_when_empty():
    raw = _raw()
    # Kicker, hero stat, meet, club, sponsor all hide when their value is blank.
    for sel in (".rc__kicker:empty", ".rc__hero:empty", ".rc__meet:empty",
                ".rc__sponsor:empty", ".rc__club:empty"):
        assert sel in raw, f"missing collapse rule {sel}"


# --------------------------------------------------------------------------- #
# Assembles through the real render_brief path (Playwright stubbed)
# --------------------------------------------------------------------------- #


def _capture_html(monkeypatch, tmp_path, brief, **kwargs):
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import mediahub.graphic_renderer.render as R

    captured = {}

    def _fake_png(html, output_path, size):
        captured["html"] = html
        Path(output_path).write_bytes(b"\x89PNG\r\n\x1a\n")
        return 8

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    R.render_brief(brief, output_dir=tmp_path, size=(1080, 1350), brand_kit=_brand(), **kwargs)
    return captured["html"]


def test_assembles_clean_html_single_photo_fallback(monkeypatch, tmp_path):
    # No squad resolved → the stage keeps its single-photo fallback, markers
    # intact, and the v2 brand-role / autofit tokens are injected as usual.
    html = _capture_html(monkeypatch, tmp_path, _brief())
    assert "{{" not in html and "}}" not in html
    assert ":root{" in html
    for token in (
        "--mh-primary:",
        "--mh-accent:",
        "--mh-surface:",
        "--mh-on-surface:",
        "--mh-fit-surname-px:",
        "--mh-fit-result-px:",
        "--mh-photo-pos:",
    ):
        assert token in html, f"missing {token}"
    # Hook was a no-op (no photos) → markers survive, no collage injected.
    assert "<!--RC:STAGE-->" in html
    assert "rc-collage" not in html
    assert "Manchester Open" in html
    assert "HUGHES" in html.upper()


def test_composites_collage_when_multiple_photos(monkeypatch, tmp_path):
    # Keep the cutout step deterministic (identity); the data-URI encode + the
    # compositor + the marker swap all run for real.
    import mediahub.graphic_renderer.render as R

    monkeypatch.setattr(R, "_maybe_cut_out_athlete", lambda p, profile_id="d": p)

    p1 = _png(tmp_path / "a1.png", (210, 40, 40, 255))
    p2 = _png(tmp_path / "a2.png", (40, 210, 90, 255))
    p3 = _png(tmp_path / "a3.png", (40, 90, 210, 255))

    brief = _brief()
    brief.collage_image_paths = [p1, p2, p3]

    html = _capture_html(monkeypatch, tmp_path, brief)

    # The stage was replaced by the composited collage: three subject figures,
    # the markers consumed, the single-photo fallback gone.
    assert "rc-collage" in html
    assert html.count("<figure") == 3
    assert 'data-collage-count="3"' in html
    assert "<!--RC:STAGE-->" not in html
    # Still a real, fully-assembled card around the collage.
    assert ":root{" in html and "{{" not in html
    assert "4X100M FREESTYLE RELAY" in html.upper()


# --------------------------------------------------------------------------- #
# Hook guards (unit level)
# --------------------------------------------------------------------------- #


def _ctx(family, brief):
    return RenderHookCtx(
        brief=brief, width=1080, height=1350, family=family,
        format_name="feed_portrait", is_v2=family,
    )


def test_hook_is_noop_for_other_archetypes():
    from types import SimpleNamespace

    html = '<!--RC:STAGE--><div class="rc__solo"></div><!--/RC:STAGE-->'
    out = hook.apply(html, _ctx("duo_athlete_split", SimpleNamespace()))
    assert out == html


def test_hook_is_noop_without_two_photos(monkeypatch, tmp_path):
    from types import SimpleNamespace

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    html = '<!--RC:STAGE--><div class="rc__solo"></div><!--/RC:STAGE-->'
    brief = SimpleNamespace(sourced_asset_ids=[], collage_image_paths=[], profile_id="t")
    out = hook.apply(html, _ctx(NAME, brief))
    assert out == html  # markers preserved, nothing composited


# --------------------------------------------------------------------------- #
# Motion-scene parity (the still archetype must read like its video)
# --------------------------------------------------------------------------- #


def test_motion_scene_file_maps_the_archetype():
    from mediahub.visual import motion

    scene = (
        motion.REMOTION_DIR
        / "src" / "compositions" / "sprint" / "scenes" / f"{NAME}.tsx"
    )
    assert scene.exists(), "relay_collage needs a motion scene for parity"
    src = scene.read_text(encoding="utf-8")
    assert f'archetype: "{NAME}"' in src
    assert "SceneComponent" in src
