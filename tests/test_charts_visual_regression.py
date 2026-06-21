"""Roadmap 1.11 quality uplift (I4) — visual-regression lock for chart rendering.

Structural-invariant regression (not brittle pixel goldens): for a canonical
fixture per chart kind it pins the guarantees that make a chart trustworthy and
on-brand — the real numbers are drawn, the brand accent is painted, the output is
deterministic and CDN-free, accessibility metadata is present, and the right
primitive is used. A future renderer change that drops a label, loses
determinism, reintroduces a font CDN, or breaks a kind fails here, loudly.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from mediahub.charts.models import Axis, ChartSpec, DataPoint, ReferenceLine, Series
from mediahub.charts.render import render_chart_svg

_NS = "{http://www.w3.org/2000/svg}"
_RV = {
    "--mh-primary": "#A30D2D",
    "--mh-secondary": "#2B6CB0",
    "--mh-surface": "#0B1B2E",
    "--mh-accent": "#F2C14E",
    "--mh-on-primary": "#FFFFFF",
    "--mh-on-surface": "#FFFFFF",
    "--mh-outline": "rgba(255,255,255,0.2)",
}


def _series(*vals):
    return (
        Series(points=tuple(DataPoint(chr(65 + i), v, display=str(v)) for i, v in enumerate(vals))),
    )


# One canonical fixture per kind. (kind, spec, primitive-tag-that-must-appear)
_FIXTURES = {
    "bar": (
        ChartSpec(
            kind="bar",
            title="Bars",
            series=_series(3, 6, 2),
            y_axis=Axis(value_format="integer"),
            source_note="Source: x",
        ),
        "rect",
    ),
    "hbar": (
        ChartSpec(
            kind="hbar",
            title="HBars",
            series=_series(3, 6, 2),
            x_axis=Axis(value_format="integer"),
            source_note="Source: x",
        ),
        "rect",
    ),
    "line": (
        ChartSpec(kind="line", title="Line", series=_series(3, 6, 2, 5), source_note="Source: x"),
        "path",
    ),
    "progression": (
        ChartSpec(
            kind="progression",
            title="Prog",
            series=_series(6300, 6200, 6100),
            y_axis=Axis(value_format="time_cs", lower_is_better=True),
            source_note="Source: x",
        ),
        "path",
    ),
    "pie": (
        ChartSpec(kind="pie", title="Pie", series=_series(11, 9, 8), source_note="Source: x"),
        "path",
    ),
    "donut": (
        ChartSpec(kind="donut", title="Donut", series=_series(11, 9, 8), source_note="Source: x"),
        "path",
    ),
    "scatter": (
        ChartSpec(
            kind="scatter", title="Scatter", series=_series(3, 6, 2), source_note="Source: x"
        ),
        "circle",
    ),
    "split_ladder": (
        ChartSpec(
            kind="split_ladder",
            title="Splits",
            series=_series(2510, 2688),
            y_axis=Axis(value_format="time_cs"),
            source_note="Source: x",
        ),
        "rect",
    ),
    "table": (
        ChartSpec(
            kind="table",
            title="Table",
            columns=("A", "B"),
            rows=(("1", "2"), ("3", "4")),
            source_note="Source: x",
        ),
        "text",
    ),
    "medal_table": (
        ChartSpec(
            kind="medal_table",
            title="Medals",
            columns=("Swimmer", "G", "S", "B"),
            rows=(("X", "2", "1", "0"),),
            source_note="Source: x",
        ),
        "text",
    ),
}


@pytest.mark.parametrize("kind", sorted(_FIXTURES))
def test_kind_is_wellformed_with_a11y_and_primitive(kind):
    spec, primitive = _FIXTURES[kind]
    svg = render_chart_svg(spec, _RV, embed_fonts=False)
    root = ET.fromstring(svg)
    # accessibility metadata, with the title text
    title = root.find(f"{_NS}title")
    assert title is not None and (spec.title in (title.text or ""))
    assert root.find(f"{_NS}desc") is not None
    # the kind's defining primitive is present
    assert root.findall(f".//{_NS}{primitive}"), f"{kind}: no <{primitive}>"


@pytest.mark.parametrize("kind", sorted(_FIXTURES))
def test_kind_is_deterministic_and_cdn_free(kind):
    spec, _ = _FIXTURES[kind]
    a = render_chart_svg(spec, _RV, embed_fonts=True)
    b = render_chart_svg(spec, _RV, embed_fonts=True)
    assert a == b, f"{kind} render is not deterministic"
    low = a.lower()
    assert "googleapis" not in low and "gstatic" not in low and "fonts.google" not in low


@pytest.mark.parametrize("kind", sorted(_FIXTURES))
def test_kind_paints_the_brand_accent(kind):
    spec, _ = _FIXTURES[kind]
    svg = render_chart_svg(spec, _RV, embed_fonts=False)
    assert "#F2C14E" in svg, f"{kind}: brand accent not painted"


# Bars/pies/splits label every datum; tables print every cell; line-family chart
# label selectively (end value only) to avoid clutter — assert that, not every point.
_LABELS_EVERY_DATUM = ("bar", "hbar", "pie", "donut", "split_ladder")
_LABELS_END_ONLY = ("line", "progression", "scatter")


@pytest.mark.parametrize("kind", sorted(_FIXTURES))
def test_data_values_are_rendered(kind):
    """The numbers are sacred — the data point display strings are drawn."""
    spec, _ = _FIXTURES[kind]
    svg = render_chart_svg(spec, _RV, embed_fonts=False)
    if kind in ("table", "medal_table"):
        for row in spec.rows:
            for cell in row:
                assert cell in svg
    elif kind in _LABELS_EVERY_DATUM:
        for p in spec.all_points():
            assert (p.display or "") in svg, f"{kind}: value {p.display!r} not rendered"
    else:  # line-family: at least the end (hero) value is labelled
        last = spec.all_points()[-1]
        assert last.display in svg, f"{kind}: end value {last.display!r} not rendered"


@pytest.mark.parametrize("kind", _LABELS_END_ONLY)
def test_line_family_plots_every_point_as_a_dot(kind):
    """Even when not labelled, every point must be plotted (a circle)."""
    spec, _ = _FIXTURES[kind]
    root = ET.fromstring(render_chart_svg(spec, _RV, embed_fonts=False))
    circles = root.findall(f".//{_NS}circle")
    assert len(circles) >= len(spec.all_points()), f"{kind}: missing plotted points"


def test_emphasis_and_reference_line_survive_render():
    spec = ChartSpec(
        kind="progression",
        title="Prog",
        series=(
            Series(
                points=(
                    DataPoint("Oct", 6300, display="1:03.00"),
                    DataPoint("Jun", 6100, display="1:01.00", emphasis=True),
                )
            ),
        ),
        y_axis=Axis(value_format="time_cs", lower_is_better=True),
        reference_lines=(ReferenceLine(6020, "Club record", display="1:00.20", role="accent"),),
        source_note="Source: x",
    )
    svg = render_chart_svg(spec, _RV, embed_fonts=False)
    ET.fromstring(svg)
    assert "Club record" in svg and "stroke-dasharray" in svg  # benchmark drawn
    assert "1:00.20" in svg  # benchmark value
    # determinism holds with annotations
    assert render_chart_svg(spec, _RV, embed_fonts=False) == svg


def test_format_resize_keeps_invariants():
    """Re-sizing to a social format keeps the chart well-formed and on-brand."""
    from dataclasses import replace

    spec, _ = _FIXTURES["bar"]
    for w, h in ((1080, 1080), (1080, 1350), (1080, 1920), (1920, 1080)):
        svg = render_chart_svg(replace(spec, width=w, height=h), _RV, embed_fonts=False)
        root = ET.fromstring(svg)
        assert root.get("viewBox") == f"0 0 {w} {h}"
        assert "#F2C14E" in svg
