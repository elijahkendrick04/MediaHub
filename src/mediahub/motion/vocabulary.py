"""The brand motion vocabulary — tokenised presets, defined once.

Roadmap **1.5**. A :class:`MotionPreset` is a named animation expressed as
keyframe data over a small set of transform channels (opacity, translate,
scale, rotate, blur). Presets are grouped the way Canva/Adobe group them — the
**in / loop / out** model — and tagged with an *energy* and a *direction* so a
caller (or the design-spec director) can pick by meaning.

The registry below is the **single source of truth**. Three compilers consume
it without re-deciding anything:

* :mod:`mediahub.motion.compile_css` → ``@keyframes`` for the browser surfaces.
* :mod:`mediahub.motion.compile_remotion` → interpolation tokens the Remotion
  stack samples with ``interpolate`` (CSS keyframes do **not** render in
  Remotion — only frame-pure interpolation does).
* :mod:`mediahub.motion.compile_ffmpeg` → whole-frame filter recipes (the
  FFmpeg engine composites pre-rendered stills, so it owns the photo-motion and
  fade families, unified with the shipped Ken Burns variants).

Two accessibility guardrails are first-class, mirrored from the source
products: :meth:`MotionPreset.reduced` (a still-respecting *reduce-motion*
variant of every preset) and the engineering :data:`MAX_ANIM_SECONDS` /
:data:`MAX_ANIMS_PER_DESIGN` caps.

Everything is deterministic — same preset, same frame, same value — so renders
stay byte-identical.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Dict, Mapping, Sequence, Tuple

from .easing import DEFAULT_EASING, get_easing

# ---------------------------------------------------------------------------
# Engineering caps (sanity + render cost) — mirrored from Canva's limits.
# ---------------------------------------------------------------------------

# Vocabulary revision — bumped when the deterministic preset output changes for
# unchanged inputs, so a motion-vocabulary change supersedes stale cache entries
# and the generated Remotion token bundle is re-checked for drift.
#   1 — original preset registry.
#   2 — per-glyph reveal: the token bundle now carries text.glyphStaggerSec (the
#       per-glyph reveal cadence the kinetic_type / cascade intents share).
MOTION_REV = 2

FPS = 30

# Per-glyph reveal cadence (seconds) — the base stagger step between consecutive
# characters when a kinetic_type / cascade card opts into glyph-level reveal
# (motion.py's seed gate). It is the SINGLE source of truth for the token bundle
# and the TSX glyph channel; the TSX clamps the resulting per-glyph start so the
# WHOLE line resolves to opacity 1 within the same short reveal budget as the
# per-word channel (so held headline glyphs never sit below the APCA floor),
# independent of glyph count. Frame-pure — no Math.random.
GLYPH_STAGGER_SEC = 0.035

MAX_ANIM_SECONDS = 10.0
MAX_ANIMS_PER_DESIGN = 50
MAX_ANIM_FRAMES = int(MAX_ANIM_SECONDS * FPS)

# Channels a preset may animate, with their resting ("animated to / from")
# value. A channel a preset omits simply stays at rest.
CHANNELS: Tuple[str, ...] = (
    "opacity",
    "translateX",
    "translateY",
    "scale",
    "rotate",
    "blur",
)
REST: Mapping[str, float] = {
    "opacity": 1.0,
    "translateX": 0.0,
    "translateY": 0.0,
    "scale": 1.0,
    "rotate": 0.0,
    "blur": 0.0,
}

FAMILIES: Tuple[str, ...] = ("in", "loop", "out")
ENERGIES: Tuple[str, ...] = ("calm", "standard", "electric")
DIRECTIONS: Tuple[str, ...] = ("up", "down", "left", "right", "in", "out", "none")


class MotionCapError(ValueError):
    """Raised when a design exceeds the engineering caps."""


@dataclass(frozen=True)
class Keyframe:
    """One keyframe: a channel value at ``offset`` (0..1 of the preset timeline).

    ``easing`` is the curve travelled *into* this keyframe from the previous one
    (a CSS keyframe declares the timing function of the segment that starts at
    it — same convention).
    """

    offset: float
    value: float
    easing: str = DEFAULT_EASING


def kf(offset: float, value: float, easing: str = DEFAULT_EASING) -> Keyframe:
    return Keyframe(offset=float(offset), value=float(value), easing=easing)


@dataclass(frozen=True)
class MotionPreset:
    """A named animation as keyframe data over transform channels."""

    name: str
    family: str  # in | loop | out
    energy: str  # calm | standard | electric
    direction: str
    duration_frames: int
    channels: Mapping[str, Tuple[Keyframe, ...]]
    loop: bool = False
    photo: bool = False  # whole-frame photo motion (Ken Burns / pan)
    is_reduced: bool = False
    description: str = ""

    # -- sampling -----------------------------------------------------------
    def channel_names(self) -> Tuple[str, ...]:
        return tuple(c for c in CHANNELS if c in self.channels)

    def value_at(self, channel: str, t: float) -> float:
        """Sample ``channel`` at normalised time ``t`` (0..1) of the timeline."""
        kfs = self.channels.get(channel)
        if not kfs:
            return REST.get(channel, 0.0)
        return _sample(kfs, t)

    def duration_seconds(self, fps: int = FPS) -> float:
        return self.duration_frames / float(fps or FPS)

    # -- reduce-motion ------------------------------------------------------
    def reduced(self) -> "MotionPreset":
        """A still-respecting variant honoured on every surface.

        Reduce-motion strips movement (translate / scale / rotate / blur) and
        keeps only a short opacity settle, so the layout the customer approved
        is what a reduce-motion viewer sees — no drift, no zoom. A loop becomes
        static; an entrance/exit becomes a quick cross-fade.
        """
        if self.is_reduced:
            return self
        if self.family == "loop":
            channels: Dict[str, Tuple[Keyframe, ...]] = {}
            dur = min(self.duration_frames, MAX_ANIM_FRAMES)
        elif self.family == "out":
            channels = {"opacity": (kf(0.0, 1.0), kf(1.0, 0.0, "ease_in_quad"))}
            dur = min(self.duration_frames, 8)
        else:  # in
            channels = {"opacity": (kf(0.0, 0.0), kf(1.0, 1.0, "ease_out_quad"))}
            dur = min(self.duration_frames, 8)
        return replace(self, channels=channels, duration_frames=dur, is_reduced=True, loop=False)

    # -- caps ---------------------------------------------------------------
    def capped(self) -> "MotionPreset":
        """Clamp the preset's duration to the per-animation cap."""
        if self.duration_frames <= MAX_ANIM_FRAMES:
            return self
        return replace(self, duration_frames=MAX_ANIM_FRAMES)


