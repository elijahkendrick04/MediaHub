"""Tests for video.captions — the editable caption layer transforms (1.6).

The edit transforms are pure dict operations, tested directly. The ASR-backed
builders return None honestly without a backend.
"""

from __future__ import annotations

from mediahub.video.captions import (
    caption_track_from_footage,
    clamp_to_frames,
    cue_count,
    delete_cue,
    edit_cue_text,
    restyle,
    retime_cue,
    shift_track,
    windowed_caption_track,
)


def _track():
    return {
        "color": "#FFFFFF",
        "scrim": "#0A2540",
        "cues": [
            {"from": 0, "dur": 30, "text": "New"},
            {"from": 30, "dur": 30, "text": "PB"},
            {"from": 60, "dur": 30, "text": "for Maria"},
        ],
    }


def test_cue_count():
    assert cue_count(_track()) == 3
    assert cue_count(None) == 0


def test_edit_cue_text_is_immutable():
    t = _track()
    out = edit_cue_text(t, 1, "personal best")
    assert out["cues"][1]["text"] == "personal best"
    assert t["cues"][1]["text"] == "PB"  # original untouched


def test_retime_cue():
    out = retime_cue(_track(), 0, from_frame=10, dur_frames=45)
    assert out["cues"][0]["from"] == 10
    assert out["cues"][0]["dur"] == 45


def test_delete_cue():
    out = delete_cue(_track(), 1)
    assert [c["text"] for c in out["cues"]] == ["New", "for Maria"]


def test_shift_track_clamps_at_zero():
    out = shift_track(_track(), -45)
    # 0 → 0 (clamped), 30 → 0 (clamped), 60 → 15
    assert [c["from"] for c in out["cues"]] == [0, 0, 15]


def test_shift_track_forward():
    out = shift_track(_track(), 15)
    assert [c["from"] for c in out["cues"]] == [15, 45, 75]


def test_restyle_recomputes_legible_colours():
    out = restyle(_track(), ground="#FFFFFF")
    # On a white ground the caption ink must not stay white.
    assert out["color"] != "#FFFFFF"
    assert out["cues"] == _track()["cues"]  # cues unchanged


def test_clamp_to_frames_drops_and_clips():
    out = clamp_to_frames(_track(), 75)
    # cue at 60 keeps but dur clipped to 15; nothing starts >= 75.
    assert all(c["from"] < 75 for c in out["cues"])
    last = out["cues"][-1]
    assert last["from"] == 60 and last["dur"] == 15


def test_clamp_to_frames_drops_out_of_range():
    out = clamp_to_frames(_track(), 45)
    assert [c["text"] for c in out["cues"]] == ["New", "PB"]


def test_caption_track_from_footage_missing_file_is_none(tmp_path):
    assert caption_track_from_footage(tmp_path / "nope.mp4") is None


def test_windowed_caption_track_missing_file_is_none(tmp_path):
    assert windowed_caption_track(tmp_path / "nope.mp4", in_ms=0, out_ms=6000) is None


def test_windowed_caption_track_no_asr_is_none(tmp_path, monkeypatch):
    # ASR not configured → honest None (captions are optional over a render).
    monkeypatch.delenv("MEDIAHUB_ASR_PROVIDER", raising=False)
    clip = tmp_path / "clip.mp4"
    clip.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    assert windowed_caption_track(clip, in_ms=0, out_ms=6000) is None
