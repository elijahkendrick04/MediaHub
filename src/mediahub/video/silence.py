"""video/silence.py — deterministic dead-air detection + jump-cut planning (1.6).

The "remove silences" / "tighten the edit" feature every short-form tool ships
(Recut, TimeBolt, Descript "Remove Gaps"), done the MediaHub way: as a fixed
FFmpeg measurement (``silencedetect``) plus pure timeline maths, **not** an AI
judgement. "Where is the dead air" is an accuracy-critical, reproducible fact —
the same clip always yields the same cuts — so it lives squarely on the
deterministic side of the engine boundary, exactly like moment detection.

The split this module keeps:

* **Measurement.** ``silencedetect`` prints ``silence_start`` / ``silence_end``
  timestamps; :func:`parse_silences` turns that text into spans. Pure.
* **Planning.** :func:`plan_keep_segments` inverts the silence spans into the
  speech windows to *keep*, pads the cuts so they don't clip a word, and drops
  slivers. Pure maths over the spans — unit-tested with no binary present.
* **Orchestration.** :func:`detect_silences` / :func:`plan_jump_cuts` shell out
  to FFmpeg and honest-error (:class:`SilenceUnavailable`) when it is absent —
  never a silently un-tightened clip pretending the dead air was removed.

The kept segments become several trimmed clips on an :class:`~mediahub.video.edl.EDL`
(one per retained span), so a rambly two-minute clip tightens into a punchy cut
with every gap removed and every word intact.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from mediahub.visual.reel_ffmpeg import ffmpeg_exe

Span = tuple[int, int]  # (start_ms, end_ms)


class SilenceUnavailable(RuntimeError):
    """Raised when silence cannot be measured (no FFmpeg binary on the box)."""


# Defaults tuned for phone clips of club sport: speech well above room tone, and
# a gap has to last ~0.6s before it reads as "dead air" worth cutting.
DEFAULT_THRESHOLD_DB = -30.0
DEFAULT_MIN_SILENCE_MS = 600
DEFAULT_PAD_MS = 120
DEFAULT_MIN_KEEP_MS = 400


_SIL_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SIL_END_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")


def silencedetect_args(
    path: Path | str, *, threshold_db: float = DEFAULT_THRESHOLD_DB, min_silence_ms: int = DEFAULT_MIN_SILENCE_MS
) -> list[str]:
    """FFmpeg args that print silence_start/end markers for a clip (pure builder)."""
    d = max(0.05, min_silence_ms / 1000.0)
    return [
        "-i",
        str(path),
        "-vn",
        "-af",
        f"silencedetect=noise={threshold_db:g}dB:d={d:.3f}",
        "-f",
        "null",
        "-",
    ]


def parse_silences(text: str) -> list[Span]:
    """Parse ``silencedetect`` output into ascending ``(start_ms, end_ms)`` spans.

    Pure and tolerant: a dangling ``silence_start`` with no matching
    ``silence_end`` (silence running to the end of the clip) is closed with a
    sentinel ``-1`` end, which :func:`plan_keep_segments` resolves against the
    real duration. Order-preserving; negative/again-clamped values are normalised.
    """
    spans: list[Span] = []
    pending_start: float | None = None
    for line in (text or "").splitlines():
        ms = _SIL_START_RE.search(line)
        if ms:
            pending_start = max(0.0, float(ms.group(1)))
            continue
        me = _SIL_END_RE.search(line)
        if me and pending_start is not None:
            end = max(0.0, float(me.group(1)))
            spans.append((round(pending_start * 1000), round(end * 1000)))
            pending_start = None
    if pending_start is not None:
        spans.append((round(pending_start * 1000), -1))  # open-ended (to clip end)
    return spans


def _merge_overlaps(spans: list[Span]) -> list[Span]:
    """Merge overlapping/adjacent spans into a clean ascending set. Pure."""
    if not spans:
        return []
    ordered = sorted(spans, key=lambda s: s[0])
    out: list[Span] = [ordered[0]]
    for s, e in ordered[1:]:
        ls, le = out[-1]
        if s <= le:
            out[-1] = (ls, max(le, e))
        else:
            out.append((s, e))
    return out


def plan_keep_segments(
    silences: list[Span],
    duration_ms: int,
    *,
    pad_ms: int = DEFAULT_PAD_MS,
    min_keep_ms: int = DEFAULT_MIN_KEEP_MS,
) -> list[Span]:
    """Invert silence spans into the speech windows to *keep*. Pure maths.

    Each kept window is padded inward by ``pad_ms`` (so a cut never clips the
    first/last syllable), then windows shorter than ``min_keep_ms`` are dropped
    (a 0.1s sliver between two gaps is noise, not a beat). Open-ended silence
    (``end == -1``) is resolved against ``duration_ms``. Returns ascending,
    non-overlapping spans; an all-silent clip returns ``[]`` and a clip with no
    detected silence returns the whole ``[0, duration_ms]``.
    """
    if duration_ms <= 0:
        return []
    resolved = _merge_overlaps(
        [(s, duration_ms if e < 0 else min(e, duration_ms)) for s, e in silences if s < duration_ms]
    )
    keeps: list[Span] = []
    cursor = 0
    for s, e in resolved:
        if s > cursor:
            keeps.append((cursor, s))
        cursor = max(cursor, e)
    if cursor < duration_ms:
        keeps.append((cursor, duration_ms))

    out: list[Span] = []
    for s, e in keeps:
        # Pad the cut edges back out (toward the silence we removed), clamped so a
        # padded keep can never run past the clip or invert.
        ps = max(0, s - pad_ms)
        pe = min(duration_ms, e + pad_ms)
        if pe - ps >= min_keep_ms:
            out.append((ps, pe))
    return _merge_overlaps(out)


def _run_for_text(args: list[str], *, timeout: int = 300) -> str:
    exe = ffmpeg_exe()
    if not exe:
        raise SilenceUnavailable(
            "Removing silences needs an FFmpeg binary (install imageio-ffmpeg, put "
            "ffmpeg on PATH, or set MEDIAHUB_FFMPEG)."
        )
    cmd = [exe, "-hide_banner", "-nostats", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise SilenceUnavailable(f"silence analysis timed out after {timeout}s") from e
    return (proc.stderr or "") + "\n" + (proc.stdout or "")


def detect_silences(
    path: Path | str,
    *,
    threshold_db: float = DEFAULT_THRESHOLD_DB,
    min_silence_ms: int = DEFAULT_MIN_SILENCE_MS,
) -> list[Span]:
    """Measure the silent spans in a clip on disk. Honest-errors without FFmpeg.

    Deterministic: the same clip + thresholds yield the same spans. A silent or
    audio-free clip yields a single open-ended span (the planner then keeps
    nothing, and the caller falls back to the untrimmed clip).
    """
    text = _run_for_text(
        silencedetect_args(path, threshold_db=threshold_db, min_silence_ms=min_silence_ms)
    )
    return parse_silences(text)


def plan_jump_cuts(
    path: Path | str,
    duration_ms: int,
    *,
    threshold_db: float = DEFAULT_THRESHOLD_DB,
    min_silence_ms: int = DEFAULT_MIN_SILENCE_MS,
    pad_ms: int = DEFAULT_PAD_MS,
    min_keep_ms: int = DEFAULT_MIN_KEEP_MS,
) -> list[Span]:
    """Detect dead air and return the speech windows to keep. Honest-errors.

    The end-to-end "tighten this clip" plan: measure silences (deterministic),
    invert to keep-windows (deterministic). When detection finds no removable
    silence the whole clip is kept (``[(0, duration_ms)]``), so the feature is a
    no-op rather than a surprise on an already-tight clip.
    """
    if duration_ms <= 0:
        return []
    sil = detect_silences(path, threshold_db=threshold_db, min_silence_ms=min_silence_ms)
    keeps = plan_keep_segments(
        sil, duration_ms, pad_ms=pad_ms, min_keep_ms=min_keep_ms
    )
    return keeps or [(0, duration_ms)]


def removed_ms(keeps: list[Span], duration_ms: int) -> int:
    """How much dead air the keep-plan removes (for the explainability manifest)."""
    kept = sum(max(0, e - s) for s, e in keeps)
    return max(0, duration_ms - kept)


__all__ = [
    "Span",
    "SilenceUnavailable",
    "DEFAULT_THRESHOLD_DB",
    "DEFAULT_MIN_SILENCE_MS",
    "DEFAULT_PAD_MS",
    "DEFAULT_MIN_KEEP_MS",
    "silencedetect_args",
    "parse_silences",
    "plan_keep_segments",
    "detect_silences",
    "plan_jump_cuts",
    "removed_ms",
]
