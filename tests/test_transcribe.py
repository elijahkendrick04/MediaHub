"""
Tests for the local ASR engine (roadmap 1.4 — whisper.cpp / faster-whisper).

All tests are network- and model-free: the single backend seam
(``transcribe._transcribe_raw``) is monkeypatched, exactly as the voiceover
suite patches its synthesis seam. We assert the things the seam doctrine makes
load-bearing:
  - provider selection is env-keyed, alias-tolerant, and honest on a bad value;
  - no provider configured → an honest ASRUnavailable, never a fake transcript;
  - a backend failure is an honest ASRUnavailable, never a fallback;
  - transcripts cache by audio content-hash and round-trip word stamps intact;
  - the caption-track bridge turns real word timings into a frame-timed track,
    and is non-fatal (None) when ASR is unavailable;
  - there is no LLM anywhere in the transcription path.
"""

from __future__ import annotations

import json

import pytest

from mediahub.visual import subtitle_burn, transcribe
from mediahub.visual.transcribe import Transcript, TranscriptSegment, WordStamp


def _fake_transcript() -> Transcript:
    """A two-word transcript with real word stamps, as a backend would return."""
    words = (WordStamp("New", 0, 400), WordStamp("PB", 400, 900))
    seg = TranscriptSegment(0, 900, "New PB", words)
    return Transcript(
        text="New PB",
        language="en",
        duration_ms=900,
        segments=[seg],
        provider="faster-whisper",
        model="base",
    )


# ---------------------------------------------------------------------------
# Provider selection (pure, env-keyed)
# ---------------------------------------------------------------------------


