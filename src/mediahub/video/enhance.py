"""video/enhance.py — deterministic footage enhancement passes (1.6).

The per-clip colour/clarity grade is compiled inline by ``edl`` (it is pure
filter maths). This module owns the enhancement steps that need their own
**file pass** over the footage, plus the small helpers the editor UI uses to
present looks. Everything here is deterministic CV/DSP — fixed FFmpeg filter
graphs, no model — so the same input always yields the same output, and a
failure is an honest :class:`VideoEnhanceUnavailable`, never a silently
un-enhanced clip.

* **Stabilisation** is the canonical two-pass ``vidstab`` (``vidstabdetect`` →
  ``vidstabtransform``) — feature-tracking + path-smoothing + a compensating
  warp, the same maths Premiere's Warp Stabilizer and Resolve's stabiliser use.
  It produces a *new, steadier source file* that an :class:`~mediahub.video.edl.EDL`
  then references, so it stays out of the pure timeline compiler and the render
  cache key tracks it via the source fingerprint like any other clip.
* **Deterministic upscale** (``scale=…:flags=lanczos``) is a windowed-sinc
  resample — it cannot invent detail (that would be a generative super-resolver,
  which MediaHub would gate behind a disclosed provider slot, not ship as a
  filter).

The argument builders are pure (unit-testable with no binary); only the runners
shell out.
"""

from __future__ import annotations

import functools
import subprocess
import tempfile
from pathlib import Path

from mediahub.video.edl import LOOKS
from mediahub.visual.reel_ffmpeg import ffmpeg_exe


class VideoEnhanceUnavailable(RuntimeError):
    """Raised when an enhancement pass cannot run (no FFmpeg / no vidstab)."""


# --------------------------------------------------------------------------
# Look helpers (for the editor's grade picker)
# --------------------------------------------------------------------------

# Short, human labels for each named look — the editor shows these; the engine
# keys off the LOOKS dict in ``edl``.
LOOK_LABELS: dict[str, str] = {
    "none": "Original",
    "vivid": "Vivid",
    "punch": "Punch",
    "warm": "Warm",
    "cool": "Cool",
    "bright": "Bright",
    "film": "Film",
    "mono": "Mono",
    "clean": "Clean-up",
}


def look_names() -> list[str]:
    """The named looks, with ``none`` first (the picker's default order)."""
    names = list(LOOKS.keys())
    names.sort(key=lambda n: (n != "none", n))
    return names


def describe_look(name: str) -> str:
    """A human label for a look name (falls back to a title-cased name)."""
    key = str(name or "none").strip().lower()
    return LOOK_LABELS.get(key, key.title() or "Original")


# --------------------------------------------------------------------------
# Stabilisation (two-pass vidstab; deterministic)
# --------------------------------------------------------------------------

# Bounds mirror the ranker's "fixed, tuned weights" spirit — a sport clip wants
# a steady hand, not a locked-off tripod look that swims when the subject moves.
DEFAULT_SHAKINESS = 5  # 1 (steady) .. 10 (very shaky) — detection sensitivity
DEFAULT_ACCURACY = 15  # 1 .. 15 — detection accuracy (15 = most accurate)
DEFAULT_SMOOTHING = 10  # ± frames averaged for the smoothed camera path


def vidstabdetect_args(
    src: Path | str, trf: Path | str, *, shakiness: int, accuracy: int
) -> list[str]:
    """Pass-1 args: analyse camera motion into a transforms file (pure builder)."""
    sh = max(1, min(10, int(shakiness)))
    ac = max(1, min(15, int(accuracy)))
    return [
        "-i",
        str(src),
        "-vf",
        f"vidstabdetect=shakiness={sh}:accuracy={ac}:result={trf}",
        "-f",
        "null",
        "-",
    ]


