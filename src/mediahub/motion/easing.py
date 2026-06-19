"""Named easing tokens — one curve, three render targets.

MediaHub's motion vocabulary (roadmap 1.5) is defined **once** in Python and
compiled to Remotion, FFmpeg and CSS. An easing is the "adverb" of a motion
(see ``.claude/skills/motion-craft/references/motion-language.md``) and has to
mean the same thing on every surface, so each token here carries three exact
representations of one curve:

* ``bezier`` — the four cubic-bézier control points. CSS consumes them directly
  as ``cubic-bezier(...)`` and Remotion as ``Easing.bezier(...)`` — identical
  curves, no drift.
* ``ffmpeg`` — a progress expression (``P`` is normalised progress 0..1) for
  FFmpeg filter graphs, whose expression language has no bézier primitive. Where
  a curve overshoots (``ease_out_back``), the FFmpeg approximation clamps to
  [0,1] — documented per token, never silently wrong.
* :meth:`Easing.sample` — a pure-Python evaluation of the same bézier, used by
  the Python-side compilers and the tests so "what the curve does" is checked in
  one place.

Everything here is a pure function of its inputs — deterministic, no clock, no
RNG — so a preset renders byte-identically every time.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Tuple


@dataclass(frozen=True)
class Easing:
    """One easing curve, expressed for all three render targets."""

    name: str
    #: cubic-bézier control points (P1x, P1y, P2x, P2y); P0=(0,0), P3=(1,1).
    bezier: Tuple[float, float, float, float]
    #: FFmpeg progress expression; ``P`` is replaced by the caller's 0..1 expr.
    ffmpeg: str
    #: human note (e.g. where an FFmpeg approximation drops overshoot).
    note: str = ""

    # -- CSS / Remotion -----------------------------------------------------
    def css(self) -> str:
        """``cubic-bezier(x1,y1,x2,y2)`` — also the Remotion ``Easing.bezier`` args."""
        x1, y1, x2, y2 = self.bezier
        return f"cubic-bezier({_num(x1)},{_num(y1)},{_num(x2)},{_num(y2)})"

    # -- FFmpeg -------------------------------------------------------------
    def ffmpeg_expr(self, progress: str) -> str:
        """Eased value for an FFmpeg expression whose progress 0..1 is ``progress``."""
        return self.ffmpeg.replace("P", f"({progress})")

    # -- Python (tests + compilers) ----------------------------------------
    def sample(self, t: float) -> float:
        """Evaluate the curve at ``t`` in [0,1] (the bézier ``y`` for ``x=t``)."""
        x = 0.0 if t < 0.0 else 1.0 if t > 1.0 else float(t)
        x1, y1, x2, y2 = self.bezier
        if (x1, y1, x2, y2) == (0.0, 0.0, 1.0, 1.0):
            return x  # linear fast-path
        # Binary-search the bézier parameter u where Bx(u) == x, return By(u).
        lo, hi = 0.0, 1.0
        u = x
        for _ in range(48):
            bx = _bezier_axis(u, x1, x2)
            if abs(bx - x) < 1e-6:
                break
            if bx < x:
                lo = u
            else:
                hi = u
            u = (lo + hi) / 2.0
        return _bezier_axis(u, y1, y2)


def _bezier_axis(u: float, c1: float, c2: float) -> float:
    """One axis of the cubic bézier with P0=0, P3=1 and the two control values."""
    v = 1.0 - u
    return 3.0 * v * v * u * c1 + 3.0 * v * u * u * c2 + u * u * u


def _num(x: float) -> str:
    """Compact, locale-free number ('1', '0.5', '0.215') for CSS/TS output."""
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


# ---------------------------------------------------------------------------
# The closed easing vocabulary. Names map onto the motion-craft easing table:
# .out for entering, .in for leaving, .inOut for moving within a scene.
# ---------------------------------------------------------------------------

_EASINGS: Tuple[Easing, ...] = (
    Easing("linear", (0.0, 0.0, 1.0, 1.0), "P"),
    # Entrances — decisive, composed deceleration.
    Easing("ease_out_quad", (0.25, 0.46, 0.45, 0.94), "(1-pow(1-P,2))"),
    Easing("ease_out_cubic", (0.215, 0.61, 0.355, 1.0), "(1-pow(1-P,3))"),
    Easing(
        "ease_out_expo",
        (0.19, 1.0, 0.22, 1.0),
        "(if(gte(P,1),1,1-pow(2,-10*P)))",
    ),
    Easing(
        "ease_out_back",
        (0.34, 1.56, 0.64, 1.0),
        "(1-pow(1-P,3))",
        note="FFmpeg approximation drops the overshoot (no negative range in zoompan).",
    ),
    # Exits — accelerate away.
    Easing("ease_in_cubic", (0.55, 0.055, 0.675, 0.19), "pow(P,3)"),
    Easing("ease_in_quad", (0.55, 0.085, 0.68, 0.53), "pow(P,2)"),
    # Reposition / ambient — neutral, organic.
    Easing(
        "ease_in_out_cubic",
        (0.645, 0.045, 0.355, 1.0),
        "(if(lt(P,0.5),4*pow(P,3),1-pow(-2*P+2,3)/2))",
    ),
    Easing("ease_in_out_sine", (0.445, 0.05, 0.55, 0.95), "(0.5-0.5*cos(PI*P))"),
)

EASINGS: Dict[str, Easing] = {e.name: e for e in _EASINGS}

DEFAULT_EASING = "ease_out_cubic"


def get_easing(name: str) -> Easing:
    """Look up an easing token, falling back to the documented default."""
    return EASINGS.get(name) or EASINGS[DEFAULT_EASING]


def easing_names() -> Tuple[str, ...]:
    return tuple(EASINGS.keys())


__all__ = [
    "Easing",
    "EASINGS",
    "DEFAULT_EASING",
    "get_easing",
    "easing_names",
]
