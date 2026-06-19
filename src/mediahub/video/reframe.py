"""video/reframe.py — saliency-tracked aspect reframe for footage (1.6).

A club films a race in landscape on a phone, but the story/reel it wants is
9:16. Naively scaling letterboxes it (black bars top and bottom); cropping the
centre often cuts the swimmer out of frame. **Reframe** crops to the target
shape while keeping the subject in view — the video twin of the still
renderer's saliency cropping.

It deliberately reuses the **deterministic** saliency maths in
``graphic_renderer.saliency`` (gradient-energy / cutout-alpha centroid — no AI,
no network), so "where is the subject" is decided the same reproducible way for
a video frame as for a photo. Per the engine rule, this is layout-intelligence
maths, not a judgement call.

The flow: sample a few frames across the clip, ask saliency for the best crop of
each, and **smooth** those crops into one stable rectangle for the clip (a
per-frame jittering crop would look like a shaky camera). The pure helpers
(:func:`sample_positions`, :func:`smooth_crops`, :func:`frame_extract_args`) are
unit-tested with no FFmpeg present; only :func:`reframe_clip_crop` shells out.

Reframe is an *enhancement*: if frame extraction or saliency fails, it returns
``None`` and the clip simply scale-pads instead — never an aborted render.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from mediahub.visual.reel_ffmpeg import ffmpeg_exe

Crop = tuple[int, int, int, int]  # (x, y, w, h) in source pixels


def target_ratio(width: int, height: int) -> float:
    """The output aspect ratio a reframe should crop *to* (w / h)."""
    return (width / height) if (width and height) else 1.0


def sample_positions(duration_ms: int, n: int = 3) -> list[int]:
    """Evenly-spaced sample timestamps (ms), avoiding the very first/last frame.

    Deterministic. For a 12s clip with n=3 → roughly 3s, 6s, 9s. A zero/short
    clip collapses sensibly (one sample at the midpoint, or none).
    """
    if duration_ms <= 0 or n <= 0:
        return []
    if n == 1:
        return [duration_ms // 2]
    step = duration_ms / (n + 1)
    return [round(step * (i + 1)) for i in range(n)]


def smooth_crops(crops: list[Crop]) -> Optional[Crop]:
    """Reduce per-frame crops to one stable rectangle (the per-axis median).

    The median is robust to a single outlier frame (a pan, a flash) in a way a
    mean is not, and it is deterministic. Returns ``None`` for an empty list.
    """
    if not crops:
        return None

    def _median(vals: list[int]) -> int:
        s = sorted(vals)
        mid = len(s) // 2
        if len(s) % 2:
            return s[mid]
        return (s[mid - 1] + s[mid]) // 2

    xs = [c[0] for c in crops]
    ys = [c[1] for c in crops]
    ws = [c[2] for c in crops]
    hs = [c[3] for c in crops]
    return (_median(xs), _median(ys), _median(ws), _median(hs))


def needs_reframe(src_w: int, src_h: int, dst_w: int, dst_h: int, *, tol: float = 0.02) -> bool:
    """True when the source and target aspect ratios differ enough to crop.

    A clip already at (near) the target ratio is left alone — scale-pad will not
    bar it, so a redundant crop is avoided (and a cache key stays stable).
    """
    if min(src_w, src_h, dst_w, dst_h) <= 0:
        return False
    return abs(target_ratio(src_w, src_h) - target_ratio(dst_w, dst_h)) > tol


def frame_extract_args(path: Path | str, ms: int, out_png: Path | str) -> list[str]:
    """FFmpeg args to grab a single frame at ``ms`` as a PNG (pure builder)."""
    return [
        "-ss", f"{max(0, ms) / 1000:.3f}",
        "-i", str(path),
        "-frames:v", "1",
        "-q:v", "2",
        "-y", str(out_png),
    ]


def _extract_frame(path: Path | str, ms: int, out_png: Path, *, timeout: int = 60) -> bool:
    exe = ffmpeg_exe()
    if not exe:
        return False
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-loglevel", "error", *frame_extract_args(path, ms, out_png)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0 and out_png.exists() and out_png.stat().st_size > 0


def reframe_clip_crop(
    source: Path | str,
    *,
    in_ms: int,
    out_ms: int,
    dst_w: int,
    dst_h: int,
    samples: int = 3,
) -> Optional[Crop]:
    """Compute the saliency-tracked crop to take a clip span to ``dst`` shape.

    Samples frames across ``[in_ms, out_ms]``, runs the deterministic saliency
    cropper on each, and smooths them into one rectangle. Returns ``None`` (so
    the clip falls back to scale-pad) when FFmpeg/saliency is unavailable or no
    frame could be measured — reframe is an enhancement, never load-bearing.
    """
    span = max(0, out_ms - in_ms)
    if span <= 0 or dst_w <= 0 or dst_h <= 0:
        return None
    try:
        from mediahub.graphic_renderer.saliency import best_crop
    except Exception:
        return None

    ratio = (dst_w, dst_h)
    crops: list[Crop] = []
    with tempfile.TemporaryDirectory(prefix="mh_reframe_") as td:
        tdp = Path(td)
        for i, rel in enumerate(sample_positions(span, samples)):
            png = tdp / f"f{i}.png"
            if not _extract_frame(source, in_ms + rel, png):
                continue
            try:
                crops.append(tuple(int(v) for v in best_crop(png, ratio)))  # type: ignore[arg-type]
            except Exception:
                continue
    return smooth_crops(crops)


__all__ = [
    "Crop",
    "target_ratio",
    "sample_positions",
    "smooth_crops",
    "needs_reframe",
    "frame_extract_args",
    "reframe_clip_crop",
]
