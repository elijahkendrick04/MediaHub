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

Synthesis is provider-selected via ``MEDIAHUB_TTS_PROVIDER`` (roadmap P0.4 — every
AI surface carries a local-capable provider slot). Roadmap **1.7** made the local
backend the default — *Piper replaces edge-tts* — so the zero-cost, fully-offline
path is what a deployment uses unless an operator deliberately opts into the
online one:

    piper  (default) the local-TTS backend (Piper, GPL-3.0-or-later) —
           **zero-cost and fully offline**: the caption text never leaves the
           box. The deployed image ships a licence-clean voice (CC BY 4.0
           ``en_GB-alba-medium``) so this works out of the box; an operator can
           also point ``MEDIAHUB_PIPER_MODEL`` at a Piper ``.onnx`` voice model,
           set ``MEDIAHUB_PIPER_VOICE`` + ``MEDIAHUB_PIPER_VOICE_DIR``, or simply
           drop a single ``.onnx`` into the voice dir (auto-discovered). We load
           it with the ``piper-tts`` package, synthesise a WAV, and transcode it
           to the same MP3 the rest of the pipeline already consumes. If the
           package or the model file is absent we raise `VoiceoverError`
           honestly — never a silent fall back to the online backend or a
           fabricated clip.
    edge   the opt-in online alternative, `edge-tts` — pure-Python, CPU-only, no
           GPU, but an **online** dependency: it streams audio from a Microsoft
           endpoint, which means the caption text leaves the box. It is no longer
           the default (1.7); select it explicitly with
           ``MEDIAHUB_TTS_PROVIDER=edge`` when a deployment genuinely wants it.

           Piper does not emit word-level timestamps, so the Piper SRT cue
           *timings* are a deterministic estimate (the measured clip duration
           distributed across the words by length). The spoken words are still
           the verbatim approved caption — only the on-screen subtitle timing is
           approximated, a presentation choice that never touches a stated
           result.

