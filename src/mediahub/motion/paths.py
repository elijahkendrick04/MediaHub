"""Motion paths — sample an SVG path, with orient-to-path.

A motion path moves an element along a curve (Canva's "Create an Animation"
motion path + orient-to-path + speed). The single source of truth is the SVG
path string; this module samples it deterministically:

* :meth:`MotionPath.point_at` — position at ``t`` in [0,1] of arc length.
* :meth:`MotionPath.angle_at` — tangent heading in degrees (orient-to-path).

and compiles it to the three targets: CSS ``offset-path``/``offset-rotate`` (the
browser does the work natively), Remotion translate/rotate keyframe tokens, and
sampled FFmpeg overlay ``x``/``y`` expressions. Supports the common path subset
(M, L, H, V, C, Q, Z; absolute and relative).
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

_TOKEN = re.compile(r"([MmLlHhVvCcQqZz])|(-?\d*\.?\d+(?:[eE][-+]?\d+)?)")

Point = Tuple[float, float]


def _tokens(d: str) -> List[str]:
    return [m.group(0) for m in _TOKEN.finditer(d)]


def _line(p0: Point, p1: Point, n: int) -> List[Point]:
    return [
        (p0[0] + (p1[0] - p0[0]) * i / n, p0[1] + (p1[1] - p0[1]) * i / n) for i in range(1, n + 1)
    ]


def _cubic(p0: Point, c1: Point, c2: Point, p1: Point, n: int) -> List[Point]:
    out: List[Point] = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        x = u**3 * p0[0] + 3 * u * u * t * c1[0] + 3 * u * t * t * c2[0] + t**3 * p1[0]
        y = u**3 * p0[1] + 3 * u * u * t * c1[1] + 3 * u * t * t * c2[1] + t**3 * p1[1]
        out.append((x, y))
    return out


def _quad(p0: Point, c1: Point, p1: Point, n: int) -> List[Point]:
    out: List[Point] = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        x = u * u * p0[0] + 2 * u * t * c1[0] + t * t * p1[0]
        y = u * u * p0[1] + 2 * u * t * c1[1] + t * t * p1[1]
        out.append((x, y))
    return out


@dataclass(frozen=True)
class MotionPath:
    d: str
    polyline: Tuple[Point, ...]
    cum_len: Tuple[float, ...]  # cumulative arc length per polyline point

    @property
    def length(self) -> float:
        return self.cum_len[-1] if self.cum_len else 0.0

    # -- sampling -----------------------------------------------------------
    def point_at(self, t: float) -> Point:
        i, local = self._locate(t)
        if i >= len(self.polyline) - 1:
            return self.polyline[-1]
        a, b = self.polyline[i], self.polyline[i + 1]
        return (a[0] + (b[0] - a[0]) * local, a[1] + (b[1] - a[1]) * local)

    def angle_at(self, t: float) -> float:
        i, _ = self._locate(t)
        i = min(i, len(self.polyline) - 2)
        a, b = self.polyline[i], self.polyline[i + 1]
        return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0]))

    def _locate(self, t: float) -> Tuple[int, float]:
        if self.length <= 0 or len(self.polyline) < 2:
            return 0, 0.0
        target = max(0.0, min(1.0, t)) * self.length
        for i in range(1, len(self.cum_len)):
            if target <= self.cum_len[i]:
                seg = self.cum_len[i] - self.cum_len[i - 1]
                local = 0.0 if seg <= 0 else (target - self.cum_len[i - 1]) / seg
                return i - 1, local
        return len(self.polyline) - 2, 1.0

    # -- compilers ----------------------------------------------------------
    def to_remotion_tokens(self, samples: int = 24) -> Dict[str, Any]:
        pts = []
        for s in range(samples + 1):
            t = s / samples
            x, y = self.point_at(t)
            pts.append(
                {
                    "offset": round(t, 6),
                    "x": round(x, 3),
                    "y": round(y, 3),
                    "angle": round(self.angle_at(t), 3),
                }
            )
        return {"d": self.d, "samples": pts}

    def to_css(
        self, *, class_name: str, duration_sec: float, orient: bool = True, easing: str = "linear"
    ) -> str:
        rotate = "auto" if orient else "0deg"
        return (
            f".{class_name}{{"
            f"offset-path:path('{self.d}');"
            f"offset-rotate:{rotate};"
            f"animation:mh-path-move {_num(duration_sec)}s {easing} both;"
            f"}}"
            "@keyframes mh-path-move{from{offset-distance:0%}to{offset-distance:100%}}"
        )

    def to_ffmpeg_overlay(self, frames: int, samples: int = 12) -> Tuple[str, str]:
        """Piecewise-linear overlay ``x``/``y`` expressions over ``on``/frames."""
        pts = [(s / samples, self.point_at(s / samples)) for s in range(samples + 1)]
        return (
            _piecewise([(t, p[0]) for t, p in pts], frames),
            _piecewise([(t, p[1]) for t, p in pts], frames),
        )


def from_svg(d: str, *, substeps: int = 16) -> MotionPath:
    """Parse an SVG path into a sampled :class:`MotionPath`."""
    toks = _tokens(d)
    poly: List[Point] = []
    cur: Point = (0.0, 0.0)
    start: Point = (0.0, 0.0)
    i = 0
    cmd = ""

    def num() -> float:
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    while i < len(toks):
        tok = toks[i]
        if re.match(r"[A-Za-z]", tok):
            cmd = tok
            i += 1
        rel = cmd.islower()
        c = cmd.upper()
        if c == "M":
            x, y = num(), num()
            cur = (cur[0] + x, cur[1] + y) if rel else (x, y)
            start = cur
            if not poly:
                poly.append(cur)
            cmd = "l" if rel else "L"  # subsequent pairs are implicit lineto
        elif c == "L":
            x, y = num(), num()
            nxt = (cur[0] + x, cur[1] + y) if rel else (x, y)
            poly.extend(_line(cur, nxt, substeps))
            cur = nxt
        elif c == "H":
            x = num()
            nxt = (cur[0] + x, cur[1]) if rel else (x, cur[1])
            poly.extend(_line(cur, nxt, substeps))
            cur = nxt
        elif c == "V":
            y = num()
            nxt = (cur[0], cur[1] + y) if rel else (cur[0], y)
            poly.extend(_line(cur, nxt, substeps))
            cur = nxt
        elif c == "C":
            c1 = (num(), num())
            c2 = (num(), num())
            p1 = (num(), num())
            if rel:
                c1 = (cur[0] + c1[0], cur[1] + c1[1])
                c2 = (cur[0] + c2[0], cur[1] + c2[1])
                p1 = (cur[0] + p1[0], cur[1] + p1[1])
            poly.extend(_cubic(cur, c1, c2, p1, substeps))
            cur = p1
        elif c == "Q":
            c1 = (num(), num())
            p1 = (num(), num())
            if rel:
                c1 = (cur[0] + c1[0], cur[1] + c1[1])
                p1 = (cur[0] + p1[0], cur[1] + p1[1])
            poly.extend(_quad(cur, c1, p1, substeps))
            cur = p1
        elif c == "Z":
            poly.extend(_line(cur, start, substeps))
            cur = start
        else:
            i += 1  # unknown command token — skip defensively

    if not poly:
        poly = [(0.0, 0.0)]
    cum = [0.0]
    for j in range(1, len(poly)):
        cum.append(cum[-1] + math.dist(poly[j - 1], poly[j]))
    return MotionPath(d=d, polyline=tuple(poly), cum_len=tuple(cum))


def _piecewise(samples: List[Tuple[float, float]], frames: int) -> str:
    """Nested ``if(lt(t,..),lerp,..)`` over ``t = on/frames`` for FFmpeg."""
    expr = _num(samples[-1][1])
    for k in range(len(samples) - 2, -1, -1):
        t0, v0 = samples[k]
        t1, v1 = samples[k + 1]
        span = t1 - t0 or 1.0
        # linear interpolation of v across [t0,t1] in terms of t
        frac = f"((on/{frames})-{_num(t0)})/{_num(span)}"
        seg = f"({_num(v0)}+({_num(v1 - v0)})*({frac}))"
        expr = f"if(lt(on/{frames},{_num(t1)}),{seg},{expr})"
    return expr


def _num(x: float) -> str:
    s = f"{x:.4f}".rstrip("0").rstrip(".")
    return s if s else "0"


__all__ = ["MotionPath", "from_svg"]
