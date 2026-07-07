"""visual/audio_mux.py — engine-agnostic audio + poster finishing.

Covers the gates (everything off by default), the deterministic music pick,
the pure mux-arg builders, the honest silent fallback, and — when an FFmpeg
binary is present (the imageio-ffmpeg wheel ships one) — a real mux + poster
extraction on a generated test clip.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from mediahub.visual import audio_mux
from mediahub.visual.voiceover import VoiceoverError

_FFMPEG = audio_mux.ffmpeg_exe()


def _make_clip(path: Path, *, seconds: float = 1.0) -> Path:
    """A tiny real H.264 clip for integration assertions."""
    subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c=red:s=320x640:d={seconds}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


def _make_tone(path: Path, *, seconds: float = 2.0) -> Path:
    subprocess.run(
        [
            _FFMPEG,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:duration={seconds}",
            str(path),
        ],
        check=True,
        capture_output=True,
    )
    return path


# ---------------------------------------------------------------------------
# Gates: silent by default
# ---------------------------------------------------------------------------


def test_everything_off_by_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_VOICEOVER", raising=False)
    monkeypatch.delenv("MEDIAHUB_REEL_MUSIC_DIR", raising=False)
    assert audio_mux.voice_active() is False
    assert audio_mux.music_dir() is None
    assert audio_mux.audio_active() is False
    assert audio_mux.build_audio_plan(script="anything", content_key="k") is None


def test_voice_needs_both_opt_in_and_a_backend(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_VOICEOVER", "1")
    monkeypatch.setattr("mediahub.visual.voiceover.is_available", lambda: False)
    assert audio_mux.voice_active() is False
    monkeypatch.setattr("mediahub.visual.voiceover.is_available", lambda: True)
    assert audio_mux.voice_active() is True


def test_voice_name_honours_the_existing_env(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_VOICEOVER_VOICE", raising=False)
    from mediahub.visual.voiceover import DEFAULT_VOICE

    assert audio_mux.voice_name() == DEFAULT_VOICE
    monkeypatch.setenv("MEDIAHUB_VOICEOVER_VOICE", "en-GB-RyanNeural")
    assert audio_mux.voice_name() == "en-GB-RyanNeural"


# ---------------------------------------------------------------------------
# Music: operator-supplied directory, deterministic pick
# ---------------------------------------------------------------------------


def test_music_pick_is_deterministic_and_suffix_filtered(tmp_path, monkeypatch):
    d = tmp_path / "music"
    d.mkdir()
    for name in ("a.mp3", "b.mp3", "c.wav", "notes.txt", "cover.png"):
        (d / name).write_bytes(b"x" * 64)
    monkeypatch.setenv("MEDIAHUB_REEL_MUSIC_DIR", str(d))
    tracks = audio_mux.music_candidates()
    assert [t.name for t in tracks] == ["a.mp3", "b.mp3", "c.wav"]
    first = audio_mux.pick_music("reel:Spring Open:3")
    again = audio_mux.pick_music("reel:Spring Open:3")
    assert first == again, "same content key must pick the same track"
    assert first is not None and first.suffix in {".mp3", ".wav"}


def test_music_dir_unset_or_missing_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_REEL_MUSIC_DIR", str(tmp_path / "nope"))
    assert audio_mux.music_dir() is None
    assert audio_mux.pick_music("k") is None


def test_plan_with_music_only(tmp_path, monkeypatch):
    d = tmp_path / "music"
    d.mkdir()
    (d / "bed.mp3").write_bytes(b"x" * 128)
    monkeypatch.setenv("MEDIAHUB_REEL_MUSIC_DIR", str(d))
    monkeypatch.delenv("MEDIAHUB_VOICEOVER", raising=False)
    plan = audio_mux.build_audio_plan(script="ignored without voice", content_key="k")
    assert plan == {"music": "bed.mp3", "music_bytes": 128}


def test_plan_with_voice(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_VOICEOVER", "1")
    monkeypatch.delenv("MEDIAHUB_REEL_MUSIC_DIR", raising=False)
    monkeypatch.setattr("mediahub.visual.voiceover.is_available", lambda: True)
    plan = audio_mux.build_audio_plan(script="Spring Open. Meet recap.", content_key="k")
    assert plan is not None
    assert plan["script"] == "Spring Open. Meet recap."
    assert plan["voice"]
    assert "music" not in plan
    # Voice on but nothing to say and no music → honest None (silent).
    assert audio_mux.build_audio_plan(script="  ", content_key="k") is None


# ---------------------------------------------------------------------------
# mux_args — pure builder
# ---------------------------------------------------------------------------


def test_mux_args_voice_only_shape(tmp_path):
    args = audio_mux.mux_args(
        tmp_path / "v.mp4", tmp_path / "n.mp3", None, tmp_path / "o.mp4", duration_sec=15.0
    )
    joined = " ".join(args)
    assert "apad" in joined and "atrim=0:15.000" in joined and "afade=t=out" in joined
    assert "-c:v copy" in joined, "video bits must never be re-encoded"
    assert "[aout]" in joined and "+faststart" in joined


def test_mux_args_music_only_loops_and_ducks_nothing(tmp_path):
    args = audio_mux.mux_args(
        tmp_path / "v.mp4", None, tmp_path / "bed.mp3", tmp_path / "o.mp4", duration_sec=7.0
    )
    joined = " ".join(args)
    assert "-stream_loop -1" in joined, "short beds must loop under long reels"
    assert f"volume={audio_mux.MUSIC_BED_VOLUME}" in joined
    assert "amix" not in joined


def test_mux_args_voice_plus_music_ducks_via_sidechain(tmp_path):
    """R1.20: music under narration is ducked dynamically by a voice-keyed
    sidechain compressor, not held at one static amix weight."""
    args = audio_mux.mux_args(
        tmp_path / "v.mp4",
        tmp_path / "n.mp3",
        tmp_path / "bed.mp3",
        tmp_path / "o.mp4",
        duration_sec=15.0,
    )
    joined = " ".join(args)
    assert "sidechaincompress=" in joined, "ducking must be sidechain-driven now"
    assert f"threshold={audio_mux.DUCK_THRESHOLD:g}" in joined
    assert f"ratio={audio_mux.DUCK_RATIO:g}" in joined
    assert "asplit=2[vmain][vkey]" in joined, "voice keys the sidechain and the mix"
    assert "amix=inputs=2" in joined, "voice and ducked bed are still mixed together"
    assert (
        f"volume={audio_mux.MUSIC_UNDER_VOICE_WEIGHT:.3f}" in joined
    ), "the resting bed level under voice is preserved"
    assert "weights=1" not in joined, "the old static-weight mix is gone"


def test_mux_args_requires_a_source(tmp_path):
    with pytest.raises(ValueError):
        audio_mux.mux_args(tmp_path / "v.mp4", None, None, tmp_path / "o.mp4", duration_sec=5.0)


# ---------------------------------------------------------------------------
# R1.20 — music-bed upgrade: beat grid, music-pool tempo, stings, accents
# ---------------------------------------------------------------------------


def test_card_cut_times_mirror_the_reel_structure():
    """The beat grid is the reel's own cover + per-card structure — a single
    source of truth shared with motion.reel_duration_for."""
    from mediahub.visual.motion import (
        REEL_COVER_SEC,
        REEL_PER_CARD_SEC,
        reel_duration_for,
    )

    # 3 cards @ the historic 15s default → cuts into card1/2/3.
    assert audio_mux.card_cut_times(reel_duration_for(3), 3) == [
        REEL_COVER_SEC,
        REEL_COVER_SEC + REEL_PER_CARD_SEC,
        REEL_COVER_SEC + 2 * REEL_PER_CARD_SEC,
    ]
    # One cut per card; capped at the same 1..5 range the route enforces.
    assert len(audio_mux.card_cut_times(reel_duration_for(1), 1)) == 1
    assert len(audio_mux.card_cut_times(reel_duration_for(9), 9)) == 5
    # Stories (single scene) have no internal cuts.
    assert audio_mux.card_cut_times(6.0, 0) == []


def test_card_cut_times_scale_with_an_overridden_duration():
    base = audio_mux.card_cut_times(15.0, 3)
    doubled = audio_mux.card_cut_times(30.0, 3)
    # approx: each grid is independently rounded to 3 dp after scaling.
    assert doubled == pytest.approx([b * 2 for b in base], abs=2e-3), (
        "cuts scale with the total"
    )


def test_card_cut_times_follow_a_custom_rhythm():
    """R1.12 — with a customised rhythm the video's real cuts move (MeetReel
    carve / reel_segment_durations); the accent grid must move with them."""
    from mediahub.visual.motion import normalise_reel_rhythm, reel_duration_for
    from mediahub.visual.reel_ffmpeg import reel_segment_durations

    rhythm = normalise_reel_rhythm(
        {"cover": 3.0, "outro": 2.0, "per_card_sec": 5.0, "weights": [2.0, 1.0, 1.0]}, 3
    )
    total = reel_duration_for(
        3, cover_sec=3.0, outro_sec=2.0, per_card_sec=5.0, beat_weights=[2.0, 1.0, 1.0]
    )
    cuts = audio_mux.card_cut_times(total, 3, rhythm)
    # Cumulative weighted seconds: cover, cover+5*2, cover+5*2+5*1.
    assert cuts == [3.0, 13.0, 18.0]
    # Same boundaries the free engine's segment maths produce (last segment
    # absorbs the outro; strip the xfade padding each non-final segment gains).
    from mediahub.visual.reel_ffmpeg import CROSSFADE_SEC

    segs = reel_segment_durations(3, total, rhythm=rhythm)
    visible = [s - (CROSSFADE_SEC if i < len(segs) - 1 else 0.0) for i, s in enumerate(segs)]
    boundaries = []
    acc = 0.0
    for v in visible[:-1]:
        acc += v
        boundaries.append(round(acc, 3))
    assert cuts == boundaries
    # No rhythm (or a default one) keeps the historic flat grid byte-identical.
    assert audio_mux.card_cut_times(15.0, 3, None) == audio_mux.card_cut_times(15.0, 3)


def test_track_bpm_from_filename_and_sidecar(tmp_path):
    assert audio_mux.track_bpm(tmp_path / "anthem.128bpm.mp3") == 128.0
    assert audio_mux.track_bpm(tmp_path / "warm up - 90 bpm.wav") == 90.0
    assert audio_mux.track_bpm(tmp_path / "plain-bed.mp3") is None
    # Out-of-range declarations are rejected (no 30 or 350 bpm beds).
    assert audio_mux.track_bpm(tmp_path / "x.30bpm.mp3") is None
    assert audio_mux.track_bpm(tmp_path / "x.350bpm.mp3") is None
    # Sidecar wins when the filename is silent on tempo.
    bed = tmp_path / "quiet.mp3"
    bed.write_bytes(b"x")
    (tmp_path / "quiet.mp3.bpm").write_text("112\n")
    assert audio_mux.track_bpm(bed) == 112.0


def test_music_pool_summary_counts_and_tempo(tmp_path, monkeypatch):
    d = tmp_path / "music"
    d.mkdir()
    (d / "a.128bpm.mp3").write_bytes(b"x")
    (d / "b.mp3").write_bytes(b"x")
    (d / "notes.txt").write_bytes(b"x")
    monkeypatch.setenv("MEDIAHUB_REEL_MUSIC_DIR", str(d))
    summary = audio_mux.music_pool_summary()
    assert summary["count"] == 2  # txt filtered out
    assert summary["with_declared_bpm"] == 1
    assert summary["tracks"] == ["a.128bpm.mp3", "b.mp3"]


def test_accent_width_prefers_one_declared_beat():
    # Unknown tempo → fixed default.
    assert audio_mux._accent_width(None) == audio_mux.CUT_ACCENT_SEC
    assert audio_mux._accent_width(0) == audio_mux.CUT_ACCENT_SEC
    # Known tempo → one beat, clamped into a sane window.
    assert audio_mux._accent_width(150) == pytest.approx(0.4)  # 60/150
    assert audio_mux._accent_width(600) == 0.12  # clamp floor
    assert audio_mux._accent_width(30) == 0.5  # clamp ceiling


def test_music_filterchain_carries_stings_and_beat_accents():
    chain = audio_mux.music_filterchain(
        base_vol=audio_mux.MUSIC_BED_VOLUME,
        duration_sec=15.0,
        cut_times=[2.0, 6.0, 10.0],
        bpm=None,
    )
    # Resting level + intro swell + outro accent + a hit on every card cut.
    assert f"volume={audio_mux.MUSIC_BED_VOLUME:.3f}" in chain
    assert f"afade=t=in:st=0:d={audio_mux.INTRO_STING_SEC}" in chain
    assert (
        f"volume={audio_mux.STING_GAIN}:enable='between(t,0,{audio_mux.INTRO_STING_SEC})'" in chain
    )
    assert (
        "between(t,2.000," in chain and "between(t,6.000," in chain and "between(t,10.000," in chain
    )


def test_music_filterchain_suppresses_stings_on_short_clips():
    """A one-second story bed gets the gentle fade, never a clashing swell."""
    chain = audio_mux.music_filterchain(
        base_vol=audio_mux.MUSIC_BED_VOLUME, duration_sec=1.0, cut_times=None, bpm=None
    )
    assert "afade=t=in:st=0:d=0.5" in chain
    assert f"d={audio_mux.INTRO_STING_SEC}" not in chain
    assert "between(t," not in chain  # no accents without cuts


def test_mux_args_music_only_carries_cut_accents(tmp_path):
    args = audio_mux.mux_args(
        tmp_path / "v.mp4",
        None,
        tmp_path / "bed.mp3",
        tmp_path / "o.mp4",
        duration_sec=15.0,
        cut_times=[2.0, 6.0, 10.0],
    )
    joined = " ".join(args)
    assert f"volume={audio_mux.CUT_ACCENT_GAIN}" in joined
    assert "between(t,2.000," in joined
    assert "amix" not in joined  # still no voice to mix


def test_mux_args_voice_only_ignores_cut_times(tmp_path):
    """Cut accents are a music feature; a voice-only render is untouched."""
    args = audio_mux.mux_args(
        tmp_path / "v.mp4",
        tmp_path / "n.mp3",
        None,
        tmp_path / "o.mp4",
        duration_sec=15.0,
        cut_times=[2.0, 6.0, 10.0],
    )
    joined = " ".join(args)
    assert "between(t," not in joined
    assert "sidechaincompress" not in joined


# ---------------------------------------------------------------------------
# Per-card audio-mix profiles (R1.19)
# ---------------------------------------------------------------------------


def _voice_on(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_VOICEOVER", "1")
    monkeypatch.delenv("MEDIAHUB_REEL_MUSIC_DIR", raising=False)
    monkeypatch.delenv("MEDIAHUB_REEL_MIX_PROFILE", raising=False)
    monkeypatch.setattr("mediahub.visual.voiceover.is_available", lambda: True)


def test_mix_profile_table_and_balanced_is_the_historic_mix():
    assert set(audio_mux.AUDIO_MIX_PROFILES) == {"voice_lead", "balanced", "music_forward"}
    assert audio_mux.DEFAULT_MIX_PROFILE == "balanced"
    # ``balanced`` must reproduce the historic constants exactly, or every
    # pre-profile cache would be silently orphaned.
    bal = audio_mux.AUDIO_MIX_PROFILES["balanced"]
    assert bal["music_under_voice_weight"] == audio_mux.MUSIC_UNDER_VOICE_WEIGHT
    assert bal["music_bed_volume"] == audio_mux.MUSIC_BED_VOLUME
    assert bal["duck_ratio"] == audio_mux.DUCK_RATIO
    # voice_lead sits below balanced; music_forward above (resting bed level)…
    assert (
        audio_mux.AUDIO_MIX_PROFILES["voice_lead"]["music_under_voice_weight"]
        < bal["music_under_voice_weight"]
        < audio_mux.AUDIO_MIX_PROFILES["music_forward"]["music_under_voice_weight"]
    )
    # …and voice_lead ducks the bed harder than music_forward does.
    assert (
        audio_mux.AUDIO_MIX_PROFILES["voice_lead"]["duck_ratio"]
        > bal["duck_ratio"]
        > audio_mux.AUDIO_MIX_PROFILES["music_forward"]["duck_ratio"]
    )


def test_resolve_mix_profile_validates_and_defaults():
    assert audio_mux.resolve_mix_profile("VOICE_LEAD") == "voice_lead"
    assert audio_mux.resolve_mix_profile("  music_forward ") == "music_forward"
    assert audio_mux.resolve_mix_profile("balanced") == "balanced"
    for bad in ("", "  ", None, "nonsense", 0):
        assert audio_mux.resolve_mix_profile(bad) == "balanced"


def test_env_mix_profile_reads_the_operator_env(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_REEL_MIX_PROFILE", raising=False)
    assert audio_mux.env_mix_profile() == "balanced"
    monkeypatch.setenv("MEDIAHUB_REEL_MIX_PROFILE", "music_forward")
    assert audio_mux.env_mix_profile() == "music_forward"
    monkeypatch.setenv("MEDIAHUB_REEL_MIX_PROFILE", "garbage")
    assert audio_mux.env_mix_profile() == "balanced", "an invalid env value falls back safely"


def test_mix_profile_levels_is_a_fresh_validated_dict():
    levels = audio_mux.mix_profile_levels("voice_lead")
    assert set(levels) == {"music_under_voice_weight", "music_bed_volume", "duck_ratio"}
    levels["music_bed_volume"] = 99.0  # mutating the copy must not poison the table
    assert audio_mux.AUDIO_MIX_PROFILES["voice_lead"]["music_bed_volume"] != 99.0
    assert audio_mux.mix_profile_levels("nope") == audio_mux.AUDIO_MIX_PROFILES["balanced"]


def test_build_audio_plan_default_omits_mix_for_byte_identity(monkeypatch):
    _voice_on(monkeypatch)
    base = audio_mux.build_audio_plan(script="Spring Open. Meet recap.", content_key="k")
    assert base is not None and set(base) == {"voice", "script"}
    explicit = audio_mux.build_audio_plan(
        script="Spring Open. Meet recap.", content_key="k", mix_profile="balanced"
    )
    assert explicit == base, "explicit balanced must not change the cache identity"


def test_build_audio_plan_records_non_default_profile(monkeypatch):
    _voice_on(monkeypatch)
    base = audio_mux.build_audio_plan(script="Spring Open.", content_key="k")
    for name in ("voice_lead", "music_forward"):
        plan = audio_mux.build_audio_plan(script="Spring Open.", content_key="k", mix_profile=name)
        assert plan["mix"] == name
        assert plan != base, "a non-default mix must diverge the cache identity"


def test_build_audio_plan_profile_precedence(monkeypatch):
    _voice_on(monkeypatch)
    monkeypatch.setenv("MEDIAHUB_REEL_MIX_PROFILE", "music_forward")
    # explicit (known) wins over env
    assert (
        audio_mux.build_audio_plan(script="x", content_key="k", mix_profile="voice_lead")["mix"]
        == "voice_lead"
    )
    # no explicit → env default applies
    assert audio_mux.build_audio_plan(script="x", content_key="k")["mix"] == "music_forward"
    # an unknown explicit value falls through to the env default
    assert (
        audio_mux.build_audio_plan(script="x", content_key="k", mix_profile="garbage")["mix"]
        == "music_forward"
    )
    # env unset + no valid explicit → balanced → no mix key
    monkeypatch.delenv("MEDIAHUB_REEL_MIX_PROFILE", raising=False)
    assert "mix" not in audio_mux.build_audio_plan(
        script="x", content_key="k", mix_profile="garbage"
    )


def test_build_audio_plan_profile_needs_an_audio_source(monkeypatch):
    # Voice off and no music → silent None even with a profile requested.
    monkeypatch.delenv("MEDIAHUB_VOICEOVER", raising=False)
    monkeypatch.delenv("MEDIAHUB_REEL_MUSIC_DIR", raising=False)
    assert (
        audio_mux.build_audio_plan(script="x", content_key="k", mix_profile="music_forward") is None
    )


def test_mux_args_balanced_default_matches_the_historic_levels(tmp_path):
    """The default profile reproduces R1.20's resting bed + duck ratio exactly."""
    vm = " ".join(
        audio_mux.mux_args(
            tmp_path / "v.mp4",
            tmp_path / "n.mp3",
            tmp_path / "bed.mp3",
            tmp_path / "o.mp4",
            duration_sec=15.0,
        )
    )
    assert f"volume={audio_mux.MUSIC_UNDER_VOICE_WEIGHT:.3f}" in vm  # resting bed 0.300
    assert f"ratio={audio_mux.DUCK_RATIO:g}" in vm  # ratio 6
    mo = " ".join(
        audio_mux.mux_args(
            tmp_path / "v.mp4", None, tmp_path / "bed.mp3", tmp_path / "o.mp4", duration_sec=7.0
        )
    )
    assert f"volume={audio_mux.MUSIC_BED_VOLUME:.3f}" in mo  # bed 0.400


