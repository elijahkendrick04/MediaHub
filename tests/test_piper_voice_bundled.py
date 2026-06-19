"""Roadmap 1.7 (build 2) — the deployed image ships a working local Piper voice.

Build 1 made Piper the default TTS backend; this guards the deployment half:
the Docker image must install the engine + its system phonemizer, bundle a
licence-clean voice, point the runtime at it, and prove a real synth works at
build time (loud-fail, never a silent runtime degrade). These are text-level
assertions on the committed Dockerfile + fetch script — no Docker build here —
so a regression that would break the shipped local voice turns CI red.
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DOCKERFILE = (REPO / "Dockerfile").read_text(encoding="utf-8")
FETCH = (REPO / "scripts" / "fetch_piper_voice.py").read_text(encoding="utf-8")


def test_dockerfile_installs_espeak_ng_for_piper():
    """piper-tts phonemizes through espeak-ng; without the system package a
    synth fails at runtime. It must be in the apt layer."""
    assert re.search(r"^\s*espeak-ng\b", DOCKERFILE, re.MULTILINE), (
        "Dockerfile must apt-install espeak-ng — piper-tts needs it to phonemize."
    )


def test_dockerfile_installs_the_voiceover_extra():
    """The default backend's package (piper-tts) ships in the image via the
    pyproject [voiceover] extra."""
    assert '[voiceover]"' in DOCKERFILE or "piper-tts" in DOCKERFILE, (
        "Dockerfile must install the local Piper TTS package (the [voiceover] "
        "extra), since Piper is the default backend (1.7)."
    )


def test_dockerfile_fetches_and_points_at_the_bundled_voice():
    assert "fetch_piper_voice.py" in DOCKERFILE, (
        "Dockerfile must fetch the licence-clean default voice into the image."
    )
    assert "MEDIAHUB_PIPER_VOICE_DIR=/opt/piper_voices" in DOCKERFILE, (
        "Runtime auto-discovery must be pointed at the bundled voice dir via "
        "the MEDIAHUB_PIPER_VOICE_DIR env."
    )


def test_dockerfile_verifies_a_real_synth_at_build_time():
    """A loud build-time check (like the rembg/sqlite-vec preloads) so a broken
    local-voice path fails the build, never degrades silently at runtime."""
    assert "voiceover" in DOCKERFILE and "synthesize(" in DOCKERFILE, (
        "Dockerfile must run a real synth verification at build time."
    )
    assert "_piper_available()" in DOCKERFILE


def test_fetch_script_only_lists_licence_cleared_voices():
    """The default voice is the CC BY 4.0 en_GB-alba-medium; the script must
    name it and carry its commercial-OK licence, and refuse unknown voices."""
    assert "en_GB-alba-medium" in FETCH
    assert "CC BY 4.0" in FETCH
    assert 'DEFAULT_VOICE = "en_GB-alba-medium"' in FETCH


def test_fetch_script_default_voice_is_in_the_cleared_map():
    """Importing the script, the default voice must be present in its VOICES
    allow-list (so a default fetch can never hit an unverified licence)."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "fetch_piper_voice", REPO / "scripts" / "fetch_piper_voice.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    assert mod.DEFAULT_VOICE in mod.VOICES
    # Every cleared voice records a licence note (4th tuple field).
    for key, meta in mod.VOICES.items():
        assert len(meta) == 4 and meta[3].strip(), f"{key} missing a licence note"