When the selected backend is not installed or unreachable we raise `VoiceoverError`
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
import importlib.util
import io
import json
import os
import subprocess
import time
import wave
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

    Covers: the selected TTS backend not installed, the synthesis endpoint
    unreachable, or the engine returning no audio. We surface this rather than
    emit a fallback voice — a silent/clear failure is better than a fake
    narration of a child's result.
    """


# ---------------------------------------------------------------------------
# Provider selection (P0.4 — local-capable slot for the TTS surface)
# ---------------------------------------------------------------------------

_VALID_TTS_PROVIDERS: frozenset[str] = frozenset({"edge", "piper"})
# Roadmap 1.7 — Piper (local, zero-cost, fully offline) replaced edge-tts as the
# default. The online 'edge' backend stays selectable for operators who want it.
_DEFAULT_TTS_PROVIDER = "piper"


def select_tts_provider() -> str:
    """Return the active TTS provider name.

    Reads ``MEDIAHUB_TTS_PROVIDER``; unset/blank means the default ``'piper'``
    (roadmap 1.7 — the zero-cost, fully-offline local backend). An unrecognised
    value raises `VoiceoverError` — an honest configuration error beats silently
    synthesising with the wrong backend.
    """
    raw = os.environ.get("MEDIAHUB_TTS_PROVIDER", "").strip().lower()
    if not raw:
        return _DEFAULT_TTS_PROVIDER
    if raw not in _VALID_TTS_PROVIDERS:
        raise VoiceoverError(
            f"MEDIAHUB_TTS_PROVIDER={raw!r} is not a recognised TTS provider. "
            f"Valid choices: {sorted(_VALID_TTS_PROVIDERS)}. 'piper' is the "
            "default zero-cost local backend (ships a voice model; also reads "
            "MEDIAHUB_PIPER_MODEL); 'edge' is the opt-in online alternative."
        )
    return raw


def tts_provider_status() -> dict:
    """Diagnostics dict for health / observability surfaces.

    Mirrors ``reel_engine_status()``: configured raw value, resolved active
    provider (bad values echoed verbatim), per-provider availability, and
    the list of providers that would synthesise right now.
    """
    configured = os.environ.get("MEDIAHUB_TTS_PROVIDER", "").strip()
    try:
        active = select_tts_provider()
    except VoiceoverError:
        active = configured
    try:
        import edge_tts  # noqa: F401

        edge_ok = True
    except Exception:
        edge_ok = False
    piper_ok = _piper_available()
    resolved = _resolve_piper_model()
    piper_model = str(resolved[0]) if resolved else ""
    available = [name for name, ok in (("edge", edge_ok), ("piper", piper_ok)) if ok]
    return {
        "configured": configured,
        "active": active,
        "edge_available": edge_ok,
        "piper_available": piper_ok,
        "piper_model": piper_model,
        "available_providers": available,
    }


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
    """True when the *selected* synthesis backend is importable.

    This deliberately does NOT probe the network — reachability is discovered at
    synthesis time and surfaced as `VoiceoverError`, the same honest-error shape
    the LLM wrapper uses. Import-ability is the cheap, side-effect-free signal a
    route uses to decide between 503-unavailable and attempting a render.
    """
    try:
        provider = select_tts_provider()
    except VoiceoverError:
        return False
    if provider == "piper":
        return _piper_available()
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


def _cache_voice(voice: str) -> str:
    """The voice identity folded into the cache key for the active provider.

    For ``edge`` this is exactly the voice name, so existing edge cache keys
    stay byte-identical (a hard requirement — the silent/edge path must not
    churn). For ``piper`` it is namespaced by provider + the configured model
    identity, so switching providers (or Piper voices) can never serve one
    backend's cached MP3 under another's key. The Piper output does not depend
    on the edge ``voice`` name, so it is deliberately excluded from the Piper
    key (two edge-voice names share one Piper render — correct, not a bug).
    """
    try:
        provider = select_tts_provider()
    except VoiceoverError:
        return voice
    if provider != "piper":
        return voice
    model = os.environ.get("MEDIAHUB_PIPER_MODEL", "").strip()
    name = os.environ.get("MEDIAHUB_PIPER_VOICE", "").strip()
    return f"piper:{model or name or 'default'}"


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
# Piper — the zero-cost, fully-offline local backend (roadmap R1.21)
# ---------------------------------------------------------------------------
#
# Piper (https://github.com/OHF-Voice/piper1-gpl, GPL-3.0-or-later) runs a small
# neural TTS model entirely on CPU with no network and no API key — a ``.onnx``
# voice file is supplied (the deployed image ships a CC BY 4.0 default; an
# operator can swap it). Used server-side in MediaHub's hosted-only deployment,
# never conveyed to customers, so the GPL imposes no source-offer obligation
# (the same hosted-only basis the repo already relies on for AGPL SearXNG).
# The implementation stays behind the same
# `_synthesize_raw` seam as edge so the rest of the pipeline (cache, SRT, route,
# audio mux) is untouched: it returns the same ``(mp3_bytes, word_boundaries)``
# tuple. Every failure mode (package absent, model absent, ffmpeg absent, empty
# audio) raises `VoiceoverError` — there is no fabricated-voice fallback.

# Leading/trailing punctuation is stripped only to weight a word's share of the
# clip duration; the word itself is emitted verbatim into the SRT.
_PUNCT = " \t\r\n.,!?;:—–-…\"'“”‘’()[]{}"


def _piper_voice_dir() -> Path:
    """Directory searched for named Piper voices (`MEDIAHUB_PIPER_VOICE`)."""
    raw = os.environ.get("MEDIAHUB_PIPER_VOICE_DIR", "").strip()
    if raw:
        return Path(raw)
    return _data_dir() / "piper_voices"


def _autodiscover_piper_model() -> Path | None:
    """The bundled/dropped-in default voice: a single ``.onnx`` in the voice dir.

    Roadmap 1.7 ships a licence-clean default voice and makes Piper the default
    provider, so a deployment must narrate locally with **no env configuration**.
    When neither ``MEDIAHUB_PIPER_MODEL`` nor ``MEDIAHUB_PIPER_VOICE`` is set we
    scan `_piper_voice_dir` for ``*.onnx`` and use it. Deterministic: with one
    voice present it is used; with several we pick the lexicographically-first so
    the choice is stable, never random. An absent/empty dir → ``None``, which
    preserves the honest "no model configured" error path exactly as before.
    """
    vdir = _piper_voice_dir()
    if not vdir.is_dir():
        return None
    try:
        onnx = sorted(p for p in vdir.glob("*.onnx") if p.is_file())
    except OSError:
        return None
    return onnx[0] if onnx else None


def _resolve_piper_model() -> tuple[Path, Path | None] | None:
    """Locate the configured Piper model + its config, without raising.

    Resolution order:
      1. ``MEDIAHUB_PIPER_MODEL`` — an explicit path to a ``.onnx`` voice model.
      2. ``MEDIAHUB_PIPER_VOICE`` — a voice name looked up in `_piper_voice_dir`
         (``<voice>.onnx``).
      3. **Auto-discovery** (1.7) — a single ``.onnx`` dropped into / bundled in
         `_piper_voice_dir`, so the shipped default voice works with no env set.

    The config sidecar is ``MEDIAHUB_PIPER_CONFIG`` when set, else the Piper
    convention ``<model>.onnx.json`` beside the model when it exists (Piper can
    also auto-discover it, so ``None`` is acceptable). Returns ``None`` when no
    model is configured or the model file is missing — the side-effect-free
    signal `_piper_available` / `tts_provider_status` use to report readiness.
    """
    explicit = os.environ.get("MEDIAHUB_PIPER_MODEL", "").strip()
    if explicit:
        model = Path(explicit)
    else:
        name = os.environ.get("MEDIAHUB_PIPER_VOICE", "").strip()
        if name:
            if not name.endswith(".onnx"):
                name += ".onnx"
            model = _piper_voice_dir() / name
        else:
            model = _autodiscover_piper_model()
            if model is None:
                return None
    if not model.is_file():
        return None

    cfg_override = os.environ.get("MEDIAHUB_PIPER_CONFIG", "").strip()
    if cfg_override:
        cfg = Path(cfg_override)
        return model, (cfg if cfg.is_file() else None)
    sibling = model.with_name(model.name + ".json")  # foo.onnx -> foo.onnx.json
    return model, (sibling if sibling.is_file() else None)


def _require_piper_model() -> tuple[Path, Path | None]:
    """Like `_resolve_piper_model`, but raise an honest `VoiceoverError` that
    tells the operator exactly what to configure (the "model is absent" case
    R1.21 calls out)."""
    resolved = _resolve_piper_model()
    if resolved is not None:
        return resolved
    explicit = os.environ.get("MEDIAHUB_PIPER_MODEL", "").strip()
    name = os.environ.get("MEDIAHUB_PIPER_VOICE", "").strip()
    if explicit:
        raise VoiceoverError(
            f"The Piper TTS backend is selected but no model file exists at "
            f"MEDIAHUB_PIPER_MODEL={explicit!r}. Point it at a Piper '.onnx' "
            "voice model, or set MEDIAHUB_TTS_PROVIDER=edge."
        )
    if name:
        raise VoiceoverError(
            f"The Piper TTS backend is selected but the voice {name!r} was not "
            f"found in {_piper_voice_dir()}. Put a '<voice>.onnx' there, set "
            "MEDIAHUB_PIPER_MODEL to an explicit path, or set "
            "MEDIAHUB_TTS_PROVIDER=edge."
        )
    raise VoiceoverError(
        "The Piper TTS backend is selected but no voice model is configured. "
        f"Drop a Piper '.onnx' voice into {_piper_voice_dir()} (auto-discovered), "
        "set MEDIAHUB_PIPER_MODEL to a '.onnx' file (or MEDIAHUB_PIPER_VOICE + "
        "MEDIAHUB_PIPER_VOICE_DIR), or set MEDIAHUB_TTS_PROVIDER=edge."
    )


def _ffmpeg_exe() -> str | None:
    """The FFmpeg binary used to transcode Piper's WAV to MP3 — reusing the
    renderer's resolver (PATH / imageio-ffmpeg / MEDIAHUB_FFMPEG) so the whole
    deployment agrees on one binary. ``None`` when none is resolvable."""
    try:
        from mediahub.visual.reel_ffmpeg import ffmpeg_exe

        return ffmpeg_exe()
    except Exception:
        return None


def _piper_available() -> bool:
    """True when a Piper synthesis would plausibly succeed right now.

    Checks, side-effect-free and network-free: the ``piper`` package is
    importable (via `find_spec`, so onnxruntime is never loaded just to probe),
    a voice model file is configured and present, and an FFmpeg binary is
    resolvable for the WAV→MP3 encode. The opposite of "implemented" — it is the
    honest "the local model is here" signal R1.21 requires.
    """
    try:
        if importlib.util.find_spec("piper") is None:
            return False
    except Exception:
        return False
    if _resolve_piper_model() is None:
        return False
    return bool(_ffmpeg_exe())


def _piper_wav_bytes(text: str, model_path: Path, config_path: Path | None) -> bytes:
    """Synthesise ``text`` with Piper and return a complete WAV as bytes.

    This is the single Piper-touching seam (tests monkeypatch it, exactly as the
    edge path's network call is patched). Importing ``piper`` or loading the
    model failing becomes a `VoiceoverError` — never a fallback.
    """
    try:
        from piper import PiperVoice
    except Exception as exc:
        raise VoiceoverError(
            "The local Piper TTS backend is selected but the 'piper-tts' "
            "package is not installed. Install it (pip install piper-tts) or "
            "set MEDIAHUB_TTS_PROVIDER=edge."
        ) from exc

    try:
        if config_path is not None:
            try:
                voice = PiperVoice.load(str(model_path), config_path=str(config_path))
            except TypeError:
                voice = PiperVoice.load(str(model_path))
        else:
            voice = PiperVoice.load(str(model_path))
    except Exception as exc:
        raise VoiceoverError(
            f"Failed to load the Piper voice model at {model_path}: {exc}"
        ) from exc

    buf = io.BytesIO()
    try:
        with wave.open(buf, "wb") as wav_out:
            synth_wav = getattr(voice, "synthesize_wav", None)
            if callable(synth_wav):
                synth_wav(text, wav_out)  # modern piper-tts (>=1.0)
            else:
                voice.synthesize(text, wav_out)  # older API wrote the WAV directly
    except Exception as exc:
        raise VoiceoverError(f"Piper synthesis failed: {exc}") from exc

    data = buf.getvalue()
    if not data:
        raise VoiceoverError("Piper synthesis produced no audio.")
    return data


def _wav_duration_ms(wav_bytes: bytes) -> int:
    """Total duration of a WAV clip in milliseconds (stdlib, no subprocess)."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            frames = w.getnframes()
            rate = w.getframerate()
    except (wave.Error, EOFError, OSError) as exc:
        raise VoiceoverError(f"Piper produced audio that is not valid WAV: {exc}") from exc
    if rate <= 0:
        return 0
    return int(round(frames / rate * 1000))


def _wav_to_mp3(wav_bytes: bytes) -> bytes:
    """Transcode WAV bytes to MP3 via FFmpeg (stdin→stdout, no temp files).

    Keeps the seam contract identical to edge: callers always receive genuine
    MP3 bytes for the ``<hash>.mp3`` cache file the route serves as
    ``audio/mpeg``. A missing FFmpeg binary or a non-zero exit raises
    `VoiceoverError` — honest, never a half-written/placeholder file.
    """
    exe = _ffmpeg_exe()
    if not exe:
        raise VoiceoverError(
            "FFmpeg is required to encode the Piper audio to MP3, but no FFmpeg "
            "binary was found. Install ffmpeg (or the imageio-ffmpeg package), "
            "put it on PATH, or set MEDIAHUB_FFMPEG to its path."
        )
    cmd = [
        exe,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "wav",
        "-i",
        "pipe:0",
        "-c:a",
        "libmp3lame",
        "-b:a",
        "128k",
        "-f",
        "mp3",
        "pipe:1",
    ]
    try:
        proc = subprocess.run(cmd, input=wav_bytes, capture_output=True, timeout=120)
    except Exception as exc:
        raise VoiceoverError(f"FFmpeg failed to encode the Piper audio: {exc}") from exc
    if proc.returncode != 0 or not proc.stdout:
        tail = (proc.stderr or b"").decode("utf-8", "replace").strip().splitlines()
        msg = "\n".join(tail[-6:]) if tail else "(no stderr)"
        raise VoiceoverError(f"FFmpeg failed to encode the Piper audio to MP3:\n{msg}")
    return proc.stdout


def _estimate_word_boundaries(text: str, total_ms: int) -> list[WordBoundary]:
    """Deterministically distribute ``total_ms`` across the words of ``text``.

    Piper does not emit word-level timestamps, so we approximate them for the
    SRT by giving each word a share of the measured clip duration proportional
    to its length (a floor of 1 so punctuation-only tokens still advance). The
    cumulative end is rounded each step so there is no drift and the final word
    ends exactly at ``total_ms``. Pure and deterministic: same text + duration →
    same boundaries.
    """
    words = text.split()
    if not words or total_ms <= 0:
        return []
    weights = [max(1, len(w.strip(_PUNCT))) for w in words]
    total_w = sum(weights)
    boundaries: list[WordBoundary] = []
    elapsed = 0
    acc = 0
    for word, weight in zip(words, weights):
        acc += weight
        end = int(round(total_ms * acc / total_w))
        if end <= elapsed:
            end = min(total_ms, elapsed + 1)
        boundaries.append(WordBoundary(word, elapsed, max(1, end - elapsed)))
        elapsed = end
    return boundaries


def _synthesize_piper(text: str, voice: str) -> tuple[bytes, list[WordBoundary]]:
    """The Piper branch of `_synthesize_raw`: resolve the model, synthesise a
    WAV, transcode to MP3, and estimate word boundaries for the SRT. The edge
    ``voice`` name is not a Piper concept (the model fixes the voice), so it is
    accepted and ignored — the cache is namespaced by the Piper model instead
    (see `_cache_voice`)."""
    model_path, config_path = _require_piper_model()
    wav_bytes = _piper_wav_bytes(text, model_path, config_path)
    total_ms = _wav_duration_ms(wav_bytes)
    mp3_bytes = _wav_to_mp3(wav_bytes)
    boundaries = _estimate_word_boundaries(text, total_ms)
    return mp3_bytes, boundaries


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------


def _synthesize_raw(text: str, voice: str) -> tuple[bytes, list[WordBoundary]]:
    """Call the selected TTS backend and return (mp3_bytes, word_boundaries).

    Isolated so the entire network/codec surface sits behind one seam that tests
    monkeypatch. Dispatches on `select_tts_provider`; any failure (missing
    dependency, unreachable endpoint, missing model, empty audio) becomes a
    `VoiceoverError` — there is no fallback path.
    """
    provider = select_tts_provider()
    if provider == "piper":
        return _synthesize_piper(text, voice)
    return _synthesize_edge(text, voice)


def _synthesize_edge(text: str, voice: str) -> tuple[bytes, list[WordBoundary]]:
    """The default `edge-tts` backend: streams MP3 + native word boundaries from
    the Microsoft endpoint (online; the reason voiceover is opt-in)."""
    try:
        import edge_tts
    except Exception as exc:  # pragma: no cover - exercised via is_available()
        raise VoiceoverError("Text-to-speech backend (edge-tts) is not installed.") from exc

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

    key = cache_key(spoken, _cache_voice(voice))
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
    duration_ms = boundaries[-1].offset_ms + boundaries[-1].duration_ms if boundaries else 0
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