def test_mux_args_profiles_scale_bed_and_duck(tmp_path):
    def vm(profile):
        return " ".join(
            audio_mux.mux_args(
                tmp_path / "v.mp4",
                tmp_path / "n.mp3",
                tmp_path / "bed.mp3",
                tmp_path / "o.mp4",
                duration_sec=15.0,
                profile=profile,
            )
        )

    def mo(profile):
        return " ".join(
            audio_mux.mux_args(
                tmp_path / "v.mp4",
                None,
                tmp_path / "bed.mp3",
                tmp_path / "o.mp4",
                duration_sec=7.0,
                profile=profile,
            )
        )

    # voice_lead: lower resting bed, harder duck.
    assert "volume=0.180" in vm("voice_lead") and "ratio=9" in vm("voice_lead")
    assert "volume=0.320" in mo("voice_lead")
    # music_forward: higher resting bed, gentler duck.
    assert "volume=0.500" in vm("music_forward") and "ratio=3.5" in vm("music_forward")
    assert "volume=0.600" in mo("music_forward")
    # The sidechain ducking stays in place under every profile (voice clear).
    for prof in ("voice_lead", "balanced", "music_forward"):
        assert "sidechaincompress=" in vm(prof)
    # An unknown profile renders as balanced, never an error.
    assert f"ratio={audio_mux.DUCK_RATIO:g}" in vm("garbage")


