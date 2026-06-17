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


def _write_synthetic_still(path: Path, colour=(10, 37, 64), *, size=None) -> Path:
    from PIL import Image

    w, h = size or (reel_ffmpeg.WIDTH, reel_ffmpeg.HEIGHT)
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (int(w), int(h)), colour).save(path)
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
# R1.17 — richer motion: Ken Burns variants, parallax, beat transitions
# ---------------------------------------------------------------------------


def test_ken_burns_default_is_byte_identical_to_the_historic_zoom():
    """The bare builders keep the historic centre zoom-in / alternating
    zoom so a caller that passes no programme renders exactly as before —
    the file-sibling guarantee against the multi-format work (R1.16)."""
    story = " ".join(reel_ffmpeg.story_ffmpeg_args(Path("s.png"), Path("o.mp4"), 6.0))
    assert "zoompan=z='min(1.0+" in story  # centre zoom-in
    assert "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'" in story

    stills = [Path(f"f{i}.png") for i in range(4)]
    segs = reel_ffmpeg.reel_segment_durations(3, reel_duration_for(3))
    fc = reel_ffmpeg.reel_ffmpeg_args(stills, Path("r.mp4"), segs)[
        reel_ffmpeg.reel_ffmpeg_args(stills, Path("r.mp4"), segs).index("-filter_complex") + 1
    ]
    assert "zoompan=z='min(1.0+" in fc and "zoompan=z='max(1.08-" in fc  # alternation
    assert fc.count("xfade=transition=fade") == 3  # plain crossfade default


@pytest.mark.parametrize(
    "variant,must_contain,must_not",
    [
        ("zoom_in", ["zoompan", "min(1.0+"], []),
        ("zoom_out", ["zoompan", "max(1.08-"], []),
        ("pan_left", ["zoompan", "z='1.12'", "(1-on/"], []),
        ("pan_right", ["zoompan", "z='1.12'"], ["1-on/"]),
        ("pan_up", ["zoompan", "(1-on/"], []),
        ("pan_down", ["zoompan"], []),
        ("zoom_tl", ["zoompan", "x='0':y='0'"], []),
        ("zoom_br", ["zoompan", "(iw-iw/zoom)"], []),
        ("hold", ["scale=1080:1920"], ["zoompan"]),
    ],
)
def test_ken_burns_variant_fragments_are_well_formed(variant, must_contain, must_not):
    frag = reel_ffmpeg._ken_burns_filter(4.0, variant=variant, tag="0")
    for token in must_contain:
        assert token in frag, f"{variant}: missing {token!r}"
    for token in must_not:
        assert token not in frag, f"{variant}: unexpected {token!r}"


def test_parallax_fragment_is_a_tag_unique_two_plane_composite():
    """Parallax is a split → blurred drifting background + sharp pushed
    foreground → overlay graph, with internal pads suffixed by the beat tag
    so two parallax beats in one filter_complex never collide."""
    a = reel_ffmpeg._ken_burns_filter(4.0, variant="parallax", tag="1")
    b = reel_ffmpeg._ken_burns_filter(4.0, variant="parallax", tag="2")
    assert "split=2[pbg1][pfg1]" in a and "split=2[pbg2][pfg2]" in b
    assert "gblur=sigma=" in a and "overlay=" in a
    assert a.count("zoompan") == 2  # one per plane, at different rates
    # No shared internal pad names between beats — chained safely in one graph.
    assert "[pbg2]" not in a and "[pbg1]" not in b


def test_ken_burns_variant_selection_honours_intent_then_seed():
    # The depth/hold intents win outright (mirror the Remotion intents)…
    assert reel_ffmpeg._ken_burns_variant_for(7, motion_intent="parallax") == "parallax"
    assert reel_ffmpeg._ken_burns_variant_for(7, motion_intent="static") == "hold"
    # …otherwise the card's own seed rotates the flat vocabulary deterministically.
    for seed in range(len(reel_ffmpeg.KEN_BURNS_VARIANTS) * 2):
        expected = reel_ffmpeg.KEN_BURNS_VARIANTS[seed % len(reel_ffmpeg.KEN_BURNS_VARIANTS)]
        assert reel_ffmpeg._ken_burns_variant_for(seed) == expected


