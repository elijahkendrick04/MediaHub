"""visual/audio_mux.py — engine-agnostic audio + poster finishing for MP4s.

Motion renders (Remotion or the free FFmpeg engine) historically shipped
silent. This module is the one seam that changes that: after an MP4 is
rendered, it can

* speak a deterministic, fact-only narration (built by
  ``visual/narration.py``, synthesised by ``visual/voiceover.py`` — the
  same verbatim-text TTS the caption voiceover uses), and/or
* lay an operator-supplied music bed under it, and
* extract a poster-frame PNG sidecar for review surfaces and platforms
  that want a thumbnail.

Rules (the same honesty contract as the rest of the renderer):

- **Off by default.** Voice rides the existing ``MEDIAHUB_VOICEOVER=1``
  opt-in; music only plays when the operator points
  ``MEDIAHUB_REEL_MUSIC_DIR`` at a directory of files *they* hold the
  licence for. MediaHub ships no audio assets and asserts no rights.
- **Honest silent fallback.** If synthesis or the mux fails, the video
  stays silent and the manifest records why — never a placeholder track.
- **Deterministic.** The music track for a given render is picked by
  content hash from the sorted directory listing; mix levels and fades are
  fixed constants. Same inputs → same audio.
- **Video bits untouched.** The mux stream-copies the video track; only an
  audio track is added.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from mediahub.visual.reel_ffmpeg import ffmpeg_exe

# Fixed mix constants — deterministic by design (no per-render knobs).
MUSIC_BED_VOLUME = 0.40  # music alone
MUSIC_UNDER_VOICE_WEIGHT = 0.30  # music's amix weight under narration
AUDIO_FADE_OUT_SEC = 0.6

_MUSIC_SUFFIXES = {".mp3", ".m4a", ".aac", ".wav", ".ogg", ".opus", ".flac"}

_TRUTHY = {"1", "true", "yes", "on"}


def voice_active() -> bool:
    """True when the operator opted into voiceover AND a backend can speak."""
    if os.environ.get("MEDIAHUB_VOICEOVER", "").strip().lower() not in _TRUTHY:
        return False
    try:
        from mediahub.visual import voiceover

        return voiceover.is_available()
    except Exception:
        return False


def voice_name() -> str:
    """The configured TTS voice (same env the caption voiceover honours)."""
    from mediahub.visual.voiceover import DEFAULT_VOICE

    return os.environ.get("MEDIAHUB_VOICEOVER_VOICE", "").strip() or DEFAULT_VOICE


def music_dir() -> Optional[Path]:
    """The operator's licensed-music directory, or None when unset/missing."""
    raw = os.environ.get("MEDIAHUB_REEL_MUSIC_DIR", "").strip()
    if not raw:
        return None
    p = Path(raw)
    return p if p.is_dir() else None


def music_candidates() -> list[Path]:
    d = music_dir()
    if d is None:
        return []
    return sorted(
        (p for p in d.iterdir() if p.is_file() and p.suffix.lower() in _MUSIC_SUFFIXES),
        key=lambda p: p.name,
    )


def pick_music(content_key: str) -> Optional[Path]:
    """Deterministic track pick: stable per content key, spread across the pool."""
    tracks = music_candidates()
    if not tracks:
        return None
    digest = hashlib.sha256((content_key or "").encode("utf-8")).hexdigest()
    return tracks[int(digest[:8], 16) % len(tracks)]


def audio_active() -> bool:
    """True when any audio source could apply to a render right now."""
    return voice_active() or bool(music_candidates())


def build_audio_plan(*, script: str, content_key: str) -> Optional[dict]:
    """The cache-identity description of a render's audio, or None for silent.

    Only identity fields live here (voice name, the exact script, the music
    file's name + size) — the plan is folded into the motion cache hash, so
    a changed script, voice, or track can never serve a stale mix. ``None``
    keeps the silent path's cache keys byte-identical to the pre-audio era.
    """
    plan: dict[str, Any] = {}
    if voice_active() and (script or "").strip():
        plan["voice"] = voice_name()
        plan["script"] = script.strip()
    track = pick_music(content_key)
    if track is not None:
        try:
            plan["music"] = track.name
            plan["music_bytes"] = track.stat().st_size
        except OSError:
            pass
    return plan or None


def _resolve_music_path(plan: dict) -> Optional[Path]:
    name = str((plan or {}).get("music") or "")
    if not name:
        return None
    d = music_dir()
    if d is None:
        return None
    p = d / name
    return p if p.is_file() else None


