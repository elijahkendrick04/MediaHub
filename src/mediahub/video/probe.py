"""video/probe.py — clip metadata for the video suite (roadmap 1.6).

A footage clip the club uploads (a phone video of a race, a cheer, a coach's
talking recap) has to be *measured* before any timeline can be built from it:
how long is it, what shape is the frame, does it carry sound, what codec is it.
The Clip-Maker (``clip_maker.py``), the EDL compiler (``edl.py``) and the
reframe planner (``reframe.py``) all read these numbers; none of them should
each re-implement the parsing.

Like ``reel_ffmpeg.media_duration_seconds``, this reads the metadata FFmpeg
prints to **stderr** for ``ffmpeg -i <file>`` — deliberately *not* ``ffprobe``,
because the bundled static wheel (``imageio-ffmpeg``) ships only ``ffmpeg``. The
text-parsing is a **pure function** (:func:`parse_ffmpeg_probe`) so it is fully
unit-testable with no binary present; the only impure part is the one
subprocess call in :func:`probe_clip`.

No AI, no judgement — this is measurement. When FFmpeg is unavailable
:func:`probe_clip` raises :class:`ProbeUnavailable` honestly rather than
guessing a duration or shape.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, asdict
from pathlib import Path

from mediahub.visual.reel_ffmpeg import ffmpeg_exe


class ProbeUnavailable(RuntimeError):
    """Raised when a clip cannot be measured (no FFmpeg binary on the box).

    Mirrors ``ReelEngineUnavailable`` / ``ASRUnavailable``: an honest error is
    always better than a fabricated duration or frame shape feeding the
    timeline.
    """


@dataclass(frozen=True)
class ClipProbe:
    """Measured metadata for one footage clip.

    Every field has a safe default so a malformed/partial FFmpeg banner still
    yields a usable record (duration 0, no streams) rather than an exception —
    the *caller* decides whether a zero-duration clip is acceptable.
    """

    duration_ms: int = 0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_video: bool = False
    has_audio: bool = False
    video_codec: str = ""
    audio_codec: str = ""
    rotation: int = 0

    @property
    def orientation(self) -> str:
        """Display orientation after any container rotation is applied."""
        w, h = self.display_size
        if w <= 0 or h <= 0:
            return "unknown"
        if w == h:
            return "square"
        return "landscape" if w > h else "portrait"

    @property
    def display_size(self) -> tuple[int, int]:
        """``(width, height)`` after a 90/270° rotation swaps the axes."""
        if self.rotation in (90, 270, -90, -270):
            return self.height, self.width
        return self.width, self.height

    @property
    def aspect_ratio(self) -> float:
        w, h = self.display_size
        return (w / h) if (w and h) else 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["orientation"] = self.orientation
        return d


# ``Duration: 00:00:12.34, start: ...`` (hours:minutes:seconds.cs)
_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")
# A video stream line carries ``, 1920x1080`` (optionally ``1920x1080 [SAR ...]``)
# and ``, 29.97 fps``. The codec is the token after ``Video: ``.
_VIDEO_RE = re.compile(r"Stream #[^\n]*Video:\s*([A-Za-z0-9_.\-]+)")
_SIZE_RE = re.compile(r"(?<!\d)(\d{2,5})x(\d{2,5})(?!\d)")
_FPS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*fps")
_TBR_RE = re.compile(r"(\d+(?:\.\d+)?)\s*tbr")
_AUDIO_RE = re.compile(r"Stream #[^\n]*Audio:\s*([A-Za-z0-9_.\-]+)")
_ROTATE_RE = re.compile(r"rotate\s*:\s*(-?\d+)")
_DISPLAYMATRIX_RE = re.compile(r"displaymatrix:\s*rotation of\s*(-?\d+(?:\.\d+)?)\s*degrees")


def _duration_ms_from(text: str) -> int:
    m = _DURATION_RE.search(text)
    if not m:
        return 0
    h, mnt, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
    return max(0, round((h * 3600 + mnt * 60 + s) * 1000))


def _video_stream_block(text: str) -> str:
    """Return the substring starting at the first Video stream line.

    Size/fps tokens are read from *that* line only so an Audio stream's stray
    number can never be mistaken for a frame dimension.
    """
    m = _VIDEO_RE.search(text)
    if not m:
        return ""
    start = m.start()
    nl = text.find("\n", start)
    return text[start:nl] if nl != -1 else text[start:]


def _normalise_rotation(deg: float) -> int:
    """Fold any rotation onto one of 0/90/180/270 (the axis-swap cases)."""
    try:
        d = int(round(deg)) % 360
    except (TypeError, ValueError):
        return 0
    # Snap to the nearest right angle; container rotations are always multiples.
    return min((0, 90, 180, 270), key=lambda q: min(abs(d - q), 360 - abs(d - q)))


def parse_ffmpeg_probe(stderr_text: str) -> ClipProbe:
    """Parse the metadata FFmpeg prints for ``ffmpeg -i <file>`` into a probe.

    Pure and deterministic: no subprocess, no I/O. Tolerates missing fields —
    an audio-only clip yields ``has_video=False`` with a real duration; a video
    with no recognised fps falls back to the ``tbr`` figure, then 0.
    """
    text = stderr_text or ""
    duration_ms = _duration_ms_from(text)

    vblock = _video_stream_block(text)
    has_video = bool(vblock)
    width = height = 0
    fps = 0.0
    video_codec = ""
    if has_video:
        cm = _VIDEO_RE.search(text)
        video_codec = cm.group(1) if cm else ""
        sm = _SIZE_RE.search(vblock)
        if sm:
            width, height = int(sm.group(1)), int(sm.group(2))
        fm = _FPS_RE.search(vblock) or _TBR_RE.search(vblock)
        if fm:
            try:
                fps = round(float(fm.group(1)), 3)
            except ValueError:
                fps = 0.0

    am = _AUDIO_RE.search(text)
    has_audio = bool(am)
    audio_codec = am.group(1) if am else ""

    rotation = 0
    rm = _ROTATE_RE.search(text)
    if rm:
        rotation = _normalise_rotation(float(rm.group(1)))
    else:
        dm = _DISPLAYMATRIX_RE.search(text)
        if dm:
            # displaymatrix reports the rotation to undo; FFmpeg negates it.
            rotation = _normalise_rotation(-float(dm.group(1)))

    return ClipProbe(
        duration_ms=duration_ms,
        width=width,
        height=height,
        fps=fps,
        has_video=has_video,
        has_audio=has_audio,
        video_codec=video_codec,
        audio_codec=audio_codec,
        rotation=rotation,
    )


def probe_clip(path: Path | str, *, timeout: int = 60) -> ClipProbe:
    """Measure a clip on disk via ``ffmpeg -i``. Raises :class:`ProbeUnavailable`.

    The one impure entry point: it shells out to FFmpeg once and hands the
    stderr banner to :func:`parse_ffmpeg_probe`. ``ffmpeg -i`` with no output
    file exits non-zero *by design* (it has nothing to write), so the return
    code is ignored — the banner on stderr is the payload.
    """
    exe = ffmpeg_exe()
    if not exe:
        raise ProbeUnavailable(
            "Measuring a video clip needs an FFmpeg binary: install the "
            "imageio-ffmpeg package, put ffmpeg on PATH, or point MEDIAHUB_FFMPEG "
            "at a binary."
        )
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"clip not found: {p}")
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-i", str(p)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as e:
        raise ProbeUnavailable(f"ffmpeg probe timed out after {timeout}s") from e
    return parse_ffmpeg_probe(proc.stderr or "")


__all__ = [
    "ProbeUnavailable",
    "ClipProbe",
    "parse_ffmpeg_probe",
    "probe_clip",
]