def vidstabtransform_args(
    src: Path | str, trf: Path | str, out: Path | str, *, smoothing: int
) -> list[str]:
    """Pass-2 args: warp the clip along the smoothed path (pure builder).

    ``optzoom=1`` lets vidstab pick a small zoom that hides the black border the
    warp would otherwise expose, and ``unsharp`` recovers the softness the warp
    interpolation introduces — the standard vidstab finishing pair.
    """
    sm = max(1, min(60, int(smoothing)))
    return [
        "-i",
        str(src),
        "-vf",
        f"vidstabtransform=input={trf}:smoothing={sm}:optzoom=1,unsharp=5:5:0.5:3:3:0.0",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        "-y",
        str(out),
    ]


@functools.lru_cache(maxsize=1)
def _vidstab_present() -> bool:
    """True when the FFmpeg binary advertises the vidstab filters (cached)."""
    exe = ffmpeg_exe()
    if not exe:
        return False
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-filters"], capture_output=True, text=True, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return "vidstabtransform" in (proc.stdout or "")


def is_stabilize_available() -> bool:
    """True when stabilisation could actually run (FFmpeg built with vidstab)."""
    return bool(ffmpeg_exe()) and _vidstab_present()


def stabilize_source(
    src: Path | str, out: Path | str, *, smoothing: int = DEFAULT_SMOOTHING, timeout: int = 600
) -> Path:
    """Stabilise ``src`` into ``out`` via two-pass vidstab. Honest-errors.

    Deterministic: the same clip + smoothing yields the same steadied file.
    Raises :class:`VideoEnhanceUnavailable` when FFmpeg lacks the vidstab filters
    rather than copying the shaky clip through as if it were stabilised.
    """
    exe = ffmpeg_exe()
    if not exe:
        raise VideoEnhanceUnavailable(
            "Stabilisation needs an FFmpeg binary (install imageio-ffmpeg, put "
            "ffmpeg on PATH, or set MEDIAHUB_FFMPEG)."
        )
    if not _vidstab_present():
        raise VideoEnhanceUnavailable(
            "This FFmpeg build has no vidstab filter, so stabilisation can't run "
            "here. Use a build that includes libvidstab."
        )
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mh_stab_") as td:
        trf = Path(td) / "transforms.trf"
        _run(
            exe,
            vidstabdetect_args(src, trf, shakiness=DEFAULT_SHAKINESS, accuracy=DEFAULT_ACCURACY),
            timeout=timeout,
        )
        _run(exe, vidstabtransform_args(src, trf, out, smoothing=smoothing), timeout=timeout)
    if not out.exists() or out.stat().st_size < 1024:
        raise VideoEnhanceUnavailable("stabilisation produced no output")
    return out


# --------------------------------------------------------------------------
# Deterministic upscale (lanczos — no invented detail)
# --------------------------------------------------------------------------


def lanczos_scale_args(src: Path | str, out: Path | str, *, width: int, height: int) -> list[str]:
    """Args for a deterministic high-quality (lanczos) resize (pure builder).

    A windowed-sinc resample — sharp and reproducible. It interpolates existing
    samples; it does **not** hallucinate new detail (that is a generative
    super-resolver, which belongs behind a disclosed provider slot).
    """
    return [
        "-i",
        str(src),
        "-vf",
        f"scale={int(width)}:{int(height)}:flags=lanczos",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        "-y",
        str(out),
    ]


def _run(exe: str, args: list[str], *, timeout: int) -> None:
    cmd = [exe, "-hide_banner", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise VideoEnhanceUnavailable(f"enhancement pass timed out after {timeout}s") from e
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-8:]) or "(no stderr)"
        raise VideoEnhanceUnavailable(f"enhancement pass failed (exit {proc.returncode}):\n{tail}")


__all__ = [
    "VideoEnhanceUnavailable",
    "LOOK_LABELS",
    "look_names",
    "describe_look",
    "DEFAULT_SHAKINESS",
    "DEFAULT_ACCURACY",
    "DEFAULT_SMOOTHING",
    "vidstabdetect_args",
    "vidstabtransform_args",
    "is_stabilize_available",
    "stabilize_source",
    "lanczos_scale_args",
]
