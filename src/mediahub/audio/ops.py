"""audio/ops.py — deterministic FFmpeg audio operations (roadmap 1.8).

The mechanical audio edits a club needs: trim a clip, fade it in/out, change
its gain, nudge its speed, extract the audio from a video, concatenate or mix
clips, and convert between formats for export (1.19). These are **maths, not
judgement** — fixed FFmpeg filter graphs with no model in the loop — so they
live here as deterministic, dependency-free helpers (same input + args → same
output bytes), exactly like the still-graphic colour science stays
deterministic.

The design mirrors ``visual/audio_mux.py``: each operation has a pure
``*_filter`` / ``*_args`` builder that returns the FFmpeg fragment (unit-testable
with no binary present) and a thin wrapper that runs it. FFmpeg is resolved via
the shared ``visual/reel_ffmpeg.ffmpeg_exe`` (system binary, ``MEDIAHUB_FFMPEG``,
or the bundled ``imageio-ffmpeg`` static build). When no binary is available the
runners raise :class:`AudioOpError` — an honest error, never a silent no-op.
"""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from mediahub.visual.reel_ffmpeg import ffmpeg_exe

# Export containers we can encode to (1.19 leans on these). Maps a logical
# format to (suffix, codec args) — deterministic, no quality guessing.
_ENCODERS: dict[str, tuple[str, list[str]]] = {
    "mp3": (".mp3", ["-c:a", "libmp3lame", "-b:a", "192k"]),
    "wav": (".wav", ["-c:a", "pcm_s16le"]),
    "m4a": (".m4a", ["-c:a", "aac", "-b:a", "192k"]),
    "aac": (".m4a", ["-c:a", "aac", "-b:a", "192k"]),
    "ogg": (".ogg", ["-c:a", "libvorbis", "-q:a", "5"]),
    "opus": (".opus", ["-c:a", "libopus", "-b:a", "128k"]),
    "flac": (".flac", ["-c:a", "flac"]),
}

_DURATION_RE = re.compile(r"Duration:\s*(\d+):(\d{2}):(\d{2})\.(\d+)")


class AudioOpError(RuntimeError):
    """An audio operation could not run — honest error, never a silent fallback."""


# ---------------------------------------------------------------------------
# Pure filter / argument builders (testable with no FFmpeg present)
# ---------------------------------------------------------------------------


def fade_filter(*, duration_sec: float, fade_in: float = 0.0, fade_out: float = 0.0) -> str:
    """An ``afade`` in/out chain for a clip of ``duration_sec``. May be empty."""
    d = max(0.0, float(duration_sec))
    parts: list[str] = []
    if fade_in and fade_in > 0:
        parts.append(f"afade=t=in:st=0:d={float(fade_in):.3f}")
    if fade_out and fade_out > 0 and d > 0:
        start = max(0.0, d - float(fade_out))
        parts.append(f"afade=t=out:st={start:.3f}:d={float(fade_out):.3f}")
    return ",".join(parts)


def gain_filter(gain_db: float) -> str:
    """A ``volume`` filter expressed in decibels (0 dB → unity, omitted)."""
    g = float(gain_db)
    if abs(g) < 1e-6:
        return ""
    return f"volume={g:.3f}dB"


def speed_filter(factor: float) -> str:
    """An ``atempo`` chain for a speed ``factor`` (pitch preserved).

    ``atempo`` only accepts 0.5–2.0 per stage, so out-of-range factors are split
    into a chain of in-range multipliers. Bounded to [0.25, 4.0]; 1.0 → empty.
    """
    f = max(0.25, min(4.0, float(factor)))
    if abs(f - 1.0) < 1e-6:
        return ""
    stages: list[float] = []
    remaining = f
    while remaining > 2.0:
        stages.append(2.0)
        remaining /= 2.0
    while remaining < 0.5:
        stages.append(0.5)
        remaining /= 0.5
    stages.append(remaining)
    return ",".join(f"atempo={s:.6f}" for s in stages)


