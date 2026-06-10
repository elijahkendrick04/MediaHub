"""Tests for the free still+FFmpeg reel engine (roadmap P0.1).

Three layers, none of which needs Node or Remotion:

  - pure maths/builders (segment durations, ffmpeg arg lists, frame briefs)
  - honest-error behaviour when the binary is missing
  - real FFmpeg assembly from synthetic stills (Pillow frames, no Chromium),
    skipped only where no FFmpeg binary is resolvable

The end-to-end proof that a zero-Remotion deployment renders reels is the
combination: dispatch tests in test_reel_engine.py + the real assembly here.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.visual import reel_ffmpeg
from mediahub.visual.motion import _content_hash, reel_duration_for
from mediahub.visual.reel_engine import ReelEngineUnavailable

_HAS_FFMPEG = reel_ffmpeg.ffmpeg_exe() is not None


def _props(name="Ada Lovelace", event="100m Freestyle LC", result="00:58.31") -> dict:
    first, surname = name.split()[0], name.split()[-1]
    return {
        "athleteFullName": name,
        "athleteFirstName": first,
        "athleteSurname": surname,
        "eventName": event,
        "resultValue": result,
        "achievementLabel": "NEW PB",
        "meetName": "Welsh Winter Nationals 2026",
        "place": "1",
        "variationSeed": 3,
    }


def _brand_dict() -> dict:
    return {
        "primary": "#0A2540",
        "secondary": "#101418",
        "accent": "#D4FF3A",
        "displayName": "City of Swansea Aquatics",
        "shortName": "COSA",
        "logoDataUri": "",
        "themeSource": "brand-kit",
    }


def _brand_kit() -> BrandKit:
    return BrandKit(
        profile_id="ffmpeg-test",
        display_name="City of Swansea Aquatics",
        short_name="COSA",
        primary_colour="#0A2540",
        secondary_colour="#101418",
        accent_colour="#D4FF3A",
    )


def _write_synthetic_still(path: Path, colour=(10, 37, 64)) -> Path:
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (reel_ffmpeg.WIDTH, reel_ffmpeg.HEIGHT), colour).save(path)
    return path


# ---------------------------------------------------------------------------
# Segment-duration arithmetic
# ---------------------------------------------------------------------------


def test_reel_segments_total_matches_advertised_duration_exactly():
    """Σ(segments) − crossfade·(n−1) must equal reel_duration_for(n) for
    every supported card count — the xfade overlap is pre-folded in."""
    for n in range(1, 6):
        total = reel_duration_for(n)
        segs = reel_ffmpeg.reel_segment_durations(n, total)
        assert len(segs) == n + 1  # cover + one per card
        chained = sum(segs) - reel_ffmpeg.CROSSFADE_SEC * (len(segs) - 1)
        assert chained == pytest.approx(total, abs=1e-9)


def test_reel_segments_scale_to_caller_override():
    """An explicit total duration scales the beats proportionally and the
    chained total still lands exactly on the override."""
    segs = reel_ffmpeg.reel_segment_durations(3, 30.0)
    chained = sum(segs) - reel_ffmpeg.CROSSFADE_SEC * (len(segs) - 1)
    assert chained == pytest.approx(30.0, abs=1e-9)


def test_reel_segments_last_carries_the_outro_beat():
    segs = reel_ffmpeg.reel_segment_durations(2, reel_duration_for(2))
    # cover (2s) + crossfade, card (4s) + crossfade, last card (4s + 1s outro)
    assert segs[0] == pytest.approx(2.0 + reel_ffmpeg.CROSSFADE_SEC)
    assert segs[1] == pytest.approx(4.0 + reel_ffmpeg.CROSSFADE_SEC)
    assert segs[2] == pytest.approx(5.0)


# ---------------------------------------------------------------------------
# FFmpeg arg builders (pure)
# ---------------------------------------------------------------------------


def test_story_args_are_streamable_silent_h264():
    args = reel_ffmpeg.story_ffmpeg_args(Path("still.png"), Path("out.mp4"), 6.0)
    joined = " ".join(args)
    assert "libx264" in joined
    assert "+faststart" in joined
    assert "-an" in args  # reels are silent — no fabricated audio bed
    assert "zoompan" in joined and "fade" in joined
    assert args[-1] == "out.mp4"


def test_reel_args_chain_one_xfade_per_join():
    stills = [Path(f"f{i}.png") for i in range(4)]
    segs = reel_ffmpeg.reel_segment_durations(3, reel_duration_for(3))
    args = reel_ffmpeg.reel_ffmpeg_args(stills, Path("reel.mp4"), segs)
    fc = args[args.index("-filter_complex") + 1]
    assert fc.count("xfade") == 3
    assert fc.count("zoompan") == 4
    # Offsets are cumulative-minus-overlap: first join at d0 − X.
    assert f"offset={segs[0] - reel_ffmpeg.CROSSFADE_SEC:.3f}" in fc


def test_reel_args_reject_mismatched_inputs():
    with pytest.raises(ValueError):
        reel_ffmpeg.reel_ffmpeg_args([Path("a.png")], Path("o.mp4"), [1.0, 2.0])


# ---------------------------------------------------------------------------
# Frame briefs — deterministic, no AI
# ---------------------------------------------------------------------------


def test_minimal_brief_carries_card_facts_and_brand_palette():
    brief = reel_ffmpeg._minimal_brief(_props(), _brand_dict(), profile_id="ffmpeg-test")
    assert brief.layout_template == "story_card"
    assert brief.text_layers["athlete_full_name"] == "Ada Lovelace"
    assert brief.text_layers["result_value"] == "00:58.31"
    assert brief.text_layers["meet_name"] == "Welsh Winter Nationals 2026"
    assert brief.palette == {
        "primary": "#0A2540",
        "secondary": "#101418",
        "accent": "#D4FF3A",
    }
    assert brief.format_priority == ["story"]


def test_rehydrate_brief_roundtrips_a_persisted_brief():
    src = reel_ffmpeg._minimal_brief(_props(), _brand_dict(), profile_id="p")
    src.layout_template = "big_number_dominant"
    back = reel_ffmpeg._rehydrate_brief(src.to_dict())
    assert back is not None
    assert back.layout_template == "big_number_dominant"
    assert back.text_layers == src.text_layers


def test_frame_brief_falls_back_when_dict_is_not_a_brief():
    brief = reel_ffmpeg._frame_brief(_props(), _brand_dict(), _brand_kit(), {"not_a_field": True})
    assert brief.layout_template == "story_card"  # deterministic fallback


def test_cover_brief_titles_the_meet_without_duplicating_it():
    cover = reel_ffmpeg._cover_brief([_props()], _brand_dict(), _brand_kit(), "")
    assert cover.layout_template == "reel_cover"
    # Meet name rides the mega-headline slot; the bottom strip stays empty
    # so the title never appears twice on the frame.
    assert cover.text_layers["athlete_full_name"] == "Welsh Winter Nationals 2026"
    assert cover.text_layers["meet_name"] == ""
    assert cover.confidence_label == "MEET RECAP"


# ---------------------------------------------------------------------------
# Honest errors
# ---------------------------------------------------------------------------


def test_missing_ffmpeg_raises_engine_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(reel_ffmpeg, "ffmpeg_exe", lambda: None)
    out = tmp_path / "story.mp4"
    with pytest.raises(ReelEngineUnavailable, match="FFmpeg"):
        reel_ffmpeg.render_story_card_from_props(_props(), _brand_dict(), _brand_kit(), out)
    assert not out.exists(), "no placeholder asset may be written on failure"


def test_missing_still_renderer_raises_engine_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(reel_ffmpeg, "ffmpeg_exe", lambda: "/bin/true")
    monkeypatch.setattr(reel_ffmpeg, "_still_renderer_available", lambda: False)
    with pytest.raises(ReelEngineUnavailable, match="Playwright"):
        reel_ffmpeg.render_story_card_from_props(
            _props(), _brand_dict(), _brand_kit(), tmp_path / "story.mp4"
        )


def test_reel_requires_at_least_one_card(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        reel_ffmpeg.render_meet_reel_from_props(
            [], _brand_dict(), _brand_kit(), tmp_path / "reel.mp4"
        )


# ---------------------------------------------------------------------------
# Cache identity — the ffmpeg engine must never serve a Remotion cache entry
# ---------------------------------------------------------------------------


def test_cache_key_is_engine_separated():
    base = {"card": _props(), "brand": _brand_dict(), "duration": 6.0}
    remotion_key = _content_hash(base, kind="story")
    ffmpeg_key = _content_hash({**base, "engine": "ffmpeg", "brief": {}}, kind="story")
    assert remotion_key != ffmpeg_key


# ---------------------------------------------------------------------------
# Real FFmpeg assembly (synthetic stills — no Chromium, no Node)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_FFMPEG, reason="no FFmpeg binary resolvable")
def test_story_assembly_produces_mp4_of_requested_duration(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        reel_ffmpeg,
        "_render_still",
        lambda brief, brand_kit, out_dir, name: _write_synthetic_still(
            out_dir / name / "story.png"
        ),
    )
    out = tmp_path / "story.mp4"
    result = reel_ffmpeg.render_story_card_from_props(
        _props(), _brand_dict(), _brand_kit(), out, duration_sec=4.0
    )
    assert Path(result).exists() and Path(result).stat().st_size > 1024
    duration = reel_ffmpeg.media_duration_seconds(Path(result))
    assert duration == pytest.approx(4.0, abs=0.25)


@pytest.mark.skipif(not _HAS_FFMPEG, reason="no FFmpeg binary resolvable")
def test_reel_assembly_hits_data_driven_duration_and_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    renders: list[str] = []

    def _fake_still(brief, brand_kit, out_dir, name):
        renders.append(name)
        shade = 40 + 40 * len(renders)
        return _write_synthetic_still(out_dir / name / "story.png", (shade, shade, 90))

    monkeypatch.setattr(reel_ffmpeg, "_render_still", _fake_still)
    cards = [_props(), _props(name="Grace Hopper", event="200m Butterfly LC")]
    out = tmp_path / "reel.mp4"
    result = reel_ffmpeg.render_meet_reel_from_props(
        cards, _brand_dict(), _brand_kit(), out, meet_name="Test Meet"
    )
    assert renders == ["cover", "card0", "card1"]
    duration = reel_ffmpeg.media_duration_seconds(Path(result))
    assert duration == pytest.approx(reel_duration_for(2), abs=0.25)

    # Second call is a pure cache hit: no further stills are rendered.
    renders.clear()
    again = reel_ffmpeg.render_meet_reel_from_props(
        cards, _brand_dict(), _brand_kit(), out, meet_name="Test Meet"
    )
    assert renders == []
    assert Path(again).exists()
