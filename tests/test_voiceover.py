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
import json
from pathlib import Path

import pytest

from mediahub.visual import pronunciation, voiceover
from mediahub.visual.voiceover import WordBoundary


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


def test_piper_synthesis_raises_honest_error_not_fake_voice(tmp_path, monkeypatch):
    """Selecting piper before P5.2 ships must produce a clear operator
    error — never a silent fallback to the cloud backend."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "piper")
    with pytest.raises(voiceover.VoiceoverError, match="[Pp]iper"):
        voiceover.synthesize("A real caption", apply_pronunciation=False)


def test_is_available_false_for_piper_until_p52(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "piper")
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
        "available_providers",
    }
    assert required <= set(status.keys())
    assert status["active"] == "edge"
    assert status["piper_available"] is False


def test_tts_provider_status_surfaces_bad_value_verbatim(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "espeak")
    status = voiceover.tts_provider_status()
    assert status["configured"] == "espeak"
    assert status["active"] == "espeak"
