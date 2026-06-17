"""
Tests for the deterministic voiceover layer (council build for Pixelle-Video).

All tests are network-free: the one online seam (`voiceover._synthesize_raw`) is
monkeypatched. We assert the things the council ruling made load-bearing:
  - the spoken text is the approved caption, verbatim (no LLM in the path);
  - pronunciation overrides are deterministic;
  - honest-error (VoiceoverError) when the backend is unavailable — no fallback;
  - caching avoids re-synthesis;
  - the route is an audio approval gate (disabled→503, not-approved→409).
"""
from __future__ import annotations

import importlib
import importlib.util
import io
import json
import wave
from pathlib import Path

import pytest

from mediahub.visual import pronunciation, voiceover
from mediahub.visual.voiceover import WordBoundary


def _tiny_wav(duration_ms: int, rate: int = 22050) -> bytes:
    """A valid mono 16-bit PCM WAV of ``duration_ms`` — the shape Piper emits,
    used to drive the mocked Piper seam without the real model/onnxruntime."""
    n_frames = int(rate * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# pronunciation.py — deterministic, no AI
# ---------------------------------------------------------------------------

def test_apply_overrides_empty_map_is_identity():
    assert pronunciation.apply_overrides("Maya Smith", {}) == "Maya Smith"
    assert pronunciation.apply_overrides("", {"a": "b"}) == ""


def test_apply_overrides_whole_word_case_insensitive():
    out = pronunciation.apply_overrides("Well done MAYA, maya!", {"Maya": "My-ah"})
    assert out == "Well done My-ah, My-ah!"


def test_apply_overrides_does_not_touch_substrings():
    # "Lee" must not rewrite "Leeds".
    out = pronunciation.apply_overrides("Lee swam at Leeds", {"Lee": "Ligh"})
    assert out == "Ligh swam at Leeds"


def test_apply_overrides_longest_key_wins():
    out = pronunciation.apply_overrides(
        "Mary Anne won", {"Mary": "Mairee", "Mary Anne": "Mary-Ann"}
    )
    assert out == "Mary-Ann won"


def test_load_overrides_absent_returns_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    assert pronunciation.load_overrides("run1") == {}


def test_load_overrides_merges_global_and_per_run(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    runs = tmp_path / "runs_v4"
    runs.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("RUNS_DIR", str(runs))
    (tmp_path / "pronunciations.json").write_text(json.dumps({"Maya": "Global"}))
    (runs / "run1__pronunciations.json").write_text(json.dumps({"Maya": "PerRun"}))
    merged = pronunciation.load_overrides("run1")
    assert merged["Maya"] == "PerRun"  # per-run wins


def test_load_overrides_tolerates_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    (tmp_path / "pronunciations.json").write_text("{not json")
    assert pronunciation.load_overrides() == {}


# ---------------------------------------------------------------------------
# voiceover.py — cache key + SRT building (pure)
# ---------------------------------------------------------------------------

def test_cache_key_is_deterministic_and_sensitive():
    a = voiceover.cache_key("hello", "v1")
    assert a == voiceover.cache_key("hello", "v1")
    assert a != voiceover.cache_key("hello!", "v1")  # text-sensitive
    assert a != voiceover.cache_key("hello", "v2")   # voice-sensitive


def test_build_srt_empty_is_empty_string():
    assert voiceover.build_srt([]) == ""


def test_build_srt_formats_and_groups():
    bounds = [
        WordBoundary("Maya", 0, 500),
        WordBoundary("set", 500, 300),
        WordBoundary("a", 800, 100),
        WordBoundary("new", 900, 300),
        WordBoundary("personal", 1200, 500),
        WordBoundary("best", 1700, 400),
        WordBoundary("today", 2100, 500),
        WordBoundary("again", 2600, 500),  # 8th word -> forces a new cue
    ]
    srt = voiceover.build_srt(bounds)
    assert srt.startswith("1\n")
    assert "00:00:00,000 -->" in srt
    # First cue holds the first 7 words; "again" spills to cue 2.
    assert "Maya set a new personal best today" in srt
    assert "\n2\n" in srt
    assert srt.endswith("\n")


def test_build_srt_breaks_on_time_window():
    bounds = [
        WordBoundary("one", 0, 200),
        WordBoundary("two", 4000, 200),  # >3s gap -> new cue
    ]
    srt = voiceover.build_srt(bounds)
    assert "1\n" in srt and "2\n" in srt


# ---------------------------------------------------------------------------
# voiceover.synthesize — honest error, verbatim, caching
# ---------------------------------------------------------------------------

def test_synthesize_empty_text_raises_value_error(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with pytest.raises(ValueError):
        voiceover.synthesize("   ")


def test_synthesize_honest_error_when_backend_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    def _boom(text, voice):
        raise voiceover.VoiceoverError("edge-tts not installed")

    monkeypatch.setattr(voiceover, "_synthesize_raw", _boom)
    with pytest.raises(voiceover.VoiceoverError):
        voiceover.synthesize("Maya set a new PB")


def test_synthesize_writes_artifacts_and_is_verbatim(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    captured = {}

    def _fake(text, voice):
        captured["text"] = text
        captured["voice"] = voice
        return b"ID3fakeaudio", [WordBoundary("Maya", 0, 500), WordBoundary("PB", 500, 400)]

    monkeypatch.setattr(voiceover, "_synthesize_raw", _fake)
    res = voiceover.synthesize("Maya new PB", voice="en-GB-SoniaNeural", apply_pronunciation=False)

    assert res.cached is False
    assert res.transcript == "Maya new PB"      # verbatim
    assert captured["text"] == "Maya new PB"     # exactly what was passed to the engine
    assert res.audio_path.exists() and res.audio_path.read_bytes() == b"ID3fakeaudio"
    assert res.srt_path.exists() and "Maya PB" in res.srt_path.read_text()
    assert res.duration_ms == 900


def test_synthesize_cache_hit_skips_resynthesis(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    calls = {"n": 0}

    def _fake(text, voice):
        calls["n"] += 1
        return b"audio", [WordBoundary("hi", 0, 100)]

    monkeypatch.setattr(voiceover, "_synthesize_raw", _fake)
    first = voiceover.synthesize("hello world", apply_pronunciation=False)
    second = voiceover.synthesize("hello world", apply_pronunciation=False)
    assert calls["n"] == 1
    assert first.cached is False and second.cached is True
    assert second.transcript == "hello world"


def test_synthesize_applies_pronunciation_before_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    (tmp_path / "pronunciations.json").write_text(json.dumps({"Siobhan": "Shiv-awn"}))
    captured = {}

    def _fake(text, voice):
        captured["text"] = text
        return b"a", [WordBoundary("x", 0, 100)]

    monkeypatch.setattr(voiceover, "_synthesize_raw", _fake)
    res = voiceover.synthesize("Well done Siobhan", apply_pronunciation=True)
    assert captured["text"] == "Well done Shiv-awn"
    assert res.transcript == "Well done Shiv-awn"


def test_voiceover_module_has_no_llm_dependency():
    """Structural guard: the verbatim path must never reach an LLM/AI surface."""
    src = Path(voiceover.__file__).read_text()
    for forbidden in ("media_ai", "ai_core", "anthropic", "gemini", "import llm"):
        assert forbidden not in src, f"voiceover.py must not reference {forbidden!r}"


def test_is_available_returns_bool():
    assert isinstance(voiceover.is_available(), bool)


# ---------------------------------------------------------------------------
# Route — the audio approval gate
# ---------------------------------------------------------------------------

@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("MEDIAHUB_VOICEOVER", "1")

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, tmp_path, monkeypatch


def _seed_run(tmp_path: Path, run_id: str = "runV"):
    run_dir = tmp_path / "runs_v4" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "run.json").write_text(json.dumps({
        "recognition_report": {
            "ranked_achievements": [
                {"id": "c1", "achievement": {"swim_id": "c1",
                 "active_caption": {"headline": "Maya Smith — new PB", "body": "2:01.34, 200 Free."}}},
                {"id": "c2", "achievement": {"swim_id": "c2",
                 "active_caption": {"headline": "Other swim", "body": "Nice race."}}},
            ]
        }
    }))
    return run_id


def test_route_disabled_returns_503(app_env):
    app, wm, tmp_path, monkeypatch = app_env
    monkeypatch.delenv("MEDIAHUB_VOICEOVER", raising=False)
    run_id = _seed_run(tmp_path)
    with app.test_client() as c:
        resp = c.get(f"/api/runs/{run_id}/card/c1/voiceover")
    assert resp.status_code == 503
    assert resp.get_json()["error"] == "voiceover_disabled"


def test_route_missing_run_returns_404(app_env):
    app, wm, tmp_path, monkeypatch = app_env
    with app.test_client() as c:
        resp = c.get("/api/runs/nope/card/c1/voiceover")
    assert resp.status_code == 404


def test_route_unapproved_card_returns_409(app_env):
    app, wm, tmp_path, monkeypatch = app_env
    run_id = _seed_run(tmp_path)
    with app.test_client() as c:
        resp = c.get(f"/api/runs/{run_id}/card/c1/voiceover")
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "not_approved"


def test_route_approved_card_synthesizes(app_env):
    app, wm, tmp_path, monkeypatch = app_env
    run_id = _seed_run(tmp_path)

    # Approve c1 with an explicit edited caption (robust regardless of _v73 import).
    from mediahub.workflow.store import WorkflowStore
    from mediahub.workflow.status import CardStatus
    ws = WorkflowStore(Path(tmp_path / "runs_v4"))
    ws.set_edits(run_id, "c1", {"warm-club_headline": "Maya Smith set a new personal best"})
    ws.set_status(run_id, "c1", CardStatus.APPROVED)

    # Stub the online synthesis seam on the module the app imported.
    def _fake(text, voice):
        return b"ID3audio", [WordBoundary("Maya", 0, 500)]
    monkeypatch.setattr(wm._voiceover, "_synthesize_raw", _fake)

    with app.test_client() as c:
        resp = c.get(f"/api/runs/{run_id}/card/c1/voiceover?format=json")
    assert resp.status_code == 200, resp.get_data(as_text=True)
    body = resp.get_json()
    assert body["ok"] is True
    assert "personal best" in body["transcript"]

    # And the audio bytes are served by default.
    with app.test_client() as c:
        audio = c.get(f"/api/runs/{run_id}/card/c1/voiceover")
    assert audio.status_code == 200
    assert audio.mimetype == "audio/mpeg"


# ---------------------------------------------------------------------------
# TTS provider seam (P0.4) — a local-capable slot for the speech surface
# ---------------------------------------------------------------------------


def test_tts_provider_defaults_to_edge(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_TTS_PROVIDER", raising=False)
    assert voiceover.select_tts_provider() == "edge"


def test_tts_provider_blank_means_edge(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "  ")
    assert voiceover.select_tts_provider() == "edge"


def test_tts_provider_piper_is_a_recognised_slot(monkeypatch):
    """The local slot must be selectable — that is the P0.4 contract: the
    interface admits a local provider even before P5.2 implements it."""
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "PIPER")
    assert voiceover.select_tts_provider() == "piper"


def test_tts_provider_unknown_raises_honest_error(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "espeak")
    with pytest.raises(voiceover.VoiceoverError, match="not a recognised"):
        voiceover.select_tts_provider()


def test_piper_synthesis_raises_honest_error_when_model_absent(tmp_path, monkeypatch):
    """Selecting piper with no voice model configured must produce a clear
    operator error naming Piper — never a silent fallback to the cloud
    backend, never a fabricated clip (the R1.21 honest-error contract)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "piper")
    for var in ("MEDIAHUB_PIPER_MODEL", "MEDIAHUB_PIPER_VOICE", "MEDIAHUB_PIPER_VOICE_DIR"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(voiceover.VoiceoverError, match="[Pp]iper"):
        voiceover.synthesize("A real caption", apply_pronunciation=False)


def test_is_available_false_for_piper_when_unconfigured(monkeypatch):
    """With piper selected but no model/package present (the dev + CI default),
    availability is honestly False — the route 503s rather than attempting a
    render that would fail."""
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "piper")
    for var in ("MEDIAHUB_PIPER_MODEL", "MEDIAHUB_PIPER_VOICE"):
        monkeypatch.delenv(var, raising=False)
    assert voiceover.is_available() is False


def test_is_available_false_for_bad_provider(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "espeak")
    assert voiceover.is_available() is False


def test_tts_provider_status_shape(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_TTS_PROVIDER", raising=False)
    status = voiceover.tts_provider_status()
    required = {
        "configured",
        "active",
        "edge_available",
        "piper_available",
        "piper_model",
        "available_providers",
    }
    assert required <= set(status.keys())
    assert status["active"] == "edge"
    assert status["piper_available"] is False
    assert isinstance(status["piper_model"], str)


def test_tts_provider_status_surfaces_bad_value_verbatim(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "espeak")
    status = voiceover.tts_provider_status()
    assert status["configured"] == "espeak"
    assert status["active"] == "espeak"


# ---------------------------------------------------------------------------
# Piper backend (R1.21) — zero-cost local TTS behind the voiceover seam
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _clear_piper_env(monkeypatch):
    """Each test starts from a clean Piper config — no stray model leaks in."""
    for var in (
        "MEDIAHUB_PIPER_MODEL",
        "MEDIAHUB_PIPER_VOICE",
        "MEDIAHUB_PIPER_VOICE_DIR",
        "MEDIAHUB_PIPER_CONFIG",
        "MEDIAHUB_FFMPEG",
    ):
        monkeypatch.delenv(var, raising=False)


# --- word-boundary estimation (pure, deterministic) ------------------------


def test_estimate_word_boundaries_proportional_and_exact():
    bounds = voiceover._estimate_word_boundaries("Maya new PB", 900)
    assert [(b.text, b.offset_ms, b.duration_ms) for b in bounds] == [
        ("Maya", 0, 400),  # len 4 of 9 -> 400ms
        ("new", 400, 300),  # len 3 of 9 -> 300ms
        ("PB", 700, 200),  # len 2 of 9 -> 200ms
    ]
    # The clip is fully consumed: the last word ends exactly at total_ms.
    assert bounds[-1].offset_ms + bounds[-1].duration_ms == 900
    # Deterministic.
    assert voiceover._estimate_word_boundaries("Maya new PB", 900) == bounds


def test_estimate_word_boundaries_empty_or_zero_duration():
    assert voiceover._estimate_word_boundaries("", 900) == []
    assert voiceover._estimate_word_boundaries("   ", 900) == []
    assert voiceover._estimate_word_boundaries("hello world", 0) == []
    assert voiceover._estimate_word_boundaries("hello world", -5) == []


def test_estimate_word_boundaries_punctuation_token_still_advances():
    # A punctuation-only token has weight floored to 1 (never zero-width).
    bounds = voiceover._estimate_word_boundaries("Go — win", 300)
    assert len(bounds) == 3
    assert all(b.duration_ms >= 1 for b in bounds)
    assert bounds[-1].offset_ms + bounds[-1].duration_ms == 300


def test_estimate_word_boundaries_feed_real_srt():
    # The estimates flow through the existing SRT builder unchanged.
    bounds = voiceover._estimate_word_boundaries(
        "Maya Smith set a brand new personal best today", 4200
    )
    srt = voiceover.build_srt(bounds)
    assert srt.startswith("1\n")
    assert "today" in srt


# --- model resolution ------------------------------------------------------


def test_resolve_piper_model_unconfigured_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert voiceover._resolve_piper_model() is None


def test_resolve_piper_model_explicit_path_with_config_sibling(tmp_path, monkeypatch):
    model = tmp_path / "en_GB-alba-medium.onnx"
    model.write_bytes(b"onnx")
    cfg = tmp_path / "en_GB-alba-medium.onnx.json"
    cfg.write_text("{}")
    monkeypatch.setenv("MEDIAHUB_PIPER_MODEL", str(model))
    resolved = voiceover._resolve_piper_model()
    assert resolved == (model, cfg)


def test_resolve_piper_model_explicit_path_without_config(tmp_path, monkeypatch):
    model = tmp_path / "voice.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setenv("MEDIAHUB_PIPER_MODEL", str(model))
    resolved = voiceover._resolve_piper_model()
    assert resolved == (model, None)  # piper can auto-discover; None is fine


def test_resolve_piper_model_missing_file_is_none(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_PIPER_MODEL", str(tmp_path / "absent.onnx"))
    assert voiceover._resolve_piper_model() is None


def test_resolve_piper_model_named_voice_in_dir(tmp_path, monkeypatch):
    vdir = tmp_path / "voices"
    vdir.mkdir()
    (vdir / "ryan.onnx").write_bytes(b"onnx")
    monkeypatch.setenv("MEDIAHUB_PIPER_VOICE_DIR", str(vdir))
    monkeypatch.setenv("MEDIAHUB_PIPER_VOICE", "ryan")  # extension appended
    resolved = voiceover._resolve_piper_model()
    assert resolved is not None and resolved[0] == vdir / "ryan.onnx"


def test_resolve_piper_model_config_override(tmp_path, monkeypatch):
    model = tmp_path / "v.onnx"
    model.write_bytes(b"onnx")
    cfg = tmp_path / "custom.json"
    cfg.write_text("{}")
    monkeypatch.setenv("MEDIAHUB_PIPER_MODEL", str(model))
    monkeypatch.setenv("MEDIAHUB_PIPER_CONFIG", str(cfg))
    assert voiceover._resolve_piper_model() == (model, cfg)


def test_require_piper_model_unconfigured_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    with pytest.raises(voiceover.VoiceoverError, match="no voice model is configured"):
        voiceover._require_piper_model()


def test_require_piper_model_missing_explicit_path_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_PIPER_MODEL", str(tmp_path / "gone.onnx"))
    with pytest.raises(voiceover.VoiceoverError, match="MEDIAHUB_PIPER_MODEL"):
        voiceover._require_piper_model()


def test_require_piper_model_missing_named_voice_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_PIPER_VOICE_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_PIPER_VOICE", "nope")
    with pytest.raises(voiceover.VoiceoverError, match="nope"):
        voiceover._require_piper_model()


# --- availability ----------------------------------------------------------


def test_piper_available_true_when_pkg_model_and_ffmpeg_present(tmp_path, monkeypatch):
    model = tmp_path / "m.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setenv("MEDIAHUB_PIPER_MODEL", str(model))
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a, **k: object() if name == "piper" else None
    )
    monkeypatch.setattr(voiceover, "_ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    assert voiceover._piper_available() is True
    # Each missing piece flips it to False (honest "not ready").
    monkeypatch.setattr(voiceover, "_ffmpeg_exe", lambda: None)
    assert voiceover._piper_available() is False


def test_piper_available_false_without_package(tmp_path, monkeypatch):
    model = tmp_path / "m.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setenv("MEDIAHUB_PIPER_MODEL", str(model))
    monkeypatch.setattr(voiceover, "_ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **k: None)
    assert voiceover._piper_available() is False


def test_piper_available_false_without_model(monkeypatch):
    monkeypatch.setattr(
        importlib.util, "find_spec", lambda name, *a, **k: object() if name == "piper" else None
    )
    monkeypatch.setattr(voiceover, "_ffmpeg_exe", lambda: "/usr/bin/ffmpeg")
    assert voiceover._piper_available() is False  # no model configured


def test_status_reports_resolved_piper_model(tmp_path, monkeypatch):
    model = tmp_path / "m.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setenv("MEDIAHUB_PIPER_MODEL", str(model))
    status = voiceover.tts_provider_status()
    assert status["piper_model"] == str(model)


# --- WAV duration + WAV->MP3 transcode -------------------------------------


def test_wav_duration_ms_parses_real_wav():
    assert voiceover._wav_duration_ms(_tiny_wav(1000)) == 1000
    assert abs(voiceover._wav_duration_ms(_tiny_wav(250)) - 250) <= 1


def test_wav_duration_ms_rejects_garbage():
    with pytest.raises(voiceover.VoiceoverError, match="not valid WAV"):
        voiceover._wav_duration_ms(b"not a wav file at all")


def test_wav_to_mp3_honest_error_without_ffmpeg(monkeypatch):
    monkeypatch.setattr(voiceover, "_ffmpeg_exe", lambda: None)
    with pytest.raises(voiceover.VoiceoverError, match="FFmpeg"):
        voiceover._wav_to_mp3(_tiny_wav(100))


def test_wav_to_mp3_real_transcode_when_ffmpeg_present():
    if voiceover._ffmpeg_exe() is None:
        pytest.skip("no FFmpeg binary available in this environment")
    mp3 = voiceover._wav_to_mp3(_tiny_wav(300))
    assert isinstance(mp3, bytes) and len(mp3) > 0
    # A real MP3 starts with an ID3 tag or an MPEG frame sync byte.
    assert mp3[:3] == b"ID3" or mp3[0] == 0xFF


# --- the piper synthesis seam (honest errors, no fabricated voice) ---------


def test_piper_wav_bytes_honest_error_when_package_absent(tmp_path):
    if importlib.util.find_spec("piper") is not None:
        pytest.skip("piper-tts is installed in this environment")
    model = tmp_path / "m.onnx"
    model.write_bytes(b"onnx")
    with pytest.raises(voiceover.VoiceoverError, match="piper-tts"):
        voiceover._piper_wav_bytes("hello", model, None)


# --- end-to-end through synthesize() with the piper seam mocked ------------


def test_synthesize_piper_end_to_end_mocked(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "piper")
    model = tmp_path / "alba.onnx"
    model.write_bytes(b"onnx-bytes")
    monkeypatch.setenv("MEDIAHUB_PIPER_MODEL", str(model))

    seen = {}

    def _fake_wav(text, model_path, config_path):
        seen["text"] = text
        seen["model"] = Path(model_path)
        return _tiny_wav(1000)

    monkeypatch.setattr(voiceover, "_piper_wav_bytes", _fake_wav)
    monkeypatch.setattr(voiceover, "_wav_to_mp3", lambda b: b"ID3piperaudio")

    res = voiceover.synthesize("Maya new PB", apply_pronunciation=False)
    assert res.cached is False
    assert res.transcript == "Maya new PB"  # verbatim — no LLM, no rewrite
    assert seen["text"] == "Maya new PB"  # exactly what Piper synthesised
    assert seen["model"] == model
    assert res.audio_path.suffix == ".mp3"  # seam contract: genuine MP3 path
    assert res.audio_path.read_bytes() == b"ID3piperaudio"
    assert res.duration_ms == 1000  # measured from the WAV, not edge timings
    assert len(res.word_boundaries) == 3
    assert res.srt_path.read_text().strip()  # SRT built from the estimates

    # A second call is a cache hit — Piper is not re-invoked.
    seen.clear()
    res2 = voiceover.synthesize("Maya new PB", apply_pronunciation=False)
    assert res2.cached is True
    assert "text" not in seen


def test_synthesize_piper_applies_pronunciation_before_engine(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "piper")
    (tmp_path / "pronunciations.json").write_text(json.dumps({"Siobhan": "Shiv-awn"}))
    model = tmp_path / "v.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setenv("MEDIAHUB_PIPER_MODEL", str(model))

    captured = {}

    def _fake_wav(text, model_path, config_path):
        captured["text"] = text
        return _tiny_wav(500)

    monkeypatch.setattr(voiceover, "_piper_wav_bytes", _fake_wav)
    monkeypatch.setattr(voiceover, "_wav_to_mp3", lambda b: b"ID3audio")

    res = voiceover.synthesize("Well done Siobhan", apply_pronunciation=True)
    assert captured["text"] == "Well done Shiv-awn"  # deterministic, pre-synthesis
    assert res.transcript == "Well done Shiv-awn"


def test_piper_and_edge_caches_do_not_collide(tmp_path, monkeypatch):
    """Switching providers for the same (text, voice) must not serve the other
    backend's cached MP3 — the cache key is namespaced by provider."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(
        voiceover,
        "_synthesize_edge",
        lambda t, v: (b"EDGEbytes", [WordBoundary("hello", 0, 200)]),
    )
    monkeypatch.setattr(voiceover, "_piper_wav_bytes", lambda *a: _tiny_wav(500))
    monkeypatch.setattr(voiceover, "_wav_to_mp3", lambda b: b"PIPERbytes")

    # Edge first (provider unset → default edge).
    monkeypatch.delenv("MEDIAHUB_TTS_PROVIDER", raising=False)
    edge_res = voiceover.synthesize("hello", voice="v1", apply_pronunciation=False)
    edge_key = edge_res.audio_path.stem

    # Same text + voice, now on Piper.
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "piper")
    model = tmp_path / "m.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setenv("MEDIAHUB_PIPER_MODEL", str(model))
    piper_res = voiceover.synthesize("hello", voice="v1", apply_pronunciation=False)

    assert edge_key != piper_res.audio_path.stem  # distinct cache entries
    assert edge_res.audio_path.read_bytes() == b"EDGEbytes"  # edge file untouched
    assert piper_res.audio_path.read_bytes() == b"PIPERbytes"


def test_edge_cache_key_is_byte_identical_after_piper_added(monkeypatch):
    """The edge path's cache identity is unchanged by the Piper work — a hard
    requirement so the default deployment's voice_cache never churns."""
    monkeypatch.delenv("MEDIAHUB_TTS_PROVIDER", raising=False)
    assert voiceover._cache_voice("en-GB-SoniaNeural") == "en-GB-SoniaNeural"
    # And the composed key matches the historical (text, voice) hash exactly.
    assert voiceover.cache_key("hi", voiceover._cache_voice("v1")) == voiceover.cache_key(
        "hi", "v1"
    )


def test_synthesize_piper_real_path_if_ffmpeg(tmp_path, monkeypatch):
    """Full Piper pipeline with a REAL WAV→MP3 transcode (only the model call
    mocked) — proves genuine MP3 bytes land in the cache when FFmpeg is present."""
    if voiceover._ffmpeg_exe() is None:
        pytest.skip("no FFmpeg binary available in this environment")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "piper")
    model = tmp_path / "v.onnx"
    model.write_bytes(b"onnx")
    monkeypatch.setenv("MEDIAHUB_PIPER_MODEL", str(model))
    monkeypatch.setattr(voiceover, "_piper_wav_bytes", lambda *a: _tiny_wav(600))

    res = voiceover.synthesize("a clean caption here", apply_pronunciation=False)
    data = res.audio_path.read_bytes()
    assert res.audio_path.suffix == ".mp3"
    assert data[:3] == b"ID3" or (data and data[0] == 0xFF)  # genuine MP3