def mux_args(
    video: Path,
    voice: Optional[Path],
    music: Optional[Path],
    out: Path,
    *,
    duration_sec: float,
) -> list[str]:
    """Argument list (after the binary) for the audio mux. Pure + testable.

    The video stream is copied untouched; the audio chain is trimmed to the
    exact video duration with a fixed fade-out, so a long narration ends
    cleanly rather than spilling past the outro.
    """
    if voice is None and music is None:
        raise ValueError("at least one audio source is required")
    d = max(0.1, float(duration_sec))
    fade_start = max(0.0, d - AUDIO_FADE_OUT_SEC)
    args: list[str] = ["-i", str(video)]
    if voice is not None:
        args += ["-i", str(voice)]
    if music is not None:
        # Loop the bed so short tracks cover long reels; atrim cuts the tail.
        args += ["-stream_loop", "-1", "-i", str(music)]

    tail = f"atrim=0:{d:.3f},afade=t=out:st={fade_start:.3f}:d={AUDIO_FADE_OUT_SEC}[aout]"
    if voice is not None and music is not None:
        graph = (
            f"[1:a]apad[v];"
            f"[2:a]volume=1.0[m];"
            f"[v][m]amix=inputs=2:duration=first:weights=1 {MUSIC_UNDER_VOICE_WEIGHT},"
            f"{tail}"
        )
    elif voice is not None:
        graph = f"[1:a]apad,{tail}"
    else:
        graph = f"[1:a]volume={MUSIC_BED_VOLUME},afade=t=in:st=0:d=0.5,{tail}"

    args += [
        "-filter_complex",
        graph,
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        "44100",
        "-movflags",
        "+faststart",
        str(out),
    ]
    return args


def _run_ffmpeg(args: list[str], *, timeout: int = 300) -> None:
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("no FFmpeg binary available for the audio mux")
    cmd = [exe, "-y", "-hide_banner", "-loglevel", "error", *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip().splitlines()
        tail = "\n".join(stderr[-8:]) if stderr else "(no stderr)"
        raise RuntimeError(f"audio mux failed (exit {proc.returncode}):\n{tail}")


def has_audio_stream(video: Path) -> bool:
    """True when the container declares an audio stream (ffmpeg -i probe)."""
    exe = ffmpeg_exe()
    if not exe or not Path(video).exists():
        return False
    proc = subprocess.run([exe, "-hide_banner", "-i", str(video)], capture_output=True, text=True)
    return "Audio:" in (proc.stderr or "")


def apply_audio(video: Path, plan: Optional[dict], *, duration_sec: float) -> dict:
    """Attach the planned audio to ``video`` in place; report what happened.

    Returns the manifest-ready record. Every failure path leaves the
    rendered video exactly as it was (silent) and says why — the honest
    fallback the motion rules require.
    """
    if not plan:
        return {"status": "off"}
    video = Path(video)
    voice_path: Optional[Path] = None
    transcript = ""
    voice_error = ""
    script = str(plan.get("script") or "")
    if plan.get("voice") and script:
        try:
            from mediahub.visual import voiceover

            result = voiceover.synthesize(script, voice=str(plan["voice"]))
            voice_path = result.audio_path
            transcript = result.transcript
        except Exception as e:
            voice_error = f"voiceover failed: {e}"
            voice_path = None

    music_path = _resolve_music_path(plan)
    if voice_path is None and music_path is None:
        return {
            "status": "silent_fallback",
            "reason": voice_error or "no audio source resolved",
        }

    try:
        with tempfile.TemporaryDirectory(prefix="mh_audio_mux_") as td:
            tmp_out = Path(td) / video.name
            _run_ffmpeg(mux_args(video, voice_path, music_path, tmp_out, duration_sec=duration_sec))
            if not tmp_out.exists() or tmp_out.stat().st_size < 1024:
                raise RuntimeError("mux produced no output")
            os.replace(tmp_out, video)
    except Exception as e:
        return {
            "status": "silent_fallback",
            "reason": f"{voice_error + '; ' if voice_error else ''}{e}",
        }

    record: dict[str, Any] = {
        "status": "mixed",
        "voice": str(plan.get("voice") or "") if voice_path is not None else "",
        "music": str(plan.get("music") or "") if music_path is not None else "",
        "transcript": transcript,
    }
    if voice_error:
        record["reason"] = voice_error
    return record


# ---------------------------------------------------------------------------
# Poster frames
# ---------------------------------------------------------------------------


def poster_time_for(kind: str, duration_sec: float) -> float:
    """Deterministic poster timestamp: stories late enough that the layers
    have animated in; reels on the brand cover."""
    d = max(0.1, float(duration_sec))
    if kind == "reel":
        return min(1.5, max(0.0, d - 0.2))
    return max(0.0, min(d * 0.55, d - 0.2))


def poster_path_for(video: Path) -> Path:
    return Path(video).with_suffix(".poster.png")


def write_poster(video: Path, poster: Path, *, at_sec: float) -> bool:
    """Extract one PNG frame beside the MP4. Best-effort: False, never raise."""
    exe = ffmpeg_exe()
    video = Path(video)
    poster = Path(poster)
    if not exe or not video.exists():
        return False
    try:
        poster.parent.mkdir(parents=True, exist_ok=True)
        proc = subprocess.run(
            [
                exe,
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{max(0.0, at_sec):.3f}",
                "-i",
                str(video),
                "-frames:v",
                "1",
                str(poster),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
        return proc.returncode == 0 and poster.exists() and poster.stat().st_size > 0
    except Exception:
        return False


__all__ = [
    "MUSIC_BED_VOLUME",
    "MUSIC_UNDER_VOICE_WEIGHT",
    "AUDIO_FADE_OUT_SEC",
    "voice_active",
    "voice_name",
    "music_dir",
    "music_candidates",
    "pick_music",
    "audio_active",
    "build_audio_plan",
    "mux_args",
    "has_audio_stream",
    "apply_audio",
    "poster_time_for",
    "poster_path_for",
    "write_poster",
]
