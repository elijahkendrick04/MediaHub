"""MediaHub motion vocabulary (roadmap 1.5).

A tokenised brand-motion vocabulary defined **once** and compiled to three
render targets — Remotion (frame-pure interpolation), FFmpeg (whole-frame
recipes) and CSS (browser keyframes) — plus motion paths, shared-element
transitions, reduce-motion variants, and engineering caps.

Start at :mod:`mediahub.motion.vocabulary` (the preset registry, the single
source of truth). The compilers are :mod:`~mediahub.motion.compile_remotion`,
:mod:`~mediahub.motion.compile_ffmpeg` and :mod:`~mediahub.motion.compile_css`.
``scripts/regen_motion_tokens.py`` regenerates the committed Remotion token
bundle and the served CSS stylesheet from this package.
"""

from __future__ import annotations

from .easing import EASINGS, Easing, easing_names, get_easing
from .paths import MotionPath, from_svg
from .shared_element import SharedElementTransition
from .vocabulary import (
    MAX_ANIM_SECONDS,
    MAX_ANIMS_PER_DESIGN,
    MOTION_REV,
    ElementMotion,
    Keyframe,
    MotionCapError,
    MotionPlan,
    MotionPreset,
    PRESETS,
    by_family,
    get,
    names,
    nearest_ken_burns_variant,
    photo_presets,
)

__all__ = [
    "MOTION_REV",
    "MAX_ANIM_SECONDS",
    "MAX_ANIMS_PER_DESIGN",
    "Easing",
    "EASINGS",
    "get_easing",
    "easing_names",
    "MotionPreset",
    "Keyframe",
    "MotionPlan",
    "ElementMotion",
    "MotionCapError",
    "PRESETS",
    "get",
    "names",
    "by_family",
    "photo_presets",
    "nearest_ken_burns_variant",
    "MotionPath",
    "from_svg",
    "SharedElementTransition",
]