# ---------------------------------------------------------------------------
# apply_audio — honest fallback paths (no real synthesis involved)
# ---------------------------------------------------------------------------


def test_apply_audio_off_plan_is_a_noop(tmp_path):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0" * 2048)
    rec = audio_mux.apply_audio(video, None, duration_sec=6.0)
    assert rec == {"status": "off"}
    assert video.read_bytes() == b"0" * 2048


def test_apply_audio_falls_back_silent_when_synthesis_fails(tmp_path, monkeypatch):
    video = tmp_path / "v.mp4"
    video.write_bytes(b"0" * 2048)

    def _boom(*a, **k):
        raise VoiceoverError("endpoint unreachable")

    monkeypatch.setattr("mediahub.visual.voiceover.synthesize", _boom)
    rec = audio_mux.apply_audio(
        video, {"voice": "en-GB-SoniaNeural", "script": "hello"}, duration_sec=6.0
    )
    assert rec["status"] == "silent_fallback"
    assert "voiceover failed" in rec["reason"]
    assert video.read_bytes() == b"0" * 2048, "the rendered video must be left untouched"


def test_poster_time_bounds():
    assert audio_mux.poster_time_for("reel", 15.0) == 1.5
    assert audio_mux.poster_time_for("reel", 1.0) == pytest.approx(0.8)
    assert 0.0 <= audio_mux.poster_time_for("story", 6.0) <= 6.0
    assert audio_mux.poster_path_for(Path("x/y.mp4")).name == "y.poster.png"


