"""audio/voice.py — the voice layer over the shipped TTS seam (roadmap 1.8).

``visual/voiceover.py`` already owns *synthesis* — the provider seam (local Piper
by default, opt-in online edge-tts), the cache, the SRT, and the
pronunciation-override hook. 1.8 grows a proper **voice layer** on top of it
without re-implementing any of that:

* a curated **voice catalogue** across the seam's providers (the local Piper
  voice; a hand-picked set of edge voices including **Welsh** for the Welsh-first
  market, W.13) — so a club can choose a named voice instead of typing a raw
  provider string;
* deterministic, SSML-ish **voice parameters** (rate / pitch / volume) mapped to
  whatever the active provider actually supports, with an honest note where a
  provider can't honour one;
* a **per-organisation pronunciation lexicon** — the genuinely loved feature for
  results content: a club teaches MediaHub how its swimmers' names are said
  *once*, and every voiceover gets them right. It persists per-org and merges
  into the existing deterministic override chain (global → org → per-run).

This module is catalogue + parameters + lexicon CRUD only — all deterministic,
no judgement. The actual synthesis stays in ``visual/voiceover.py``; build 2
threads these params and the org id through it (folding non-default params into
the cache key so a re-voiced clip never serves a stale render).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from mediahub.visual import pronunciation


@dataclass(frozen=True)
class Voice:
    """One selectable voice on the TTS seam.

    ``id`` is MediaHub's stable handle; ``provider`` is the seam backend
    (``piper`` / ``edge``); ``name`` is what that backend expects (the Piper
    model identity, or the edge short name).
    """

    id: str
    provider: str
    name: str
    language: str  # BCP-47-ish: "en-GB", "cy-GB", ...
    gender: str = ""
    description: str = ""
    local: bool = False  # True for the zero-cost offline Piper voice

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "provider": self.provider,
            "name": self.name,
            "language": self.language,
            "gender": self.gender,
            "description": self.description,
            "local": self.local,
        }


# The curated catalogue. Piper (local, zero-cost, the default provider since 1.7)
# leads; the edge voices are the opt-in online set, including Welsh for W.13.
# edge names are real Microsoft Neural short names the edge-tts backend accepts.
_PIPER_DEFAULT = Voice(
    id="piper-en-gb",
    provider="piper",
    name="",  # resolved from MEDIAHUB_PIPER_MODEL/VOICE at synthesis time
    language="en-GB",
    gender="",
    description="Local, offline, zero-cost — the default voice. Caption text never leaves the box.",
    local=True,
)

_EDGE_VOICES: tuple[Voice, ...] = (
    Voice("edge-en-gb-ryan", "edge", "en-GB-RyanNeural", "en-GB", "male", "British English, warm."),
    Voice("edge-en-gb-sonia", "edge", "en-GB-SoniaNeural", "en-GB", "female", "British English, clear."),
    Voice("edge-en-gb-libby", "edge", "en-GB-LibbyNeural", "en-GB", "female", "British English, bright."),
    Voice("edge-en-us-aria", "edge", "en-US-AriaNeural", "en-US", "female", "US English, friendly."),
    Voice("edge-en-us-guy", "edge", "en-US-GuyNeural", "en-US", "male", "US English, confident."),
    Voice("edge-en-au-natasha", "edge", "en-AU-NatashaNeural", "en-AU", "female", "Australian English."),
    Voice("edge-cy-gb-nia", "edge", "cy-GB-NiaNeural", "cy-GB", "female", "Welsh (Cymraeg)."),
    Voice("edge-cy-gb-aled", "edge", "cy-GB-AledNeural", "cy-GB", "male", "Welsh (Cymraeg)."),
)

VOICE_CATALOGUE: tuple[Voice, ...] = (_PIPER_DEFAULT, *_EDGE_VOICES)


def list_voices(*, provider: Optional[str] = None, language: Optional[str] = None) -> list[Voice]:
    """The catalogue, optionally filtered by provider and/or language prefix."""
    prov = (provider or "").strip().lower() or None
    lang = (language or "").strip().lower() or None
    out: list[Voice] = []
    for v in VOICE_CATALOGUE:
        if prov and v.provider != prov:
            continue
        if lang and not v.language.lower().startswith(lang):
            continue
        out.append(v)
    return out


def get_voice(voice_id: str) -> Optional[Voice]:
    for v in VOICE_CATALOGUE:
        if v.id == voice_id:
            return v
    return None


def default_voice() -> Voice:
    """The local Piper voice — the zero-cost default."""
    return _PIPER_DEFAULT


# ---------------------------------------------------------------------------
# Voice parameters (SSML-ish, deterministic, provider-mapped)
# ---------------------------------------------------------------------------

_RATE_MIN, _RATE_MAX = -50, 100
_PITCH_MIN, _PITCH_MAX = -50, 50
_VOL_MIN, _VOL_MAX = -50, 50


def _clamp(value: object, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(round(float(value)))))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0


@dataclass(frozen=True)
class VoiceParams:
    """Prosody knobs, provider-neutral on the way in, provider-mapped on the way out.

    * ``rate_pct`` — speaking rate, percent off natural (clamped −50…+100).
      Honoured by *both* providers (edge: prosody rate; Piper: ``length_scale``).
    * ``pitch_hz`` — pitch shift in Hz (clamped −50…+50). edge-only; Piper has no
      pitch control, so it is recorded but not applied (honest, not faked).
    * ``volume_pct`` — loudness, percent (clamped −50…+50). edge-only; for Piper,
      use ``audio/clean.normalise`` / ``ops.gain`` downstream instead.
    """

    rate_pct: int = 0
    pitch_hz: int = 0
    volume_pct: int = 0

    @classmethod
    def make(cls, *, rate_pct: object = 0, pitch_hz: object = 0, volume_pct: object = 0) -> "VoiceParams":
        return cls(
            rate_pct=_clamp(rate_pct, _RATE_MIN, _RATE_MAX),
            pitch_hz=_clamp(pitch_hz, _PITCH_MIN, _PITCH_MAX),
            volume_pct=_clamp(volume_pct, _VOL_MIN, _VOL_MAX),
        )

    def is_default(self) -> bool:
        return self.rate_pct == 0 and self.pitch_hz == 0 and self.volume_pct == 0

    def to_edge(self) -> dict[str, str]:
        """edge-tts prosody kwargs (``rate`` / ``pitch`` / ``volume``)."""
        return {
            "rate": f"{self.rate_pct:+d}%",
            "pitch": f"{self.pitch_hz:+d}Hz",
            "volume": f"{self.volume_pct:+d}%",
        }

    def to_piper(self) -> dict[str, float]:
        """Piper synthesis kwargs — only ``length_scale`` (speed) is supported.

        Faster rate → shorter scale. Pitch/volume have no Piper equivalent and
        are deliberately omitted (apply them downstream with clean/ops).
        """
        return {"length_scale": round(1.0 / (1.0 + self.rate_pct / 100.0), 4)}

    def cache_token(self) -> str:
        """Stable token folded into the voice cache key — empty when default.

        Empty for the default params means the pre-1.8 cache keys stay
        byte-identical (no cache orphaned), mirroring the audio-mix-profile rule.
        """
        if self.is_default():
            return ""
        return f"r{self.rate_pct}p{self.pitch_hz}v{self.volume_pct}"


# ---------------------------------------------------------------------------
# Per-organisation pronunciation lexicon
# ---------------------------------------------------------------------------


class OrgLexicon:
    """CRUD over one organisation's pronunciation lexicon.

    A thin, deterministic wrapper over the JSON file that
    ``visual/pronunciation.py`` already reads in its override chain
    (global → **org** → per-run). Teaching MediaHub a name here makes every
    voiceover for that club say it correctly, with no AI guessing.
    """

    def __init__(self, profile_id: str) -> None:
        self.profile_id = profile_id
        self.path = pronunciation.org_overrides_path(profile_id)

    def entries(self) -> dict[str, str]:
        """The current ``{written: spoken}`` map (empty if none set)."""
        return pronunciation._read_map(self.path)

    def _write(self, mapping: dict[str, str]) -> None:
        import json

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def set(self, written: str, spoken: str) -> dict[str, str]:
        """Add or update one entry; returns the full map."""
        w, s = (written or "").strip(), (spoken or "").strip()
        if not w or not s:
            raise ValueError("both 'written' and 'spoken' are required")
        mapping = self.entries()
        mapping[w] = s
        self._write(mapping)
        return mapping

    def remove(self, written: str) -> dict[str, str]:
        """Delete one entry (no-op if absent); returns the full map."""
        mapping = self.entries()
        mapping.pop((written or "").strip(), None)
        self._write(mapping)
        return mapping

    def clear(self) -> None:
        """Forget the whole lexicon (removes the file)."""
        try:
            self.path.unlink()
        except OSError:
            pass


__all__ = [
    "Voice",
    "VOICE_CATALOGUE",
    "list_voices",
    "get_voice",
    "default_voice",
    "VoiceParams",
    "OrgLexicon",
]
