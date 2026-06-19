"""Compile motion presets to CSS ``@keyframes`` — for the browser surfaces.

CSS keyframes render in a real browser (the web UI and the story/HTML preview
surfaces), **not** in Remotion — Remotion needs frame-pure interpolation
(:mod:`mediahub.motion.compile_remotion`). So this compiler targets the
first-party web surfaces only.

The multi-channel, multi-easing curve is **baked** into a fine grid of keyframe
stops sampled from the single source of truth, and the animation runs
``linear`` over them — so a preset's CSS playback matches its Python/Remotion
sampling exactly, with no second easing applied on top.

Reduce-motion is emitted as a ``@media (prefers-reduced-motion: reduce)`` block
that swaps in the still-respecting variant (:meth:`MotionPreset.reduced`), so
every preset honours the accessibility setting wherever this CSS is served.
"""
from __future__ import annotations

from typing import Iterable, List

from .vocabulary import FPS, PRESETS, MotionPreset

# Number of baked stops for a non-trivial (eased / multi-keyframe) channel.
_BAKE_STOPS = 20


def _anim_name(preset: MotionPreset) -> str:
    return f"mh-{preset.name.replace('_', '-')}"


def class_name(preset: MotionPreset) -> str:
    """The utility class that plays ``preset`` (e.g. ``mh-anim-slide-up``)."""
    return f"mh-anim-{preset.name.replace('_', '-')}"


def _needs_fine_grid(preset: MotionPreset) -> bool:
    """True when any channel uses a non-linear easing or 3+ keyframes."""
    for kfs in preset.channels.values():
        if len(kfs) > 2:
            return True
        for k in kfs:
            if k.easing != "linear":
                return True
    return False


def _stops(preset: MotionPreset) -> List[float]:
    if _needs_fine_grid(preset):
        return [i / _BAKE_STOPS for i in range(_BAKE_STOPS + 1)]
    offs = {0.0, 1.0}
    for kfs in preset.channels.values():
        offs.update(k.offset for k in kfs)
    return sorted(offs)


def _frame_decls(preset: MotionPreset, t: float) -> str:
    parts: List[str] = []
    tx = preset.value_at("translateX", t)
    ty = preset.value_at("translateY", t)
    sc = preset.value_at("scale", t)
    rot = preset.value_at("rotate", t)
    transform = f"translate3d({_px(tx)},{_px(ty)},0) scale({_num(sc)}) rotate({_num(rot)}deg)"
    parts.append(f"transform:{transform}")
    if "opacity" in preset.channels:
        parts.append(f"opacity:{_num(preset.value_at('opacity', t))}")
    if "blur" in preset.channels:
        parts.append(f"filter:blur({_px(preset.value_at('blur', t))})")
    return ";".join(parts)


def keyframes_block(preset: MotionPreset, *, name: str | None = None) -> str:
    anim = name or _anim_name(preset)
    stops = _stops(preset)
    body = "".join(
        f"{_pct(t)}{{{_frame_decls(preset, t)}}}" for t in _dedupe(stops)
    )
    return f"@keyframes {anim}{{{body}}}"


def class_block(preset: MotionPreset, *, fps: int = FPS) -> str:
    anim = _anim_name(preset)
    secs = preset.duration_frames / float(fps or FPS)
    # Loops iterate forever and hold no end-state; entrances/exits play once and
    # keep their final frame (fill-mode both).
    iteration = "infinite" if preset.loop else "1"
    fill = "none" if preset.loop else "both"
    return (
        f".{class_name(preset)}{{"
        f"animation:{anim} {_num(secs)}s linear {iteration} {fill};"
        f"will-change:transform,opacity;"
        f"}}"
    )


def reduced_block(preset: MotionPreset, *, fps: int = FPS) -> str:
    """The ``prefers-reduced-motion`` override for one preset."""
    reduced = preset.reduced()
    cls = class_name(preset)
    if not reduced.channels:
        # Loop with nothing left to animate → no motion at all.
        return f".{cls}{{animation:none!important;transform:none!important;filter:none!important;}}"
    rname = f"{_anim_name(preset)}-reduced"
    secs = reduced.duration_frames / float(fps or FPS)
    return (
        keyframes_block(reduced, name=rname)
        + f".{cls}{{animation:{rname} {_num(secs)}s linear both!important;}}"
    )


def compile_preset_css(preset: MotionPreset, *, fps: int = FPS) -> str:
    """Keyframes + class + reduce-motion override for a single preset."""
    return "\n".join(
        (
            keyframes_block(preset),
            class_block(preset, fps=fps),
        )
    )


def compile_all_css(
    presets: Iterable[MotionPreset] | None = None, *, fps: int = FPS
) -> str:
    """The full motion-vocabulary stylesheet (served as a static asset)."""
    items = list(presets if presets is not None else PRESETS.values())
    blocks: List[str] = [
        "/* MediaHub motion vocabulary — GENERATED from src/mediahub/motion/.",
        "   Do not edit by hand; run scripts/regen_motion_tokens.py. */",
    ]
    for p in items:
        blocks.append(keyframes_block(p))
        blocks.append(class_block(p, fps=fps))
    reduced = [reduced_block(p, fps=fps) for p in items]
    blocks.append("@media (prefers-reduced-motion: reduce){")
    blocks.extend(reduced)
    blocks.append("}")
    return "\n".join(blocks) + "\n"


# -- formatting helpers -----------------------------------------------------


def _dedupe(values: List[float]) -> List[float]:
    out: List[float] = []
    seen = set()
    for v in values:
        key = round(v, 5)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out


def _pct(t: float) -> str:
    return f"{round(t * 100, 3):g}%"


def _num(x: float) -> str:
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _px(x: float) -> str:
    n = _num(x)
    return "0" if n == "0" else f"{n}px"


__all__ = [
    "class_name",
    "keyframes_block",
    "class_block",
    "reduced_block",
    "compile_preset_css",
    "compile_all_css",
]