def trim_args(src: Path, out: Path, *, start: float = 0.0, end: Optional[float] = None) -> list[str]:
    """FFmpeg args (after the binary) to cut ``[start, end)`` from ``src``."""
    s = max(0.0, float(start))
    args = ["-ss", f"{s:.3f}", "-i", str(src)]
    if end is not None:
        dur = max(0.0, float(end) - s)
        args += ["-t", f"{dur:.3f}"]
    args += ["-map", "0:a", "-c:a", "pcm_s16le", str(out)]
    return args


def filter_args(src: Path, out: Path, *, chain: str, codec: Optional[list[str]] = None) -> list[str]:
    """FFmpeg args to apply a single-input audio filter ``chain`` to ``src``."""
    args = ["-i", str(src)]
    if chain:
        args += ["-af", chain]
    args += ["-map", "0:a"]
    args += codec if codec is not None else ["-c:a", "pcm_s16le"]
    args += [str(out)]
    return args


def extract_audio_args(video: Path, out: Path, *, fmt: str = "wav") -> list[str]:
    """FFmpeg args to pull the audio track out of a video into ``fmt``."""
    suffix, codec = _ENCODERS.get(fmt.lower(), _ENCODERS["wav"])
    return ["-i", str(video), "-vn", "-map", "0:a", *codec, str(out)]


def convert_args(src: Path, out: Path, *, fmt: str) -> list[str]:
    """FFmpeg args to transcode ``src`` to ``fmt`` (export engine, 1.19)."""
    key = fmt.lower()
    if key not in _ENCODERS:
        raise AudioOpError(f"unsupported audio export format {fmt!r}")
    _, codec = _ENCODERS[key]
    return ["-i", str(src), "-map", "0:a", *codec, str(out)]


def export_suffix(fmt: str) -> str:
    """The canonical file suffix for an export format (``mp3`` → ``.mp3``)."""
    key = fmt.lower()
    if key not in _ENCODERS:
        raise AudioOpError(f"unsupported audio export format {fmt!r}")
    return _ENCODERS[key][0]


# ---------------------------------------------------------------------------
# Runners (need a binary; raise AudioOpError when absent or on failure)
# ---------------------------------------------------------------------------


def _run(args: list[str], *, timeout: int = 300) -> None:
    exe = ffmpeg_exe()
    if not exe:
        raise AudioOpError("no FFmpeg binary available for the audio operation")
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioOpError(f"FFmpeg failed to start: {exc}") from exc
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip().splitlines()
        tail = "\n".join(stderr[-6:]) if stderr else "(no stderr)"
        raise AudioOpError(f"audio op failed (exit {proc.returncode}):\n{tail}")


