"""Tests for the 1.8 voice layer wired into visual/voiceover.py.

Covers the new ``params`` (VoiceParams) + ``profile_id`` arguments: prosody
folds into the cache key only when non-default (byte-parity otherwise), the
per-org lexicon joins the pronunciation chain, and the Piper length_scale is
threaded best-effort. Synthesis backends are mocked at the existing seams.
"""

from __future__ import annotations

import io
import wave

from mediahub.audio.voice import OrgLexicon, VoiceParams
from mediahub.visual import voiceover
from mediahub.visual.voiceover import WordBoundary


def _tiny_wav(ms: int = 500, rate: int = 22050) -> bytes:
    n = int(rate * ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n)
    return buf.getvalue()


def test_nondefault_params_get_distinct_cache_and_reach_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "edge")
    calls: list = []

    def _fake(text, voice, params=None):
        calls.append(params)
        return b"AUDIO", [WordBoundary("hi", 0, 100)]

    monkeypatch.setattr(voiceover, "_synthesize_raw", _fake)
    base = voiceover.synthesize("hello world", voice="v1", apply_pronunciation=False)
    fast = voiceover.synthesize(
        "hello world", voice="v1", apply_pronunciation=False, params=VoiceParams.make(rate_pct=25)
    )
    assert base.audio_path.stem != fast.audio_path.stem  # distinct cache entries
    assert calls[0] is None  # default path → 2-arg call, no params
    assert calls[1] is not None and calls[1].rate_pct == 25


def test_default_params_keep_byte_identical_cache_key(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "edge")
    monkeypatch.setattr(
        voiceover, "_synthesize_raw", lambda *a, **k: (b"A", [WordBoundary("hi", 0, 100)])
    )
    res = voiceover.synthesize(
        "hello", voice="v1", apply_pronunciation=False, params=VoiceParams()
    )
    # Default params must not change the historical (text, voice) cache key.
    assert res.audio_path.stem == voiceover.cache_key("hello", voiceover._cache_voice("v1"))


def test_profile_id_applies_org_lexicon(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "edge")
    OrgLexicon("club-x").set("Saoirse", "Seer-sha")
    captured: dict = {}

    def _fake(text, voice):  # default path → 2-arg
        captured["text"] = text
        return b"A", [WordBoundary("hi", 0, 100)]

    monkeypatch.setattr(voiceover, "_synthesize_raw", _fake)
    voiceover.synthesize("Well done Saoirse", voice="v1", profile_id="club-x")
    assert captured["text"] == "Well done Seer-sha"  # org lexicon applied before synthesis


def test_piper_length_scale_threaded(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "piper")
    model = tmp_path / "m.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setenv("MEDIAHUB_PIPER_MODEL", str(model))
    seen: dict = {}

    def _fake_wav(text, model_path, config_path, length_scale=None):
        seen["ls"] = length_scale
        return _tiny_wav(500)

    monkeypatch.setattr(voiceover, "_piper_wav_bytes", _fake_wav)
    monkeypatch.setattr(voiceover, "_wav_to_mp3", lambda b: b"PIPER")
    voiceover.synthesize("hi", apply_pronunciation=False, params=VoiceParams.make(rate_pct=50))
    assert seen["ls"] is not None and seen["ls"] < 1.0  # faster → shorter length_scale


def test_piper_default_keeps_three_arg_seam(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "piper")
    model = tmp_path / "m.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setenv("MEDIAHUB_PIPER_MODEL", str(model))

    # The default path must still call _piper_wav_bytes with the original 3 args.
    def _fake_wav(text, model_path, config_path):
        return _tiny_wav(400)

    monkeypatch.setattr(voiceover, "_piper_wav_bytes", _fake_wav)
    monkeypatch.setattr(voiceover, "_wav_to_mp3", lambda b: b"PIPER")
    res = voiceover.synthesize("hi there", apply_pronunciation=False)
    assert res.cached is False
