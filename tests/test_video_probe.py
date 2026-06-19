"""Tests for video.probe — the pure ffmpeg-banner parser (roadmap 1.6).

No FFmpeg binary is required: the parsing is a pure function over the text
FFmpeg prints to stderr, so these run anywhere.
"""

from __future__ import annotations

from mediahub.video.probe import ClipProbe, ProbeUnavailable, parse_ffmpeg_probe, probe_clip

import pytest

# A representative `ffmpeg -i` banner for a portrait phone clip with audio.
_PORTRAIT = """\
Input #0, mov,mp4,m4a,3gp,3g2,mj2, from 'race.mp4':
  Metadata:
    major_brand     : isom
  Duration: 00:00:12.34, start: 0.000000, bitrate: 4200 kb/s
  Stream #0:0(und): Video: h264 (High) (avc1 / 0x31637661), yuv420p, 1080x1920 [SAR 1:1 DAR 9:16], 4000 kb/s, 29.97 fps, 30 tbr, 90k tbn
  Stream #0:1(und): Audio: aac (LC) (mp4a / 0x6134706D), 48000 Hz, stereo, fltp, 128 kb/s
"""

_LANDSCAPE_NOAUDIO = """\
  Duration: 00:01:05.00, start: 0.000000, bitrate: 8000 kb/s
  Stream #0:0: Video: hevc (Main), yuv420p(tv), 1920x1080, 7800 kb/s, 60 fps, 60 tbr
"""

_AUDIO_ONLY = """\
  Duration: 00:00:30.50, start: 0.000000, bitrate: 128 kb/s
  Stream #0:0: Audio: mp3, 44100 Hz, stereo, 128 kb/s
"""

_ROTATED = """\
  Duration: 00:00:08.00, start: 0.000000, bitrate: 4200 kb/s
  Stream #0:0: Video: h264, yuv420p, 1920x1080, 4000 kb/s, 30 fps, 30 tbr
    Side data:
      displaymatrix: rotation of -90.00 degrees
"""


def test_parses_portrait_clip_with_audio():
    p = parse_ffmpeg_probe(_PORTRAIT)
    assert p.duration_ms == 12_340
    assert (p.width, p.height) == (1080, 1920)
    assert p.fps == 29.97
    assert p.has_video and p.has_audio
    assert p.video_codec == "h264"
    assert p.audio_codec == "aac"
    assert p.orientation == "portrait"


def test_parses_landscape_without_audio():
    p = parse_ffmpeg_probe(_LANDSCAPE_NOAUDIO)
    assert p.duration_ms == 65_000
    assert (p.width, p.height) == (1920, 1080)
    assert p.fps == 60.0
    assert p.has_video is True
    assert p.has_audio is False
    assert p.orientation == "landscape"
    assert abs(p.aspect_ratio - (1920 / 1080)) < 1e-6


def test_audio_only_clip_has_no_video_but_real_duration():
    p = parse_ffmpeg_probe(_AUDIO_ONLY)
    assert p.has_video is False
    assert p.has_audio is True
    assert p.duration_ms == 30_500
    assert (p.width, p.height) == (0, 0)
    assert p.orientation == "unknown"


def test_rotation_swaps_display_axes():
    p = parse_ffmpeg_probe(_ROTATED)
    assert p.rotation == 90  # -90 displaymatrix → undo by +90
    # Stored 1920x1080 landscape, but displayed portrait after rotation.
    assert p.display_size == (1080, 1920)
    assert p.orientation == "portrait"


def test_size_not_taken_from_audio_numbers():
    # The audio "48000 Hz" must never be mistaken for a frame dimension.
    p = parse_ffmpeg_probe(_PORTRAIT)
    assert (p.width, p.height) == (1080, 1920)


def test_empty_banner_is_all_defaults():
    p = parse_ffmpeg_probe("")
    assert p == ClipProbe()
    assert p.orientation == "unknown"
    assert p.to_dict()["orientation"] == "unknown"


def test_probe_clip_missing_file_raises(monkeypatch, tmp_path):
    # With a fake ffmpeg present, a missing source is a FileNotFoundError.
    monkeypatch.setattr("mediahub.video.probe.ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    with pytest.raises(FileNotFoundError):
        probe_clip(tmp_path / "nope.mp4")


def test_probe_clip_without_ffmpeg_is_honest(monkeypatch, tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00\x00")
    monkeypatch.setattr("mediahub.video.probe.ffmpeg_exe", lambda: None)
    with pytest.raises(ProbeUnavailable):
        probe_clip(src)
