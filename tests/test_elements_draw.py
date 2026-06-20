"""Roadmap 1.10 build 4 — the deterministic telestration / draw engine."""

from __future__ import annotations

import math

import pytest

from mediahub.elements import draw
from mediahub.elements.draw import AnnotationLayer, Stroke


# --------------------------------------------------------------------------- #
# RDP simplification
# --------------------------------------------------------------------------- #
def test_rdp_collapses_collinear_points():
    pts = [(0.0, 0.0), (0.25, 0.0), (0.5, 0.0), (0.75, 0.0), (1.0, 0.0)]
    out = draw.rdp(pts, epsilon=0.01)
    assert out == [(0.0, 0.0), (1.0, 0.0)]  # straight line → endpoints only


def test_rdp_keeps_corners():
    pts = [(0.0, 0.0), (0.5, 0.5), (1.0, 0.0)]  # a peak
    out = draw.rdp(pts, epsilon=0.01)
    assert (0.5, 0.5) in out


def test_rdp_short_paths_passthrough():
    assert draw.rdp([(0.0, 0.0)]) == [(0.0, 0.0)]


# --------------------------------------------------------------------------- #
# Shape Assist auto-snap
# --------------------------------------------------------------------------- #
def test_auto_snap_line():
    pts = [(0.1 + 0.04 * i, 0.1) for i in range(0, 20)]  # a straight horizontal stroke
    kind, snapped = draw.auto_snap(pts)
    assert kind == "line"
    assert len(snapped) == 2


def test_auto_snap_ellipse():
    pts = [
        (0.5 + 0.3 * math.cos(t), 0.5 + 0.3 * math.sin(t))
        for t in [i * math.pi / 18 for i in range(37)]  # full circle, closed
    ]
    kind, _ = draw.auto_snap(pts)
    assert kind == "ellipse"


def test_auto_snap_rect():
    # a closed square path: along 4 edges
    pts = []
    for i in range(11):
        pts.append((0.2 + 0.6 * i / 10, 0.2))  # top
    for i in range(11):
        pts.append((0.8, 0.2 + 0.6 * i / 10))  # right
    for i in range(11):
        pts.append((0.8 - 0.6 * i / 10, 0.8))  # bottom
    for i in range(11):
        pts.append((0.2, 0.8 - 0.6 * i / 10))  # left back to start
    kind, _ = draw.auto_snap(pts)
    assert kind == "rect"


def test_snap_stroke_line_uses_endpoints():
    s = Stroke(points=((0.1, 0.1), (0.3, 0.12), (0.5, 0.5)), kind="line")
    out = draw.snap_stroke(s)
    assert out.points == ((0.1, 0.1), (0.5, 0.5))


def test_snap_stroke_rect_uses_bbox():
    s = Stroke(points=((0.2, 0.3), (0.7, 0.1), (0.5, 0.8)), kind="rect")
    out = draw.snap_stroke(s)
    assert out.points == ((0.2, 0.1), (0.7, 0.8))


# --------------------------------------------------------------------------- #
# symmetry
# --------------------------------------------------------------------------- #
def test_mirror_vertical():
    out = draw.mirror_points([(0.2, 0.4)], "vertical")
    assert out == [[(0.8, 0.4)]]


def test_mirror_quad_three_copies():
    out = draw.mirror_points([(0.25, 0.25)], "quad")
    assert len(out) == 3
    assert (0.75, 0.25) in [p[0] for p in out]
    assert (0.25, 0.75) in [p[0] for p in out]
    assert (0.75, 0.75) in [p[0] for p in out]


def test_expand_symmetry_counts():
    layer = AnnotationLayer(strokes=(Stroke(points=((0.2, 0.2), (0.3, 0.3)), kind="line"),), symmetry="vertical")
    out = draw.expand_symmetry(layer)
    assert len(out) == 2  # original + 1 vertical mirror


# --------------------------------------------------------------------------- #
# colour resolution
# --------------------------------------------------------------------------- #
def test_resolve_colour_role_and_literal():
    rv = {"--mh-accent": "#FFB81C"}
    assert draw.resolve_colour("--mh-accent", rv) == "#FFB81C"
    assert draw.resolve_colour("#FF0000", rv) == "#FF0000"
    # missing role → fallback, never raises
    assert draw.resolve_colour("--mh-accent", {}).startswith("#")


# --------------------------------------------------------------------------- #
# SVG render
# --------------------------------------------------------------------------- #
def test_render_overlay_svg_shapes():
    layer = AnnotationLayer(
        strokes=(
            Stroke(points=((0.1, 0.1), (0.9, 0.9)), kind="arrow"),
            Stroke(points=((0.2, 0.2), (0.6, 0.6)), kind="rect"),
            Stroke(points=((0.3, 0.3), (0.7, 0.5)), kind="ellipse"),
        )
    )
    svg = draw.render_overlay_svg(layer, width=1000, height=1000)
    assert svg.startswith("<svg")
    assert "<polygon" in svg  # arrowhead
    assert "<rect" in svg
    assert "<ellipse" in svg


def test_render_overlay_empty_is_bare_svg():
    svg = draw.render_overlay_svg(AnnotationLayer(), width=100, height=100)
    assert svg.startswith("<svg") and svg.endswith("</svg>")


# --------------------------------------------------------------------------- #
# Pillow raster render (export)
# --------------------------------------------------------------------------- #
def test_render_onto_image_is_nondestructive():
    from PIL import Image

    base = Image.new("RGBA", (200, 200), (10, 20, 30, 255))
    layer = AnnotationLayer(strokes=(Stroke(points=((0.1, 0.5), (0.9, 0.5)), kind="line", colour="#FF0000", width=0.02),))
    out = draw.render_onto_image(layer, base, {})
    assert out.size == (200, 200)
    # original untouched
    assert base.getpixel((100, 100)) == (10, 20, 30, 255)
    # a red mark now sits on the centre line of the output
    px = out.convert("RGBA").getpixel((100, 100))
    assert px[0] > 150 and px[1] < 100  # reddish


def test_render_onto_image_empty_layer_matches_base():
    from PIL import Image

    base = Image.new("RGBA", (50, 50), (1, 2, 3, 255))
    out = draw.render_onto_image(AnnotationLayer(), base, {})
    assert out.getpixel((25, 25)) == (1, 2, 3, 255)


# --------------------------------------------------------------------------- #
# serialization
# --------------------------------------------------------------------------- #
def test_layer_roundtrip():
    layer = AnnotationLayer(
        strokes=(
            Stroke(points=((0.1, 0.2), (0.3, 0.4)), kind="arrow", colour="--mh-accent", width=0.008),
        ),
        symmetry="quad",
    )
    again = AnnotationLayer.from_dict(layer.to_dict())
    assert again.symmetry == "quad"
    assert len(again.strokes) == 1
    assert again.strokes[0].kind == "arrow"


def test_from_dict_drops_bad_strokes():
    layer = AnnotationLayer.from_dict(
        {"strokes": [{"points": []}, {"points": [[0.1, 0.1], [0.2, 0.2]], "kind": "weird"}], "symmetry": "bad"}
    )
    assert len(layer.strokes) == 1  # empty dropped
    assert layer.strokes[0].kind == "free"  # unknown kind → free
    assert layer.symmetry == "none"  # unknown symmetry → none


def test_deterministic_svg():
    layer = AnnotationLayer(strokes=(Stroke(points=((0.1, 0.1), (0.9, 0.2)), kind="free"),))
    a = draw.render_overlay_svg(layer, width=500, height=500)
    b = draw.render_overlay_svg(layer, width=500, height=500)
    assert a == b