# ---------------------------------------------------------------------------
# Integration — real FFmpeg (bundled by imageio-ffmpeg), no network
# ---------------------------------------------------------------------------


@pytest.mark.skipif(_FFMPEG is None, reason="no FFmpeg binary available")
def test_real_mux_music_bed_and_poster(tmp_path, monkeypatch):
    video = _make_clip(tmp_path / "clip.mp4", seconds=1.0)
    assert audio_mux.has_audio_stream(video) is False

    music_dir = tmp_path / "music"
    music_dir.mkdir()
    _make_tone(music_dir / "bed.wav", seconds=0.4)  # shorter than the clip: must loop
    monkeypatch.setenv("MEDIAHUB_REEL_MUSIC_DIR", str(music_dir))
    monkeypatch.delenv("MEDIAHUB_VOICEOVER", raising=False)

    plan = audio_mux.build_audio_plan(script="", content_key="itest")
    assert plan and plan["music"] == "bed.wav"

    rec = audio_mux.apply_audio(video, plan, duration_sec=1.0)
    assert rec["status"] == "mixed"
    assert rec["music"] == "bed.wav"
    assert audio_mux.has_audio_stream(video) is True
    # Explainability: a bed-backed record carries the operator-pool snapshot
    # the deterministic pick chose from.
    assert rec["music_pool"]["count"] == 1
    assert rec["music_pool"]["tracks"] == ["bed.wav"]

    poster = audio_mux.poster_path_for(video)
    assert audio_mux.write_poster(video, poster, at_sec=audio_mux.poster_time_for("story", 1.0))
    assert poster.exists() and poster.stat().st_size > 0