def _sample(kfs: Sequence[Keyframe], t: float) -> float:
    """Eased interpolation of a keyframe track at ``t`` (0..1)."""
    if t <= kfs[0].offset:
        return kfs[0].value
    if t >= kfs[-1].offset:
        return kfs[-1].value
    for i in range(1, len(kfs)):
        a, b = kfs[i - 1], kfs[i]
        if t <= b.offset:
            span = b.offset - a.offset
            local = 0.0 if span <= 0 else (t - a.offset) / span
            eased = get_easing(b.easing).sample(local)
            return a.value + (b.value - a.value) * eased
    return kfs[-1].value


# ---------------------------------------------------------------------------
# Cap helpers (design-level)
# ---------------------------------------------------------------------------


def clamp_anim_seconds(seconds: float) -> float:
    return max(0.0, min(float(seconds), MAX_ANIM_SECONDS))


def clamp_anim_frames(frames: int) -> int:
    return max(0, min(int(frames), MAX_ANIM_FRAMES))


def enforce_design_caps(n_animations: int) -> None:
    """Raise :class:`MotionCapError` if a design animates too many elements."""
    if n_animations > MAX_ANIMS_PER_DESIGN:
        raise MotionCapError(
            f"{n_animations} animations exceeds the {MAX_ANIMS_PER_DESIGN} "
            "per-design cap (sanity + render cost)."
        )


