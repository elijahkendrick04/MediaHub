"""elements.draw — the telestration / annotate layer (roadmap 1.10, build 4).

A light, deterministic annotate layer for coach telestration on photos — freehand
pen, straight line, arrow, rectangle, ellipse, plus a symmetry mirror and a
**Shape Assist** auto-snap (a rough freehand circle becomes a clean ellipse, a
rough line snaps straight). Not an illustration suite: a few clear marks a coach
draws over an action shot ("watch this gap", "lead arm here").

Everything here is deterministic maths (Ramer–Douglas–Peucker simplification,
shape detection by geometry, mirroring) — same strokes in → same SVG / same
pixels out. It's stored as a **spec layer** on the asset (``annotation``), so the
original photo is never touched; the overlay is rendered to SVG (live web overlay)
or composited onto the image with Pillow (export) at paint time. Strokes use
normalised 0..1 coordinates so one annotation renders at any size/format.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional

# Stroke kinds. "auto" runs Shape Assist (detect line/rect/ellipse from freehand).
KINDS: tuple[str, ...] = ("free", "line", "arrow", "rect", "ellipse", "auto")
SYMMETRIES: tuple[str, ...] = ("none", "vertical", "horizontal", "quad")

Point = tuple[float, float]


@dataclass(frozen=True)
class Stroke:
    """One annotate mark. ``points`` are normalised (0..1) to the image box."""

    points: tuple[Point, ...]
    kind: str = "free"
    colour: str = "--mh-accent"  # a brand role var key, or a literal hex
    width: float = 0.006  # stroke width as a fraction of the short edge

    def to_dict(self) -> dict:
        return {
            "points": [[round(x, 5), round(y, 5)] for x, y in self.points],
            "kind": self.kind,
            "colour": self.colour,
            "width": self.width,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Optional["Stroke"]:
        if not isinstance(data, dict):
            return None
        pts = _clean_points(data.get("points"))
        if not pts:
            return None
        kind = str(data.get("kind", "free")).strip().lower()
        if kind not in KINDS:
            kind = "free"
        return cls(
            points=pts,
            kind=kind,
            colour=str(data.get("colour", "--mh-accent")).strip() or "--mh-accent",
            width=_clamp(_safe_float(data.get("width", 0.006), 0.006), 0.001, 0.05),
        )


@dataclass(frozen=True)
class AnnotationLayer:
    """A photo's annotation: a set of strokes + an optional symmetry mirror."""

    strokes: tuple[Stroke, ...] = ()
    symmetry: str = "none"

    def is_empty(self) -> bool:
        return not self.strokes

    def to_dict(self) -> dict:
        return {
            "strokes": [s.to_dict() for s in self.strokes],
            "symmetry": self.symmetry,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AnnotationLayer":
        if not isinstance(data, dict):
            return cls()
        strokes = []
        for raw in data.get("strokes", []) or []:
            s = Stroke.from_dict(raw)
            if s is not None:
                strokes.append(s)
        sym = str(data.get("symmetry", "none")).strip().lower()
        if sym not in SYMMETRIES:
            sym = "none"
        return cls(strokes=tuple(strokes), symmetry=sym)


# --------------------------------------------------------------------------- #
# geometry: RDP simplification + Shape Assist snapping + symmetry
# --------------------------------------------------------------------------- #
def rdp(points: list[Point] | tuple[Point, ...], epsilon: float = 0.004) -> list[Point]:
    """Ramer–Douglas–Peucker polyline simplification (deterministic).

    Drops points that lie within ``epsilon`` of the line between their
    neighbours — a freehand stroke of 400 jittery points becomes a clean ~12.
    """
    pts = list(points)
    if len(pts) < 3:
        return pts
    dmax, index = 0.0, 0
    a, b = pts[0], pts[-1]
    for i in range(1, len(pts) - 1):
        d = _perp_distance(pts[i], a, b)
        if d > dmax:
            dmax, index = d, i
    if dmax > epsilon:
        left = rdp(pts[: index + 1], epsilon)
        right = rdp(pts[index:], epsilon)
        return left[:-1] + right
    return [a, b]


def auto_snap(points: list[Point] | tuple[Point, ...]) -> tuple[str, list[Point]]:
    """Shape Assist: classify a freehand stroke as line/rect/ellipse/free.

    Deterministic geometry — no model. Returns ``(kind, canonical_points)`` where
    canonical_points are the two bbox corners for rect/ellipse, the two endpoints
    for line, or the RDP-simplified path for free.
    """
    pts = [(_clamp01(x), _clamp01(y)) for x, y in points]
    if len(pts) < 2:
        return "free", pts
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    diag = math.hypot(bbox[2] - bbox[0], bbox[3] - bbox[1]) or 1e-6
    start, end = pts[0], pts[-1]
    closed = _dist(start, end) < 0.18 * diag

    if not closed:
        straightness = max(_perp_distance(p, start, end) for p in pts) / diag
        if straightness < 0.08:
            return "line", [start, end]
        return "free", rdp(pts)

    # closed → rectangle vs ellipse by which the path fits better. For each point
    # compare its residual to the bounding box's perimeter (rectangle) against the
    # inscribed-ellipse equation; the lower mean residual wins. Robust + exact.
    x0, y0, x1, y1 = bbox
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    rx = max((x1 - x0) / 2, 1e-6)
    ry = max((y1 - y0) / 2, 1e-6)
    rect_res = 0.0
    ell_res = 0.0
    for x, y in pts:
        edge = min(abs(x - x0), abs(x - x1), abs(y - y0), abs(y - y1))
        rect_res += edge / diag
        r = math.hypot((x - cx) / rx, (y - cy) / ry)
        ell_res += abs(r - 1.0)
    rect_res /= len(pts)
    ell_res /= len(pts)
    corners = [(x0, y0), (x1, y1)]
    return ("rect" if rect_res <= ell_res else "ellipse"), corners


def snap_stroke(stroke: Stroke) -> Stroke:
    """Resolve a stroke's geometry by its kind (Shape Assist for ``auto``)."""
    pts = list(stroke.points)
    if stroke.kind == "auto":
        kind, snapped = auto_snap(pts)
        return Stroke(points=tuple(snapped), kind=kind, colour=stroke.colour, width=stroke.width)
    if stroke.kind == "free":
        return Stroke(points=tuple(rdp(pts)), kind="free", colour=stroke.colour, width=stroke.width)
    if stroke.kind in ("line", "arrow") and len(pts) >= 2:
        return Stroke(
            points=(pts[0], pts[-1]), kind=stroke.kind, colour=stroke.colour, width=stroke.width
        )
    if stroke.kind in ("rect", "ellipse") and len(pts) >= 2:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        corners = ((min(xs), min(ys)), (max(xs), max(ys)))
        return Stroke(points=corners, kind=stroke.kind, colour=stroke.colour, width=stroke.width)
    return stroke


def mirror_points(points: list[Point] | tuple[Point, ...], mode: str) -> list[list[Point]]:
    """Return mirrored copies of a point list for the symmetry mode (excl. original)."""
    pts = list(points)
    out: list[list[Point]] = []
    if mode in ("vertical", "quad"):
        out.append([(1.0 - x, y) for x, y in pts])
    if mode in ("horizontal", "quad"):
        out.append([(x, 1.0 - y) for x, y in pts])
    if mode == "quad":
        out.append([(1.0 - x, 1.0 - y) for x, y in pts])
    return out


def expand_symmetry(layer: AnnotationLayer) -> list[Stroke]:
    """All strokes to paint: each snapped stroke plus its symmetry mirrors."""
    out: list[Stroke] = []
    for s in layer.strokes:
        snapped = snap_stroke(s)
        out.append(snapped)
        for mpts in mirror_points(snapped.points, layer.symmetry):
            out.append(
                Stroke(
                    points=tuple(mpts),
                    kind=snapped.kind,
                    colour=snapped.colour,
                    width=snapped.width,
                )
            )
    return out


# --------------------------------------------------------------------------- #
# colour resolution (brand role or literal)
# --------------------------------------------------------------------------- #
def resolve_colour(colour: str, role_vars: Optional[dict] = None) -> str:
    """A brand role key resolves to its hex; a literal hex passes through."""
    c = (colour or "").strip()
    if c.startswith("--"):
        from .recolour import _ROLE_FALLBACK

        return (role_vars or {}).get(c) or _ROLE_FALLBACK.get(c, "#FFB81C")
    return c or "#FFB81C"


# --------------------------------------------------------------------------- #
# render: SVG overlay (web) + Pillow raster (export)
# --------------------------------------------------------------------------- #
def render_overlay_svg(
    layer: AnnotationLayer, *, width: int, height: int, role_vars: Optional[dict] = None
) -> str:
    """An inline ``<svg>`` of the annotation, sized to ``width``×``height``."""
    short = max(1, min(width, height))
    parts: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" fill="none">'
    ]
    for s in expand_symmetry(layer):
        col = resolve_colour(s.colour, role_vars)
        w = max(1.0, s.width * short)
        parts.append(_svg_for_stroke(s, width, height, col, w))
    parts.append("</svg>")
    return "".join(parts)


