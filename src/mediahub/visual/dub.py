"""AI-dub pipeline (roadmap 1.24) — a reel's narration, spoken in another language.

MediaHub's reels carry a **deterministic, fact-only** narration (``visual/narration``)
— never an AI-written script. Dubbing reuses exactly that verified text: it
**translates the known narration** into a target language, synthesises it with a
target-language voice, and swaps the voice track onto the video, leaving the
music bed in place. The result is clearly labelled **AI-dubbed** in the manifest
(1.23 provenance).

Two honest boundaries, both deliberate:

* **No fabrication.** The dubbed words are the translation of the same verified
  facts the English reel narrated — there is no LLM-written dub script. The
  translation goes through the localisation engine (glossary-protected); if no
  provider is configured it raises, never a fake dub.
* **Voice-preservation and lip-sync are out of scope** (and explicitly so per the
  roadmap): we synthesise a clean target-language voice, we do not clone the
  original speaker or align lips. That stays out until it can be done
  consent-safely.

When a target language has no mapped/available voice, or synthesis fails, the
caller's existing honest fallback applies — the reel ships **silent** with the
reason in the manifest (``audio_mux.apply_audio``), never a fabricated track.
"""

from __future__ import annotations

from mediahub.localize import base_code
from mediahub.localize.translate import ClaudeUnavailableError, translate_text

__all__ = [
    "DubUnavailable",
    "ClaudeUnavailableError",
    "voice_for_language",
    "dub_plan",
    "is_dubbable",
]


class DubUnavailable(RuntimeError):
    """Raised when a reel cannot be dubbed honestly (no voice for the language,
    or no narration to dub). Honest, in the spirit of ``VoiceoverError``."""


# Target language (base ISO code) → a neutral TTS voice id. These are the
# standard cross-provider neural voice names: with the online ``edge`` backend
# they synthesise directly; with the default local Piper backend an operator
# points ``MEDIAHUB_PIPER_MODEL`` at the matching ``.onnx`` (else synthesis
# honest-errors and the reel ships silent). Welsh leads — the flagship locale.
_VOICE_BY_LANG: dict[str, str] = {
    "en": "en-GB-SoniaNeural",
    "cy": "cy-GB-NiaNeural",
    "ga": "ga-IE-OrlaNeural",
    "fr": "fr-FR-DeniseNeural",
    "es": "es-ES-ElviraNeural",
    "pt": "pt-PT-RaquelNeural",
    "ru": "ru-RU-SvetlanaNeural",
    "zh": "zh-CN-XiaoxiaoNeural",
    "hi": "hi-IN-SwaraNeural",
    "ar": "ar-EG-SalmaNeural",
    "bn": "bn-IN-TanishaaNeural",
    "ur": "ur-PK-UzmaNeural",
}


def voice_for_language(language: str | None) -> str:
    """A TTS voice id for a target language, or "" if we map none."""
    return _VOICE_BY_LANG.get(base_code(language), "")


def is_dubbable(language: str | None) -> bool:
    """True if we have a voice mapped for this target language."""
    return bool(voice_for_language(language))


def dub_plan(
    base_audio_plan: dict | None,
    target_language: str,
    *,
    source_language: str = "en",
    sport: str = "swimming",
) -> dict:
    """Return a dubbed copy of an audio plan for ``target_language``.

    Takes the reel's English audio plan (voice + verified narration ``script`` +
    optional music bed), translates the narration, swaps in a target-language
    voice, keeps the music, and stamps dub provenance. The returned plan is fed
    to :func:`mediahub.visual.audio_mux.apply_audio` unchanged.

    Raises :class:`DubUnavailable` when there is no narration to dub or no voice
    for the language; propagates :class:`ClaudeUnavailableError` when translation
    has no provider — never a fake dub.
    """
    script = str((base_audio_plan or {}).get("script") or "").strip()
    if not script:
        raise DubUnavailable("nothing to dub — the reel has no narration script")
    base = base_code(target_language)
    voice = voice_for_language(base)
    if not voice:
        raise DubUnavailable(f"no dubbing voice configured for language {target_language!r}")

    src = base_code(source_language) or "en"
    if base == src:
        # Same language — not a dub. Return the plan unchanged (no provider call).
        return dict(base_audio_plan or {})

    translated = translate_text(script, base, sport=sport, source_language=src).strip()
    if not translated:
        raise DubUnavailable("translation returned no narration text")

    plan = dict(base_audio_plan or {})
    plan["script"] = translated
    plan["voice"] = voice
    plan["dubbed"] = True
    plan["dub_source_language"] = src
    plan["dub_target_language"] = base
    return plan
