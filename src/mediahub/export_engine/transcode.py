"""export_engine/transcode.py — deterministic FFmpeg video/GIF transcodes (1.19).

The one renderer the export engine did not already have a home for: turning a
rendered MP4 into an animated GIF or a WebM (VP9), and the reverse hop GIF→MP4
that social tools always want. Everything else (PNG/JPG/SVG/print-PDF, PPTX/
DOCX, WAV/MP3, the reel MP4 itself, the pack ZIP) is produced by an adapter
that already shipped; this module fills the GIF/WebM gap.

Design mirrors ``audio/ops.py`` exactly: each operation has a pure ``*_args``
builder that returns the FFmpeg fragment (unit-testable with no binary present)
and a thin runner that executes it. FFmpeg is resolved via the shared
``visual/reel_ffmpeg.ffmpeg_exe``; when no binary is available the runners raise
:class:`TranscodeError` — an honest error, never a silent no-op or a fabricated
file. These are **maths, not judgement** — fixed filter graphs, same input +
args → same bytes — so they stay deterministic like the rest of the engine.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from mediahub.visual.reel_ffmpeg import ffmpeg_exe


class TranscodeError(RuntimeError):
    """A transcode could not run — honest error, never a silent fallback."""


def available() -> bool:
    """True when an FFmpeg binary can be resolved (cheap, no subprocess)."""
    return ffmpeg_exe() is not None


# ---------------------------------------------------------------------------
# Pure helpers / argument builders (testable with no FFmpeg present)
# ---------------------------------------------------------------------------


def crf_for_quality(quality: int, *, best: int, worst: int) -> int:
    """Map a 10–100 quality slider onto an encoder CRF.

    CRF is inverted (lower = better), so ``best`` is the CRF at quality 100 and
    ``worst`` the CRF at quality 10, interpolated linearly between.
    """
    q = max(10, min(100, int(quality)))
    frac = (q - 10) / 90.0
    return int(round(worst + (best - worst) * frac))


def _even_scale(scale: float) -> str:
    """A lanczos scale filter by factor, snapped to even dimensions (H.264/VP9
    need even width/height). ``1.0`` → empty (no scaling)."""
    s = max(0.1, min(4.0, float(scale)))
    if abs(s - 1.0) < 1e-6:
        return ""
    return f"scale=trunc(iw*{s:.4f}/2)*2:trunc(ih*{s:.4f}/2)*2:flags=lanczos"


def gif_args(
    src: Path,
    out: Path,
    *,
    fps: int = 12,
    width: int = 0,
    scale: float = 1.0,
    loop: int = 0,
    dither: str = "bayer",
    max_colors: int = 256,
) -> list[str]:
    """FFmpeg args to turn a video into a high-quality animated GIF.

    Uses the two-stage ``palettegen``/``paletteuse`` graph in a single command
    (split → generate an optimal palette → apply it) — the standard way to get
    a clean GIF instead of FFmpeg's muddy default 256-colour quantiser. ``loop``
    is GIF's own field (0 = loop forever, -1 = play once). Size comes from
    ``width`` (explicit px, height auto) if given, else from ``scale`` (a factor
    on the source size); ``width`` 0 and ``scale`` 1.0 keep the source size.
    """
    fps = max(1, min(50, int(fps)))
    colors = max(2, min(256, int(max_colors)))
    if width and width > 0:
        scale_filt = f",scale={int(width)}:-1:flags=lanczos"
    elif abs(float(scale) - 1.0) > 1e-6:
        s = max(0.1, min(4.0, float(scale)))
        scale_filt = f",scale=trunc(iw*{s:.4f}):-1:flags=lanczos"
    else:
        scale_filt = ""
    d = dither if dither in ("bayer", "sierra2_4a", "floyd_steinberg") else "bayer"
    bayer = ":bayer_scale=5" if d == "bayer" else ""
    chain = (
        f"[0:v]fps={fps}{scale_filt},split[a][b];"
        f"[a]palettegen=max_colors={colors}:stats_mode=diff[p];"
        f"[b][p]paletteuse=dither={d}{bayer}"
    )
    return ["-i", str(src), "-filter_complex", chain, "-loop", str(int(loop)), str(out)]


def gif_to_video_args(src: Path, out: Path, *, crf: int = 23, fmt: str = "mp4") -> list[str]:
    """FFmpeg args to turn an (animated) GIF into an MP4/WebM.

    Pads to even dimensions and sets ``yuv420p`` so the result plays in every
    browser/phone — GIFs are commonly odd-sized, which H.264 rejects.
    """
    even = "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    if fmt == "webm":
        codec = ["-c:v", "libvpx-vp9", "-crf", str(int(crf)), "-b:v", "0", "-pix_fmt", "yuv420p"]
        # -movflags is an MP4/MOV muxer option; the WebM muxer rejects it.
        movflags: list[str] = []
    else:
        codec = [
            "-c:v",
            "libx264",
            "-crf",
            str(int(crf)),
            "-preset",
            "medium",
            "-pix_fmt",
            "yuv420p",
        ]
        movflags = ["-movflags", "faststart"]
    return ["-i", str(src), *movflags, "-vf", even, *codec, str(out)]


def webm_args(
    src: Path,
    out: Path,
    *,
    crf: int = 32,
    scale: float = 1.0,
    transparent: bool = False,
) -> list[str]:
    """FFmpeg args to transcode a video to WebM (VP9).

    Constant-quality VP9 (``-b:v 0`` + CRF). ``transparent`` keeps an alpha
    channel (``yuva420p``) for overlay use; otherwise ``yuv420p``.
    """
    # VP9 + yuv420p needs even dimensions; snap them even even at scale 1.0
    # (an odd-sized source would otherwise fail), mirroring mp4_args.
    vf = _even_scale(scale) or "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    pix = "yuva420p" if transparent else "yuv420p"
    args = ["-i", str(src), "-vf", vf]
    args += [
        "-c:v",
        "libvpx-vp9",
        "-crf",
        str(int(crf)),
        "-b:v",
        "0",
        "-pix_fmt",
        pix,
    ]
    if transparent:
        args += ["-auto-alt-ref", "0"]
    args += ["-c:a", "libopus", "-b:a", "128k", str(out)]
    return args


def mp4_args(src: Path, out: Path, *, crf: int = 23, scale: float = 1.0) -> list[str]:
    """FFmpeg args to (re-)transcode a video to a web-friendly H.264 MP4."""
    vf = _even_scale(scale) or "scale=trunc(iw/2)*2:trunc(ih/2)*2"
    return [
        "-i",
        str(src),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-crf",
        str(int(crf)),
        "-preset",
        "medium",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "faststart",
        "-c:a",
        "aac",
        "-b:a",
        "160k",
        str(out),
    ]


# ---------------------------------------------------------------------------
# Runners (need a binary; raise TranscodeError when absent or on failure)
# ---------------------------------------------------------------------------


def _run(args: list[str], *, timeout: int = 600) -> None:
    exe = ffmpeg_exe()
    if not exe:
        raise TranscodeError("no FFmpeg binary available for the transcode")
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise TranscodeError(f"FFmpeg failed to start: {exc}") from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip().splitlines()
        tail = "\n".join(stderr[-6:]) if stderr else "(no stderr)"
        raise TranscodeError(f"transcode failed (exit {proc.returncode}):\n{tail}")


def video_to_gif(
    src: Path,
    out: Path,
    *,
    fps: int = 12,
    width: int = 480,
    scale: float = 1.0,
    loop: int = 0,
    dither: str = "bayer",
) -> Path:
    """Render ``src`` to an animated GIF at ``out``.

    Size is ``width`` px (height auto) when given, else ``scale`` × source.
    """
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    _run(
        gif_args(Path(src), Path(out), fps=fps, width=width, scale=scale, loop=loop, dither=dither)
    )
    return Path(out)


def gif_to_video(src: Path, out: Path, *, fmt: str = "mp4", quality: int = 80) -> Path:
    """Turn a GIF into an MP4 (``fmt="mp4"``) or WebM (``fmt="webm"``)."""
    best, worst = (18, 28) if fmt != "webm" else (24, 40)
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    _run(
        gif_to_video_args(
            Path(src), Path(out), crf=crf_for_quality(quality, best=best, worst=worst), fmt=fmt
        )
    )
    return Path(out)


def to_webm(
    src: Path,
    out: Path,
    *,
    quality: int = 70,
    scale: float = 1.0,
    transparent: bool = False,
) -> Path:
    """Transcode ``src`` to a VP9 WebM at ``out``."""
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    crf = crf_for_quality(quality, best=15, worst=50)
    _run(webm_args(Path(src), Path(out), crf=crf, scale=scale, transparent=transparent))
    return Path(out)


def to_mp4(src: Path, out: Path, *, quality: int = 80, scale: float = 1.0) -> Path:
    """(Re-)transcode ``src`` to a web-friendly H.264 MP4 at ``out``."""
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    crf = crf_for_quality(quality, best=18, worst=28)
    _run(mp4_args(Path(src), Path(out), crf=crf, scale=scale))
    return Path(out)


__all__ = [
    "TranscodeError",
    "available",
    "crf_for_quality",
    "gif_args",
    "gif_to_video_args",
    "webm_args",
    "mp4_args",
    "video_to_gif",
    "gif_to_video",
    "to_webm",
    "to_mp4",
]