def _svg_for_stroke(s: Stroke, W: int, H: int, col: str, w: float) -> str:
    pts = [(x * W, y * H) for x, y in s.points]
    stroke_attrs = (
        f'stroke="{col}" stroke-width="{w:.2f}" stroke-linecap="round" stroke-linejoin="round"'
    )
    if s.kind == "ellipse" and len(pts) >= 2:
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rx, ry = abs(x1 - x0) / 2, abs(y1 - y0) / 2
        return f'<ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" {stroke_attrs}/>'
    if s.kind == "rect" and len(pts) >= 2:
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        return (
            f'<rect x="{min(x0, x1):.1f}" y="{min(y0, y1):.1f}" '
            f'width="{abs(x1 - x0):.1f}" height="{abs(y1 - y0):.1f}" rx="4" {stroke_attrs}/>'
        )
    d = "M " + " L ".join(f"{x:.1f} {y:.1f}" for x, y in pts)
    out = f'<path d="{d}" {stroke_attrs}/>'
    if s.kind == "arrow" and len(pts) >= 2:
        out += _svg_arrowhead(pts[-2], pts[-1], col, w)
    return out


def _svg_arrowhead(p0: Point, p1: Point, col: str, w: float) -> str:
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    size = max(8.0, w * 3.5)
    a1 = ang + math.radians(150)
    a2 = ang - math.radians(150)
    x1, y1 = p1[0] + size * math.cos(a1), p1[1] + size * math.sin(a1)
    x2, y2 = p1[0] + size * math.cos(a2), p1[1] + size * math.sin(a2)
    return (
        f'<polygon points="{p1[0]:.1f},{p1[1]:.1f} {x1:.1f},{y1:.1f} {x2:.1f},{y2:.1f}" '
        f'fill="{col}"/>'
    )


