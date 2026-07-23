"""visual/reel_parallel.py — parallel reel composition (roadmap R1.28).

A wall-clock accelerator for the Remotion reel render. Instead of rendering
the whole reel timeline in one serial Node pass, it splits the timeline into
contiguous frame ranges, renders those ranges **concurrently** (one shared
bundle, several segments at once via ``remotion/render_segments.js``), and
**composites** them back into one MP4 with FFmpeg's concat demuxer.

Why this is exact, not approximate
----------------------------------
Every MediaHub Remotion composition is *frame-pure*: a frame's pixels are a
deterministic function of its absolute frame index (``useCurrentFrame()``),
never of wall-clock or render order. Remotion's ``frameRange`` renders the
requested frames at their TRUE timeline positions, so the concatenation of
segments ``[0,a] + [a+1,b] + …`` is byte-for-byte the serial reel — the
cross-beat transition overlaps and the continuous reel-overlay layers are all
computed within whichever segment owns each frame. The split changes only
*how fast* the reel renders, never *what* it renders, so it is invisible to
the content cache key (the same reel rendered serially or in parallel hashes
identically and is freely interchangeable on a cache hit).

Contract (the same honesty rules as the rest of the renderer)
-------------------------------------------------------------
- **Off by default.** Gated on ``MEDIAHUB_REEL_PARALLEL``. Unset → the caller
  takes the unchanged serial path; nothing here runs.
- **Honest fallback, never a broken reel.** Missing Node/Remotion/FFmpeg, too
  few frames to split, a segment-render failure, a concat failure, or an
  output that fails the duration sanity-check all resolve to "use the serial
  render" (``try_render_reel_parallel`` returns ``None``) — never a partial or
  placeholder MP4.
- **Deterministic split.** The frame partition is pure integer arithmetic
  (``plan_segments``); the same duration always splits the same way.

The bulk of the logic is pure builders (``plan_segments``, ``concat_args``,
``concat_list_text``) so the orchestration is unit-tested without Node, a GPU,
or an FFmpeg binary present.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from mediahub.visual.reel_ffmpeg import ffmpeg_exe, media_duration_seconds

_log = logging.getLogger(__name__)

# The compositions run at 30fps (remotion/src/Root.tsx); the split is planned
# at the same rate the serial render uses to derive durationInFrames.
REEL_FPS = 30

# Cap concurrent segments so a parallel render can't launch an unbounded number
# of headless-Chromium instances on a small worker. Operators raise the ceiling
# with MEDIAHUB_REEL_PARALLEL_WORKERS when their box has the cores + RAM.
DEFAULT_MAX_WORKERS = 4

# Below this the split isn't worth the bundle/concat overhead — fall back to
# serial. Every supported reel (≥ 7s ⇒ 210 frames) clears this comfortably.
MIN_FRAMES_TO_SPLIT = 60

# Container-duration tolerance for the post-concat correctness gate. Frame-exact
# segments concat to the exact timeline; a result off by more than this means
# the split went wrong, so we discard it and let the serial path render.
_DURATION_TOLERANCE_SEC = 0.5

REMOTION_DIR = Path(__file__).resolve().parents[1] / "remotion"
RENDER_SEGMENTS_SCRIPT = REMOTION_DIR / "render_segments.js"

_TRUTHY = {"1", "true", "yes", "on"}


class ReelParallelUnavailable(RuntimeError):
    """The parallel path cannot service this request (too few frames, etc.).

    Raised internally and caught by :func:`try_render_reel_parallel`, which
    degrades to the serial render. Never surfaced to the caller as a hard
    error — the serial path is always the source of truth.
    """


# ---------------------------------------------------------------------------
# Gating + sizing (env-driven; pure given the environment)
# ---------------------------------------------------------------------------


def parallel_enabled() -> bool:
    """True when the operator opted into parallel reel composition.

    Off by default so the serial render — and therefore every existing reel
    cache entry — stays byte-identical to the pre-R1.28 behaviour.
    """
    return os.environ.get("MEDIAHUB_REEL_PARALLEL", "").strip().lower() in _TRUTHY


def _cpu_count() -> int:
    return os.cpu_count() or 1


def worker_count(total_frames: int) -> int:
    """How many segments to split ``total_frames`` into.

    ``MEDIAHUB_REEL_PARALLEL_WORKERS`` overrides; otherwise the core count,
    capped at :data:`DEFAULT_MAX_WORKERS`. Never more segments than frames.
    """
    total = max(1, int(total_frames))
    raw = os.environ.get("MEDIAHUB_REEL_PARALLEL_WORKERS", "").strip()
    if raw:
        try:
            n = int(raw)
        except ValueError:
            n = 0
        if n >= 1:
            return min(n, total)
    return max(1, min(_cpu_count(), DEFAULT_MAX_WORKERS, total))


def per_segment_concurrency(n_segments: int) -> int:
    """Browser tabs to allow *per segment* while ``n_segments`` run at once.

    The parallelism comes from running the segments concurrently, so the cores
    are shared across them: ``cores // segments`` tabs each (at least one). On a
    4-core box split four ways that's a single tab per segment — four tabs
    total — which matches the machine without oversubscribing it.
    """
    return max(1, _cpu_count() // max(1, int(n_segments)))


def node_available() -> bool:
    return shutil.which("node") is not None


def remotion_segments_installed() -> bool:
    """True when the segment render script + Remotion deps are present."""
    return RENDER_SEGMENTS_SCRIPT.exists() and (REMOTION_DIR / "node_modules" / "remotion").exists()


def available() -> bool:
    """True when a parallel reel render could run right now.

    Needs Node, the Remotion install + segment script, and an FFmpeg binary to
    composite the segments. Any gap → the caller uses the serial render.
    """
    return node_available() and remotion_segments_installed() and ffmpeg_exe() is not None


# ---------------------------------------------------------------------------
# Pure builders (no subprocess, no filesystem) — the unit-tested core
# ---------------------------------------------------------------------------


def plan_segments(total_frames: int, n_segments: int) -> list[tuple[int, int]]:
    """Partition ``[0, total_frames)`` into contiguous inclusive frame ranges.

    Returns ``[(start, end), …]`` where ``end`` is inclusive, the ranges are
    contiguous with no gaps or overlaps, and they cover every frame exactly
    once — the invariant that makes the concatenation frame-identical to the
    serial render. Frames are spread as evenly as possible (sizes differ by at
    most one), and the number of ranges never exceeds the frame count.
    """
    total = int(total_frames)
    if total < 1:
        raise ValueError("total_frames must be >= 1")
    n = max(1, min(int(n_segments), total))
    base, remainder = divmod(total, n)
    ranges: list[tuple[int, int]] = []
    cursor = 0
    for i in range(n):
        size = base + (1 if i < remainder else 0)
        ranges.append((cursor, cursor + size - 1))
        cursor += size
    return ranges


def concat_list_text(segment_paths: list[Path]) -> str:
    """The FFmpeg concat-demuxer list-file body for ``segment_paths``.

    One ``file '<path>'`` line per segment, in order. Single quotes in a path
    are escaped the way the concat demuxer expects (``'\\''``) so odd cache
    directory names can't break the join.
    """
    if not segment_paths:
        raise ValueError("at least one segment is required to concat")
    lines = []
    for p in segment_paths:
        escaped = str(p).replace("'", "'\\''")
        lines.append(f"file '{escaped}'")
    return "\n".join(lines) + "\n"


def concat_args(list_file: Path, out_path: Path) -> list[str]:
    """Argument list (after the binary) for the lossless segment concat.

    Stream-copies the video (``-c copy``) — the segments share the encoder and
    geometry, so the join is byte-exact and costs no re-encode. The reel is
    silent at this stage; audio rides the existing mux pass afterwards.
    """
    return [
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_file),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(out_path),
    ]


# ---------------------------------------------------------------------------
# Subprocess runners
# ---------------------------------------------------------------------------


def _run_node_segments(
    *,
    composition_id: str,
    props_path: Path,
    manifest_path: Path,
    duration_sec: float,
    size: tuple[int, int],
    concurrency: int,
    timeout: int,
    fps: int = REEL_FPS,
) -> None:
    """Render every planned segment concurrently via render_segments.js."""
    cmd = [
        "node",
        str(RENDER_SEGMENTS_SCRIPT),
        "--composition",
        composition_id,
        "--props",
        str(props_path),
        "--manifest",
        str(manifest_path),
        "--duration",
        str(duration_sec),
        "--width",
        str(int(size[0])),
        "--height",
        str(int(size[1])),
        "--concurrency",
        str(int(concurrency)),
    ]
    # fps-option: append --fps only for a non-default rate so the default
    # segment command stays byte-identical to the pre-fps behaviour.
    if int(fps) != REEL_FPS:
        cmd.extend(["--fps", str(int(fps))])
    from mediahub.visual.proc import run_capture

    try:
        # Kill the whole process group on timeout so the segment's Chromium
        # children die with node instead of leaking (see visual/proc.py).
        proc = run_capture(cmd, cwd=str(REMOTION_DIR), timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"segment render timed out after {timeout}s") from e
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip().splitlines()
        tail = "\n".join(stderr[-15:]) if stderr else "(no stderr)"
        raise RuntimeError(f"segment render failed (exit {proc.returncode}):\n{tail}")


def _run_ffmpeg_concat(list_file: Path, out_path: Path, *, timeout: int) -> None:
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("no FFmpeg binary available for segment concat")
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", *concat_args(list_file, out_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"segment concat timed out after {timeout}s") from e
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip().splitlines()
        tail = "\n".join(stderr[-12:]) if stderr else "(no stderr)"
        raise RuntimeError(f"segment concat failed (exit {proc.returncode}):\n{tail}")


def _verify_duration(video: Path, expected_sec: float) -> None:
    """Correctness gate: the composited reel must be the expected length.

    Best-effort — when the duration can't be probed we trust the frame
    arithmetic and proceed; when it *can* be probed and is off by more than the
    tolerance, the split went wrong, so we raise and let the serial path render.
    """
    measured = media_duration_seconds(video)
    if measured is None:
        return
    if abs(measured - float(expected_sec)) > _DURATION_TOLERANCE_SEC:
        raise RuntimeError(
            f"composited reel is {measured:.2f}s, expected ~{expected_sec:.2f}s "
            "— discarding the parallel result"
        )


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


def render_reel_parallel(
    *,
    composition_id: str,
    props: dict[str, Any],
    out_path: Path,
    duration_sec: float,
    size: tuple[int, int],
    fps: int = REEL_FPS,
    timeout: int = 600,
) -> Path:
    """Render ``props`` as ``composition_id`` in parallel frame-range segments
    and composite them to a single silent MP4 at ``out_path``.

    Produces exactly what the serial ``_run_remotion`` would have written to the
    same path (a silent reel); the caller's downstream audio + poster + manifest
    finishing pass is unchanged. Raises on any failure — callers should use
    :func:`try_render_reel_parallel` for the gated, honest-fallback entry point.
    """
    total_frames = max(1, round(float(duration_sec) * int(fps)))
    if total_frames < MIN_FRAMES_TO_SPLIT:
        raise ReelParallelUnavailable(
            f"{total_frames} frames is below the {MIN_FRAMES_TO_SPLIT}-frame "
            "split threshold; serial render is cheaper"
        )
    n_segments = worker_count(total_frames)
    ranges = plan_segments(total_frames, n_segments)
    if len(ranges) < 2:
        raise ReelParallelUnavailable("split resolved to a single segment; no parallelism to gain")

    out_path = Path(out_path)
    with tempfile.TemporaryDirectory(prefix="mh_reel_par_") as td:
        work = Path(td)
        props_path = work / "props.json"
        props_path.write_text(json.dumps(props, indent=2), encoding="utf-8")

        seg_paths = [work / f"seg{i:02d}.mp4" for i in range(len(ranges))]
        manifest = {
            "segments": [
                {"start": start, "end": end, "output": str(seg)}
                for (start, end), seg in zip(ranges, seg_paths)
            ]
        }
        manifest_path = work / "segments.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

        _run_node_segments(
            composition_id=composition_id,
            props_path=props_path,
            manifest_path=manifest_path,
            duration_sec=float(duration_sec),
            size=size,
            concurrency=per_segment_concurrency(len(ranges)),
            timeout=timeout,
            fps=int(fps),
        )

        missing = [str(p) for p in seg_paths if not (p.exists() and p.stat().st_size > 256)]
        if missing:
            raise RuntimeError(f"segment render left {len(missing)} segment(s) missing/empty")

        list_file = work / "concat.txt"
        list_file.write_text(concat_list_text(seg_paths), encoding="utf-8")
        concat_tmp = work / "reel.mp4"
        _run_ffmpeg_concat(list_file, concat_tmp, timeout=timeout)
        if not concat_tmp.exists() or concat_tmp.stat().st_size < 1024:
            raise RuntimeError("segment concat produced no output")
        _verify_duration(concat_tmp, float(duration_sec))

        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(concat_tmp), str(out_path))

    _log.info(
        "reel_parallel: composited %d segments (%d frames) → %s",
        len(ranges),
        total_frames,
        out_path.name,
    )
    return out_path


def try_render_reel_parallel(
    *,
    composition_id: str,
    props: dict[str, Any],
    out_path: Path,
    duration_sec: float,
    size: tuple[int, int],
    fps: int = REEL_FPS,
    timeout: int = 600,
) -> Optional[Path]:
    """Gated, honest-fallback wrapper around :func:`render_reel_parallel`.

    Returns the rendered path on success, or ``None`` when the parallel path is
    disabled, unavailable, or fails for any reason — the signal for the caller
    to take the serial render. Never raises; the serial path is the source of
    truth and a parallel hiccup must never fail a reel.
    """
    if not parallel_enabled():
        return None
    if not available():
        _log.info(
            "reel_parallel: enabled but prerequisites missing "
            "(node=%s remotion=%s ffmpeg=%s); using serial render",
            node_available(),
            remotion_segments_installed(),
            ffmpeg_exe() is not None,
        )
        return None
    try:
        return render_reel_parallel(
            composition_id=composition_id,
            props=props,
            out_path=out_path,
            duration_sec=duration_sec,
            size=size,
            fps=fps,
            timeout=timeout,
        )
    except ReelParallelUnavailable as e:
        _log.info("reel_parallel: %s; using serial render", e)
        return None
    except Exception as e:  # noqa: BLE001 — any failure degrades to serial
        _log.warning("reel_parallel: parallel render failed (%s); falling back to serial render", e)
        return None


__all__ = [
    "REEL_FPS",
    "DEFAULT_MAX_WORKERS",
    "MIN_FRAMES_TO_SPLIT",
    "ReelParallelUnavailable",
    "parallel_enabled",
    "worker_count",
    "per_segment_concurrency",
    "node_available",
    "remotion_segments_installed",
    "available",
    "plan_segments",
    "concat_list_text",
    "concat_args",
    "render_reel_parallel",
    "try_render_reel_parallel",
]