# ---------------------------------------------------------------------------
# Per-element motion plan — the substrate for DesignSpec motion tokens.
#
# DesignSpec is card-level today (no stable per-element ids), so this is the
# data model a future per-element surface attaches to: each element references
# preset names for its enter / loop / exit, keyed by a stable id so a
# shared-element transition can find the same element across scenes.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ElementMotion:
    element_id: str
    enter: str = ""
    loop: str = ""
    exit: str = ""
    enter_at_frame: int = 0  # stagger by importance, not DOM order


@dataclass(frozen=True)
class MotionPlan:
    elements: Tuple[ElementMotion, ...] = field(default_factory=tuple)
    reduce_motion: bool = False

    def validate(self) -> None:
        enforce_design_caps(len(self.elements))
        for el in self.elements:
            for slot in (el.enter, el.loop, el.exit):
                if slot and slot not in PRESETS:
                    raise MotionCapError(f"unknown motion preset {slot!r}")


# ---------------------------------------------------------------------------
# The preset registry. Durations follow the motion-craft speed table
# (5-9f percussive, 9-15f workhorse, 15-24f deliberate, 24f+ atmospheric).
# ---------------------------------------------------------------------------


def _preset(
    name: str,
    family: str,
    energy: str,
    direction: str,
    duration_frames: int,
    channels: Mapping[str, Sequence[Keyframe]],
    *,
    loop: bool = False,
    photo: bool = False,
    description: str = "",
) -> MotionPreset:
    return MotionPreset(
        name=name,
        family=family,
        energy=energy,
        direction=direction,
        duration_frames=duration_frames,
        channels={k: tuple(v) for k, v in channels.items()},
        loop=loop,
        photo=photo,
        description=description,
    )


