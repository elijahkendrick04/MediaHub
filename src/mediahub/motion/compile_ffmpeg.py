"""Compile motion presets to FFmpeg filter recipes — whole-frame motion.

The FFmpeg reel engine composites **pre-rendered still PNGs**, so it animates
*frames*, not individual DOM elements. That makes FFmpeg the right home for the
photo-motion family (Ken Burns / pan), opacity fades, and the beat transitions
(xfade) — and the wrong tool for a per-element entrance like ``rise`` (there is
no separate element to translate on a flattened still). This compiler is honest
about that boundary: it serves the frame-level families and raises a clear
error for element-only transforms, pointing the caller at the Remotion/CSS
target instead.

Crucially, the photo presets **delegate to the shipped, reel-proven recipe**
(:func:`mediahub.visual.reel_ffmpeg._ken_burns_filter`) via the
``KEN_BURNS_ALIASES`` map, so the vocabulary unifies with the variants already
rendering production reels instead of shipping a second, unvalidated zoompan
implementation.
"""

from __future__ import annotations

from typing import Mapping

from .vocabulary import MotionCapError, MotionPreset, nearest_ken_burns_variant


def _has_non_bezier_interp(preset: MotionPreset) -> bool:
    """True when any keyframe uses a hold/auto/continuous interp mode.

    FFmpeg's fade/zoompan recipes express only bezier easing — a step or
    cubic-Hermite track shape cannot be reproduced by the fade filter (opacity
    tracks) or the Ken Burns zoompan (photo scale tracks). Rendering one anyway
    would silently diverge from Remotion/CSS, so it's declared unsupported.
    """
    return any(k.interp != "bezier" for kfs in preset.channels.values() for k in kfs)


def supports_ffmpeg(preset: MotionPreset) -> bool:
    """True when FFmpeg can render this preset at the frame level."""
    # A non-bezier interp (hold/auto/continuous) is unsupported on this engine —
    # honest fallback rather than a wrong linear fade or bezier Ken Burns.
    if _has_non_bezier_interp(preset):
        return False
    if preset.photo and nearest_ken_burns_variant(preset.name):
        return True
    # Opacity-only entrances/exits map cleanly to the fade filter.
    return preset.channel_names() == ("opacity",)


def compile_ffmpeg(
    preset: MotionPreset,
    *,
    duration_sec: float,
    clip_sec: float | None = None,
    width: int = 1080,
    height: int = 1920,
    tag: str = "0",
    fps: int = 30,
) -> str:
    """An FFmpeg filtergraph fragment for ``preset`` (no leading/trailing pads).

    Matches the pad convention of :func:`reel_ffmpeg._ken_burns_filter`: the
    caller wraps the fragment with its input/output labels. ``duration_sec`` is
    the animation length; ``clip_sec`` (defaulting to it) is the whole clip, so
    a fade-out lands at the clip's tail.
    """
    clip = float(clip_sec if clip_sec is not None else duration_sec)
    # A non-bezier interp reaches both the photo (scale) and opacity branches; the
    # FFmpeg recipes can only express bezier easing, so refuse it honestly rather
    # than render a curve that diverges from Remotion/CSS.
    if _has_non_bezier_interp(preset):
        raise MotionCapError(
            f"{preset.name!r} uses a non-bezier keyframe interpolation "
            "(hold/auto/continuous); the FFmpeg engine only expresses bezier "
            "easing — use the Remotion or CSS target."
        )
    if preset.photo:
        variant = nearest_ken_burns_variant(preset.name)
        if not variant:
            raise MotionCapError(f"photo preset {preset.name!r} has no FFmpeg Ken Burns variant")
        # Delegate to the shipped recipe — single source of truth for zoompan.
        from mediahub.visual.reel_ffmpeg import _ken_burns_filter

        return _ken_burns_filter(
            float(duration_sec), variant=variant, tag=tag, width=width, height=height, fps=fps
        )
    if preset.channel_names() == ("opacity",):
        return _fade_fragment(preset, float(duration_sec), clip)
    raise MotionCapError(
        f"{preset.name!r} is an element-level transform; FFmpeg renders whole "
        "frames — use the Remotion or CSS target for per-element motion."
    )


def _fade_fragment(preset: MotionPreset, anim_sec: float, clip_sec: float) -> str:
    start = preset.value_at("opacity", 0.0)
    end = preset.value_at("opacity", 1.0)
    if end >= start:  # fading up → in
        return f"fade=t=in:st=0:d={_num(anim_sec)}"
    st = max(0.0, clip_sec - anim_sec)
    return f"fade=t=out:st={_num(st)}:d={_num(anim_sec)}"


def ffmpeg_xfade_for(kind: str) -> str | None:
    """The FFmpeg ``xfade`` transition name for a beat-transition ``kind``.

    Reads the shipped mapping in :mod:`reel_ffmpeg` so the transition vocabulary
    has one source of truth across both engines.
    """
    mapping = xfade_kinds()
    return mapping.get(kind)


def xfade_kinds() -> Mapping[str, str]:
    from mediahub.visual.reel_ffmpeg import _XFADE_FOR_KIND

    return dict(_XFADE_FOR_KIND)


def _num(x: float) -> str:
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


__all__ = [
    "supports_ffmpeg",
    "compile_ffmpeg",
    "ffmpeg_xfade_for",
    "xfade_kinds",
]
