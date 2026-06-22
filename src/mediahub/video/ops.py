"""video/ops.py — deterministic single-clip FFmpeg video edits (roadmap 1.6).

The mechanical clip edits a volunteer reaches for in the "quick actions" toolbox
(roadmap 1.19): trim a clip, crop it, resize it, change its speed, mute it,
reverse it, and join a few compatible clips end-to-end. These are **maths, not
judgement** — fixed FFmpeg filter graphs, same input + args → same bytes — so
they live here as deterministic helpers, the video-side sibling of
``audio/ops.py``.

This is deliberately *not* the reel/timeline engine: multi-clip composition with
transitions, captions, colour looks and audio plans is the ``video/edl.py`` +
``video/render.py`` job. These are the one-clip utilities the export engine
exposes directly, so a quick trim doesn't have to spin up the whole EDL machine.

Design mirrors ``audio/ops.py``: each op has a pure ``*_args`` builder (testable
with no binary present) and a thin runner that executes it. FFmpeg is resolved
via the shared ``visual/reel_ffmpeg.ffmpeg_exe``; with no binary the runners
raise :class:`VideoOpError` — an honest error, never a silent no-op.
"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from mediahub.audio.ops import speed_filter as _atempo_chain
from mediahub.visual.reel_ffmpeg import ffmpeg_exe

# A consistent, web-friendly H.264 video encode tail for every re-encoding op.
_VENC: list[str] = [
    "-c:v", "libx264",
    "-crf", "18",
    "-preset", "veryfast",
    "-pix_fmt", "yuv420p",
    "-movflags", "faststart",
]


class VideoOpError(RuntimeError):
    """A video operation could not run — honest error, never a silent fallback."""


# ---------------------------------------------------------------------------
# Pure argument builders (testable with no FFmpeg present)
# ---------------------------------------------------------------------------


def trim_args(src: Path, out: Path, *, start: float = 0.0, end: Optional[float] = None) -> list[str]:
    """FFmpeg args to cut ``[start, end)`` from ``src`` (frame-accurate re-encode)."""
    s = max(0.0, float(start))
    args = ["-ss", f"{s:.3f}", "-i", str(src)]
    if end is not None:
        dur = max(0.0, float(end) - s)
        args += ["-t", f"{dur:.3f}"]
    args += [*_VENC, "-c:a", "aac", "-b:a", "160k", str(out)]
    return args


def crop_args(src: Path, out: Path, *, x: int, y: int, width: int, height: int) -> list[str]:
    """FFmpeg args to crop a ``width×height`` window at ``(x, y)`` (source px)."""
    w = max(2, int(width) - int(width) % 2)
    h = max(2, int(height) - int(height) % 2)
    vf = f"crop={w}:{h}:{max(0, int(x))}:{max(0, int(y))}"
    return ["-i", str(src), "-vf", vf, *_VENC, "-c:a", "copy", str(out)]


def resize_args(
    src: Path,
    out: Path,
    *,
    width: int = 0,
    height: int = 0,
    keep_aspect: bool = True,
) -> list[str]:
    """FFmpeg args to resize. With ``keep_aspect`` one dimension may be ``-2``
    (auto, even); set both for an exact (possibly distorting) fit."""
    if width <= 0 and height <= 0:
        raise VideoOpError("resize needs a width and/or a height")
    if keep_aspect and (width <= 0 or height <= 0):
        w = int(width) if width > 0 else -2
        h = int(height) if height > 0 else -2
        vf = f"scale={w}:{h}:flags=lanczos"
    else:
        w = max(2, int(width)) if width > 0 else 2
        h = max(2, int(height)) if height > 0 else 2
        vf = f"scale={w - w % 2}:{h - h % 2}:flags=lanczos"
    return ["-i", str(src), "-vf", vf, *_VENC, "-c:a", "copy", str(out)]


def speed_args(src: Path, out: Path, *, factor: float, mute: bool = False) -> list[str]:
    """FFmpeg args to change playback speed (``factor`` >1 = faster).

    Video uses ``setpts``; audio uses the pitch-preserving ``atempo`` chain
    shared with ``audio/ops`` (or is dropped when ``mute``)."""
    f = max(0.25, min(4.0, float(factor)))
    args = ["-i", str(src), "-vf", f"setpts={1.0 / f:.6f}*PTS"]
    atempo = _atempo_chain(f)
    if mute:
        tail = ["-an"]
    elif atempo:
        args += ["-af", atempo]
        tail = ["-c:a", "aac", "-b:a", "160k"]
    else:
        # Speed unchanged (f≈1.0): keep the audio untouched.
        tail = ["-c:a", "copy"]
    args += [*_VENC, *tail, str(out)]
    return args


def mute_args(src: Path, out: Path) -> list[str]:
    """FFmpeg args to drop the audio track (stream-copy the video — fast)."""
    return ["-i", str(src), "-c:v", "copy", "-an", str(out)]


def reverse_args(src: Path, out: Path, *, mute: bool = False) -> list[str]:
    """FFmpeg args to play a clip backwards (video and, unless muted, audio).

    The whole clip is buffered to reverse it, so this is for short quick-action
    clips — exactly the toolbox use case.
    """
    args = ["-i", str(src), "-vf", "reverse"]
    if mute:
        args += ["-an"]
    else:
        args += ["-af", "areverse", "-c:a", "aac", "-b:a", "160k"]
    args += [*_VENC, str(out)]
    return args


# ---------------------------------------------------------------------------
# Runners (need a binary; raise VideoOpError when absent or on failure)
# ---------------------------------------------------------------------------


def _run(args: list[str], *, timeout: int = 600) -> None:
    exe = ffmpeg_exe()
    if not exe:
        raise VideoOpError("no FFmpeg binary available for the video operation")
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise VideoOpError(f"FFmpeg failed to start: {exc}") from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip().splitlines()
        tail = "\n".join(stderr[-6:]) if stderr else "(no stderr)"
        raise VideoOpError(f"video op failed (exit {proc.returncode}):\n{tail}")


def trim(src: Path, out: Path, *, start: float = 0.0, end: Optional[float] = None) -> Path:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    _run(trim_args(Path(src), Path(out), start=start, end=end))
    return Path(out)


def crop(src: Path, out: Path, *, x: int, y: int, width: int, height: int) -> Path:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    _run(crop_args(Path(src), Path(out), x=x, y=y, width=width, height=height))
    return Path(out)


def resize(src: Path, out: Path, *, width: int = 0, height: int = 0, keep_aspect: bool = True) -> Path:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    _run(resize_args(Path(src), Path(out), width=width, height=height, keep_aspect=keep_aspect))
    return Path(out)


def change_speed(src: Path, out: Path, *, factor: float, mute: bool = False) -> Path:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    _run(speed_args(Path(src), Path(out), factor=factor, mute=mute))
    return Path(out)


def mute(src: Path, out: Path) -> Path:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    _run(mute_args(Path(src), Path(out)))
    return Path(out)


def reverse(src: Path, out: Path, *, mute: bool = False) -> Path:
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    _run(reverse_args(Path(src), Path(out), mute=mute))
    return Path(out)


def concat(sources: list[Path], out: Path, *, timeout: int = 600) -> Path:
    """Join compatible clips end-to-end via the concat demuxer (stream-copy).

    Fast and lossless for clips that share codec/params — the common case when
    merging clips MediaHub itself rendered (reels, story cards). Mismatched
    inputs should be normalised first (resize) before merging.
    """
    srcs = [Path(s) for s in sources]
    if not srcs:
        raise VideoOpError("concat needs at least one source")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as fh:
        for s in srcs:
            # Single-quote-escape per the concat demuxer's grammar.
            safe = str(s.resolve()).replace("'", "'\\''")
            fh.write(f"file '{safe}'\n")
        list_path = fh.name
    try:
        _run(
            ["-f", "concat", "-safe", "0", "-i", list_path, "-c", "copy", str(out)],
            timeout=timeout,
        )
    finally:
        try:
            Path(list_path).unlink()
        except OSError:
            pass
    return Path(out)


def ffmpeg_available() -> bool:
    """True when an FFmpeg binary is resolvable (cheap, no subprocess)."""
    return bool(ffmpeg_exe())


__all__ = [
    "VideoOpError",
    "trim_args",
    "crop_args",
    "resize_args",
    "speed_args",
    "mute_args",
    "reverse_args",
    "trim",
    "crop",
    "resize",
    "change_speed",
    "mute",
    "reverse",
    "concat",
    "ffmpeg_available",
]