def test_transition_kind_mirrors_meetreel_transitionfor():
    # Connective beats: variationSeed % 3 → crossfade / push / wipe.
    assert [reel_ffmpeg._transition_kind_for(s) for s in (0, 1, 2)] == [
        "crossfade",
        "push",
        "wipe",
    ]
    assert reel_ffmpeg._transition_kind_for(3) == "crossfade"  # wraps mod 3
    # Peak beat: the cut's character derives from the beat's mood.
    assert reel_ffmpeg._transition_kind_for(0, peak=True, mood="calm precise") == "blur"
    assert reel_ffmpeg._transition_kind_for(0, peak=True, mood="electric fierce") == "whip"
    assert reel_ffmpeg._transition_kind_for(0, peak=True, mood="celebratory medal") == "iris"
    assert reel_ffmpeg._transition_kind_for(0, peak=True, mood="bold") == "zoom"


def test_xfade_mapping_covers_every_kind_with_real_transition_names():
    # Each Remotion kind maps to a distinct, valid FFmpeg xfade name.
    names = {
        reel_ffmpeg._xfade_for(k)
        for k in ("crossfade", "push", "wipe", "blur", "zoom", "whip", "iris")
    }
    assert names == {"fade", "slideup", "wiperight", "hblur", "zoomin", "slideleft", "circleopen"}
    assert reel_ffmpeg._xfade_for("unknown_kind") == "fade"  # safe fallback


def test_reel_transition_names_earn_one_peak_cut_then_stay_connective():
    # >1 card: cover→peak earns the mood cut (celebratory → iris/circleopen),
    # every later handoff shares the one connective kind from the top seed.
    cards = [
        {"variationSeed": 0, "mood": "celebratory"},
        {"variationSeed": 9, "mood": "fierce"},
        {"variationSeed": 4, "mood": "calm"},
    ]
    names = reel_ffmpeg._reel_transition_names(cards)
    assert len(names) == 3  # one join per card beat (cover→c0, c0→c1, c1→c2)
    assert names[0] == "circleopen"  # earned peak cut from card 0's mood
    assert names[1] == names[2] == "fade"  # connective from seed 0 → crossfade
    # A single-card reel has no peak — the lone handoff is connective.
    assert reel_ffmpeg._reel_transition_names([{"variationSeed": 1}]) == ["slideup"]
    assert reel_ffmpeg._reel_transition_names([]) == []


def test_reel_kb_variants_lead_with_a_steady_cover_then_per_card():
    cards = [
        {"variationSeed": 0},  # → zoom_in
        {"variationSeed": 2},  # → pan_left
        {"variationSeed": 0, "motionIntent": "parallax"},
    ]
    variants = reel_ffmpeg._reel_kb_variants(cards)
    assert variants == ["zoom_in", "zoom_in", "pan_left", "parallax"]
    assert len(variants) == len(cards) + 1  # cover + one per card


def test_reel_args_thread_variants_and_transitions_into_the_graph():
    stills = [Path(f"f{i}.png") for i in range(4)]
    segs = reel_ffmpeg.reel_segment_durations(3, reel_duration_for(3))
    args = reel_ffmpeg.reel_ffmpeg_args(
        stills,
        Path("reel.mp4"),
        segs,
        kb_variants=["zoom_in", "parallax", "pan_right", "hold"],
        transitions=["circleopen", "slideup", "slideup"],
    )
    fc = args[args.index("-filter_complex") + 1]
    assert "split=2[pbg1][pfg1]" in fc  # the parallax beat (still index 1)
    assert fc.count("xfade=transition=circleopen") == 1
    assert fc.count("xfade=transition=slideup") == 2
    # Wrong-length programmes are rejected, not silently truncated.
    with pytest.raises(ValueError):
        reel_ffmpeg.reel_ffmpeg_args(stills, Path("o.mp4"), segs, kb_variants=["zoom_in"])
    with pytest.raises(ValueError):
        reel_ffmpeg.reel_ffmpeg_args(stills, Path("o.mp4"), segs, transitions=["fade"])


def test_story_args_respect_a_requested_variant():
    pan = " ".join(
        reel_ffmpeg.story_ffmpeg_args(Path("s.png"), Path("o.mp4"), 6.0, variant="pan_up")
    )
    assert "z='1.12'" in pan  # the pan zoom, not the centre zoom-in
    par = " ".join(
        reel_ffmpeg.story_ffmpeg_args(Path("s.png"), Path("o.mp4"), 6.0, variant="parallax")
    )
    assert "split=2[pbgs][pfgs]" in par and "overlay=" in par


def test_motion_is_deterministic():
    """Same inputs → identical args (no RNG, no clock)."""
    a = reel_ffmpeg.story_ffmpeg_args(Path("s.png"), Path("o.mp4"), 5.0, variant="zoom_br")
    b = reel_ffmpeg.story_ffmpeg_args(Path("s.png"), Path("o.mp4"), 5.0, variant="zoom_br")
    assert a == b


