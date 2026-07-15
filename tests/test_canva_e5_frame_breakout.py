"""E5 (Canva gap analysis) — the frame_breakout pop-out archetype.

The signature announcement move: the athlete cutout is clipped inside a brand
shape frame with a second pixel-aligned paint escaping above the frame's top
edge. These tests pin the registration (cutout mode, gallery, notes, motion
scene) and the deterministic seeded frame-shape lever.
"""

from __future__ import annotations

from pathlib import Path

from mediahub.graphic_renderer import archetypes as A

_ROOT = Path(A.__file__).parent
_HTML = _ROOT / "layouts" / "v2" / "frame_breakout.html"
_TSX = _ROOT.parents[0] / "remotion" / "src" / "compositions" / "StoryCard.tsx"


def test_archetype_is_registered():
    assert "frame_breakout" in A.list_archetypes()
    # It is a photo-led, cutout-mode archetype (transparent silhouette).
    assert "frame_breakout" in A.photo_archetypes()
    assert A.photo_mode("frame_breakout") == "cutout"


def test_layout_has_the_two_aligned_copies_and_matte_fallback():
    raw = _HTML.read_text()
    # Two copies from ONE source var, each inset:0 of the same stage.
    assert raw.count("var(--mh-athlete-img)") >= 2
    assert "fbo__inside" in raw and "fbo__breakout" in raw
    # The breakout copy is clipped to only the band above the frame.
    assert "--mh-breakout-floor" in raw and "clip-path: inset(" in raw
    # The frame shape is one shared var (so a seeded arch swaps both at once).
    assert "--mh-frame-clip" in raw
    # Matte-gate flat fallback + no hardcoded decorative hex fills.
    assert "mh-photo-flat" in raw and "{{PHOTO_FLAT_CLASS}}" in raw
    import re

    # Only #fff in a color-mix lightening step is allowed; no other literal hex.
    hexes = set(re.findall(r"#[0-9A-Fa-f]{3,6}", raw))
    assert hexes <= {"#fff"}, f"unexpected hardcoded hex: {hexes}"


def test_notes_file_ships():
    notes = _ROOT / "layouts" / "v2" / "frame_breakout.notes.md"
    assert notes.exists()
    body = notes.read_text().lower()
    assert "the director should pick" in body
    assert A.director_note("frame_breakout")  # non-empty catalog line


def test_seeded_frame_shape_is_deterministic():
    from mediahub.graphic_renderer.style_packs import _seed_for

    # The three framings the renderer indexes into (salt='breakout' % 3).
    a = _seed_for("swim-2", salt="breakout") % 3
    b = _seed_for("swim-2", salt="breakout") % 3
    assert a == b
    # At least two distinct framings appear across a content pack.
    picks = {_seed_for(f"swim-{i}", salt="breakout") % 3 for i in range(20)}
    assert len(picks) >= 2


def test_motion_scene_mapping_exists():
    src = _TSX.read_text()
    assert '"frame_breakout"' in src  # mapped in sceneForArchetype


def test_renders_to_png(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    from mediahub.brand.kit import BrandKit
    from mediahub.creative_brief.generator import generate
    from mediahub.graphic_renderer.render import render_brief

    brand = BrandKit(
        profile_id="p",
        display_name="Test SC",
        primary_colour="#0E2A47",
        secondary_colour="#C9A227",
        accent_colour="#E8563F",
        short_name="TSC",
    )
    br = generate(
        {
            "id": "swim-2",
            "post_angle": "confirmed_official_pb",
            "achievement": {
                "swimmer_name": "Eira Hughes",
                "event_name": "200 Free",
                "result_time": "2:08.41",
            },
        },
        None,
        brand,
        profile_id="p",
        variation_seed=1,
    )
    br.layout_template = "frame_breakout"
    br.id = "swim-2"  # seeds the arch framing (index 2)
    out = tmp_path / "out"
    out.mkdir()
    try:
        r = render_brief(
            br, output_dir=out, size=(1080, 1350), format_name="feed_portrait", brand_kit=brand
        )
    except Exception as exc:  # Playwright/Chromium absent → skip, not fail
        import pytest

        pytest.skip(f"renderer unavailable: {exc}")
    assert Path(r.visual.file_path).read_bytes()[:8] == b"\x89PNG\r\n\x1a\n"
