"""Motion ↔ still parity + formats + explainability (graphic/reel builder v2).

Covers the reel-side catch-up with the Gen v2 still engine:

  * the design-spec director's ``motion_intent`` flows design spec → brief →
    Remotion props, and the TSX executes every vocabulary member;
  * the card's resolved colour roles (the APCA-gated set the still painted)
    ride along as ``roleGround``/``roleSurface``/``roleAccent``/``roleOnGround``
    so motion and still can never disagree on colour — with the seed-permutation
    fallback intact for brief-less callers;
  * saliency photo focus (``photoPos``) reuses the still's deterministic maths;
  * every v2 still archetype maps to a motion scene (no archetype silently
    collapses back into the one hero layout);
  * output formats: story / portrait / square / landscape sizes, cache-key
    sensitivity,
    and an honest error from the ffmpeg fallback engine for non-story cuts;
  * the explainability manifest written next to each cached MP4;
  * the reel's outro scene, honest cover stats, and deterministic per-beat
    transitions exist in the composition.

No Node needed: real renders stay behind the existing integration gates;
everything here is pure-Python shaping or TSX source contracts.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from unittest import mock

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief import design_spec as ds
from mediahub.creative_brief.generator import CreativeBrief, apply_design_spec, generate
from mediahub.visual import motion
from mediahub.visual.reel_engine import ReelEngineUnavailable


BRAND = BrandKit(
    profile_id="parity",
    display_name="Parity SC",
    primary_colour="#0E2A47",
    secondary_colour="#C9A227",
    accent_colour="#FFFFFF",
    short_name="PSC",
)


def _card(i: int = 1) -> dict:
    return {
        "id": f"swim-parity-{i}",
        "swim_id": f"swim-parity-{i}",
        "achievement": {
            "swim_id": f"swim-parity-{i}",
            "swimmer_name": f"Swimmer {i}",
            "event_name": "100m Freestyle",
            "result_time": f"1:0{i}.00",
        },
        "meet_name": "Parity Invitational",
    }


def _full_brief(**overrides) -> dict:
    """A persisted-shape brief dict (CreativeBrief.to_dict())."""
    brief = generate(
        {"id": "swim-parity-1", "post_angle": "confirmed_official_pb",
         "achievement": _card(1)["achievement"]},
        None,
        BRAND,
        profile_id="parity",
    )
    d = brief.to_dict()
    d.update(overrides)
    return d


# ---------------------------------------------------------------------------
# motion_intent: design spec → brief → props → TSX
# ---------------------------------------------------------------------------


def test_apply_design_spec_carries_motion_intent():
    spec = ds.normalise(
        {"motion_intent": "kinetic_type", "archetype": "big_number_dominant"},
        archetypes=["big_number_dominant", "minimal_type_poster"],
        token_roles=["primary", "secondary"],
    )
    brief = CreativeBrief.from_dict(_full_brief())
    assert brief is not None
    apply_design_spec(brief, spec)
    assert brief.motion_intent == "kinetic_type"
    assert brief.to_dict()["motion_intent"] == "kinetic_type"


def test_card_props_forward_motion_intent_and_photo_axes():
    props = motion._card_to_props(
        _card(1),
        variation_seed=3,
        brief=_full_brief(motion_intent="slide_up"),
    )
    assert props["motionIntent"] == "slide_up"
    assert props["photoPos"] == ""  # no sourced photo on this brief


def test_card_props_without_brief_keep_new_axes_empty():
    props = motion._card_to_props(_card(1), variation_seed=3)
    for key in ("motionIntent", "photoPos", "roleGround", "roleSurface",
                "roleAccent", "roleOnGround"):
        assert props[key] == "", key


def _motion_source_corpus() -> str:
    """StoryCard.tsx plus every sprint-registry module.

    Generator-sprint capabilities (R1.*) may live either inline in StoryCard.tsx
    or as their own auto-discovered file under ``src/compositions/sprint/`` (an
    intent registers ``{ name: "<intent>" }``, a scene ``{ archetype: "<name>" }``).
    Both are real execution paths, so parity scans the union.
    """
    comp = motion.REMOTION_DIR / "src" / "compositions"
    parts = [(comp / "StoryCard.tsx").read_text()]
    sprint = comp / "sprint"
    if sprint.is_dir():
        parts.extend(
            p.read_text()
            for p in sorted(sprint.rglob("*"))
            if p.suffix in {".ts", ".tsx"}
        )
    return "\n".join(parts)


def test_tsx_executes_every_motion_intent():
    """Drift guard: every vocabulary member the director can pick must have
    an execution branch — inline in StoryCard.tsx or as a registered file under
    sprint/intents/. A picked-but-ignored intent is the bug this removes."""
    src = _motion_source_corpus()
    for intent in ds.MOTION_INTENTS:
        if intent == "fade_in":
            # fade_in is also the documented safe default; still must appear.
            assert '"fade_in"' in src
            continue
        assert f'"{intent}"' in src, f"no execution path for intent {intent!r}"


# ---------------------------------------------------------------------------
# Colour-role parity (the still's APCA-gated set rides into motion)
# ---------------------------------------------------------------------------


def test_card_props_carry_resolved_still_roles():
    props = motion._card_to_props(
        _card(1), variation_seed=2, brief=_full_brief(), brand_kit=BRAND
    )
    # The resolver starts from the BrandKit's canonical colours.
    assert props["roleGround"] == "#0E2A47"
    assert props["roleAccent"]  # accent resolved (brand or legible tint)
    assert props["roleOnGround"] in ("#FFFFFF", "#101418", "#000000") or props[
        "roleOnGround"
    ].startswith("#")


def test_resolved_roles_match_the_still_renderer_exactly():
    from mediahub.graphic_renderer.render import resolved_role_vars_for_brief

    brief_dict = _full_brief()
    brief = CreativeBrief.from_dict(brief_dict)
    expected = resolved_role_vars_for_brief(brief, BRAND)
    props = motion._card_to_props(
        _card(1), variation_seed=2, brief=brief_dict, brand_kit=BRAND
    )
    assert props["roleGround"] == expected["--mh-primary"]
    assert props["roleSurface"] == expected["--mh-surface"]
    assert props["roleAccent"] == expected["--mh-accent"]
    assert props["roleOnGround"] == expected["--mh-on-primary"]


def test_partial_brief_dict_keeps_role_fallback():
    """A partial brief (not a persisted to_dict shape) can't be rehydrated —
    roles stay empty so the TSX seed permutation takes over. Never a crash."""
    props = motion._card_to_props(
        _card(1),
        variation_seed=2,
        brief={"background_style": "dots"},
        brand_kit=BRAND,
    )
    assert props["roleGround"] == ""
    assert props["backgroundStyle"] == "dots"


# ---------------------------------------------------------------------------
# Archetype → motion scene parity
# ---------------------------------------------------------------------------


def test_every_v2_archetype_has_a_motion_scene_mapping():
    """Every still archetype must appear in StoryCard.tsx's scene switch so
    its motion render reads like its still (SEQ-4 contract). A new archetype
    must consciously pick its scene group — falling through to the default
    hero layout silently is the 'samey video' bug."""
    from mediahub.graphic_renderer.archetypes import list_archetypes

    src = _motion_source_corpus()
    missing = [a for a in list_archetypes() if f'"{a}"' not in src]
    assert not missing, f"archetypes without a motion scene mapping: {missing}"


def test_saliency_focus_position_shared_helper():
    from PIL import Image

    from mediahub.graphic_renderer.saliency import focus_position

    # No path → safe default; junk path → safe default (never raises).
    assert focus_position("") == "center 28%"
    assert focus_position("/nonexistent/photo.jpg") == "center 28%"


def test_photo_focus_for_brief_empty_without_photo():
    assert motion._photo_focus_for_brief(None) == ""
    assert motion._photo_focus_for_brief({"photo_treatment": "no-photo"}) == ""


# ---------------------------------------------------------------------------
# Output formats
# ---------------------------------------------------------------------------


def test_motion_format_sizes():
    assert motion.motion_format_size("story") == (1080, 1920)
    assert motion.motion_format_size("portrait") == (1080, 1350)  # 4:5 feed cut
    assert motion.motion_format_size("square") == (1080, 1080)
    assert motion.motion_format_size("landscape") == (1920, 1080)
    assert motion.motion_format_size("") == (1080, 1920)  # default
    with pytest.raises(ValueError):
        motion.motion_format_size("imax")


def _stub_render(tmp_path, monkeypatch, fmt: str, captured: dict):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    def _fake_run(*, composition_id, props, out_path, duration_sec=None, size=None, timeout=600):
        captured["size"] = size
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        return out

    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        return motion.render_story_card(
            _card(1), BRAND, tmp_path / "out" / f"{fmt}.mp4", format_name=fmt
        )


def test_story_card_formats_render_at_their_sizes(tmp_path, monkeypatch):
    for fmt, size in motion.MOTION_FORMATS.items():
        captured: dict = {}
        _stub_render(tmp_path, monkeypatch, fmt, captured)
        assert captured["size"] == size, fmt


def test_cache_key_varies_with_format(tmp_path, monkeypatch):
    for fmt in motion.MOTION_FORMATS:
        _stub_render(tmp_path, monkeypatch, fmt, {})
    cache = motion._cache_dir()
    assert len(list(cache.glob("*.mp4"))) == len(motion.MOTION_FORMATS)


def test_ffmpeg_engine_rejects_non_story_formats_honestly(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_REEL_ENGINE", "ffmpeg")
    with pytest.raises(ReelEngineUnavailable, match="story"):
        motion.render_story_card(
            _card(1), BRAND, tmp_path / "x.mp4", format_name="square"
        )
    with pytest.raises(ReelEngineUnavailable, match="story"):
        motion.render_meet_reel(
            [_card(1)], BRAND, tmp_path / "y.mp4", format_name="landscape"
        )
    with pytest.raises(ReelEngineUnavailable, match="story"):
        motion.render_story_card(
            _card(1), BRAND, tmp_path / "z.mp4", format_name="portrait"
        )


# ---------------------------------------------------------------------------
# count_up intent + cover stat count-up (TSX source contracts)
# ---------------------------------------------------------------------------


def test_count_up_settles_on_the_verbatim_value():
    """The count-up must end on the EXACT verified string (and ignore
    non-numeric results entirely) — the same zero-invention rule the rest
    of the renderer lives by. Checked at the source-contract level."""
    src = (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text()
    assert "countUpDisplay" in src
    assert "resultProgress" in src
    # Progress 1 returns the original text verbatim (no reformat).
    assert "if (progress >= 1 || !t)" in src
    # Mega/ticker sizing + crawl use the FINAL value, not the mid-count text.
    assert "resultFinal" in src


def test_reel_cover_chips_count_up_honestly():
    src = (motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx").read_text()
    # Chips count up to totals derived only from the honest reelStats.
    assert "chipsProgress" in src
    assert "progress: number" in src
    # The number counts up over each chip's honest value (frame-pure).
    assert "Math.round(chip.value * p)" in src
    # Pluralisation follows the FINAL count (no mid-count flicker): the words
    # are chosen on n in reelStats and baked into the chip before the count-up.
    assert "n === 1" in src


# ---------------------------------------------------------------------------
# Explainability manifest
# ---------------------------------------------------------------------------


def test_story_render_writes_explainability_manifest(tmp_path, monkeypatch):
    captured: dict = {}
    out = _stub_render(tmp_path, monkeypatch, "story", captured)
    sidecars = list(motion._cache_dir().glob("*.json"))
    # props/ holds the render props; the manifest sits next to the MP4.
    manifests = [p for p in sidecars if p.parent == motion._cache_dir()]
    assert manifests, "no manifest written next to the cached MP4"
    data = json.loads(manifests[0].read_text())
    assert data["kind"] == "story"
    assert data["format"] == "story"
    assert data["card"]["colour_source"] in ("still-parity-roles", "seed-permutation")
    assert "motion_intent" in data["card"]


def test_reel_render_writes_manifest_with_per_card_axes(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    def _fake_run(*, composition_id, props, out_path, duration_sec=None, size=None, timeout=600):
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"0" * 2048)
        return out

    with mock.patch.object(motion, "_run_remotion", side_effect=_fake_run):
        motion.render_meet_reel(
            [_card(1), _card(2)], BRAND, tmp_path / "out" / "reel.mp4"
        )
    manifests = list(motion._cache_dir().glob("*.json"))
    assert manifests
    data = json.loads(manifests[0].read_text())
    assert data["kind"] == "reel"
    assert len(data["cards"]) == 2


# ---------------------------------------------------------------------------
# Reel structure: outro, honest cover stats, deterministic transitions
# ---------------------------------------------------------------------------


def test_meet_reel_declares_outro_and_honest_stats():
    src = (motion.REMOTION_DIR / "src" / "compositions" / "MeetReel.tsx").read_text()
    assert "OutroScreen" in src, "the reel must end on a branded outro scene"
    assert "reelStats" in src, "cover stats must come from the honest derivation"
    assert "transitionFor" in src, "per-beat transitions must be deterministic"
    # Honest derivation: medals counted ONLY from labels, never guessed
    # from bare place numbers.
    stats_fn = src.split("export function reelStats", 1)[1].split("\n}", 1)[0]
    assert "achievementLabel" in stats_fn
    assert ".place" not in stats_fn


def test_reel_duration_contract_unchanged():
    """The Python duration maths is the reel's public contract — the outro
    second was always budgeted (REEL_OUTRO_SEC); the TSX now renders a real
    outro scene inside the same total, so cached durations stay valid."""
    assert motion.reel_duration_for(3) == 15.0
    assert motion.REEL_OUTRO_SEC == 1.0


# ---------------------------------------------------------------------------
# render.js size override
# ---------------------------------------------------------------------------


def test_render_js_supports_width_height_override():
    src = (motion.REMOTION_DIR / "render.js").read_text()
    assert "--width" in src and "--height" in src
    assert re.search(r"width,\s*\n\s*height,", src), (
        "render.js must pass the overridden canvas into renderMedia"
    )
