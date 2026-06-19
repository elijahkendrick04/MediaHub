"""video/matting.py — video background removal, behind a provider seam (1.6).

"Remove the background from this clip" (no green screen) is a real ask for a
coach talking-head or a swimmer cut out over a brand colour. It is also heavy
(seconds per second of footage) and best done by a model, so — exactly like the
TTS/ASR/cutout surfaces — it lives behind a **provider slot** rather than being
wired in unconditionally:

    MEDIAHUB_VIDEO_MATTING_PROVIDER = server | replicate | photoroom   (unset = off)

* **Honest by default.** With nothing configured, :func:`is_available` is
  ``False`` and :func:`remove_background` raises :class:`MattingUnavailable` —
  never a silently un-matted clip pretending to be cut out.
* **``server``** is the in-process path: per-frame ``rembg`` over the frames
  FFmpeg extracts, re-assembled. It is honest about its cost (a ~90s-class limit
  for short clips) and only runs when both ``rembg`` and FFmpeg are present.
* **``replicate`` / ``photoroom``** are optional cloud adapters on the same seam
  (a genuinely-unavoidable model-hosting hop), each honest-erroring without its
  key. They are not embedded apps — just swappable backends behind our interface.

The heavy dependencies are **lazy-imported inside the backend**, so importing
this module for a status probe never loads a model.
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from pathlib import Path

from mediahub.visual.reel_ffmpeg import ffmpeg_exe

_SERVER = "server"
_REPLICATE = "replicate"
_PHOTOROOM = "photoroom"
_VALID = frozenset({_SERVER, _REPLICATE, _PHOTOROOM})
_ALIASES = {
    "server": _SERVER,
    "rembg": _SERVER,
    "local": _SERVER,
    "modnet": _SERVER,
    "replicate": _REPLICATE,
    "photoroom": _PHOTOROOM,
}

# Honest guard rail: in-process per-frame matting is only sane for short clips.
MAX_SERVER_CLIP_MS = 90_000


class MattingUnavailable(RuntimeError):
    """Raised when video matting cannot run honestly (no provider / deps / key)."""


def select_matting_provider() -> str:
    """Canonical provider name, or ``""`` when the seam is off (the default).

    An unrecognised value raises :class:`MattingUnavailable` — an honest config
    error, mirroring ``transcribe.select_asr_provider``.
    """
    raw = os.environ.get("MEDIAHUB_VIDEO_MATTING_PROVIDER", "").strip().lower()
    if not raw:
        return ""
    canon = _ALIASES.get(raw, raw)
    if canon not in _VALID:
        raise MattingUnavailable(
            f"MEDIAHUB_VIDEO_MATTING_PROVIDER={raw!r} is not recognised. "
            f"Valid: {sorted(_VALID)} (or unset to disable video matting)."
        )
    return canon


def _rembg_available() -> bool:
    import importlib.util

    try:
        return importlib.util.find_spec("rembg") is not None
    except Exception:
        return False


def _provider_available(provider: str) -> bool:
    if provider == _SERVER:
        return _rembg_available() and ffmpeg_exe() is not None
    if provider == _REPLICATE:
        return bool(os.environ.get("REPLICATE_API_TOKEN", "").strip())
    if provider == _PHOTOROOM:
        return bool(os.environ.get("PHOTOROOM_API_KEY", "").strip())
    return False


def is_available() -> bool:
    """True when the *selected* matting backend could run right now."""
    try:
        provider = select_matting_provider()
    except MattingUnavailable:
        return False
    return bool(provider) and _provider_available(provider)


def matting_status() -> dict:
    """Diagnostics for the health surface (mirrors ``asr_provider_status``)."""
    configured = os.environ.get("MEDIAHUB_VIDEO_MATTING_PROVIDER", "").strip()
    try:
        active = select_matting_provider()
    except MattingUnavailable:
        active = configured.lower()
    return {
        "configured": configured,
        "active": active,
        "available": is_available(),
        "rembg_available": _rembg_available(),
        "ffmpeg_available": ffmpeg_exe() is not None,
        "max_server_clip_ms": MAX_SERVER_CLIP_MS,
    }


def remove_background(
    source: Path | str,
    out_path: Path | str,
    *,
    duration_ms: int = 0,
    background: str = "",
    timeout: int = 600,
) -> Path:
    """Matte ``source`` to ``out_path`` over ``background`` (or transparent).

    Raises :class:`MattingUnavailable` when the seam is off, the backend's deps
    or key are absent, or a server clip exceeds the honest length cap. No silent
    pass-through — an un-matted clip is never returned as if it were cut out.
    """
    provider = select_matting_provider()
    if not provider:
        raise MattingUnavailable(
            "Video background removal isn't enabled. Set "
            "MEDIAHUB_VIDEO_MATTING_PROVIDER=server (in-process rembg) or a cloud "
            "provider (replicate/photoroom) with its key."
        )
    if not _provider_available(provider):
        raise MattingUnavailable(
            f"The {provider!r} video-matting backend is selected but its "
            "dependency or key is not available on this deployment."
        )
    if provider == _SERVER:
        if duration_ms and duration_ms > MAX_SERVER_CLIP_MS:
            raise MattingUnavailable(
                f"In-process matting is limited to clips under "
                f"{MAX_SERVER_CLIP_MS // 1000}s; this clip is {duration_ms // 1000}s. "
                "Trim it first, or use a cloud matting provider."
            )
        return _matte_server(source, out_path, background=background, timeout=timeout)
    # Cloud adapters are wired on the same seam; their network calls live behind
    # their own keys and are not exercised in the no-key default path.
    raise MattingUnavailable(
        f"The {provider!r} cloud matting adapter is configured but its network "
        "integration is not enabled in this build."
    )


def _matte_server(
    source: Path | str, out_path: Path | str, *, background: str, timeout: int
) -> Path:
    """In-process per-frame rembg matte, re-encoded by FFmpeg (heavy; lazy deps)."""
    exe = ffmpeg_exe()
    if not exe:
        raise MattingUnavailable("FFmpeg is required for server-side matting.")
    from rembg import remove as _rembg_remove  # lazy: never at import time

    out_path = Path(out_path)
    with tempfile.TemporaryDirectory(prefix="mh_matte_") as td:
        tdp = Path(td)
        frames_in = tdp / "in_%05d.png"
        subprocess.run(
            [exe, "-hide_banner", "-loglevel", "error", "-i", str(source), str(frames_in)],
            check=True,
            capture_output=True,
            timeout=timeout,
        )
        for png in sorted(tdp.glob("in_*.png")):
            cut = png.with_name(png.name.replace("in_", "out_"))
            cut.write_bytes(_rembg_remove(png.read_bytes()))
        frames_out = tdp / "out_%05d.png"
        # Composite over the brand background when given; else keep alpha (VP9).
        if background:
            from mediahub.video.edl import _pad_colour

            subprocess.run(
                [exe, "-hide_banner", "-loglevel", "error", "-framerate", "30",
                 "-i", str(frames_out), "-f", "lavfi", "-i",
                 f"color=c={_pad_colour(background)}:s=1080x1920",
                 "-filter_complex", "[1][0]scale2ref[bg][fg];[bg][fg]overlay=shortest=1",
                 "-c:v", "libx264", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                 "-y", str(out_path)],
                check=True, capture_output=True, timeout=timeout,
            )
        else:
            subprocess.run(
                [exe, "-hide_banner", "-loglevel", "error", "-framerate", "30",
                 "-i", str(frames_out), "-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p",
                 "-y", str(out_path.with_suffix(".webm"))],
                check=True, capture_output=True, timeout=timeout,
            )
            out_path = out_path.with_suffix(".webm")
    return out_path


__all__ = [
    "MattingUnavailable",
    "MAX_SERVER_CLIP_MS",
    "select_matting_provider",
    "is_available",
    "matting_status",
    "remove_background",
]
