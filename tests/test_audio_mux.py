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


def test_mux_args_voice_plus_music_mixes_with_fixed_weights(tmp_path):
    args = audio_mux.mux_args(
        tmp_path / "v.mp4",
        tmp_path / "n.mp3",
        tmp_path / "bed.mp3",
        tmp_path / "o.mp4",
        duration_sec=15.0,
    )
    joined = " ".join(args)
    assert f"weights=1 {audio_mux.MUSIC_UNDER_VOICE_WEIGHT}" in joined
    assert "amix=inputs=2" in joined


def test_mux_args_requires_a_source(tmp_path):
    with pytest.raises(ValueError):
        audio_mux.mux_args(tmp_path / "v.mp4", None, None, tmp_path / "o.mp4", duration_sec=5.0)


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