# ---------------------------------------------------------------------------
# Frame briefs — deterministic, no AI
# ---------------------------------------------------------------------------


def test_minimal_brief_carries_card_facts_and_brand_palette():
    brief = reel_ffmpeg._minimal_brief(
        _props(), _brand_dict(), profile_id="ffmpeg-test"
    )
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
    brief = reel_ffmpeg._frame_brief(
        _props(), _brand_dict(), _brand_kit(), {"not_a_field": True}
    )
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
        reel_ffmpeg.render_story_card_from_props(
            _props(), _brand_dict(), _brand_kit(), out
        )
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
        lambda brief, brand_kit, out_dir, name, **kw: _write_synthetic_still(
            out_dir / name / "story.png",
            size=kw.get("size", (reel_ffmpeg.WIDTH, reel_ffmpeg.HEIGHT)),
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

    def _fake_still(brief, brand_kit, out_dir, name, **kw):
        renders.append(name)
        shade = 40 + 40 * len(renders)
        return _write_synthetic_still(
            out_dir / name / "story.png",
            (shade, shade, 90),
            size=kw.get("size", (reel_ffmpeg.WIDTH, reel_ffmpeg.HEIGHT)),
        )

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


# ---------------------------------------------------------------------------
# Multi-format support (R1.16) — the free fallback renders every Remotion cut
# (story / portrait / square / landscape), not just story.
# ---------------------------------------------------------------------------

# (width, height) per cut — the single source of truth lives in
# motion.MOTION_FORMATS; pinned here so a silent geometry drift is caught.
_FORMAT_SIZES = {
    "story": (1080, 1920),
    "portrait": (1080, 1350),
    "square": (1080, 1080),
    "landscape": (1920, 1080),
}
_NON_STORY = ["portrait", "square", "landscape"]


def _media_dimensions(path: Path):
    """(width, height) of the first video stream via ``ffmpeg -i`` stderr."""
    import re as _re
    import subprocess as _sp

    exe = reel_ffmpeg.ffmpeg_exe()
    proc = _sp.run([exe, "-hide_banner", "-i", str(path)], capture_output=True, text=True)
    m = _re.search(r"Video:.*?\b(\d{2,5})x(\d{2,5})\b", proc.stderr or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


# ---- Geometry resolution -------------------------------------------------


@pytest.mark.parametrize("fmt,size", list(_FORMAT_SIZES.items()))
def test_format_size_resolves_every_cut(fmt, size):
    assert reel_ffmpeg._format_size(fmt) == size


def test_format_size_rejects_unknown_cut():
    # Honest config error — never a silently wrong aspect ratio.
    with pytest.raises(ValueError):
        reel_ffmpeg._format_size("imax")


# ---- Pure arg builders carry the requested geometry ----------------------


@pytest.mark.parametrize("fmt,size", list(_FORMAT_SIZES.items()))
def test_ken_burns_filter_targets_requested_geometry(fmt, size):
    w, h = size
    vf = reel_ffmpeg._ken_burns_filter(4.0, width=w, height=h)
    assert f"scale={w * 2}:{h * 2}" in vf
    assert f"s={w}x{h}" in vf


@pytest.mark.parametrize("fmt,size", list(_FORMAT_SIZES.items()))
def test_story_args_carry_requested_geometry(fmt, size):
    w, h = size
    args = reel_ffmpeg.story_ffmpeg_args(Path("s.png"), Path("o.mp4"), 6.0, width=w, height=h)
    joined = " ".join(args)
    assert f"scale={w * 2}:{h * 2}" in joined
    assert f"s={w}x{h}" in joined


@pytest.mark.parametrize("fmt,size", list(_FORMAT_SIZES.items()))
def test_reel_args_carry_requested_geometry(fmt, size):
    w, h = size
    stills = [Path(f"f{i}.png") for i in range(3)]
    segs = reel_ffmpeg.reel_segment_durations(2, reel_duration_for(2))
    args = reel_ffmpeg.reel_ffmpeg_args(stills, Path("r.mp4"), segs, width=w, height=h)
    fc = args[args.index("-filter_complex") + 1]
    assert fc.count(f"s={w}x{h}") == 3  # one zoompan per beat at the cut size


def test_story_args_default_to_story_geometry():
    """Omitting width/height keeps the historic story geometry byte-for-byte."""
    explicit = reel_ffmpeg.story_ffmpeg_args(Path("s.png"), Path("o.mp4"), 6.0)
    keyed = reel_ffmpeg.story_ffmpeg_args(
        Path("s.png"),
        Path("o.mp4"),
        6.0,
        width=reel_ffmpeg.WIDTH,
        height=reel_ffmpeg.HEIGHT,
    )
    assert explicit == keyed


# ---- Frame briefs tag the requested cut ----------------------------------


@pytest.mark.parametrize("fmt", list(_FORMAT_SIZES))
def test_minimal_brief_tags_requested_format(fmt):
    brief = reel_ffmpeg._minimal_brief(_props(), _brand_dict(), profile_id="p", format_name=fmt)
    assert brief.format_priority == [fmt]


@pytest.mark.parametrize("fmt", _NON_STORY)
def test_frame_brief_tags_requested_format_on_fallback(fmt):
    brief = reel_ffmpeg._frame_brief(_props(), _brand_dict(), _brand_kit(), None, format_name=fmt)
    assert brief.format_priority == [fmt]


@pytest.mark.parametrize("fmt", _NON_STORY)
def test_frame_brief_tags_requested_format_on_rehydrated_brief(fmt):
    persisted = reel_ffmpeg._minimal_brief(_props(), _brand_dict(), profile_id="p").to_dict()
    brief = reel_ffmpeg._frame_brief(
        _props(), _brand_dict(), _brand_kit(), persisted, format_name=fmt
    )
    assert brief.format_priority == [fmt]


@pytest.mark.parametrize("fmt", _NON_STORY)
def test_cover_brief_tags_requested_format(fmt):
    cover = reel_ffmpeg._cover_brief([_props()], _brand_dict(), _brand_kit(), "", format_name=fmt)
    assert cover.layout_template == "reel_cover"
    assert cover.format_priority == [fmt]


# ---- Cache identity: story stays byte-identical, cuts never collide -------


def _story_cache_payload(fmt: str) -> dict:
    """Mirror render_story_card_from_props's cache payload for ``fmt``."""
    p = {
        "card": _props(),
        "brand": _brand_dict(),
        "duration": 6.0,
        "engine": "ffmpeg",
        "brief": {},
    }
    if fmt != "story":
        p["format"] = fmt
    return p


def test_story_cache_key_is_unchanged_by_multiformat():
    """The story payload must carry NO 'format' key, so a pre-multiformat
    cached story render keeps the exact same hash (byte-identical promise)."""
    legacy = {
        "card": _props(),
        "brand": _brand_dict(),
        "duration": 6.0,
        "engine": "ffmpeg",
        "brief": {},
    }
    assert _content_hash(_story_cache_payload("story"), kind="story") == _content_hash(
        legacy, kind="story"
    )


def test_each_cut_gets_a_distinct_cache_key():
    keys = {fmt: _content_hash(_story_cache_payload(fmt), kind="story") for fmt in _FORMAT_SIZES}
    assert len(set(keys.values())) == len(keys), f"cache-key collision across cuts: {keys}"


# ---- Real FFmpeg assembly at each cut (synthetic stills, no Chromium) -----


@pytest.mark.skipif(not _HAS_FFMPEG, reason="no FFmpeg binary resolvable")
@pytest.mark.parametrize("fmt,size", list(_FORMAT_SIZES.items()))
def test_story_assembly_renders_each_cut_at_correct_dimensions(fmt, size, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        reel_ffmpeg,
        "_render_still",
        lambda brief, brand_kit, out_dir, name, **kw: _write_synthetic_still(
            out_dir / name / "frame.png", size=kw.get("size", size)
        ),
    )
    out = tmp_path / f"story_{fmt}.mp4"
    result = reel_ffmpeg.render_story_card_from_props(
        _props(), _brand_dict(), _brand_kit(), out, duration_sec=2.0, format_name=fmt
    )
    assert Path(result).exists() and Path(result).stat().st_size > 1024
    assert _media_dimensions(Path(result)) == size


@pytest.mark.skipif(not _HAS_FFMPEG, reason="no FFmpeg binary resolvable")
@pytest.mark.parametrize("fmt,size", [(f, _FORMAT_SIZES[f]) for f in _NON_STORY])
def test_reel_assembly_renders_each_cut_at_correct_dimensions(fmt, size, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        reel_ffmpeg,
        "_render_still",
        lambda brief, brand_kit, out_dir, name, **kw: _write_synthetic_still(
            out_dir / name / "frame.png", size=kw.get("size", size)
        ),
    )
    out = tmp_path / f"reel_{fmt}.mp4"
    result = reel_ffmpeg.render_meet_reel_from_props(
        [_props()],
        _brand_dict(),
        _brand_kit(),
        out,
        meet_name="Cut Test",
        duration_sec=3.0,
        format_name=fmt,
    )
    assert Path(result).exists() and Path(result).stat().st_size > 1024
    assert _media_dimensions(Path(result)) == size


@pytest.mark.skipif(not _HAS_FFMPEG, reason="no FFmpeg binary resolvable")
def test_each_cut_caches_independently(tmp_path, monkeypatch):
    """Rendering all four cuts of the same card leaves four distinct cache
    entries, and a story re-render is a pure cache hit (key is stable)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        reel_ffmpeg,
        "_render_still",
        lambda brief, brand_kit, out_dir, name, **kw: _write_synthetic_still(
            out_dir / name / "frame.png",
            size=kw.get("size", (reel_ffmpeg.WIDTH, reel_ffmpeg.HEIGHT)),
        ),
    )
    cache = tmp_path / "motion_cache"
    for fmt in _FORMAT_SIZES:
        reel_ffmpeg.render_story_card_from_props(
            _props(),
            _brand_dict(),
            _brand_kit(),
            tmp_path / f"{fmt}.mp4",
            duration_sec=1.5,
            format_name=fmt,
        )
    assert len(list(cache.glob("*.mp4"))) == 4  # one cache entry per cut

    reel_ffmpeg.render_story_card_from_props(
        _props(),
        _brand_dict(),
        _brand_kit(),
        tmp_path / "story_again.mp4",
        duration_sec=1.5,
        format_name="story",
    )
    assert len(list(cache.glob("*.mp4"))) == 4  # story re-render hit the cache


# ---------------------------------------------------------------------------
# Richer motion (R1.17) — Ken Burns variants, parallax, mood-chosen peak cut.
# These render via the same multi-format path above (story geometry here).
# ---------------------------------------------------------------------------


@pytest.mark.skipif(not _HAS_FFMPEG, reason="no FFmpeg binary resolvable")
def test_reel_assembly_with_parallax_hold_and_mood_peak_is_valid(tmp_path, monkeypatch):
    """The richer motion graph (a parallax beat, a held beat, and a
    mood-chosen peak cut) must assemble into a valid MP4 of the exact
    data-driven length — the end-to-end proof the new vocabulary renders."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        reel_ffmpeg,
        "_render_still",
        lambda brief, brand_kit, out_dir, name, **kw: _write_synthetic_still(
            out_dir / name / "story.png"
        ),
    )
    cards = [
        # peak (card 0): celebratory mood → iris/circleopen, parallax depth beat
        {**_props(), "variationSeed": 0, "mood": "celebratory", "motionIntent": "parallax"},
        # seed-driven flat Ken Burns beat
        {**_props(name="Grace Hopper", event="200m Butterfly LC"), "variationSeed": 2},
        # honest held beat
        {**_props(name="Katie Ledecky", event="800m Free LC"), "motionIntent": "static"},
    ]
    out = tmp_path / "reel.mp4"
    result = reel_ffmpeg.render_meet_reel_from_props(
        cards, _brand_dict(), _brand_kit(), out, meet_name="Test Meet"
    )
    assert Path(result).exists() and Path(result).stat().st_size > 1024
    duration = reel_ffmpeg.media_duration_seconds(Path(result))
    assert duration == pytest.approx(reel_duration_for(3), abs=0.25)


@pytest.mark.skipif(not _HAS_FFMPEG, reason="no FFmpeg binary resolvable")
def test_story_assembly_with_a_parallax_variant_renders(tmp_path, monkeypatch):
    """A single story card under the parallax (split/blur/overlay) graph
    still produces a valid MP4 of the requested length."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        reel_ffmpeg,
        "_render_still",
        lambda brief, brand_kit, out_dir, name, **kw: _write_synthetic_still(
            out_dir / name / "story.png"
        ),
    )
    out = tmp_path / "story.mp4"
    result = reel_ffmpeg.render_story_card_from_props(
        {**_props(), "motionIntent": "parallax"},
        _brand_dict(),
        _brand_kit(),
        out,
        duration_sec=4.0,
    )
    assert Path(result).exists() and Path(result).stat().st_size > 1024
    assert reel_ffmpeg.media_duration_seconds(Path(result)) == pytest.approx(4.0, abs=0.25)
