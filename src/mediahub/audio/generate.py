"""audio/generate.py — optional music/SFX generation provider slots (1.8).

Canva/Adobe ship "AI music generation" and "AI sound-effects generation". The
MediaHub shape (parity doc): an **optional provider slot**, off by default, with
the licence-clean :mod:`~mediahub.audio.library` as the no-key default. There is
no keyless local music model that is licence-clean and good, so generation is a
flagged seam — when an operator wires a provider it is used; otherwise the call
**honest-errors** and the caller falls back to the catalogue. Nothing here ever
fabricates a track silently.

Providers are selected per env (``MEDIAHUB_MUSIC_GEN_PROVIDER`` /
``MEDIAHUB_SFX_GEN_PROVIDER``). The only recognised slot today is ``gemini``
(Lyria-class), and even then the concrete generation call honest-errors until a
real backend is connected — the seam exists so a provider drops in without
touching callers, exactly like the TTS/ASR slots. The library remains the
working default in every configuration.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

# Recognised generation provider slots. Empty env → generation disabled (the
# library is the default), which is the supported, no-key configuration.
_VALID_PROVIDERS: frozenset[str] = frozenset({"gemini"})


class GenerationUnavailable(RuntimeError):
    """No generation provider could produce audio — caller uses the library.

    Mirrors the ``VoiceoverError`` / ``ClaudeUnavailableError`` honest-error
    contract: a clear "not available" beats a fabricated or silently-substituted
    track.
    """


def _select(env_var: str) -> str:
    raw = os.environ.get(env_var, "").strip().lower()
    if not raw:
        return ""
    if raw not in _VALID_PROVIDERS:
        raise GenerationUnavailable(
            f"{env_var}={raw!r} is not a recognised generation provider "
            f"(valid: {sorted(_VALID_PROVIDERS)}). Leave it unset to use the "
            "licence-clean audio library, which is the default."
        )
    return raw


def select_music_provider() -> str:
    """The configured music-generation provider, or '' (disabled → library)."""
    return _select("MEDIAHUB_MUSIC_GEN_PROVIDER")


def select_sfx_provider() -> str:
    """The configured SFX-generation provider, or '' (disabled → library)."""
    return _select("MEDIAHUB_SFX_GEN_PROVIDER")


def music_gen_available() -> bool:
    try:
        return bool(select_music_provider())
    except GenerationUnavailable:
        return False


def sfx_gen_available() -> bool:
    try:
        return bool(select_sfx_provider())
    except GenerationUnavailable:
        return False


def generation_status() -> dict:
    """Diagnostics for the health surface — what's wired, what's the default."""
    music = os.environ.get("MEDIAHUB_MUSIC_GEN_PROVIDER", "").strip()
    sfx = os.environ.get("MEDIAHUB_SFX_GEN_PROVIDER", "").strip()
    return {
        "music_provider": music,
        "sfx_provider": sfx,
        "music_available": music_gen_available(),
        "sfx_available": sfx_gen_available(),
        "default": "library",
        "recognised_providers": sorted(_VALID_PROVIDERS),
    }


def _dispatch(provider: str, kind: str, prompt: str, duration_sec: float, out: Path) -> Path:
    """Call the selected backend. Honest-errors until one is connected.

    The dispatch table is the extension point: a real Lyria-class call slots in
    here behind the env flag, and every caller keeps working unchanged. Until
    then this raises ``GenerationUnavailable`` so callers fall back to the
    catalogue rather than receiving a fabricated clip.
    """
    if provider == "gemini":
        raise GenerationUnavailable(
            "The 'gemini' audio-generation slot is recognised but no generation "
            "backend is connected in this build. Use the audio library (the "
            "default) or wire a provider into audio/generate._dispatch."
        )
    raise GenerationUnavailable(f"no generation backend for provider {provider!r}")


def generate_music(prompt: str, *, duration_sec: float = 8.0, out: Optional[Path] = None) -> Path:
    """Generate a ~``duration_sec`` music bed for ``prompt``.

    Raises :class:`GenerationUnavailable` when no provider is configured (the
    library is the default) or when the configured provider has no connected
    backend. Never returns a fabricated or substituted file.
    """
    provider = select_music_provider()
    if not provider:
        raise GenerationUnavailable(
            "no music-generation provider configured (MEDIAHUB_MUSIC_GEN_PROVIDER "
            "is unset) — the audio library is the default source"
        )
    if out is None:
        raise GenerationUnavailable("an output path is required for generation")
    return _dispatch(provider, "music", prompt, duration_sec, Path(out))


def generate_sfx(prompt: str, *, duration_sec: float = 1.0, out: Optional[Path] = None) -> Path:
    """Generate a short sound effect for ``prompt`` (honest-error contract)."""
    provider = select_sfx_provider()
    if not provider:
        raise GenerationUnavailable(
            "no SFX-generation provider configured (MEDIAHUB_SFX_GEN_PROVIDER is "
            "unset) — the audio library is the default source"
        )
    if out is None:
        raise GenerationUnavailable("an output path is required for generation")
    return _dispatch(provider, "sfx", prompt, duration_sec, Path(out))


__all__ = [
    "GenerationUnavailable",
    "select_music_provider",
    "select_sfx_provider",
    "music_gen_available",
    "sfx_gen_available",
    "generation_status",
    "generate_music",
    "generate_sfx",
]
