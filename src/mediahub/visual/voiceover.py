"""
visual/voiceover.py — deterministic, source-grounded voiceover for cards.

This is MediaHub's answer to the one genuinely portable idea in topic-to-video
engines like Pixelle-Video: *finished assembled audio over a video*. Everything
else those engines do (AI-written scripts, AI-generated imagery, digital-human
avatars) is rejected — it manufactures content where MediaHub's whole value is
rendering verified facts with zero invention.

So the rule here is strict and load-bearing:

    The spoken text is the already-approved caption, **verbatim**.

There is no LLM in this module. We do not draft, summarise, or embellish a script —
narrating an AI-written script would re-open the exact fabrication surface (inventing
a PB, misstating a time) that the caption-approval gate exists to close, and a spoken
error is far harder to catch than a written one. The caller passes the human-approved
caption text; we (optionally) apply deterministic pronunciation overrides for swimmer
names, then synthesise.

Synthesis uses `edge-tts` (pure-Python, CPU-only, no GPU). It is an **online**
dependency: it streams audio from a Microsoft endpoint, which means the caption text
leaves the box. That is why the feature is operator-gated and off by default. When
`edge-tts` is not installed or the endpoint is unreachable we raise `VoiceoverError`
— an honest error, in the spirit of `ClaudeUnavailableError` / `ProviderNotConfigured`
— and **never** fall back to a degraded/robot voice or a fabricated clip.

Outputs are cached by content hash under `DATA_DIR/voice_cache/<hash>.{mp3,srt,json}`.
Alongside the MP3 we emit an SRT subtitle track built from the engine's word-boundary
timings, because most social video autoplays muted — the captions are required, not a
nicety. (Burning the SRT into the MP4 is a separate, deferred step; see the repo
CLAUDE.md / council plan. This module produces the grounded audio + subtitle primitive
everything else hangs off.)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

# A neutral British English voice by default — sport clubs in the current wedge
# are UK-centric. Operators can override per deployment; this is a presentation
# choice, not a judgement surface, so a fixed default is correct.
DEFAULT_VOICE = "en-GB-SoniaNeural"

# Subtitle cue grouping — boring, deterministic windows so the same boundaries
# always produce the same SRT.
_MAX_CUE_WORDS = 7
_MAX_CUE_MS = 3000


class VoiceoverError(RuntimeError):
    """Raised when voiceover cannot be produced honestly.

    Covers: edge-tts not installed, the synthesis endpoint unreachable, or the
    engine returning no audio. We surface this rather than emit a fallback voice —
    a silent/clear failure is better than a fake narration of a child's result.
    """


@dataclass(frozen=True)
class WordBoundary:
    """One word with its start offset and duration, in milliseconds."""

    text: str
    offset_ms: int
    duration_ms: int


@dataclass
class VoiceoverResult:
    """The product of a synthesis (or a cache hit)."""

    audio_path: Path
    srt_path: Path
    transcript: str
    voice: str
    duration_ms: int
    cached: bool
    word_boundaries: list[WordBoundary] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Availability + cache plumbing
# ---------------------------------------------------------------------------

def is_available() -> bool:
    """True when the synthesis backend is importable.

    This deliberately does NOT probe the network — reachability is discovered at
    synthesis time and surfaced as `VoiceoverError`, the same honest-error shape
    the LLM wrapper uses. Import-ability is the cheap, side-effect-free signal a
    route uses to decide between 503-unavailable and attempting a render.
    """
    try:
        import edge_tts  # noqa: F401
    except Exception:
        return False
    return True


def _data_dir() -> Path:
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def cache_dir() -> Path:
    d = _data_dir() / "voice_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_key(text: str, voice: str) -> str:
    """Stable content hash for (voice, text). NUL separator avoids collisions."""
    payload = f"{voice}\x00{text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:24]


# ---------------------------------------------------------------------------
# SRT building (pure, deterministic)
# ---------------------------------------------------------------------------

def _fmt_ts(ms: int) -> str:
    ms = max(0, int(ms))
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, msec = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{msec:03d}"


def build_srt(boundaries: list[WordBoundary]) -> str:
    """Group word boundaries into readable subtitle cues and render SRT.

    Pure and deterministic: cues break at `_MAX_CUE_WORDS` words or `_MAX_CUE_MS`
    of elapsed time, whichever comes first. Empty input yields an empty string.
    """
    if not boundaries:
        return ""

    cues: list[tuple[int, int, str]] = []
    cur: list[WordBoundary] = []

    def _flush() -> None:
        if not cur:
            return
        start = cur[0].offset_ms
        end = cur[-1].offset_ms + max(0, cur[-1].duration_ms)
        text = " ".join(w.text for w in cur).strip()
        if text:
            cues.append((start, end, text))

    for wb in boundaries:
        if cur:
            span = (wb.offset_ms + wb.duration_ms) - cur[0].offset_ms
            if len(cur) >= _MAX_CUE_WORDS or span > _MAX_CUE_MS:
                _flush()
                cur = []
        cur.append(wb)
    _flush()

    lines: list[str] = []
    for i, (start, end, text) in enumerate(cues, start=1):
        # Guarantee a strictly increasing end so players never reject a zero-length cue.
        if end <= start:
            end = start + 1
        lines.append(str(i))
        lines.append(f"{_fmt_ts(start)} --> {_fmt_ts(end)}")
        lines.append(text)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

def _synthesize_raw(text: str, voice: str) -> tuple[bytes, list[WordBoundary]]:
    """Call edge-tts and return (mp3_bytes, word_boundaries).

    Isolated so the entire network/codec surface sits behind one seam that tests
    monkeypatch. Any failure (missing dependency, unreachable endpoint, empty
    audio) becomes a `VoiceoverError` — there is no fallback path.
    """
    try:
        import edge_tts
    except Exception as exc:  # pragma: no cover - exercised via is_available()
        raise VoiceoverError(
            "Text-to-speech backend (edge-tts) is not installed."
        ) from exc

    async def _run() -> tuple[bytes, list[WordBoundary]]:
        communicate = edge_tts.Communicate(text, voice)
        audio = bytearray()
        boundaries: list[WordBoundary] = []
        async for chunk in communicate.stream():
            ctype = chunk.get("type")
            if ctype == "audio" and chunk.get("data"):
                audio.extend(chunk["data"])
            elif ctype == "WordBoundary":
                # edge-tts reports offset/duration in 100-nanosecond units.
                boundaries.append(
                    WordBoundary(
                        text=str(chunk.get("text", "")),
                        offset_ms=int(chunk.get("offset", 0)) // 10_000,
                        duration_ms=int(chunk.get("duration", 0)) // 10_000,
                    )
                )
        return bytes(audio), boundaries

    try:
        audio_bytes, boundaries = asyncio.run(_run())
    except VoiceoverError:
        raise
    except Exception as exc:
        raise VoiceoverError(f"Text-to-speech synthesis failed: {exc}") from exc

    if not audio_bytes:
        raise VoiceoverError("Text-to-speech returned no audio.")
    return audio_bytes, boundaries


def synthesize(
    text: str,
    *,
    voice: str = DEFAULT_VOICE,
    run_id: str | None = None,
    apply_pronunciation: bool = True,
) -> VoiceoverResult:
    """Synthesise a voiceover for the (already-approved) caption `text`, verbatim.

    The text is spoken as given, after an optional deterministic pronunciation
    pre-pass for swimmer names (no AI). Output is cached by content hash; a second
    call with the same text+voice returns the cached artefacts without re-synthesis.

    Raises:
        ValueError: if `text` is empty after stripping.
        VoiceoverError: if synthesis is unavailable or fails (honest error; no
            fallback voice is ever produced).
    """
    spoken = (text or "").strip()
    if not spoken:
        raise ValueError("voiceover text is empty")

    if apply_pronunciation:
        from . import pronunciation
        spoken = pronunciation.pronounce(spoken, run_id)

    key = cache_key(spoken, voice)
    cdir = cache_dir()
    mp3_path = cdir / f"{key}.mp3"
    srt_path = cdir / f"{key}.srt"
    json_path = cdir / f"{key}.json"

    if mp3_path.exists() and mp3_path.stat().st_size > 0 and json_path.exists():
        try:
            meta = json.loads(json_path.read_text())
            boundaries = [
                WordBoundary(b["text"], int(b["offset_ms"]), int(b["duration_ms"]))
                for b in meta.get("word_boundaries", [])
            ]
            return VoiceoverResult(
                audio_path=mp3_path,
                srt_path=srt_path,
                transcript=meta.get("transcript", spoken),
                voice=meta.get("voice", voice),
                duration_ms=int(meta.get("duration_ms", 0)),
                cached=True,
                word_boundaries=boundaries,
            )
        except (OSError, ValueError, KeyError):
            # Corrupt sidecar → fall through and re-synthesise.
            pass

    audio_bytes, boundaries = _synthesize_raw(spoken, voice)
    duration_ms = (
        boundaries[-1].offset_ms + boundaries[-1].duration_ms if boundaries else 0
    )
    srt = build_srt(boundaries)

    mp3_path.write_bytes(audio_bytes)
    srt_path.write_text(srt)
    json_path.write_text(
        json.dumps(
            {
                "transcript": spoken,
                "voice": voice,
                "duration_ms": duration_ms,
                "created_at": time.time(),
                "word_boundaries": [
                    {"text": b.text, "offset_ms": b.offset_ms, "duration_ms": b.duration_ms}
                    for b in boundaries
                ],
            },
            indent=2,
        )
    )

    return VoiceoverResult(
        audio_path=mp3_path,
        srt_path=srt_path,
        transcript=spoken,
        voice=voice,
        duration_ms=duration_ms,
        cached=False,
        word_boundaries=boundaries,
    )
