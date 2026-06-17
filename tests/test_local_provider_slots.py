"""P0.4 — every AI surface admits a local-capable provider (no cloud key
*required* by any interface).

This is the precondition for Phase 5 (local-AI substitution): the seams must
already accept a local backend so P5 only has to implement, not rearchitect.
Pinned per surface:

  LLM       both wrappers (ai_core.llm, media_ai.llm) accept an
            OpenAI-compatible endpoint — keyless local servers (Ollama,
            llama.cpp, vLLM) included — via MEDIAHUB_LLM_ENDPOINTS.
  TTS       voiceover carries a provider seam (MEDIAHUB_TTS_PROVIDER) with a
            registered local slot ('piper'); selecting it never silently
            falls back to the cloud backend.
  ASR       no ASR surface exists yet (it arrives with P5.3); this guard
            fails the moment a cloud ASR import lands outside a provider
            seam, so the slot rule can't be bypassed by accident.
  graphics  rendering is on-server already (Playwright stills; ffmpeg reel
            engine ships with P0.1); cutout defaults to in-process rembg;
            the only cloud-only image call (Imagen backgrounds) is opt-in
            and reports unavailable without its key.

Config-level assertions only — no test here performs a network call.
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "mediahub"

_CLOUD_KEY_ENVS = (
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
    "MEDIAHUB_LLM_ENDPOINTS",
    "MEDIAHUB_LLM_API_KEY",
    "OPENAI_API_KEY",
    "MEDIAHUB_LLM_PROVIDER",
)


def _clear_llm_env(monkeypatch, tmp_path):
    for name in _CLOUD_KEY_ENVS:
        monkeypatch.delenv(name, raising=False)
    # Point DATA_DIR at an empty dir so the secrets_store fallback is empty too.
    monkeypatch.setenv("DATA_DIR", str(tmp_path))


# ---------------------------------------------------------------------------
# LLM — the OpenAI-compatible endpoint slot (Ollama et al.)
# ---------------------------------------------------------------------------


def test_ai_core_accepts_keyless_local_endpoint(monkeypatch, tmp_path):
    """A bare local endpoint with NO bearer key joins the provider chain —
    that is what makes Ollama/llama.cpp drop-in capable."""
    from mediahub.ai_core import llm

    _clear_llm_env(monkeypatch, tmp_path)
    monkeypatch.setenv("MEDIAHUB_LLM_ENDPOINTS", "http://localhost:11434/v1")
    assert llm._key_for("openai") is not None
    assert llm.active_provider() == "openai"


def test_media_ai_accepts_keyless_local_endpoint(monkeypatch, tmp_path):
    from mediahub.media_ai import llm as media_llm
    from mediahub.media_ai.llm_providers import is_openai_configured

    _clear_llm_env(monkeypatch, tmp_path)
    monkeypatch.setenv("MEDIAHUB_LLM_ENDPOINTS", "http://localhost:11434/v1")
    assert is_openai_configured() is True
    assert media_llm.is_available() is True


def test_llm_with_nothing_configured_errors_honestly(monkeypatch, tmp_path):
    """No providers at all → ProviderNotConfigured, never a heuristic fake."""
    import pytest

    from mediahub.ai_core import llm

    _clear_llm_env(monkeypatch, tmp_path)
    assert llm.active_provider() is None
    with pytest.raises(llm.ProviderNotConfigured):
        llm.ask("system", "user")


# ---------------------------------------------------------------------------
# TTS — the piper slot (zero-cost local backend implemented in R1.21)
# ---------------------------------------------------------------------------


def test_tts_interface_admits_a_local_provider(monkeypatch):
    from mediahub.visual import voiceover

    monkeypatch.setenv("MEDIAHUB_TTS_PROVIDER", "piper")
    assert voiceover.select_tts_provider() == "piper"
    status = voiceover.tts_provider_status()
    assert "piper_available" in status


# ---------------------------------------------------------------------------
# ASR — no unslotted cloud ASR may exist
# ---------------------------------------------------------------------------


def test_no_cloud_asr_import_outside_a_provider_seam():
    """There is no ASR call in MediaHub today (reel-caption ASR is P5.3).
    When it arrives it must live behind a provider seam like the LLM/TTS
    ones; this scan fails the moment a speech-to-text dependency is
    imported anywhere else, forcing that conversation."""
    asr_import = re.compile(
        r"^\s*(?:import|from)\s+"
        r"(whisper|faster_whisper|whispercpp|openai\.audio|"
        r"google\.cloud\.speech|boto3\.transcribe|azure\.cognitiveservices\.speech)\b",
        re.MULTILINE,
    )
    offenders = []
    for py in SRC.rglob("*.py"):
        if "node_modules" in py.parts:
            continue
        if asr_import.search(py.read_text(encoding="utf-8", errors="ignore")):
            offenders.append(str(py.relative_to(SRC)))
    assert not offenders, (
        "Cloud/loose ASR imports found outside a provider seam: "
        f"{offenders}. Add a MEDIAHUB_ASR_PROVIDER seam first (P0.4 rule)."
    )


# ---------------------------------------------------------------------------
# Graphics — local paths are the defaults; the cloud image call is opt-in
# ---------------------------------------------------------------------------


def test_reel_engine_registers_a_local_capable_engine(monkeypatch):
    from mediahub.visual.reel_engine import reel_engine_status

    monkeypatch.delenv("MEDIAHUB_REEL_ENGINE", raising=False)
    status = reel_engine_status()
    assert "ffmpeg_available" in status  # the P0.1 free engine is a slot


def test_cutout_defaults_to_in_process_server_backend(monkeypatch):
    from mediahub.media_ai.providers import _resolve_provider_choice

    monkeypatch.delenv("MEDIAHUB_CUTOUT_PROVIDER", raising=False)
    monkeypatch.delenv("MEDIAHUB_BG_PROVIDER", raising=False)
    assert _resolve_provider_choice() == "server"


def test_generated_backgrounds_unavailable_without_key(monkeypatch, tmp_path):
    """Imagen backgrounds are the one cloud-only image call: opt-in, and
    honestly unavailable with no key — the renderer's procedural
    backgrounds (first-class, deterministic) are the local default."""
    from mediahub.visual import ai_background

    _clear_llm_env(monkeypatch, tmp_path)
    assert ai_background.is_available() is False
