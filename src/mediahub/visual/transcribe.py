"""
visual/transcribe.py — local speech-to-text (ASR) with word-level timing (roadmap 1.4).

This is the ASR twin of :mod:`mediahub.visual.voiceover`: where voiceover *speaks*
an already-approved caption, this module *listens* — it turns an uploaded audio (or
video) clip into a transcript with **per-word timestamps**, the primitive the video
suite (roadmap 1.6) burns onto muted feed video as word-level captions, and the
server path the copilot's voice input rides for uploaded audio.

Two honest rules, both load-bearing:

* **No invention.** ASR is *transcription*, not judgement — it reports the words
  that were actually spoken, with their measured timings. There is no LLM in this
  module (a structural test pins that), and there is no fabricated transcript: when
  the backend is unavailable we raise :class:`ASRUnavailable`, in the exact spirit
  of ``VoiceoverError`` / ``ClaudeUnavailableError``.
* **Local-first, behind a provider seam (P0.4).** Synthesis is selected via
  ``MEDIAHUB_ASR_PROVIDER`` — the same env-keyed doctrine as the LLM/TTS surfaces —
  so no cloud key is ever *required* by this interface:

      faster-whisper  (recommended) the MIT ``faster-whisper`` backend — a
                      CTranslate2 reimplementation of OpenAI Whisper that runs
                      **fully offline on CPU** and emits true word-level
                      timestamps (``word_timestamps=True``). The operator picks
                      the model with ``MEDIAHUB_WHISPER_MODEL`` (default
                      ``base``); on first use the weights download once to the
                      HuggingFace cache (or pre-place them under
                      ``MEDIAHUB_WHISPER_MODEL_DIR`` for a no-network box).
      whisper.cpp     the ``pywhispercpp`` bindings to whisper.cpp (also MIT,
                      also offline). It reports **segment**-level timings; the
                      per-word split inside a segment is a deterministic estimate
                      (length-weighted, like Piper's SRT timing) — the words are
                      exact, only their in-segment placement is approximated.

When the selected backend's package or model is absent we raise
:class:`ASRUnavailable` honestly — never a silent fall back to a cloud service or a
made-up transcript. The default (no provider configured) is also an honest
``ASRUnavailable``: the live copilot voice path is the browser's on-device Web
Speech API, which needs no server ASR at all.

Transcripts are cached by audio content-hash under
``DATA_DIR/asr_cache/<hash>.json`` so a re-run (or a second consumer) never
re-transcribes the same clip.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

# Canonical provider names + the aliases an operator might reasonably type. The
# bare ``whisper`` maps to the faster-whisper (CTranslate2) backend — it is the
# in-process, word-timestamped default this seam ships.
_FASTER_WHISPER = "faster-whisper"
_WHISPER_CPP = "whisper.cpp"
_VALID_ASR_PROVIDERS: frozenset[str] = frozenset({_FASTER_WHISPER, _WHISPER_CPP})
_PROVIDER_ALIASES: dict[str, str] = {
    "faster-whisper": _FASTER_WHISPER,
    "faster_whisper": _FASTER_WHISPER,
    "fasterwhisper": _FASTER_WHISPER,
    "whisper": _FASTER_WHISPER,
    "openai-whisper": _FASTER_WHISPER,
    "whisper.cpp": _WHISPER_CPP,
    "whisper-cpp": _WHISPER_CPP,
    "whispercpp": _WHISPER_CPP,
    "pywhispercpp": _WHISPER_CPP,
}

# A small, fast, accurate-enough default for CPU transcription of short club
# clips. The operator can trade speed for accuracy via MEDIAHUB_WHISPER_MODEL
# (tiny | base | small | medium | large-v3, or a path under the model dir).
DEFAULT_WHISPER_MODEL = "base"

# Map an upload's declared content type to a file suffix so the backend's
# decoder (PyAV / ffmpeg) has a format hint; the bytes are sniffed regardless,
# so an unknown type just gets a neutral suffix.
_CT_SUFFIX: dict[str, str] = {
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
    "audio/oga": ".ogg",
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/mp4": ".m4a",
    "audio/x-m4a": ".m4a",
    "audio/aac": ".aac",
    "audio/flac": ".flac",
    "video/mp4": ".mp4",
    "video/webm": ".webm",
    "video/quicktime": ".mov",
}

# Leading/trailing punctuation stripped only to weight a word's share of a
# segment when a backend gives no per-word timing; the word is emitted verbatim.
_PUNCT = " \t\r\n.,!?;:—–-…\"'“”‘’()[]{}"


class ASRUnavailable(RuntimeError):
    """Raised when speech-to-text cannot be produced honestly.

    Covers every honest-failure mode — no provider configured, the selected
    backend package not installed, its model unobtainable, the decoder failing,
    or empty audio out of the engine. We surface this rather than emit a
    fabricated transcript: a clear error is always better than invented words
    attributed to a real person.
    """


# ---------------------------------------------------------------------------
# Provider selection (P0.4 — the local-capable slot for the ASR surface)
# ---------------------------------------------------------------------------


def select_asr_provider() -> str:
    """Return the canonical active ASR provider name, or ``""`` when none is set.

    Reads ``MEDIAHUB_ASR_PROVIDER`` and folds known aliases onto their canonical
    name. Unset/blank → ``""`` (no server ASR; the browser's on-device speech is
    the live copilot path). An unrecognised value raises :class:`ASRUnavailable`
    — an honest configuration error beats silently transcribing with a backend
    the operator didn't ask for, mirroring ``voiceover.select_tts_provider``.
    """
    raw = os.environ.get("MEDIAHUB_ASR_PROVIDER", "").strip().lower()
    if not raw:
        return ""
    canon = _PROVIDER_ALIASES.get(raw, raw)
    if canon not in _VALID_ASR_PROVIDERS:
        raise ASRUnavailable(
            f"MEDIAHUB_ASR_PROVIDER={raw!r} is not a recognised ASR provider. "
            f"Valid choices: {sorted(_VALID_ASR_PROVIDERS)} (aliases 'whisper'/"
            "'faster_whisper' → faster-whisper, 'whispercpp' → whisper.cpp). "
            "Leave it unset to use the browser's on-device speech capture."
        )
    return canon


def _whisper_model_id() -> str:
    """The configured Whisper model name/path (``MEDIAHUB_WHISPER_MODEL``)."""
    return os.environ.get("MEDIAHUB_WHISPER_MODEL", "").strip() or DEFAULT_WHISPER_MODEL


def _faster_whisper_available() -> bool:
    """True when the ``faster-whisper`` package is importable (side-effect-free).

    Uses :func:`importlib.util.find_spec` so CTranslate2/onnxruntime are never
    loaded just to probe readiness. The model itself is fetched/cached lazily on
    first transcription, so package-importability is the honest "this backend
    could run" signal — the analogue of ``voiceover._piper_available``.
    """
    try:
        return importlib.util.find_spec("faster_whisper") is not None
    except Exception:
        return False


def _whispercpp_available() -> bool:
    """True when the ``pywhispercpp`` (whisper.cpp) bindings are importable."""
    try:
        return importlib.util.find_spec("pywhispercpp") is not None
    except Exception:
        return False


def _provider_available(provider: str) -> bool:
    if provider == _FASTER_WHISPER:
        return _faster_whisper_available()
    if provider == _WHISPER_CPP:
        return _whispercpp_available()
    return False


def is_available() -> bool:
    """True when the *selected* ASR backend could transcribe right now.

    Side-effect-free and network-free: a configured-but-unrecognised provider,
    or one whose package is absent, returns ``False`` (the route then answers an
    honest 503 rather than attempting a doomed transcription).
    """
    try:
        provider = select_asr_provider()
    except ASRUnavailable:
        return False
    if not provider:
        return False
    return _provider_available(provider)


def asr_provider_status() -> dict:
    """Diagnostics dict for the health / observability surfaces.

    Mirrors ``voiceover.tts_provider_status`` / ``reel_engine_status``: the raw
    configured value, the resolved active provider (a bad value echoed
    verbatim), per-backend availability, the resolved model, and the list of
    backends that would transcribe right now.
    """
    configured = os.environ.get("MEDIAHUB_ASR_PROVIDER", "").strip()
    try:
        active = select_asr_provider()
    except ASRUnavailable:
        active = configured.lower()
    fw_ok = _faster_whisper_available()
    cpp_ok = _whispercpp_available()
    available = [name for name, ok in ((_FASTER_WHISPER, fw_ok), (_WHISPER_CPP, cpp_ok)) if ok]
    return {
        "configured": configured,
        "active": active,
        "faster_whisper_available": fw_ok,
        "whisper_cpp_available": cpp_ok,
        "model": _whisper_model_id(),
        "available_providers": available,
    }


# ---------------------------------------------------------------------------
# Result shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WordStamp:
    """One spoken word with its start/end offset in milliseconds."""

    text: str
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return max(0, self.end_ms - self.start_ms)


@dataclass(frozen=True)
class TranscriptSegment:
    """A contiguous spoken segment: its span, its text, and its word stamps.

    ``words`` is empty when the backend reported only segment-level timing and
    no per-word split was requested.
    """

    start_ms: int
    end_ms: int
    text: str
    words: tuple[WordStamp, ...] = ()


@dataclass
class Transcript:
    """The product of a transcription (or a cache hit)."""

    text: str
    language: str
    duration_ms: int
    segments: list[TranscriptSegment] = field(default_factory=list)
    cached: bool = False
    provider: str = ""
    model: str = ""

    def words(self) -> list[WordStamp]:
        """Flatten every segment's word stamps into one ordered list."""
        return [w for seg in self.segments for w in seg.words]

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "language": self.language,
            "duration_ms": self.duration_ms,
            "provider": self.provider,
            "model": self.model,
            "segments": [
                {
                    "start_ms": s.start_ms,
                    "end_ms": s.end_ms,
                    "text": s.text,
                    "words": [
                        {"text": w.text, "start_ms": w.start_ms, "end_ms": w.end_ms}
                        for w in s.words
                    ],
                }
                for s in self.segments
            ],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Transcript":
        segs: list[TranscriptSegment] = []
        for s in d.get("segments") or []:
            words = tuple(
                WordStamp(str(w.get("text", "")), int(w["start_ms"]), int(w["end_ms"]))
                for w in (s.get("words") or [])
            )
            segs.append(
                TranscriptSegment(
                    int(s.get("start_ms", 0)),
                    int(s.get("end_ms", 0)),
                    str(s.get("text", "")),
                    words,
                )
            )
        return cls(
            text=str(d.get("text", "")),
            language=str(d.get("language", "")),
            duration_ms=int(d.get("duration_ms", 0)),
            segments=segs,
            provider=str(d.get("provider", "")),
            model=str(d.get("model", "")),
        )


