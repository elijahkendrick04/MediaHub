"""Tests for video.filler — deterministic filler-word detection (1.6).

The lexicon matcher is pure; the transcribe-backed runner honest-errors to [].
"""

from __future__ import annotations

from mediahub.video import filler
from mediahub.video.filler import find_filler_spans


def test_safe_register_cuts_only_disfluencies():
    words = [("So", 0, 300), ("um", 300, 500), ("we", 500, 800), ("uh", 800, 1000), ("won", 1000, 1400)]
    spans = find_filler_spans(words)
    assert spans == [(300, 500), (800, 1000)]  # um, uh — "So"/"we"/"won" kept


def test_safe_register_leaves_discourse_markers_alone():
    words = [("like", 0, 200), ("you", 200, 400), ("know", 400, 600)]
    assert find_filler_spans(words) == []  # not cut unless aggressive


def test_aggressive_register_cuts_words_and_phrases():
    words = [("like", 0, 200), ("you", 200, 400), ("know", 400, 600), ("we", 600, 900)]
    spans = find_filler_spans(words, aggressive=True)
    assert (0, 200) in spans  # "like"
    assert (200, 600) in spans  # "you know" as one phrase span


def test_longest_phrase_wins():
    words = [("you", 0, 200), ("know", 200, 400), ("what", 400, 600), ("i", 600, 800), ("mean", 800, 1000)]
    spans = find_filler_spans(words, aggressive=True)
    assert spans == [(0, 1000)]  # whole "you know what i mean" as one span


def test_normalisation_strips_surrounding_punctuation():
    assert find_filler_spans([("Um,", 0, 300), ("Uh.", 300, 600)]) == [(0, 300), (300, 600)]


def test_detect_filler_spans_missing_file_is_empty(tmp_path):
    assert filler.detect_filler_spans(tmp_path / "nope.mp4") == []


def test_detect_filler_spans_no_asr_is_empty(monkeypatch, tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"\x00" * 32)

    import mediahub.visual.transcribe as tr

    def boom(*a, **k):
        raise RuntimeError("no ASR provider")

    monkeypatch.setattr(tr, "transcribe_audio", boom)
    assert filler.detect_filler_spans(clip) == []


def test_detect_filler_spans_rebases_to_window(monkeypatch, tmp_path):
    clip = tmp_path / "c.mp4"
    clip.write_bytes(b"\x00" * 32)

    class _W:
        def __init__(self, t, a, b):
            self.text, self.start_ms, self.end_ms = t, a, b

    class _Tr:
        def words(self):
            return [_W("hello", 5000, 5400), _W("um", 5400, 5600)]

        segments = []

    import mediahub.visual.transcribe as tr

    monkeypatch.setattr(tr, "transcribe_audio", lambda *a, **k: _Tr())
    spans = filler.detect_filler_spans(clip, in_ms=5000, out_ms=6000)
    assert spans == [(400, 600)]  # "um" at 5400-5600 rebased to window origin 5000
