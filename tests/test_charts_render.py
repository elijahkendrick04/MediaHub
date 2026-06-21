"""Roadmap 1.11 build 1 — deterministic, brand-styled, CDN-free chart SVG."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from mediahub.charts.models import Axis, ChartSpec, DataPoint, Series
from mediahub.charts.render import render_chart_svg

# A representative spec per kind (series-based + table-based).
_SERIES = (
    Series(
        name="PBs",
        points=(
            DataPoint("Smith, J", 3, source_ref="swim:1"),
            DataPoint("Okafor, A", 2),
            DataPoint("Lee, M", 4),
        ),
    ),
)
_KINDS_SERIES = ("bar", "hbar", "line", "progression", "pie", "donut", "scatter", "split_ladder")


def _spec(kind: str) -> ChartSpec:
    if kind in ("table", "medal_table"):
        return ChartSpec(
            kind=kind,
            title=kind,
            columns=("Swimmer", "G", "S", "B"),
            rows=(("Smith, J", "2", "1", "0"), ("Lee, M", "1", "0", "1")),
        )
    return ChartSpec(kind=kind, title=kind.title(), subtitle="County Champs", series=_SERIES)


@pytest.mark.parametrize("kind", _KINDS_SERIES + ("table", "medal_table"))
def test_every_kind_is_wellformed_svg(kind):
    svg = render_chart_svg(_spec(kind), embed_fonts=False)
    assert svg.startswith("<svg")
    # Parses as XML → no malformed attributes / unescaped text.
    root = ET.fromstring(svg)
    assert root.tag.endswith("svg")


@pytest.mark.parametrize("kind", _KINDS_SERIES + ("table", "medal_table"))
def test_every_kind_is_byte_identical_on_repeat(kind):
    s = _spec(kind)
    a = render_chart_svg(s, embed_fonts=True)
    b = render_chart_svg(s, embed_fonts=True)
    assert a == b, f"{kind} render is not deterministic"


def test_viewbox_matches_requested_size():
    svg = render_chart_svg(ChartSpec(kind="bar", width=1200, height=900, series=_SERIES), embed_fonts=False)
    assert 'width="1200"' in svg and 'height="900"' in svg
    assert 'viewBox="0 0 1200 900"' in svg


def test_no_font_cdn_anywhere():
    """The self-hosted-fonts rule: a chart never references a font CDN."""
    for embed in (True, False):
        svg = render_chart_svg(_spec("bar"), embed_fonts=embed)
        low = svg.lower()
        assert "googleapis" not in low
        assert "gstatic" not in low
        assert "fonts.google" not in low


def test_embed_fonts_inlines_woff2_data_uri():
    svg = render_chart_svg(_spec("bar"), embed_fonts=True)
    assert "data:font/woff2;base64," in svg
    assert "@font-face" in svg


def test_no_embed_does_not_inline_but_still_declares_faces():
    svg = render_chart_svg(_spec("bar"), embed_fonts=False)
    assert "data:font/woff2;base64," not in svg
    assert "@font-face" in svg


def test_brand_accent_colour_is_painted():
    role_vars = {
        "--mh-primary": "#A30D2D",
        "--mh-secondary": "#1B3D5C",
        "--mh-surface": "#0B1B2B",
        "--mh-accent": "#FFB81C",
        "--mh-on-primary": "#FFFFFF",
        "--mh-on-surface": "#FFFFFF",
        "--mh-outline": "rgba(255,255,255,0.2)",
    }
    svg = render_chart_svg(_spec("bar"), role_vars, embed_fonts=False)
    assert "#FFB81C" in svg  # accent appears on the bars / title rule
    assert "#0B1B2B" in svg  # surface is the ground


def test_exact_numbers_are_rendered_not_invented():
    spec = ChartSpec(
        kind="bar",
        series=(Series(points=(DataPoint("A", 3, display="3"), DataPoint("B", 4, display="4"))),),
        y_axis=Axis(value_format="integer"),
    )
    svg = render_chart_svg(spec, embed_fonts=False)
    # The exact data labels are present.
    assert ">3<" in svg and ">4<" in svg


def test_labels_are_xss_escaped():
    spec = ChartSpec(
        kind="bar",
        title="<script>alert(1)</script>",
        series=(Series(points=(DataPoint('Bobby "><b>', 5),)),),
    )
    svg = render_chart_svg(spec, embed_fonts=False)
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg
    # still well-formed
    ET.fromstring(svg)


def test_empty_spec_shows_honest_empty_state():
    svg = render_chart_svg(ChartSpec(kind="bar", title="Nothing yet"), embed_fonts=False)
    assert "No data to chart yet" in svg
    ET.fromstring(svg)


def test_lower_is_better_inverts_progression_axis():
    """For a times line, a faster (smaller) time must sit higher (smaller y)."""
    from mediahub.charts.render import _v2y

    # smaller value, lower_is_better → nearer the top (smaller y) than a big value
    y_fast = _v2y(6000, 6000, 7000, top=0.0, bottom=100.0, invert=True)
    y_slow = _v2y(7000, 6000, 7000, top=0.0, bottom=100.0, invert=True)
    assert y_fast < y_slow


def test_nice_ticks_are_deterministic_and_spanning():
    from mediahub.charts.render import _nice_ticks

    t1 = _nice_ticks(0, 47)
    t2 = _nice_ticks(0, 47)
    assert t1 == t2
    assert t1[0] <= 0 <= t1[-1]
    assert all(b > a for a, b in zip(t1, t1[1:]))  # strictly increasing


def test_medal_table_uses_medal_tints():
    from mediahub.charts.palette import MEDAL_COLOURS

    svg = render_chart_svg(_spec("medal_table"), embed_fonts=False)
    # at least one medal tint shows up for the G/S/B columns
    assert any(hexv in svg for hexv in MEDAL_COLOURS.values())