@pytest.mark.skipif(_FFMPEG is None, reason="no FFmpeg binary available")
def test_real_mux_voice_track_via_synth_stub(tmp_path, monkeypatch):
    """Voice path end-to-end with the TTS seam stubbed by a generated tone —
    the mux mechanics are real, only the network synthesis is faked."""
    video = _make_clip(tmp_path / "clip.mp4", seconds=1.0)
    tone = _make_tone(tmp_path / "voice.wav", seconds=2.0)

    class _Result:
        audio_path = tone
        transcript = "Spring Open. Meet recap."

    monkeypatch.setattr("mediahub.visual.voiceover.synthesize", lambda *a, **k: _Result())
    rec = audio_mux.apply_audio(
        video,
        {"voice": "en-GB-SoniaNeural", "script": "Spring Open. Meet recap."},
        duration_sec=1.0,
    )
    assert rec["status"] == "mixed"
    assert rec["voice"] == "en-GB-SoniaNeural"
    assert rec["transcript"] == "Spring Open. Meet recap."
    assert audio_mux.has_audio_stream(video) is True


@pytest.mark.skipif(_FFMPEG is None, reason="no FFmpeg binary available")
def test_real_mux_reel_music_with_beat_accents_and_tempo(tmp_path, monkeypatch):
    """R1.20: a tempo-tagged bed with intro/outro stings + per-cut accents
    muxes for real and produces a playable audio stream (graph is valid)."""
    video = _make_clip(tmp_path / "reel.mp4", seconds=15.0)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    _make_tone(music_dir / "anthem.120bpm.wav", seconds=4.0)  # shorter: must loop
    monkeypatch.setenv("MEDIAHUB_REEL_MUSIC_DIR", str(music_dir))
    monkeypatch.delenv("MEDIAHUB_VOICEOVER", raising=False)

    plan = audio_mux.build_audio_plan(script="", content_key="reel:Spring:3")
    assert plan and plan["music"] == "anthem.120bpm.wav"

    cuts = audio_mux.card_cut_times(15.0, 3)
    rec = audio_mux.apply_audio(video, plan, duration_sec=15.0, cut_times=cuts)
    assert rec["status"] == "mixed"
    assert rec["music_bpm"] == 120.0
    assert rec["beat_aligned_cuts"] == cuts
    assert "ducking" not in rec  # music-only: nothing to duck under
    assert audio_mux.has_audio_stream(video) is True


