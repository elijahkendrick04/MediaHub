"""Speech-to-text seam (P6.2) — voice input for the copilot.

Voice has two honest paths:

* **Browser capture (default, free):** the chat UI uses the browser's built-in
  Web Speech API to transcribe on the device and drop the text into the chat
  box. No server round-trip, no provider, no audio leaves the device.
* **Server ASR (this seam):** for uploaded audio, :func:`transcribe` routes to a
  configured ASR provider. None ships yet (it's the P5.3 provider seam), so it
  raises :class:`ASRUnavailable` — an honest error, never a fabricated
  transcript. When a provider lands it slots in behind this one function.

The seam is deliberately tiny: a provider check + one entry point, mirroring the
AI-core provider doctrine (env-keyed, honest failure).
"""

from __future__ import annotations

import os


class ASRUnavailable(RuntimeError):
    """Raised when no speech-to-text provider is configured."""


def asr_provider() -> str:
    """The configured ASR provider name, or "" when none is set.

    Reads ``MEDIAHUB_ASR_PROVIDER``; no provider is wired yet, so this returns
    "" on every current deployment (the browser Web Speech API is the live
    voice path). Kept as the single seam a future provider plugs into.
    """
    return os.environ.get("MEDIAHUB_ASR_PROVIDER", "").strip().lower()


def is_available() -> bool:
    return bool(asr_provider())


def transcribe(audio_bytes: bytes, *, content_type: str = "") -> str:
    """Transcribe uploaded audio to text via the configured ASR provider.

    Raises :class:`ASRUnavailable` when no provider is configured (the honest
    state today). A future provider implementation slots in here, behind the
    same env-keyed seam as the LLM and image providers.
    """
    provider = asr_provider()
    if not provider:
        raise ASRUnavailable(
            "Speech-to-text isn't configured on this deployment. Use the "
            "microphone button (your browser transcribes on-device), or type "
            "your request."
        )
    # No server-side provider ships yet (P5.3 seam). When one lands it is
    # dispatched here by name; until then an "configured but unimplemented"
    # provider is still an honest error rather than a fake transcript.
    raise ASRUnavailable(  # pragma: no cover - no provider wired yet
        f"ASR provider {provider!r} is named but not implemented on this build."
    )


__all__ = ["ASRUnavailable", "asr_provider", "is_available", "transcribe"]