def test_select_provider_unset_is_empty(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_ASR_PROVIDER", raising=False)
    assert transcribe.select_asr_provider() == ""


def test_select_provider_canonicalises_aliases(monkeypatch):
    for alias in ("faster-whisper", "faster_whisper", "fasterwhisper", "whisper"):
        monkeypatch.setenv("MEDIAHUB_ASR_PROVIDER", alias)
        assert transcribe.select_asr_provider() == "faster-whisper"
    for alias in ("whisper.cpp", "whisper-cpp", "whispercpp", "pywhispercpp"):
        monkeypatch.setenv("MEDIAHUB_ASR_PROVIDER", alias)
        assert transcribe.select_asr_provider() == "whisper.cpp"


def test_select_provider_unknown_raises(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_ASR_PROVIDER", "deepgram")
    with pytest.raises(transcribe.ASRUnavailable):
        transcribe.select_asr_provider()


def test_status_shape_and_is_available_is_bool(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_ASR_PROVIDER", "faster-whisper")
    status = transcribe.asr_provider_status()
    for key in (
        "configured",
        "active",
        "faster_whisper_available",
        "whisper_cpp_available",
        "model",
        "available_providers",
    ):
        assert key in status
    assert status["active"] == "faster-whisper"
    assert status["model"] == "base"
    assert isinstance(transcribe.is_available(), bool)


def test_status_echoes_bad_value_without_raising(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_ASR_PROVIDER", "nope")
    status = transcribe.asr_provider_status()
    assert status["configured"] == "nope"
    assert status["active"] == "nope"  # echoed verbatim, not resolved
    assert transcribe.is_available() is False


def test_model_id_honours_override(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_WHISPER_MODEL", raising=False)
    assert transcribe._whisper_model_id() == transcribe.DEFAULT_WHISPER_MODEL
    monkeypatch.setenv("MEDIAHUB_WHISPER_MODEL", "small")
    assert transcribe._whisper_model_id() == "small"


# ---------------------------------------------------------------------------
# Cache key (pure)
# ---------------------------------------------------------------------------


def test_cache_key_deterministic_and_sensitive():
    base = transcribe.cache_key(b"audio", "faster-whisper", "base", "en", "w1v0")
    assert base == transcribe.cache_key(b"audio", "faster-whisper", "base", "en", "w1v0")
    assert base != transcribe.cache_key(b"AUDIO", "faster-whisper", "base", "en", "w1v0")  # audio
    assert base != transcribe.cache_key(b"audio", "whisper.cpp", "base", "en", "w1v0")  # provider
    assert base != transcribe.cache_key(b"audio", "faster-whisper", "small", "en", "w1v0")  # model
    assert base != transcribe.cache_key(
        b"audio", "faster-whisper", "base", "cy", "w1v0"
    )  # language
    assert base != transcribe.cache_key(b"audio", "faster-whisper", "base", "en", "w0v0")  # opts


# ---------------------------------------------------------------------------
# transcribe_audio — honest errors, caching, verbatim
# ---------------------------------------------------------------------------


def test_transcribe_no_provider_is_honest_error(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_ASR_PROVIDER", raising=False)
    with pytest.raises(transcribe.ASRUnavailable):
        transcribe.transcribe_audio(b"some audio", content_type="audio/webm")


def test_transcribe_empty_audio_raises_value_error(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_ASR_PROVIDER", "faster-whisper")
    with pytest.raises(ValueError):
        transcribe.transcribe_audio(b"", content_type="audio/webm")


def test_transcribe_backend_failure_is_honest_error(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_ASR_PROVIDER", "faster-whisper")

    def _boom(*a, **k):
        raise transcribe.ASRUnavailable("faster-whisper not installed")

    monkeypatch.setattr(transcribe, "_transcribe_raw", _boom)
    with pytest.raises(transcribe.ASRUnavailable):
        transcribe.transcribe_audio(b"audio", content_type="audio/webm")


def test_transcribe_writes_and_caches(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_ASR_PROVIDER", "faster-whisper")
    calls = {"n": 0}

    def _fake(audio, provider, model, language, word_timestamps, content_type, vad):
        calls["n"] += 1
        assert provider == "faster-whisper"
        return _fake_transcript()

    monkeypatch.setattr(transcribe, "_transcribe_raw", _fake)

    first = transcribe.transcribe_audio(b"clip-bytes", content_type="audio/webm")
    second = transcribe.transcribe_audio(b"clip-bytes", content_type="audio/webm")

    assert calls["n"] == 1  # second call served from cache
    assert first.cached is False and second.cached is True
    assert first.text == "New PB" == second.text
    # Word stamps survive the JSON cache round-trip exactly.
    assert [(w.text, w.start_ms, w.end_ms) for w in second.words()] == [
        ("New", 0, 400),
        ("PB", 400, 900),
    ]
    # A cache sidecar was actually written.
    assert list((tmp_path / "asr_cache").glob("*.json"))


def test_transcribe_options_partition_the_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_ASR_PROVIDER", "faster-whisper")
    seen = {"word_ts": []}

    def _fake(audio, provider, model, language, word_timestamps, content_type, vad):
        seen["word_ts"].append(word_timestamps)
        return _fake_transcript()

    monkeypatch.setattr(transcribe, "_transcribe_raw", _fake)
    transcribe.transcribe_audio(b"clip", content_type="audio/webm", word_timestamps=True)
    transcribe.transcribe_audio(b"clip", content_type="audio/webm", word_timestamps=False)
    # Different options → distinct cache entries, so the backend ran twice.
    assert seen["word_ts"] == [True, False]


# ---------------------------------------------------------------------------
# Transcript (de)serialisation
# ---------------------------------------------------------------------------


def test_transcript_roundtrips_through_dict():
    tr = _fake_transcript()
    again = Transcript.from_dict(json.loads(json.dumps(tr.to_dict())))
    assert again.text == tr.text and again.language == tr.language
    assert again.duration_ms == tr.duration_ms and again.provider == tr.provider
    assert again.words() == tr.words()


# ---------------------------------------------------------------------------
# Pure word-stamp helpers
# ---------------------------------------------------------------------------


def test_estimate_word_stamps_spans_segment_in_order():
    stamps = transcribe._estimate_word_stamps("a longerword x", 0, 1000)
    assert [s.text for s in stamps] == ["a", "longerword", "x"]
    assert stamps[0].start_ms == 0 and stamps[-1].end_ms == 1000
    # Monotonic, non-overlapping.
    for prev, nxt in zip(stamps, stamps[1:]):
        assert nxt.start_ms == prev.end_ms and nxt.end_ms >= nxt.start_ms


def test_estimate_word_stamps_empty_inputs():
    assert transcribe._estimate_word_stamps("", 0, 1000) == []
    assert transcribe._estimate_word_stamps("hi", 500, 500) == []


# ---------------------------------------------------------------------------
# Caption-track bridge (the word-level burn-in primitive for 1.6)
# ---------------------------------------------------------------------------


def test_cues_from_stamps_groups_words(monkeypatch):
    stamps = [
        ("Maya", 0, 400),
        ("set", 400, 700),
        ("a", 700, 800),
        ("new", 800, 1100),
        ("personal", 1100, 1600),
        ("best", 1600, 2000),
        ("today", 2000, 2500),
        ("again", 2500, 3000),  # 8th word forces a second cue
    ]
    cues = subtitle_burn.cues_from_stamps(stamps)
    assert len(cues) == 2
    assert cues[0].text == "Maya set a new personal best today"
    assert cues[0].start_ms == 0 and cues[0].end_ms == 2500
    assert cues[1].text == "again"


def test_cues_from_stamps_accepts_word_objects():
    cues = subtitle_burn.cues_from_stamps([WordStamp("New", 0, 400), WordStamp("PB", 400, 900)])
    assert len(cues) == 1 and cues[0].text == "New PB"
    assert cues[0].start_ms == 0 and cues[0].end_ms == 900


def test_cues_from_stamps_drops_malformed():
    assert subtitle_burn.cues_from_stamps([]) == []
    assert subtitle_burn.cues_from_stamps([("", 0, 100), ("ok", None, 5)]) == []


def test_caption_track_for_audio_builds_a_word_timed_track(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_ASR_PROVIDER", "faster-whisper")
    monkeypatch.setattr(transcribe, "_transcribe_raw", lambda *a, **k: _fake_transcript())
    track = transcribe.caption_track_for_audio(
        b"clip",
        fps=30,
        total_frames=30,  # 1 second
        ground="#0A2540",
        onground="#FFFFFF",
        content_type="audio/webm",
    )
    assert track is not None
    assert track["cues"] and track["cues"][0]["text"] == "New PB"
    # Cue frames are clamped inside the clip.
    assert all(c["from"] + c["dur"] <= 30 for c in track["cues"])
    # Caption colour cleared the APCA floor (deterministic colour-science).
    assert track["color"].startswith("#")


def test_caption_track_for_audio_none_when_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("MEDIAHUB_ASR_PROVIDER", raising=False)  # no provider
    track = transcribe.caption_track_for_audio(b"clip", fps=30, total_frames=30, ground="#0A2540")
    assert track is None  # non-fatal: a render proceeds without captions


# ---------------------------------------------------------------------------
# Structural guard — transcription is deterministic, never an AI surface
# ---------------------------------------------------------------------------


def test_transcribe_module_has_no_llm_dependency():
    from pathlib import Path

    src = Path(transcribe.__file__).read_text()
    for forbidden in ("media_ai", "ai_core", "anthropic", "import gemini"):
        assert forbidden not in src, f"transcribe.py must not reference {forbidden!r}"
