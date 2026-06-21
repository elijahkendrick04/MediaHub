"""video/audio_post.py — lay the soundtrack onto a rendered footage cut (1.6).

The footage compiler (``edl``/``render``) produces a video whose audio is the
**footage voice** (trimmed/concatenated/cross-faded per the timeline). This
module applies an :class:`~mediahub.video.edl.AudioPlan` *over* that cut: clean
the voice, lay a music bed that ducks under speech, and land the whole mix at a
named loudness — the soundtrack stage every short-form tool ships.

It is the footage twin of ``visual/audio_mux`` for reels, and it deliberately
**reuses the deterministic ``audio`` engine** (1.8): ``audio.clean`` for the
``afftdn`` denoise + EBU-R128 ``loudnorm`` filter strings, ``audio.ops`` for the
``volume``/``afade`` builders, and the same voice-keyed ``sidechaincompress``
ducking the reel mixer uses. No model is in the loop — the same cut + plan + bed
always produces the same soundtrack — so it stays on the deterministic side of
the engine boundary.

Honesty rules, as everywhere: the build re-encodes **only the audio**
(``-c:v copy``), folds the plan into the render cache key upstream, and raises
:class:`AudioPostUnavailable` when FFmpeg is missing rather than shipping a cut
with the soundtrack silently dropped.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from mediahub.audio.clean import denoise_filter, loudnorm_filter, resolve_target
from mediahub.audio.ops import fade_filter, gain_filter
from mediahub.video.edl import AudioPlan
from mediahub.visual.reel_ffmpeg import ffmpeg_exe

# Reuse the reel mixer's tuned ducking constants so the footage path and the
# data-driven reels duck identically; fall back to the same literals if the
# private names ever move.
try:
    from mediahub.visual.audio_mux import (
        DUCK_ATTACK_MS,
        DUCK_RELEASE_MS,
        DUCK_RATIO,
        DUCK_THRESHOLD,
    )
except Exception:  # pragma: no cover - audio_mux always imports in practice
    DUCK_THRESHOLD, DUCK_RATIO, DUCK_ATTACK_MS, DUCK_RELEASE_MS = 0.03, 6.0, 20.0, 250.0


class AudioPostUnavailable(RuntimeError):
    """Raised when the soundtrack pass cannot run (no FFmpeg binary)."""


def _voice_chain(plan: AudioPlan) -> str:
    """The footage-voice filter chain (denoise when the plan enhances it)."""
    parts = ["aresample=44100"]
    if plan.enhance_voice:
        parts.append(denoise_filter())  # afftdn — deterministic spectral denoise
    return ",".join(parts)


def _music_chain(plan: AudioPlan, *, duration_s: float) -> str:
    """The music-bed chain: bound to the cut, gained, faded. Pure."""
    dur = max(0.1, float(duration_s))
    parts = [f"atrim=0:{dur:.3f}", "asetpts=PTS-STARTPTS", "aresample=44100"]
    g = gain_filter(plan.music_gain_db)
    if g:
        parts.append(g)
    fade_s = max(0.0, plan.music_fade_ms / 1000.0)
    fade = fade_filter(duration_sec=dur, fade_in=fade_s, fade_out=fade_s)
    if fade:
        parts.append(fade)
    return ",".join(parts)


def _final_loudnorm(plan: AudioPlan) -> str:
    """The master loudness filter applied to the final mix (always, when working).

    Whenever the plan asks for *any* audio work, the mix is landed at a named EBU
    R128 target (the plan's, or the social default) so a club's clips all sit at
    the same perceived loudness — the deterministic "Balance All" promise.
    """
    target = resolve_target(plan.loudness) if plan.loudness else "social"
    return loudnorm_filter(target)


def build_audio_post_args(
    video: Path | str,
    out: Path | str,
    plan: AudioPlan,
    *,
    has_voice: bool,
    music_path: Optional[str],
    duration_s: float,
) -> list[str]:
    """Assemble the FFmpeg args that apply ``plan`` over ``video`` (pure builder).

    ``-c:v copy`` keeps the picture bit-exact; only the audio graph is rebuilt:
    the footage voice (cleaned), an optional ducked music bed, and a master
    loudness landing. Deterministic — same inputs, same args. The four shapes:
    voice-only, voice+music (ducked), music-only (silent footage), and the
    degenerate no-op all resolve to one ``[aout]`` map.
    """
    args: list[str] = ["-i", str(video)]
    have_music = bool(music_path)
    if have_music:
        args += ["-stream_loop", "-1", "-i", str(music_path)]

    voice_fx = _voice_chain(plan)
    music_fx = _music_chain(plan, duration_s=duration_s) if have_music else ""
    final = _final_loudnorm(plan)

    lines: list[str] = []
    if has_voice and have_music:
        # Voice cleans, splits (one copy mixes, one keys the duck); bed ducks
        # under the voice, then the two are summed and the mix is loudness-landed.
        lines.append(f"[0:a]{voice_fx},asplit=2[vmain][vkey]")
        lines.append(f"[1:a]{music_fx}[mraw]")
        lines.append(
            f"[mraw][vkey]sidechaincompress=threshold={DUCK_THRESHOLD:g}:"
            f"ratio={DUCK_RATIO:g}:attack={DUCK_ATTACK_MS:g}:release={DUCK_RELEASE_MS:g}[mduck]"
        )
        lines.append(
            f"[vmain][mduck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            f"{final}[aout]"
        )
    elif has_voice:
        lines.append(f"[0:a]{voice_fx},{final}[aout]")
    elif have_music:
        # Silent footage: the bed is the whole soundtrack.
        lines.append(f"[1:a]{music_fx},{final}[aout]")
    else:
        # No voice, no bed — just land whatever is there (degenerate; rare).
        lines.append(f"[0:a]{final}[aout]")

    args += ["-filter_complex", ";".join(lines)]
    args += ["-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k"]
    args += ["-movflags", "+faststart", "-shortest", "-y", str(out)]
    return args


def _probe_has_voice(video: Path) -> bool:
    """Whether the composite carries a (non-silent-source) audio stream."""
    try:
        from mediahub.video.probe import probe_clip

        return probe_clip(video).has_audio
    except Exception:
        return True  # assume present; the graph tolerates a real stream


def _probe_duration_s(video: Path) -> float:
    try:
        from mediahub.video.probe import probe_clip

        return max(0.1, probe_clip(video).duration_ms / 1000.0)
    except Exception:
        return 10.0


def apply_audio_plan(
    video: Path | str,
    out: Path | str,
    plan: AudioPlan,
    *,
    music_path: Optional[str] = None,
    timeout: int = 600,
) -> Path:
    """Apply ``plan`` to ``video`` → ``out`` (audio rebuilt, video copied).

    Returns ``out``. An empty plan is a copy-through (nothing to do). Raises
    :class:`AudioPostUnavailable` when FFmpeg is absent — never a cut with the
    requested soundtrack silently missing.
    """
    video = Path(video)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if plan.is_empty() and not music_path:
        if video.resolve() != out.resolve():
            import shutil

            shutil.copy2(video, out)
        return out

    exe = ffmpeg_exe()
    if not exe:
        raise AudioPostUnavailable(
            "Building the soundtrack needs an FFmpeg binary (install imageio-ffmpeg, "
            "put ffmpeg on PATH, or set MEDIAHUB_FFMPEG)."
        )
    # Resolve the bed: the plan's path, or its music field if it is a real file.
    bed = music_path or (plan.music if plan.music and Path(plan.music).is_file() else None)
    args = build_audio_post_args(
        video,
        out,
        plan,
        has_voice=_probe_has_voice(video),
        music_path=bed,
        duration_s=_probe_duration_s(video),
    )
    cmd = [exe, "-hide_banner", "-loglevel", "error", *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise AudioPostUnavailable(f"soundtrack pass timed out after {timeout}s") from e
    if proc.returncode != 0:
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-10:]) or "(no stderr)"
        raise RuntimeError(f"FFmpeg soundtrack pass failed (exit {proc.returncode}):\n{tail}")
    if not out.exists() or out.stat().st_size < 1024:
        raise RuntimeError("FFmpeg reported success but the soundtracked MP4 is missing/empty")
    return out


__all__ = [
    "AudioPostUnavailable",
    "build_audio_post_args",
    "apply_audio_plan",
]