_PRESET_LIST: Tuple[MotionPreset, ...] = (
    # -- Entrances (in) -----------------------------------------------------
    _preset(
        "fade_in",
        "in",
        "standard",
        "none",
        12,
        {"opacity": [kf(0, 0), kf(1, 1, "ease_out_cubic")]},
        description="Pure opacity arrival; no movement.",
    ),
    _preset(
        "rise",
        "in",
        "calm",
        "up",
        16,
        {
            "translateY": [kf(0, 40), kf(1, 0, "ease_out_cubic")],
            "opacity": [kf(0, 0), kf(0.7, 1, "ease_out_quad")],
        },
        description="Gentle lift from below with a fade (Canva Rise).",
    ),
    _preset(
        "slide_up",
        "in",
        "standard",
        "up",
        14,
        {
            "translateY": [kf(0, 60), kf(1, 0, "ease_out_cubic")],
            "opacity": [kf(0, 0), kf(0.6, 1, "ease_out_quad")],
        },
        description="Slides in from below.",
    ),
    _preset(
        "slide_left",
        "in",
        "standard",
        "left",
        14,
        {
            "translateX": [kf(0, 64), kf(1, 0, "ease_out_cubic")],
            "opacity": [kf(0, 0), kf(0.6, 1, "ease_out_quad")],
        },
        description="Enters from the right, travelling left.",
    ),
    _preset(
        "slide_right",
        "in",
        "standard",
        "right",
        14,
        {
            "translateX": [kf(0, -64), kf(1, 0, "ease_out_cubic")],
            "opacity": [kf(0, 0), kf(0.6, 1, "ease_out_quad")],
        },
        description="Enters from the left, travelling right.",
    ),
    _preset(
        "scale_in",
        "in",
        "standard",
        "in",
        14,
        {
            "scale": [kf(0, 0.82), kf(1, 1, "ease_out_cubic")],
            "opacity": [kf(0, 0), kf(0.6, 1, "ease_out_quad")],
        },
        description="Grows into place (Canva/Adobe Grow).",
    ),
    _preset(
        "pop",
        "in",
        "electric",
        "in",
        12,
        {
            "scale": [kf(0, 0.6), kf(1, 1, "ease_out_back")],
            "opacity": [kf(0, 0), kf(0.4, 1, "ease_out_quad")],
        },
        description="Scale punch with overshoot (Adobe Pop).",
    ),
    _preset(
        "drop_in",
        "in",
        "electric",
        "down",
        16,
        {
            "translateY": [kf(0, -64), kf(1, 0, "ease_out_back")],
            "opacity": [kf(0, 0), kf(0.3, 1, "ease_out_quad")],
        },
        description="Drops from above and bounces to rest.",
    ),
    _preset(
        "tumble",
        "in",
        "standard",
        "up",
        18,
        {
            "rotate": [kf(0, -12), kf(1, 0, "ease_out_cubic")],
            "translateY": [kf(0, 36), kf(1, 0, "ease_out_cubic")],
            "opacity": [kf(0, 0), kf(0.6, 1, "ease_out_quad")],
        },
        description="Rotates and lifts into place (Adobe Tumble).",
    ),
    _preset(
        "blur_in",
        "in",
        "calm",
        "none",
        14,
        {
            "blur": [kf(0, 16), kf(1, 0, "ease_out_cubic")],
            "opacity": [kf(0, 0), kf(0.7, 1, "ease_out_quad")],
        },
        description="Resolves from a soft blur (register shift).",
    ),
    _preset(
        "snap_in",
        "in",
        "electric",
        "up",
        10,
        {
            "translateY": [kf(0, 28), kf(1, 0, "ease_out_expo")],
            "opacity": [kf(0, 0), kf(0.35, 1, "ease_out_quad")],
        },
        description="Decisive snap with an exponential settle.",
    ),
    # -- Loops (loop) -------------------------------------------------------
    _preset(
        "drift",
        "loop",
        "calm",
        "none",
        90,
        {"translateX": [kf(0, 0), kf(0.5, 6, "ease_in_out_sine"), kf(1, 0, "ease_in_out_sine")]},
        loop=True,
        description="Slow ambient horizontal drift.",
    ),
    _preset(
        "breathe",
        "loop",
        "calm",
        "none",
        96,
        {"scale": [kf(0, 1), kf(0.5, 1.03, "ease_in_out_sine"), kf(1, 1, "ease_in_out_sine")]},
        loop=True,
        description="Breathing scale on a glow or panel.",
    ),
    _preset(
        "pulse",
        "loop",
        "standard",
        "none",
        48,
        {"scale": [kf(0, 1), kf(0.5, 1.06, "ease_in_out_sine"), kf(1, 1, "ease_in_out_sine")]},
        loop=True,
        description="Emphasis pulse.",
    ),
    _preset(
        "float",
        "loop",
        "calm",
        "up",
        84,
        {"translateY": [kf(0, 0), kf(0.5, -8, "ease_in_out_sine"), kf(1, 0, "ease_in_out_sine")]},
        loop=True,
        description="Gentle bob.",
    ),
    _preset(
        "wiggle",
        "loop",
        "electric",
        "none",
        36,
        {
            "rotate": [
                kf(0, 0),
                kf(0.25, 2, "ease_in_out_sine"),
                kf(0.75, -2, "ease_in_out_sine"),
                kf(1, 0, "ease_in_out_sine"),
            ]
        },
        loop=True,
        description="Playful rotation wiggle.",
    ),
    # -- Photo motion (loop, whole-frame; maps to Ken Burns / pan) ----------
    _preset(
        "ken_burns_in",
        "loop",
        "calm",
        "in",
        120,
        {"scale": [kf(0, 1.0), kf(1, 1.06, "ease_in_out_sine")]},
        loop=True,
        photo=True,
        description="Slow zoom toward the saliency focus.",
    ),
    _preset(
        "ken_burns_out",
        "loop",
        "calm",
        "out",
        120,
        {"scale": [kf(0, 1.06), kf(1, 1.0, "ease_in_out_sine")]},
        loop=True,
        photo=True,
        description="Slow zoom pull-back.",
    ),
    _preset(
        "pan_left",
        "loop",
        "calm",
        "left",
        120,
        {
            "scale": [kf(0, 1.08), kf(1, 1.08)],
            "translateX": [kf(0, 0), kf(1, -48, "ease_in_out_sine")],
        },
        loop=True,
        photo=True,
        description="Fixed zoom, crop slides left.",
    ),
    _preset(
        "pan_right",
        "loop",
        "calm",
        "right",
        120,
        {
            "scale": [kf(0, 1.08), kf(1, 1.08)],
            "translateX": [kf(0, 0), kf(1, 48, "ease_in_out_sine")],
        },
        loop=True,
        photo=True,
        description="Fixed zoom, crop slides right.",
    ),
    _preset(
        "pan_up",
        "loop",
        "calm",
        "up",
        120,
        {
            "scale": [kf(0, 1.08), kf(1, 1.08)],
            "translateY": [kf(0, 0), kf(1, -48, "ease_in_out_sine")],
        },
        loop=True,
        photo=True,
        description="Fixed zoom, crop slides up.",
    ),
    _preset(
        "pan_down",
        "loop",
        "calm",
        "down",
        120,
        {
            "scale": [kf(0, 1.08), kf(1, 1.08)],
            "translateY": [kf(0, 0), kf(1, 48, "ease_in_out_sine")],
        },
        loop=True,
        photo=True,
        description="Fixed zoom, crop slides down.",
    ),
    # -- Exits (out) --------------------------------------------------------
    _preset(
        "fade_out",
        "out",
        "standard",
        "none",
        8,
        {"opacity": [kf(0, 1), kf(1, 0, "ease_in_cubic")]},
        description="Opacity exit.",
    ),
    _preset(
        "sink",
        "out",
        "standard",
        "down",
        10,
        {
            "translateY": [kf(0, 0), kf(1, 24, "ease_in_cubic")],
            "opacity": [kf(0, 1), kf(1, 0, "ease_in_quad")],
        },
        description="Settles down and away.",
    ),
    _preset(
        "zoom_out",
        "out",
        "standard",
        "out",
        10,
        {
            "scale": [kf(0, 1), kf(1, 0.9, "ease_in_cubic")],
            "opacity": [kf(0, 1), kf(1, 0, "ease_in_quad")],
        },
        description="Recedes on exit.",
    ),
)