# ---------------------------------------------------------------------------
# Cache plumbing
# ---------------------------------------------------------------------------


def _data_dir() -> Path:
    env = os.environ.get("DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def cache_dir() -> Path:
    d = _data_dir() / "asr_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def cache_key(audio_bytes: bytes, provider: str, model: str, language: str, opts: str = "") -> str:
    """Stable content hash for (provider, model, language, options, audio).

    The audio bytes are part of the key, so the same clip transcribed under the
    same settings is served from cache, while a different clip — or a switch of
    backend/model/language/option — re-transcribes. NUL separators keep the
    string fields from colliding.
    """
    h = hashlib.sha256()
    for part in (provider, model, language, opts):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    h.update(audio_bytes)
    return h.hexdigest()[:24]


# ---------------------------------------------------------------------------
# Pure helpers (deterministic; no backend)
# ---------------------------------------------------------------------------


def _sec_to_ms(value) -> int:
    try:
        return max(0, int(round(float(value) * 1000)))
    except (TypeError, ValueError):
        return 0


def _suffix_for(content_type: str) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    return _CT_SUFFIX.get(ct, ".audio")


def _estimate_word_stamps(text: str, start_ms: int, end_ms: int) -> list[WordStamp]:
    """Distribute ``[start_ms, end_ms]`` across the words of ``text`` by length.

    The honest fallback for a backend that times only whole segments
    (whisper.cpp): the words are exact, their in-segment placement proportional
    to their character length. Pure and deterministic — same inputs, same
    stamps. Mirrors ``voiceover._estimate_word_boundaries``.
    """
    words = text.split()
    span = max(0, end_ms - start_ms)
    if not words or span <= 0:
        return []
    weights = [max(1, len(w.strip(_PUNCT))) for w in words]
    total = sum(weights)
    out: list[WordStamp] = []
    elapsed = start_ms
    acc = 0
    for word, weight in zip(words, weights):
        acc += weight
        end = start_ms + int(round(span * acc / total))
        if end <= elapsed:
            end = min(end_ms, elapsed + 1)
        out.append(WordStamp(word, elapsed, end))
        elapsed = end
    return out


def _segments_from_whisper(segments, *, word_timestamps: bool) -> list[TranscriptSegment]:
    """Convert faster-whisper ``Segment`` objects to :class:`TranscriptSegment`.

    ``segments`` is faster-whisper's lazy generator; iterating it is what runs
    the transcription. Word stamps are taken verbatim from the backend when
    present, else the segment carries no per-word split.
    """
    out: list[TranscriptSegment] = []
    for seg in segments:
        s_ms = _sec_to_ms(getattr(seg, "start", 0.0))
        e_ms = _sec_to_ms(getattr(seg, "end", 0.0))
        text = (getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        words: tuple[WordStamp, ...] = ()
        raw_words = getattr(seg, "words", None)
        if word_timestamps and raw_words:
            ws: list[WordStamp] = []
            for w in raw_words:
                wt = (getattr(w, "word", None) or getattr(w, "text", "") or "").strip()
                if not wt:
                    continue
                a = _sec_to_ms(getattr(w, "start", getattr(seg, "start", 0.0)))
                b = _sec_to_ms(getattr(w, "end", getattr(seg, "end", 0.0)))
                ws.append(WordStamp(wt, a, max(a, b)))
            words = tuple(ws)
        out.append(TranscriptSegment(s_ms, e_ms, text, words))
    return out


def _build_transcript(
    segments: list[TranscriptSegment],
    language: str,
    duration_sec: float,
    *,
    provider: str,
    model: str,
) -> Transcript:
    text = " ".join(s.text for s in segments).strip()
    duration_ms = _sec_to_ms(duration_sec)
    if not duration_ms and segments:
        duration_ms = segments[-1].end_ms
    return Transcript(
        text=text,
        language=(language or ""),
        duration_ms=duration_ms,
        segments=segments,
        provider=provider,
        model=model,
    )


# ---------------------------------------------------------------------------
# Backends — each lazy-imports its dependency (P0.4 seam: the whisper imports
# live ONLY in this module; tests/test_local_provider_slots.py pins that).
# ---------------------------------------------------------------------------

# Loaded backend models, memoised for the worker's lifetime. Model load is the
# expensive part (seconds of weight allocation on CPU); the key carries every
# env-derived load parameter so an env change picks up a fresh instance.
_MODEL_CACHE: dict[tuple, object] = {}
_MODEL_CACHE_LOCK = threading.Lock()


def _cached_model(key: tuple, loader):
    """Return the memoised backend model for ``key``, loading it once."""
    with _MODEL_CACHE_LOCK:
        model = _MODEL_CACHE.get(key)
        if model is None:
            model = loader()
            _MODEL_CACHE[key] = model
        return model


def _transcribe_faster_whisper(
    audio_bytes: bytes,
    model: str,
    language: str,
    word_timestamps: bool,
    content_type: str,
    vad: bool,
) -> Transcript:
    """The faster-whisper backend: offline CPU transcription with real word stamps."""
    try:
        from faster_whisper import WhisperModel
    except Exception as exc:
        raise ASRUnavailable(
            "The faster-whisper ASR backend is selected but the "
            "'faster-whisper' package is not installed. Install it "
            "(pip install faster-whisper) or unset MEDIAHUB_ASR_PROVIDER to use "
            "the browser's on-device speech capture."
        ) from exc

    device = os.environ.get("MEDIAHUB_WHISPER_DEVICE", "cpu").strip() or "cpu"
    compute = os.environ.get("MEDIAHUB_WHISPER_COMPUTE", "int8").strip() or "int8"
    download_root = os.environ.get("MEDIAHUB_WHISPER_MODEL_DIR", "").strip() or None
    try:
        whisper_model = _cached_model(
            (_FASTER_WHISPER, model, device, compute, download_root),
            lambda: WhisperModel(
                model, device=device, compute_type=compute, download_root=download_root
            ),
        )
    except Exception as exc:
        raise ASRUnavailable(
            f"Failed to load the faster-whisper model {model!r} "
            f"(device={device}, compute_type={compute}): {exc}"
        ) from exc

    with tempfile.NamedTemporaryFile(suffix=_suffix_for(content_type), delete=True) as tf:
        tf.write(audio_bytes)
        tf.flush()
        try:
            segments, info = whisper_model.transcribe(
                tf.name,
                language=(language or None),
                word_timestamps=word_timestamps,
                vad_filter=vad,
            )
            seglist = _segments_from_whisper(segments, word_timestamps=word_timestamps)
        except Exception as exc:
            raise ASRUnavailable(f"faster-whisper transcription failed: {exc}") from exc

    detected = (getattr(info, "language", "") or language or "").strip()
    duration = float(getattr(info, "duration", 0.0) or 0.0)
    return _build_transcript(seglist, detected, duration, provider=_FASTER_WHISPER, model=model)


def _transcribe_whispercpp(
    audio_bytes: bytes,
    model: str,
    language: str,
    word_timestamps: bool,
    content_type: str,
    vad: bool,
) -> Transcript:
    """The whisper.cpp backend via ``pywhispercpp``: segment timings, words estimated."""
    try:
        from pywhispercpp.model import Model
    except Exception as exc:
        raise ASRUnavailable(
            "The whisper.cpp ASR backend is selected but the 'pywhispercpp' "
            "package is not installed. Install it (pip install pywhispercpp) or "
            "set MEDIAHUB_ASR_PROVIDER=faster-whisper."
        ) from exc

    with tempfile.NamedTemporaryFile(suffix=_suffix_for(content_type), delete=True) as tf:
        tf.write(audio_bytes)
        tf.flush()
        try:
            cpp_model = _cached_model((_WHISPER_CPP, model), lambda: Model(model))
            raw_segments = cpp_model.transcribe(tf.name)
        except Exception as exc:
            raise ASRUnavailable(f"whisper.cpp transcription failed: {exc}") from exc

    seglist: list[TranscriptSegment] = []
    for seg in raw_segments:
        # pywhispercpp Segment timings (t0/t1) are in centiseconds.
        a = int(getattr(seg, "t0", 0)) * 10
        b = int(getattr(seg, "t1", 0)) * 10
        text = (getattr(seg, "text", "") or "").strip()
        if not text:
            continue
        words = tuple(_estimate_word_stamps(text, a, max(a, b))) if word_timestamps else ()
        seglist.append(TranscriptSegment(a, max(a, b), text, words))
    duration_sec = (seglist[-1].end_ms / 1000.0) if seglist else 0.0
    return _build_transcript(seglist, language, duration_sec, provider=_WHISPER_CPP, model=model)


def _transcribe_raw(
    audio_bytes: bytes,
    provider: str,
    model: str,
    language: str,
    word_timestamps: bool,
    content_type: str,
    vad: bool,
) -> Transcript:
    """Dispatch to the selected backend. The single seam tests monkeypatch — the
    entire model/decoder surface sits behind it, so unit tests never touch a real
    model. Any failure becomes :class:`ASRUnavailable`; there is no fallback."""
    if provider == _WHISPER_CPP:
        return _transcribe_whispercpp(
            audio_bytes, model, language, word_timestamps, content_type, vad
        )
    return _transcribe_faster_whisper(
        audio_bytes, model, language, word_timestamps, content_type, vad
    )


# ---------------------------------------------------------------------------
# Public transcription entry point
# ---------------------------------------------------------------------------


def transcribe_audio(
    audio_bytes: bytes,
    *,
    content_type: str = "",
    language: str = "",
    word_timestamps: bool = True,
) -> Transcript:
    """Transcribe ``audio_bytes`` to a :class:`Transcript` via the configured backend.

    The result is cached by audio content-hash under ``DATA_DIR/asr_cache`` so a
    repeat call (or a second consumer — copilot voice + reel captions) reuses the
    work. ``language`` defaults to ``MEDIAHUB_WHISPER_LANGUAGE`` (blank = the
    backend auto-detects).

    Raises:
        :class:`ASRUnavailable`: no provider configured, the backend package or
            model is absent, or transcription fails — an honest error, never a
            fabricated transcript.
        ValueError: ``audio_bytes`` is empty (a configured backend with nothing
            to transcribe).
    """
    provider = select_asr_provider()
    if not provider:
        raise ASRUnavailable(
            "Speech-to-text isn't configured on this deployment. Use the "
            "microphone button (your browser transcribes on-device), or set "
            "MEDIAHUB_ASR_PROVIDER=faster-whisper to enable server transcription."
        )
    if not audio_bytes:
        raise ValueError("audio is empty")

    model = _whisper_model_id()
    lang = (language or os.environ.get("MEDIAHUB_WHISPER_LANGUAGE", "")).strip()
    vad = os.environ.get("MEDIAHUB_WHISPER_VAD", "").strip().lower() in {"1", "true", "yes", "on"}
    opts = f"w{int(bool(word_timestamps))}v{int(vad)}"

    key = cache_key(audio_bytes, provider, model, lang, opts)
    jpath = cache_dir() / f"{key}.json"
    if jpath.exists():
        try:
            transcript = Transcript.from_dict(json.loads(jpath.read_text(encoding="utf-8")))
            transcript.cached = True
            return transcript
        except (OSError, ValueError, KeyError):
            # Corrupt sidecar → fall through and re-transcribe.
            pass

    transcript = _transcribe_raw(
        audio_bytes, provider, model, lang, bool(word_timestamps), content_type, vad
    )
    transcript.cached = False
    payload = transcript.to_dict()
    payload["created_at"] = time.time()
    jpath.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return transcript


# ---------------------------------------------------------------------------
# Caption-track bridge — the word-level burn-in primitive (unblocks 1.6)
# ---------------------------------------------------------------------------


def caption_track_for_audio(
    audio_bytes: bytes,
    *,
    fps: int = 30,
    total_frames: int = 0,
    ground: str = "",
    onground: str = "",
    accent: str = "",
    language: str = "",
    content_type: str = "",
) -> dict | None:
    """Transcribe ``audio_bytes`` and build a frame-timed, APCA-gated caption track.

    This is the word-level burn-in primitive the video suite (1.6) consumes: the
    spoken words become caption cues at their measured timings, coloured by the
    deterministic colour-science in ``subtitle_burn`` so they read on the brand
    ground. Word stamps drive the cues when the backend provides them; otherwise
    the segment text/timings do.

    Honest and non-fatal: returns ``None`` when ASR is unavailable or the clip
    yields nothing — captions are an overlay, so a render proceeds *without*
    them rather than failing, exactly as ``subtitle_burn`` requires.
    """
    try:
        transcript = transcribe_audio(audio_bytes, content_type=content_type, language=language)
    except (ASRUnavailable, ValueError):
        return None

    from mediahub.visual import subtitle_burn

    words = transcript.words()
    if words:
        stamps = [(w.text, w.start_ms, w.end_ms) for w in words]
    else:
        stamps = [(s.text, s.start_ms, s.end_ms) for s in transcript.segments]
    cues = subtitle_burn.cues_from_stamps(stamps)
    if not cues:
        return None
    return subtitle_burn.build_track(
        cues,
        fps=fps,
        total_frames=total_frames,
        ground=ground,
        onground=onground,
        accent=accent,
    )


__all__ = [
    "ASRUnavailable",
    "WordStamp",
    "TranscriptSegment",
    "Transcript",
    "DEFAULT_WHISPER_MODEL",
    "select_asr_provider",
    "is_available",
    "asr_provider_status",
    "cache_dir",
    "cache_key",
    "transcribe_audio",
    "caption_track_for_audio",
]