@pytest.mark.skipif(_FFMPEG is None, reason="no FFmpeg binary available")
def test_real_mux_voice_plus_music_sidechain_ducks(tmp_path, monkeypatch):
    """R1.20: the sidechain-ducked voice+music graph is valid FFmpeg and the
    record advertises the refined ducking."""
    video = _make_clip(tmp_path / "reel.mp4", seconds=15.0)
    voice = _make_tone(tmp_path / "voice.wav", seconds=9.0)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    _make_tone(music_dir / "bed.wav", seconds=4.0)
    monkeypatch.setenv("MEDIAHUB_REEL_MUSIC_DIR", str(music_dir))

    class _Result:
        audio_path = voice
        transcript = "Spring Open. Recap."

    monkeypatch.setattr("mediahub.visual.voiceover.synthesize", lambda *a, **k: _Result())
    plan = {
        "voice": "en-GB-SoniaNeural",
        "script": "Spring Open. Recap.",
        "music": "bed.wav",
        "music_bytes": (music_dir / "bed.wav").stat().st_size,
    }
    rec = audio_mux.apply_audio(
        video, plan, duration_sec=15.0, cut_times=audio_mux.card_cut_times(15.0, 3)
    )
    assert rec["status"] == "mixed"
    assert rec["voice"] == "en-GB-SoniaNeural"
    assert rec["music"] == "bed.wav"
    assert rec["ducking"] == "sidechain"
    assert rec["mix"] == "balanced", "a plan with no mix key records the default profile"
    assert audio_mux.has_audio_stream(video) is True