PRESETS: Dict[str, MotionPreset] = {p.name: p for p in _PRESET_LIST}

# Vocabulary preset name → the closest shipped Ken Burns variant
# (reel_ffmpeg.KEN_BURNS_VARIANTS), so the FFmpeg compiler unifies with the
# recipes already rendering reels instead of forking a parallel set.
KEN_BURNS_ALIASES: Mapping[str, str] = {
    "ken_burns_in": "zoom_in",
    "ken_burns_out": "zoom_out",
    "pan_left": "pan_left",
    "pan_right": "pan_right",
    "pan_up": "pan_up",
    "pan_down": "pan_down",
}


def get(name: str) -> MotionPreset:
    """Look up a preset by name (raises ``KeyError`` if unknown — no silent guess)."""
    return PRESETS[name]


def names() -> Tuple[str, ...]:
    return tuple(PRESETS.keys())


def by_family(family: str) -> Tuple[MotionPreset, ...]:
    return tuple(p for p in _PRESET_LIST if p.family == family)


def photo_presets() -> Tuple[MotionPreset, ...]:
    return tuple(p for p in _PRESET_LIST if p.photo)


def nearest_ken_burns_variant(name: str) -> str | None:
    """The shipped FFmpeg Ken Burns variant for a photo preset, or ``None``."""
    return KEN_BURNS_ALIASES.get(name)


__all__ = [
    "MOTION_REV",
    "FPS",
    "GLYPH_STAGGER_SEC",
    "MAX_ANIM_SECONDS",
    "MAX_ANIMS_PER_DESIGN",
    "MAX_ANIM_FRAMES",
    "CHANNELS",
    "REST",
    "FAMILIES",
    "ENERGIES",
    "DIRECTIONS",
    "MotionCapError",
    "Keyframe",
    "kf",
    "MotionPreset",
    "ElementMotion",
    "MotionPlan",
    "PRESETS",
    "KEN_BURNS_ALIASES",
    "get",
    "names",
    "by_family",
    "photo_presets",
    "nearest_ken_burns_variant",
    "clamp_anim_seconds",
    "clamp_anim_frames",
    "enforce_design_caps",
]
