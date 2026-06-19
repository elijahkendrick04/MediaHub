"""Speech-to-text seam (P6.2) — voice input for the copilot.

Voice has two honest paths:

* **Browser capture (default, free):** the chat UI uses the browser's built-in
  Web Speech API to transcribe on the device and drop the text into the chat
  box. No server round-trip, no provider, no audio leaves the device.
* **Server ASR (this seam):** for uploaded audio, :func:`transcribe` routes to a
  configured local ASR backend via ``MEDIAHUB_ASR_PROVIDER``. The real engine —
  faster-whisper / whisper.cpp, with word-level timestamps for the video suite's
  captions — lives in :mod:`mediahub.visual.transcribe` (roadmap 1.4); this module
  is the thin copilot-facing seam over it, returning just the transcript text.

When no provider is configured (the default) :func:`transcribe` raises
:class:`ASRUnavailable` — an honest error, never a fabricated transcript.
"""

from __future__ import annotations

from mediahub.visual.transcribe import (
    ASRUnavailable,
    asr_provider_status,
    is_available,
    select_asr_provider,
    transcribe_audio,
)


def asr_provider() -> str:
    """The configured ASR provider name (canonical), or "" when none/invalid.

    Reads ``MEDIAHUB_ASR_PROVIDER`` via the engine; an unset or unrecognised
    value resolves to "" here (the browser Web Speech API is the live voice
    path), so this stays a non-raising readiness probe.
    """
    try:
        return select_asr_provider()
    except ASRUnavailable:
        return ""


def transcribe(audio_bytes: bytes, *, content_type: str = "") -> str:
    """Transcribe uploaded audio to text via the configured ASR backend.

    Delegates to :func:`mediahub.visual.transcribe.transcribe_audio` and returns
    just the transcript text (the copilot only needs the words; the word-level
    stamps feed the caption surfaces). Raises :class:`ASRUnavailable` when no
    provider is configured or the backend is unavailable — the honest state the
    route turns into a 503.
    """
    return transcribe_audio(audio_bytes, content_type=content_type).text


__all__ = [
    "ASRUnavailable",
    "asr_provider",
    "asr_provider_status",
    "is_available",
    "transcribe",
]