@pytest.mark.skipif(_FFMPEG is None, reason="no FFmpeg binary available")
def test_real_mux_honours_a_non_default_profile(tmp_path, monkeypatch):
    """R1.19: a voice+music plan carrying ``mix=voice_lead`` muxes for real
    (a lower, harder-ducked bed) and the record reports the applied profile."""
    video = _make_clip(tmp_path / "reel.mp4", seconds=15.0)
    voice = _make_tone(tmp_path / "voice.wav", seconds=9.0)
    music_dir = tmp_path / "music"
    music_dir.mkdir()
    _make_tone(music_dir / "bed.wav", seconds=4.0)
    monkeypatch.setenv("MEDIAHUB_REEL_MUSIC_DIR", str(music_dir))

    class _Result:
        audio_path = voice
        transcript = "Spring Open. Recap."

    monkeypatch.setattr("mediahub.visual.voiceover.synthesize", lambda *a, **k: _Result())
    plan = {
        "voice": "en-GB-SoniaNeural",
        "script": "Spring Open. Recap.",
        "music": "bed.wav",
        "music_bytes": (music_dir / "bed.wav").stat().st_size,
        "mix": "voice_lead",
    }
    rec = audio_mux.apply_audio(
        video, plan, duration_sec=15.0, cut_times=audio_mux.card_cut_times(15.0, 3)
    )
    assert rec["status"] == "mixed"
    assert rec["mix"] == "voice_lead"
    assert rec["ducking"] == "sidechain"
    assert audio_mux.has_audio_stream(video) is True