def render_onto_image(layer: AnnotationLayer, image, role_vars: Optional[dict] = None):
    """Composite the annotation onto a PIL image (export). Returns a new image.

    Deterministic Pillow raster — no SVG rasteriser dependency. The source image
    is never mutated (we draw on a copy), honouring the non-destructive rule.
    """
    from PIL import Image, ImageDraw

    base = image.convert("RGBA")
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    W, H = base.size
    short = max(1, min(W, H))
    for s in expand_symmetry(layer):
        col = _hex_to_rgba(resolve_colour(s.colour, role_vars))
        w = max(1, int(round(s.width * short)))
        pts = [(x * W, y * H) for x, y in s.points]
        _draw_stroke(draw, s.kind, pts, col, w)
    return Image.alpha_composite(base, overlay)


def _draw_stroke(draw, kind: str, pts: list[Point], col, w: int) -> None:
    if len(pts) < 2:
        if pts:
            r = max(1, w // 2)
            x, y = pts[0]
            draw.ellipse([x - r, y - r, x + r, y + r], fill=col)
        return
    if kind == "ellipse":
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        draw.ellipse([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], outline=col, width=w)
        return
    if kind == "rect":
        (x0, y0), (x1, y1) = pts[0], pts[-1]
        draw.rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], outline=col, width=w)
        return
    draw.line(pts, fill=col, width=w, joint="curve")
    if kind == "arrow":
        _draw_arrowhead(draw, pts[-2], pts[-1], col, w)


def _draw_arrowhead(draw, p0: Point, p1: Point, col, w: int) -> None:
    ang = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    size = max(8.0, w * 3.5)
    a1 = ang + math.radians(150)
    a2 = ang - math.radians(150)
    pts = [
        p1,
        (p1[0] + size * math.cos(a1), p1[1] + size * math.sin(a1)),
        (p1[0] + size * math.cos(a2), p1[1] + size * math.sin(a2)),
    ]
    draw.polygon(pts, fill=col)


# --------------------------------------------------------------------------- #
# small helpers
# --------------------------------------------------------------------------- #
def _clean_points(raw) -> tuple[Point, ...]:
    if not isinstance(raw, (list, tuple)):
        return ()
    out: list[Point] = []
    for item in raw:
        if isinstance(item, (list, tuple)) and len(item) >= 2:
            out.append((_clamp01(_safe_float(item[0], 0.0)), _clamp01(_safe_float(item[1], 0.0))))
    return tuple(out)


def _perp_distance(p: Point, a: Point, b: Point) -> float:
    if a == b:
        return _dist(p, a)
    num = abs((b[0] - a[0]) * (a[1] - p[1]) - (a[0] - p[0]) * (b[1] - a[1]))
    den = math.hypot(b[0] - a[0], b[1] - a[1]) or 1e-9
    return num / den


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _hex_to_rgba(hex_str: str, alpha: int = 255):
    h = (hex_str or "").lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    if len(h) != 6:
        return (255, 184, 28, alpha)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), alpha)
    except ValueError:
        return (255, 184, 28, alpha)


def _safe_float(v, default: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _clamp01(v: float) -> float:
    return _clamp(v, 0.0, 1.0)


__all__ = [
    "Stroke",
    "AnnotationLayer",
    "KINDS",
    "SYMMETRIES",
    "rdp",
    "auto_snap",
    "snap_stroke",
    "expand_symmetry",
    "mirror_points",
    "resolve_colour",
    "render_overlay_svg",
    "render_onto_image",
]
