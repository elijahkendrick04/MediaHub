"""documents.deck_video — turn a deck into an MP4 (roadmap 1.15).

"Turn a presentation into a video": each slide is rendered to a PNG by the same
brand-locked document renderer (:func:`documents.render.render_section_png`) and the
slides are stitched into an MP4 with FFmpeg — the same free engine the reels fall
back to. Deterministic (cached by the slide bytes + timing) and honest: if FFmpeg
isn't available the caller gets a clear error, never a broken file.

This is a straight slideshow (each slide held for a fixed time); the motion reel
engine remains the path for animated, card-driven video.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from . import cache
from .models import DocumentSpec
from .render import render_section_png


def _ffmpeg() -> Optional[str]:
    """Resolve FFmpeg via the reel engine's resolver (MEDIAHUB_FFMPEG / PATH /
    imageio-ffmpeg), falling back to a bare PATH lookup."""
    try:
        from mediahub.visual.reel_ffmpeg import ffmpeg_exe

        return ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def deck_to_mp4(
    spec: DocumentSpec,
    out_path: Optional[Path] = None,
    *,
    brand_kit: Any = None,
    role_vars: Optional[dict[str, str]] = None,
    seconds_per_slide: float = 4.0,
    fps: int = 30,
) -> Path:
    """Render every section to a slide PNG and stitch them into an MP4.

    Cached by content (slide bytes + timing). Raises ``RuntimeError`` when FFmpeg
    or Chromium is unavailable (an honest infra error)."""
    if not spec.sections:
        raise ValueError("cannot make a video from a document with no sections")
    seconds_per_slide = max(0.5, float(seconds_per_slide))
    fps = max(1, int(fps))

    ffmpeg = _ffmpeg()
    if not ffmpeg:
        raise RuntimeError(
            "deck_to_mp4 needs FFmpeg: install imageio-ffmpeg, put ffmpeg on PATH, "
            "or set MEDIAHUB_FFMPEG."
        )

    # Render each slide (these are themselves content-cached).
    slide_pngs: list[Path] = [
        render_section_png(spec, i, brand_kit=brand_kit, role_vars=role_vars)
        for i in range(len(spec.sections))
    ]

    key_parts = ["deck-mp4", seconds_per_slide, fps] + [p.read_bytes() for p in slide_pngs]
    cached = cache.cached_path(".mp4", *key_parts)
    if not (cached.exists() and cached.stat().st_size > 0):
        _stitch(ffmpeg, slide_pngs, cached, seconds_per_slide, fps)

    if out_path is not None:
        out_path = Path(out_path)
        if out_path.resolve() != cached.resolve():
            out_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(cached, out_path)
        return out_path
    return cached


def _stitch(ffmpeg: str, pngs: list[Path], out: Path, seconds: float, fps: int) -> None:
    """Build the MP4 from the slide PNGs via FFmpeg's concat demuxer."""
    with tempfile.TemporaryDirectory() as td:
        list_file = Path(td) / "slides.txt"
        lines = []
        for p in pngs:
            lines.append(f"file '{p.resolve().as_posix()}'")
            lines.append(f"duration {seconds}")
        # concat demuxer needs the last file repeated to hold its final duration.
        lines.append(f"file '{pngs[-1].resolve().as_posix()}'")
        list_file.write_text("\n".join(lines), encoding="utf-8")

        out.parent.mkdir(parents=True, exist_ok=True)
        args = [
            ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
            "-vf", f"fps={fps},format=yuv420p,scale=trunc(iw/2)*2:trunc(ih/2)*2",
            "-c:v", "libx264", "-preset", "medium", "-movflags", "+faststart",
            str(out),
        ]
        proc = subprocess.run(args, capture_output=True, text=True, timeout=600)
        if proc.returncode != 0 or not (out.exists() and out.stat().st_size > 0):
            raise RuntimeError(f"FFmpeg failed to build the deck video: {proc.stderr[-400:]}")


__all__ = ["deck_to_mp4"]