@pytest.mark.skipif(_FFMPEG is None, reason="no FFmpeg binary available")
def test_real_mux_dub_stamps_provenance(tmp_path, monkeypatch):
    """1.24: a dubbed plan muxes and the manifest labels it AI-dubbed."""
    video = _make_clip(tmp_path / "clip.mp4", seconds=1.0)
    tone = _make_tone(tmp_path / "voice.wav", seconds=1.2)

    class _Result:
        audio_path = tone
        transcript = "Gosododd Hannah PB newydd."

    monkeypatch.setattr("mediahub.visual.voiceover.synthesize", lambda *a, **k: _Result())
    plan = {
        "voice": "cy-GB-NiaNeural",
        "script": "Gosododd Hannah PB newydd.",
        "dubbed": True,
        "dub_source_language": "en",
        "dub_target_language": "cy",
    }
    rec = audio_mux.apply_audio(video, plan, duration_sec=1.0)
    assert rec["status"] == "mixed"
    assert rec["dubbed"] is True
    assert rec["dub_source_language"] == "en"
    assert rec["dub_target_language"] == "cy"
    assert audio_mux.has_audio_stream(video) is True


@pytest.mark.skipif(_FFMPEG is None, reason="no FFmpeg binary available")
def test_real_mux_plain_voice_has_no_dub_provenance(tmp_path, monkeypatch):
    """A non-dubbed voice track must NOT carry dub provenance."""
    video = _make_clip(tmp_path / "clip.mp4", seconds=1.0)
    tone = _make_tone(tmp_path / "voice.wav", seconds=1.2)

    class _Result:
        audio_path = tone
        transcript = "Spring Open. Recap."

    monkeypatch.setattr("mediahub.visual.voiceover.synthesize", lambda *a, **k: _Result())
    rec = audio_mux.apply_audio(
        video, {"voice": "en-GB-SoniaNeural", "script": "Spring Open. Recap."}, duration_sec=1.0
    )
    assert rec["status"] == "mixed"
    assert "dubbed" not in rec