def probe_duration(src: Path) -> Optional[float]:
    """Clip duration in seconds, parsed from FFmpeg's banner. ``None`` if unknown.

    Uses ``ffmpeg -i`` (no separate ffprobe needed — the bundled imageio-ffmpeg
    ships only ffmpeg). Best-effort and side-effect-free; never raises.
    """
    exe = ffmpeg_exe()
    if not exe or not Path(src).is_file():
        return None
    try:
        proc = subprocess.run(
            [exe, "-hide_banner", "-i", str(src)],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    m = _DURATION_RE.search(proc.stderr or "")
    if not m:
        return None
    h, mm, ss, frac = m.groups()
    return int(h) * 3600 + int(mm) * 60 + int(ss) + float("0." + frac)


def apply_filter(src: Path, out: Path, *, chain: str, codec: Optional[list[str]] = None) -> Path:
    """Run a single-input audio filter ``chain`` over ``src`` → ``out``.

    The shared runner for every single-input filter op (gain/fade/speed and the
    ``audio/clean`` denoise/loudnorm passes), so callers never reach for the
    private runner.
    """
    _run(filter_args(Path(src), Path(out), chain=chain, codec=codec))
    return Path(out)


def trim(src: Path, out: Path, *, start: float = 0.0, end: Optional[float] = None) -> Path:
    _run(trim_args(Path(src), Path(out), start=start, end=end))
    return Path(out)


def fade(
    src: Path,
    out: Path,
    *,
    fade_in: float = 0.0,
    fade_out: float = 0.0,
    duration_sec: Optional[float] = None,
) -> Path:
    d = duration_sec if duration_sec is not None else (probe_duration(src) or 0.0)
    chain = fade_filter(duration_sec=d, fade_in=fade_in, fade_out=fade_out)
    if not chain:
        raise AudioOpError("fade requested with no fade_in/fade_out")
    return apply_filter(src, out, chain=chain)


def gain(src: Path, out: Path, *, gain_db: float) -> Path:
    chain = gain_filter(gain_db)
    if not chain:
        raise AudioOpError("gain of 0 dB is a no-op")
    return apply_filter(src, out, chain=chain)


def change_speed(src: Path, out: Path, *, factor: float) -> Path:
    chain = speed_filter(factor)
    if not chain:
        raise AudioOpError("speed factor of 1.0 is a no-op")
    return apply_filter(src, out, chain=chain)


def extract_audio(video: Path, out: Path, *, fmt: str = "wav") -> Path:
    _run(extract_audio_args(Path(video), Path(out), fmt=fmt))
    return Path(out)


def convert(src: Path, out: Path, *, fmt: str) -> Path:
    _run(convert_args(Path(src), Path(out), fmt=fmt))
    return Path(out)


def concat(sources: list[Path], out: Path) -> Path:
    """Join clips end-to-end (re-encoded to PCM so mismatched inputs splice)."""
    srcs = [Path(s) for s in sources]
    if not srcs:
        raise AudioOpError("concat needs at least one source")
    args: list[str] = []
    for s in srcs:
        args += ["-i", str(s)]
    streams = "".join(f"[{i}:a]" for i in range(len(srcs)))
    graph = f"{streams}concat=n={len(srcs)}:v=0:a=1[aout]"
    args += ["-filter_complex", graph, "-map", "[aout]", "-c:a", "pcm_s16le", str(out)]
    _run(args)
    return Path(out)


def mix(sources: list[Path], out: Path, *, normalize: bool = False) -> Path:
    """Sum clips into one track (``amix``). Pads to the longest input."""
    srcs = [Path(s) for s in sources]
    if not srcs:
        raise AudioOpError("mix needs at least one source")
    args: list[str] = []
    for s in srcs:
        args += ["-i", str(s)]
    streams = "".join(f"[{i}:a]" for i in range(len(srcs)))
    norm = 1 if normalize else 0
    graph = (
        f"{streams}amix=inputs={len(srcs)}:duration=longest:"
        f"dropout_transition=0:normalize={norm}[aout]"
    )
    args += ["-filter_complex", graph, "-map", "[aout]", "-c:a", "pcm_s16le", str(out)]
    _run(args)
    return Path(out)


def silence(out: Path, *, duration_sec: float, sample_rate: int = 44100) -> Path:
    """A deterministic silent clip — useful for padding/timeline gaps."""
    d = max(0.01, float(duration_sec))
    _run(
        [
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=channel_layout=mono:sample_rate={int(sample_rate)}",
            "-t",
            f"{d:.3f}",
            "-c:a",
            "pcm_s16le",
            str(out),
        ]
    )
    return Path(out)


def with_temp_wav(prefix: str = "mh_audio_op_"):
    """Context-manager helper returning a fresh temp dir for op intermediates."""
    return tempfile.TemporaryDirectory(prefix=prefix)


def ffmpeg_available() -> bool:
    """True when an FFmpeg binary is resolvable (cheap, no subprocess)."""
    return bool(ffmpeg_exe())


__all__ = [
    "AudioOpError",
    "fade_filter",
    "gain_filter",
    "speed_filter",
    "trim_args",
    "filter_args",
    "extract_audio_args",
    "convert_args",
    "export_suffix",
    "probe_duration",
    "apply_filter",
    "trim",
    "fade",
    "gain",
    "change_speed",
    "extract_audio",
    "convert",
    "concat",
    "mix",
    "silence",
    "with_temp_wav",
    "ffmpeg_available",
]
