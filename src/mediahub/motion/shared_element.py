"""Shared-element transitions — the same element morphs between two scenes.

Canva's "Match & Move": the same athlete photo (or stat, or logo) keeps its
identity across a scene change, gliding and scaling from where it sat in scene A
to where it sits in scene B instead of cutting. The element is matched by a
**stable id**, so both engines know it is the *same* element on both sides.

The geometry is a deterministic interpolation of two rectangles (and an optional
brand-colour tween). It compiles to:

* CSS — a FLIP transform: the element is laid out at its destination and
  transformed *from* the source delta back to identity.
* Remotion — translate/scale (and colour) keyframe tokens the TS samples.

FFmpeg (whole-frame compositing) expresses this as the reel crossfade it already
ships; the per-element morph is a Remotion/CSS capability.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from .easing import get_easing

Rect = Tuple[float, float, float, float]  # x, y, w, h


@dataclass(frozen=True)
class SharedElementTransition:
    element_id: str
    from_rect: Rect
    to_rect: Rect
    from_color: Optional[str] = None
    to_color: Optional[str] = None
    easing: str = "ease_in_out_cubic"
    duration_frames: int = 12

    # -- sampling -----------------------------------------------------------
    def at(self, t: float) -> Dict[str, Any]:
        """Absolute geometry (and colour) at ``t`` in [0,1]."""
        e = get_easing(self.easing).sample(t)
        fx, fy, fw, fh = self.from_rect
        tx, ty, tw, th = self.to_rect
        out: Dict[str, Any] = {
            "x": _lerp(fx, tx, e),
            "y": _lerp(fy, ty, e),
            "w": _lerp(fw, tw, e),
            "h": _lerp(fh, th, e),
        }
        if self.from_color and self.to_color:
            out["color"] = _lerp_hex(self.from_color, self.to_color, e)
        return out

    # -- compilers ----------------------------------------------------------
    def to_css(
        self,
        *,
        class_name: Optional[str] = None,
        duration_sec: Optional[float] = None,
        fps: int = 30,
    ) -> str:
        cls = class_name or f"mh-shared-{self.element_id}"
        secs = duration_sec if duration_sec is not None else self.duration_frames / float(fps)
        fx, fy, fw, fh = self.from_rect
        tx, ty, tw, th = self.to_rect
        # FLIP: element is positioned at the destination; start frame is the
        # inverse transform back to the source rect, animating to identity.
        dx, dy = fx - tx, fy - ty
        sx = (fw / tw) if tw else 1.0
        sy = (fh / th) if th else 1.0
        easing = get_easing(self.easing).css()
        start_extra = (
            f"background-color:{self.from_color};" if self.from_color and self.to_color else ""
        )
        end_extra = (
            f"background-color:{self.to_color};" if self.from_color and self.to_color else ""
        )
        kf_name = f"mh-shared-{self.element_id}-kf"
        return (
            f"@keyframes {kf_name}{{"
            f"0%{{transform:translate3d({_px(dx)},{_px(dy)},0) scale({_num(sx)},{_num(sy)});{start_extra}}}"
            f"100%{{transform:translate3d(0,0,0) scale(1,1);{end_extra}}}"
            f"}}"
            f".{cls}{{transform-origin:top left;"
            f"animation:{kf_name} {_num(secs)}s {easing} both;}}"
        )

    def to_remotion_tokens(self, samples: int = 12) -> Dict[str, Any]:
        tw = self.to_rect[2] or 1.0
        th = self.to_rect[3] or 1.0
        stops = []
        for s in range(samples + 1):
            t = s / samples
            g = self.at(t)
            stop = {
                "offset": round(t, 6),
                "translateX": round(g["x"] - self.to_rect[0], 3),
                "translateY": round(g["y"] - self.to_rect[1], 3),
                "scaleX": round(g["w"] / tw, 5),
                "scaleY": round(g["h"] / th, 5),
            }
            if "color" in g:
                stop["color"] = g["color"]
            stops.append(stop)
        return {
            "elementId": self.element_id,
            "durationFrames": self.duration_frames,
            "stops": stops,
        }


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _lerp_hex(a: str, b: str, t: float) -> str:
    ar, ag, ab = _rgb(a)
    br, bg, bb = _rgb(b)
    return "#{:02X}{:02X}{:02X}".format(
        round(_lerp(ar, br, t)), round(_lerp(ag, bg, t)), round(_lerp(ab, bb, t))
    )


def _rgb(hex_str: str) -> Tuple[int, int, int]:
    h = hex_str.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _num(x: float) -> str:
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


def _px(x: float) -> str:
    n = _num(x)
    return "0" if n == "0" else f"{n}px"


__all__ = ["SharedElementTransition", "Rect"]
