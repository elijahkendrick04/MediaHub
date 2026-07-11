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
    merge_tracks,
    offset_track,
    restyle,
    retime_cue,
    retime_track_for_edit,
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


def test_edit_cue_text_drops_stale_karaoke_words():
    """On a karaoke cue the burned line comes from the per-word ``words`` stamps,
    so a text edit must drop the now-mismatched words — otherwise the corrected
    text is silently ignored and the old words stay on screen. caption_render then
    renders the word-less cue as a still line of the new text.
    """
    from mediahub.video.caption_render import _karaoke_line

    t = {
        "style": "karaoke",
        "cues": [
            {
                "from": 0,
                "dur": 30,
                "text": "New PB",
                "words": [
                    {"from": 0, "dur": 15, "text": "New"},
                    {"from": 15, "dur": 15, "text": "PB"},
                ],
            }
        ],
    }
    out = edit_cue_text(t, 0, "New club record")
    assert out["cues"][0]["text"] == "New club record"
    assert "words" not in out["cues"][0]  # stale per-word stamps dropped
    # The renderer now burns the corrected text (word-less cue → still line).
    assert "New club record" in _karaoke_line(out["cues"][0], fps=30)
    assert t["cues"][0].get("words")  # original track untouched


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


def test_offset_track_shifts_cues_and_karaoke_words():
    t = {
        "color": "#FFF",
        "scrim": "#000",
        "style": "karaoke",
        "cues": [
            {"from": 10, "dur": 30, "text": "hi", "words": [{"from": 12, "dur": 8, "text": "hi"}]}
        ],
    }
    out = offset_track(t, 60)
    assert out["cues"][0]["from"] == 70
    assert out["cues"][0]["words"][0]["from"] == 72  # the word stamp moves too
    assert t["cues"][0]["from"] == 10  # original untouched


def test_offset_track_clamps_at_zero():
    t = {"cues": [{"from": 5, "dur": 10, "text": "x"}]}
    assert offset_track(t, -50)["cues"][0]["from"] == 0


def test_merge_tracks_concatenates_and_takes_first_style():
    a = {
        "color": "#AAA",
        "scrim": "#111",
        "style": "karaoke",
        "cues": [{"from": 0, "dur": 10, "text": "a"}],
    }
    b = {"color": "#BBB", "scrim": "#222", "cues": [{"from": 100, "dur": 10, "text": "b"}]}
    merged = merge_tracks([a, None, b])
    assert [c["text"] for c in merged["cues"]] == ["a", "b"]
    assert merged["color"] == "#AAA" and merged["style"] == "karaoke"  # first track's style


def test_merge_tracks_none_when_nothing_to_merge():
    assert merge_tracks([None, {}, {"cues": []}]) is None


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


# --- animated (karaoke) captions ------------------------------------------

from dataclasses import dataclass  # noqa: E402

from mediahub.video import captions as _captions  # noqa: E402
from mediahub.video.caption_render import (  # noqa: E402
    ass_for_track,
    is_karaoke,
    karaoke_ass_document,
)
from mediahub.visual.subtitle_burn import ass_document  # noqa: E402


def test_is_karaoke_flag():
    assert is_karaoke({"style": "karaoke", "cues": []})
    assert not is_karaoke({"cues": []})
    assert not is_karaoke(None)


def test_static_dispatch_is_byte_identical_to_shared_renderer():
    # The static path must not diverge from subtitle_burn — the reel engine
    # shares it, so any drift would change reel output.
    t = {"color": "#FFFFFF", "scrim": "#0A2540", "cues": [{"from": 0, "dur": 30, "text": "New PB"}]}
    assert ass_for_track(t, width=1080, height=1920, fps=30) == ass_document(
        t, width=1080, height=1920, fps=30
    )


def test_karaoke_document_emits_kf_per_word():
    track = {
        "color": "#FFFFFF",
        "scrim": "#0A2540",
        "accent": "#22D3EE",
        "style": "karaoke",
        "cues": [
            {
                "from": 0,
                "dur": 60,
                "text": "new club record",
                "words": [
                    {"from": 0, "dur": 20, "text": "new"},
                    {"from": 20, "dur": 20, "text": "club"},
                    {"from": 40, "dur": 20, "text": "record"},
                ],
            }
        ],
    }
    doc = karaoke_ass_document(track, width=1080, height=1920, fps=30)
    assert doc.count("\\kf") == 3
    assert "new" in doc and "record" in doc
    assert "[V4+ Styles]" in doc and "Dialogue:" in doc


def test_karaoke_falls_back_to_still_line_without_words():
    track = {"style": "karaoke", "cues": [{"from": 0, "dur": 30, "text": "no words"}]}
    doc = karaoke_ass_document(track, width=1080, height=1920, fps=30)
    assert "no words" in doc and "\\kf" not in doc


@dataclass
class _Word:
    text: str
    start_ms: int
    end_ms: int


class _FakeTranscript:
    def __init__(self, words):
        self._words = words
        self.segments = []

    def words(self):
        return self._words


def _patch_transcribe(monkeypatch, words):
    import mediahub.visual.transcribe as tr

    monkeypatch.setattr(tr, "transcribe_audio", lambda *a, **k: _FakeTranscript(words))


