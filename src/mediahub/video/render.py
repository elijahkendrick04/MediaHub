"""video/render.py — render an EDL to an MP4 over the FFmpeg engine (1.6).

This is the footage path's equivalent of ``visual.motion`` for reels: it takes a
validated :class:`~mediahub.video.edl.EDL`, compiles its deterministic filter
graph (``edl.compile_filtergraph``), burns the caption track (via
``subtitle_burn``'s ASS document), runs FFmpeg **server-side**, and caches the
result under ``DATA_DIR/motion_cache/video/<hash>.mp4`` with a ``<hash>.json``
explainability manifest beside it — the same cache-and-manifest discipline the
reel renderer uses.

What stays honest and deterministic, by the engine rules:

* **Frame-pure.** The output is a pure function of the EDL + the source bytes,
  so the content hash (which folds in each source's size+mtime) makes a re-render
  a cache hit and a changed cut a fresh key — never a silently stale video.
* **Server-side only.** Rendering shells out to FFmpeg on the box (the free reel
  engine's binary); there is no customer-side render. When FFmpeg/Playwright
  isn't available the call raises :class:`VideoEngineUnavailable` — never a fake
  or half-made file.
* **Captions carry the message.** Burned from the verbatim transcript via the
  APCA-gated ASS document; if the track is empty the video renders without it.

The argument assembly (:func:`build_ffmpeg_args`) is a pure builder, unit-tested
with no binary; only :func:`render_edl` touches the disk and the subprocess.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from mediahub.video import edl as _edl
from mediahub.video.edl import EDL, CompiledGraph
from mediahub.visual.reel_ffmpeg import available as _ffmpeg_available
from mediahub.visual.reel_ffmpeg import ffmpeg_exe


class VideoEngineUnavailable(RuntimeError):
    """Raised when the video render engine cannot run (no FFmpeg on the box).

    Mirrors ``ReelEngineUnavailable``: an honest error beats a missing or
    fabricated clip.
    """


def _data_dir() -> Path:
    env = os.environ.get("DATA_DIR")
    return Path(env) if env else Path(__file__).resolve().parents[2]


def cache_dir() -> Path:
    """``DATA_DIR/motion_cache/video`` — beside the reel cache, video subfolder."""
    d = _data_dir() / "motion_cache" / "video"
    d.mkdir(parents=True, exist_ok=True)
    return d


def available() -> bool:
    """True when an EDL can actually be rendered right now (FFmpeg + renderer)."""
    return _ffmpeg_available()


def _source_fingerprint(path: str) -> str:
    """A cheap content fingerprint for a source clip (``size:mtime``).

    Folded into the cache key so re-cutting or replacing a source file produces
    a fresh render, while an unchanged source is a cache hit.
    """
    try:
        st = Path(path).stat()
        return f"{st.st_size}:{int(st.st_mtime)}"
    except OSError:
        return "0:0"


# Bump when the filter-graph shape or output options change, so older cached
# renders are not served against new compile logic (the reel engine's gotcha).
_RENDER_VERSION = "v1"


def cache_key(edl: EDL) -> str:
    """Stable content hash over the timeline + each source's fingerprint.

    Folds in every clip source *and* the audio plan's music bed (so swapping or
    re-encoding the bed re-renders), while an EDL with no audio plan hashes
    exactly as before this feature — ``to_dict`` omits the inert keys.
    """
    sources = {c.source: _source_fingerprint(c.source) for c in edl.clips}
    if edl.audio is not None and edl.audio.music:
        sources[edl.audio.music] = _source_fingerprint(edl.audio.music)
    payload = {
        "version": _RENDER_VERSION,
        "edl": edl.to_dict(),
        "sources": sources,
    }
    blob = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:24]


def build_ffmpeg_args(
    compiled: CompiledGraph,
    *,
    fps: int,
    out_path: Path | str,
    ass_paths: Optional[list[str]] = None,
    duration_ms: int = 0,
) -> list[str]:
    """Assemble the FFmpeg argument list for a compiled graph (pure builder).

    Chains a libass burn (``ass=``) onto the composited video for each path in
    ``ass_paths`` (captions, then titles), maps the final video + audio, and
    writes a web-faststart H.264/AAC MP4. Deterministic — same inputs, same args.
    """
    args: list[str] = []
    for src in compiled.inputs:
        args += ["-i", str(src)]

    fc = compiled.filter_complex
    vlabel = compiled.vout
    for i, ass_path in enumerate(ass_paths or []):
        from mediahub.visual.subtitle_burn import ass_filter

        nxt = f"vcap{i}"
        fc = f"{fc};[{vlabel}]{ass_filter(ass_path)}[{nxt}]"
        vlabel = nxt

    args += ["-filter_complex", fc, "-map", f"[{vlabel}]"]
    if compiled.aout:
        args += ["-map", f"[{compiled.aout}]"]

    args += [
        "-r",
        str(fps),
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
    ]
    if compiled.aout:
        args += ["-c:a", "aac", "-b:a", "160k"]
    if duration_ms and duration_ms > 0:
        args += ["-t", f"{duration_ms / 1000:.3f}"]
    args += ["-movflags", "+faststart", "-y", str(out_path)]
    return args


def _run_ffmpeg(args: list[str], *, timeout: int = 600) -> None:
    exe = ffmpeg_exe()
    if not exe:
        raise VideoEngineUnavailable(
            "Rendering a video timeline needs an FFmpeg binary (install "
            "imageio-ffmpeg, put ffmpeg on PATH, or set MEDIAHUB_FFMPEG)."
        )
    cmd = [exe, "-hide_banner", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise VideoEngineUnavailable(f"video render timed out after {timeout}s") from e
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-12:]) or "(no stderr)"
        raise RuntimeError(f"FFmpeg video render failed (exit {proc.returncode}):\n{tail}")


def _probe_sources(edl: EDL) -> tuple[dict[str, int], dict[str, bool]]:
    """Probe each distinct source for (duration, has-audio).

    Duration resolves open-ended out points; the audio map tells the compiler
    which clips need a silence segment (no audio stream) versus a real one — so a
    silent clip never produces a dangling ``[i:a]`` that crashes FFmpeg.
    Best-effort: an unprobeable source is omitted from both maps.
    """
    from mediahub.video.probe import probe_clip

    durations: dict[str, int] = {}
    audio: dict[str, bool] = {}
    for c in edl.clips:
        if c.source in durations:
            continue
        try:
            p = probe_clip(c.source)
            durations[c.source] = p.duration_ms
            audio[c.source] = p.has_audio
        except Exception:
            pass
    return durations, audio


def _write_manifest(cached: Path, edl: EDL, *, duration_ms: int) -> None:
    reframed = any(c.crop for c in edl.clips)
    manifest = {
        "kind": "video_edl",
        "engine": "ffmpeg",
        "width": edl.width,
        "height": edl.height,
        "fps": edl.fps,
        "duration_ms": duration_ms,
        "clips": [
            {
                "source": Path(c.source).name,
                "in_ms": c.in_ms,
                "out_ms": c.out_ms,
                "speed": c.speed,
                "muted": c.mute,
                "reframed": bool(c.crop),
                "transition_in": c.transition_in.to_dict(),
            }
            for c in edl.clips
        ],
        "reframed": reframed,
        "graded": bool(edl.look and edl.look != "none")
        or any(not c.adjust.is_identity() for c in edl.clips),
        "look": edl.look,
        "audio_plan": edl.audio.to_dict() if (edl.audio and not edl.audio.is_empty()) else None,
        "overlays": [o.to_dict() for o in edl.overlays],
        "captions": {"cues": len((edl.captions or {}).get("cues") or [])},
        "created_at": time.time(),
    }
    try:
        cached.with_suffix(".json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True, default=str), encoding="utf-8"
        )
    except OSError:
        pass


def _write_poster(cached: Path) -> None:
    """Extract the opening frame as a ``.poster.png`` sidecar (best-effort).

    Mirrors the reel path's poster sidecar, giving review surfaces and platforms
    a thumbnail without decoding the MP4. A failure is silent — a poster is a
    convenience, never load-bearing.
    """
    exe = ffmpeg_exe()
    if not exe:
        return
    poster = cached.with_suffix(".poster.png")
    try:
        subprocess.run(
            [
                exe,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(cached),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(poster),
            ],
            capture_output=True,
            timeout=60,
        )
    except (subprocess.SubprocessError, OSError):
        pass


def _publish(cached: Path, out_path: Path) -> Path:
    """Copy the cached MP4 + its manifest + poster to ``out_path`` (cache-hit safe)."""
    import shutil

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if cached.resolve() != out_path.resolve():
        shutil.copy2(cached, out_path)
        for suffix, dst in (
            (".json", out_path.with_suffix(".json")),
            (".poster.png", out_path.with_suffix(".poster.png")),
        ):
            src = cached.with_suffix(suffix)
            if src.exists():
                try:
                    shutil.copy2(src, dst)
                except OSError:
                    pass
    return out_path


def render_edl(edl: EDL, out_path: Path | str, *, timeout: int = 600) -> Path:
    """Render ``edl`` to ``out_path`` (MP4), via the content-addressed cache.

    Cache hits return immediately (the typical < a second). A cold render
    compiles the graph, burns captions, and runs FFmpeg server-side. Raises
    :class:`VideoEngineUnavailable` when the engine can't run and
    :class:`~mediahub.video.edl.EDLError` when the timeline is invalid — never a
    fabricated clip.
    """
    _edl.validate(edl)
    if not available():
        raise VideoEngineUnavailable(
            "The video engine needs FFmpeg + the still renderer (Playwright). "
            "Neither is available on this deployment."
        )

    key = cache_key(edl)
    cached = cache_dir() / f"{key}.mp4"
    out_path = Path(out_path)
    if cached.exists() and cached.stat().st_size > 1024:
        return _publish(cached, out_path)

    probes, audio = _probe_sources(edl)
    compiled = compile_with_probes(edl, probes, audio)
    duration_ms = edl.total_timeline_ms() or _compiled_duration_from_probes(edl, probes)

    with tempfile.TemporaryDirectory(prefix="mh_video_render_") as td:
        ass_paths: list[str] = []
        if edl.captions and (edl.captions.get("cues")):
            from mediahub.video.caption_render import ass_for_track

            cap_file = Path(td) / "captions.ass"
            cap_file.write_text(
                ass_for_track(edl.captions, width=edl.width, height=edl.height, fps=edl.fps),
                encoding="utf-8",
            )
            ass_paths.append(str(cap_file))
        overlay_lines = [o.to_dict() for o in edl.overlays if (o.text or "").strip()]
        if overlay_lines:
            from mediahub.visual.subtitle_burn import titles_ass_document

            title_file = Path(td) / "titles.ass"
            title_file.write_text(
                titles_ass_document(
                    overlay_lines,
                    width=edl.width,
                    height=edl.height,
                    fps=edl.fps,
                    scrim=edl.background,
                ),
                encoding="utf-8",
            )
            ass_paths.append(str(title_file))

        tmp_out = Path(td) / "out.mp4"
        args = build_ffmpeg_args(
            compiled, fps=edl.fps, out_path=tmp_out, ass_paths=ass_paths, duration_ms=duration_ms
        )
        _run_ffmpeg(args, timeout=timeout)
        if not tmp_out.exists() or tmp_out.stat().st_size < 1024:
            raise RuntimeError("FFmpeg reported success but the MP4 is missing or empty")

        # Soundtrack post-pass: clean the voice + lay a ducked music bed + land
        # the loudness, re-encoding only the audio. An empty/absent plan is a
        # no-op, so the no-soundtrack path stays byte-identical.
        final_tmp = tmp_out
        if edl.audio is not None and not edl.audio.is_empty():
            from mediahub.video.audio_post import apply_audio_plan

            final_tmp = Path(td) / "out_audio.mp4"
            apply_audio_plan(tmp_out, final_tmp, edl.audio, timeout=timeout)

        cached.parent.mkdir(parents=True, exist_ok=True)
        import shutil

        shutil.move(str(final_tmp), str(cached))

    _write_manifest(cached, edl, duration_ms=duration_ms)
    _write_poster(cached)
    return _publish(cached, out_path)


def compile_with_probes(
    edl: EDL, probes: dict[str, int], audio: Optional[dict[str, bool]] = None
) -> CompiledGraph:
    """Compile, threading probe durations + audio presence (text is burned via ASS)."""
    return _edl.compile_filtergraph(edl, probes=probes, audio=audio)


def _compiled_duration_from_probes(edl: EDL, probes: dict[str, int]) -> int:
    """Total timeline duration once open-ended out points resolve to probe ends."""
    total = 0
    for i, c in enumerate(edl.clips):
        span = c.source_span_ms or max(0, probes.get(c.source, 0) - c.in_ms)
        tl = round(span / c.speed) if (span and c.speed > 0) else 0
        total += tl
        if i > 0 and not c.transition_in.is_cut:
            total -= max(0, c.transition_in.duration_ms)
    return max(0, total)


__all__ = [
    "VideoEngineUnavailable",
    "cache_dir",
    "available",
    "cache_key",
    "build_ffmpeg_args",
    "render_edl",
    "compile_with_probes",
]
