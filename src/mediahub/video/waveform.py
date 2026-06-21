"""video/waveform.py — deterministic audio-waveform peaks for the trim scrubber (1.6).

The timeline editor's scrubber needs to *show* a clip's audio so a human can see
where the speech and the dead air are when they trim. That is a measurement, not
a judgement: the same clip always yields the same peaks. So, like silence
detection (``silence.py``) and moment scoring, it lives on the deterministic side
of the engine boundary — a fixed FFmpeg decode to raw PCM plus pure bucketing
maths, with an honest error (never a faked flat line) when no FFmpeg binary is
present.

The split that keeps it testable:

* **Decode args.** :func:`pcm_args` builds the FFmpeg command that writes mono
  signed-16-bit little-endian PCM to stdout. Pure builder.
* **Bucketing.** :func:`peaks_from_pcm` turns that raw PCM into ``buckets``
  normalised ``[0, 1]`` peak amplitudes (max-abs per bucket / global max). Pure —
  unit-tested against synthetic PCM with no binary present.
* **Orchestration.** :func:`extract_peaks` shells out (FFmpeg injectable) and
  honest-errors (:class:`WaveformUnavailable`) when FFmpeg is absent.
"""

from __future__ import annotations

import array
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from mediahub.visual.reel_ffmpeg import ffmpeg_exe

DEFAULT_BUCKETS = 240  # ~one peak per few px across a full-width strip
DEFAULT_SAMPLE_RATE = 8000  # plenty for an amplitude envelope; keeps PCM small
MIN_BUCKETS = 16
MAX_BUCKETS = 2000


class WaveformUnavailable(RuntimeError):
    """Raised when a waveform cannot be measured (no FFmpeg binary on the box)."""


def pcm_args(path: Path | str, *, sample_rate: int = DEFAULT_SAMPLE_RATE) -> list[str]:
    """FFmpeg args that write mono ``s16le`` PCM for a clip to stdout (pure builder)."""
    sr = max(1000, int(sample_rate))
    return ["-i", str(path), "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"]


def peaks_from_pcm(data: bytes, buckets: int) -> list[float]:
    """Bucket raw mono ``s16le`` PCM into ``buckets`` normalised ``[0, 1]`` peaks. Pure.

    Each bucket is the max absolute sample in its slice; the whole array is then
    normalised by the global peak so the loudest moment reads as ``1.0``. A silent,
    audio-free, or empty clip yields all-zeros — an honest flat line, never a
    fabricated shape. Deterministic: the same PCM always buckets identically.
    """
    buckets = max(MIN_BUCKETS, min(MAX_BUCKETS, int(buckets)))
    n = len(data) - (len(data) % 2)  # s16le is 2 bytes/sample; drop a dangling byte
    if n <= 0:
        return [0.0] * buckets
    samples = array.array("h")
    samples.frombytes(data[:n])
    if sys.byteorder == "big":  # s16le → swap to native on a big-endian host
        samples.byteswap()
    total = len(samples)
    if total == 0:
        return [0.0] * buckets

    out = [0.0] * buckets
    peak = 0
    for b in range(buckets):
        lo = (b * total) // buckets
        hi = ((b + 1) * total) // buckets
        if hi <= lo:
            hi = min(total, lo + 1)
        seg = samples[lo:hi]
        if not seg:
            continue
        # max abs over the slice via two C-level passes (negation of -32768 is a
        # Python int, so no overflow).
        m = max(max(seg), -min(seg))
        out[b] = float(m)
        if m > peak:
            peak = m
    if peak <= 0:
        return [0.0] * buckets
    inv = 1.0 / peak
    return [round(v * inv, 4) for v in out]


def _run_pcm(args: list[str], *, timeout: int = 300) -> bytes:
    exe = ffmpeg_exe()
    if not exe:
        raise WaveformUnavailable(
            "A waveform needs an FFmpeg binary (install imageio-ffmpeg, put ffmpeg "
            "on PATH, or set MEDIAHUB_FFMPEG)."
        )
    cmd = [exe, "-hide_banner", "-nostats", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise WaveformUnavailable(f"waveform analysis timed out after {timeout}s") from e
    return proc.stdout or b""


def extract_peaks(
    path: Path | str,
    *,
    buckets: int = DEFAULT_BUCKETS,
    sample_rate: int = DEFAULT_SAMPLE_RATE,
    runner: Optional[Callable[..., bytes]] = None,
    timeout: int = 300,
) -> list[float]:
    """Decode a clip's audio and return ``buckets`` normalised peaks. Honest-errors.

    Deterministic: the same clip + params yield the same peaks. ``runner`` is an
    injection seam (defaults to the real FFmpeg) so the orchestration is unit-tested
    without a binary. A clip with no audio stream decodes to empty PCM → a flat
    (all-zero) waveform, which honestly shows 'no audio' rather than inventing one.
    """
    run = runner or _run_pcm
    data = run(pcm_args(path, sample_rate=sample_rate), timeout=timeout)
    return peaks_from_pcm(data or b"", buckets)


__all__ = [
    "DEFAULT_BUCKETS",
    "DEFAULT_SAMPLE_RATE",
    "MIN_BUCKETS",
    "MAX_BUCKETS",
    "WaveformUnavailable",
    "pcm_args",
    "peaks_from_pcm",
    "extract_peaks",
]