def test_windowed_karaoke_track_builds_word_timed_cues(monkeypatch, tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00" * 64)
    _patch_transcribe(
        monkeypatch,
        [_Word("new", 0, 400), _Word("club", 400, 800), _Word("record", 800, 1200)],
    )
    track = _captions.windowed_karaoke_track(
        src, in_ms=0, out_ms=2000, fps=30, ground="#0A2540", accent="#22D3EE"
    )
    assert track is not None and track["style"] == "karaoke" and track["accent"] == "#22D3EE"
    cue = track["cues"][0]
    assert cue["words"] and all("from" in w and "dur" in w and "text" in w for w in cue["words"])
    assert " ".join(w["text"] for w in cue["words"]) == "new club record"


def test_windowed_karaoke_falls_back_to_static_without_word_timing(monkeypatch, tmp_path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00" * 64)
    _patch_transcribe(monkeypatch, [])  # no word-level timing
    called = {}

    def fake_static(*a, **k):
        called["yes"] = True
        return {"color": "#fff", "scrim": "#000", "cues": [{"from": 0, "dur": 10, "text": "hi"}]}

    monkeypatch.setattr(_captions, "windowed_caption_track", fake_static)
    track = _captions.windowed_karaoke_track(src, in_ms=0, out_ms=2000)
    assert called.get("yes") and track.get("style") != "karaoke"


# --- F-14: re-time captions when clips are reordered / trimmed / deleted -------


def _desc(source, offset_ms, in_ms, out_ms):
    return {"source": source, "offset_ms": offset_ms, "in_ms": in_ms, "out_ms": out_ms}


def _two_clip_track():
    # 30fps; clip A [a.mp4] at timeline 0 (frames 0..89), clip B [b.mp4] at 3000ms
    # (frame 90..179). One cue sits in each clip.
    return {
        "color": "#FFFFFF",
        "scrim": "#0A2540",
        "cues": [
            {"from": 10, "dur": 20, "text": "clip A line"},
            {"from": 100, "dur": 20, "text": "clip B line"},  # local frame 10 of B
        ],
    }


def _AB_old():
    return [_desc("a.mp4", 0, 0, 3000), _desc("b.mp4", 3000, 0, 3000)]


def test_retime_unchanged_structure_is_noop():
    track = _two_clip_track()
    out = retime_track_for_edit(track, _AB_old(), _AB_old(), fps=30)
    assert out["cues"] == track["cues"]  # identity mapping → byte-identical cues


def test_retime_follows_reordered_clips():
    # Swap the order: B first (timeline 0), A second (timeline 3000).
    new = [_desc("b.mp4", 0, 0, 3000), _desc("a.mp4", 3000, 0, 3000)]
    out = retime_track_for_edit(_two_clip_track(), _AB_old(), new, fps=30)
    by_text = {c["text"]: c["from"] for c in out["cues"]}
    assert by_text["clip B line"] == 10  # B now at the front
    assert by_text["clip A line"] == 100  # A now second (offset 90 + local 10)


def test_retime_drops_cues_of_deleted_clip():
    # Delete clip A; only B survives, now at timeline 0.
    new = [_desc("b.mp4", 0, 0, 3000)]
    out = retime_track_for_edit(_two_clip_track(), _AB_old(), new, fps=30)
    assert [c["text"] for c in out["cues"]] == ["clip B line"]
    assert out["cues"][0]["from"] == 10  # re-based to B's new front position


def test_retime_shifts_on_head_trim_and_drops_trimmed_words():
    # Trim clip A's head forward by 500ms (15 frames @30fps). The cue at local
    # frame 10 is now before the kept content → dropped; a later cue survives shifted.
    track = {
        "color": "#FFF",
        "scrim": "#000",
        "cues": [
            {"from": 10, "dur": 10, "text": "trimmed away"},  # local 10 < 15 → gone
            {"from": 40, "dur": 10, "text": "kept"},  # local 40 → new local 25
        ],
    }
    old = [_desc("a.mp4", 0, 0, 3000)]
    new = [_desc("a.mp4", 0, 500, 3000)]
    out = retime_track_for_edit(track, old, new, fps=30)
    assert [c["text"] for c in out["cues"]] == ["kept"]
    assert out["cues"][0]["from"] == 25  # 40 - 15 head-trim frames


def test_retime_karaoke_words_ride_the_shift():
    track = {
        "color": "#FFF",
        "scrim": "#000",
        "style": "karaoke",
        "cues": [
            {
                "from": 100,
                "dur": 30,
                "text": "go team",
                "words": [
                    {"from": 100, "dur": 15, "text": "go"},
                    {"from": 115, "dur": 15, "text": "team"},
                ],
            }
        ],
    }
    old = [_desc("a.mp4", 0, 0, 3000), _desc("b.mp4", 3000, 0, 3000)]
    new = [_desc("b.mp4", 0, 0, 3000), _desc("a.mp4", 3000, 0, 3000)]  # B to front
    out = retime_track_for_edit(track, old, new, fps=30)
    cue = out["cues"][0]
    assert cue["from"] == 10  # B moved to timeline 0, cue local 10
    assert [w["from"] for w in cue["words"]] == [10, 25]  # words re-based too


def test_retime_returns_none_when_all_cues_drop():
    # The only cue's clip was deleted and nothing else carries captions.
    track = {"color": "#FFF", "scrim": "#000", "cues": [{"from": 100, "dur": 10, "text": "gone"}]}
    old = [_desc("a.mp4", 0, 0, 3000), _desc("b.mp4", 3000, 0, 3000)]
    new = [_desc("a.mp4", 0, 0, 3000)]  # dropped B, whose window held the cue
    assert retime_track_for_edit(track, old, new, fps=30) is None
