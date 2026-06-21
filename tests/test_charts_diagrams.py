"""Roadmap 1.11 build 4 — data-driven diagram formats (deterministic, brand-styled)."""

from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from mediahub.charts.diagrams import (
    DIAGRAM_KINDS,
    DiagramSpec,
    athlete_journey,
    org_chart_from_roster,
    render_diagram_svg,
    season_timeline_from_meets,
    training_flow,
)

_RV = {
    "--mh-primary": "#A30D2D",
    "--mh-secondary": "#2B6CB0",
    "--mh-surface": "#0B1B2E",
    "--mh-accent": "#F2C14E",
    "--mh-on-primary": "#FFFFFF",
    "--mh-on-surface": "#FFFFFF",
    "--mh-outline": "rgba(255,255,255,0.2)",
}


def _org():
    return org_chart_from_roster(
        [
            {"name": "Sarah Hall", "role": "Chair"},
            {"name": "Tom Reed", "role": "Secretary", "reports_to": "Sarah Hall"},
            {"name": "Priya Shah", "role": "Treasurer", "reports_to": "Sarah Hall"},
            {"name": "Welfare Officer", "role": "Safeguarding", "reports_to": "Tom Reed"},
        ],
        title="Committee",
    )


def test_org_chart_resolves_parents_by_name():
    spec = _org()
    assert spec is not None and spec.kind == "org_chart"
    by_id = {n.id: n for n in spec.nodes}
    chair = [n for n in spec.nodes if n.label == "Sarah Hall"][0]
    tom = [n for n in spec.nodes if n.label == "Tom Reed"][0]
    welfare = [n for n in spec.nodes if n.label == "Welfare Officer"][0]
    assert chair.parent == ""  # root
    assert by_id[tom.parent].label == "Sarah Hall"
    assert by_id[welfare.parent].label == "Tom Reed"


def test_timeline_sorts_by_date():
    spec = season_timeline_from_meets(
        [
            {"date": "2026-02-15", "name": "County"},
            {"date": "2025-10-12", "name": "Autumn"},
            {"date": "2026-06-14", "name": "Summer"},
        ]
    )
    labels = [n.label for n in spec.nodes]
    assert labels == ["Autumn", "County", "Summer"]
    # dates are prettified into the sublabel
    assert "Oct" in spec.nodes[0].sublabel


def test_builders_return_none_when_empty():
    assert org_chart_from_roster([]) is None
    assert season_timeline_from_meets([]) is None
    assert athlete_journey("Jess", []) is None
    assert training_flow([]) is None
    # rows with no usable label are skipped
    assert org_chart_from_roster([{"role": "x"}]) is None


def test_training_flow_chains_edges():
    spec = training_flow([{"label": "Warm-up"}, {"label": "Main"}, {"label": "Cool"}])
    assert spec.kind == "flow"
    assert spec.edges == (("s0", "s1"), ("s1", "s2"))


@pytest.mark.parametrize("kind", DIAGRAM_KINDS)
def test_every_kind_renders_wellformed_and_deterministic(kind):
    builders = {
        "org_chart": _org(),
        "timeline": season_timeline_from_meets([{"date": "2025-10-12", "name": "A"}, {"date": "2026-02-01", "name": "B"}]),
        "journey": athlete_journey("Jess", [{"label": "First gala", "detail": "2019"}, {"label": "PB", "detail": "2026"}]),
        "flow": training_flow([{"label": "Warm-up"}, {"label": "Main"}]),
    }
    spec = builders[kind]
    a = render_diagram_svg(spec, _RV, embed_fonts=True)
    b = render_diagram_svg(spec, _RV, embed_fonts=True)
    assert a == b  # byte-identical
    ET.fromstring(a)  # well-formed
    assert "googleapis" not in a.lower() and "gstatic" not in a.lower()
    assert "#F2C14E" in a  # brand accent painted


def test_empty_diagram_shows_honest_state():
    svg = render_diagram_svg(DiagramSpec(kind="org_chart", title="Empty"), _RV, embed_fonts=False)
    assert "Nothing to diagram yet" in svg
    ET.fromstring(svg)


def test_spec_round_trips_through_json():
    spec = _org()
    again = DiagramSpec.from_dict(spec.to_dict())
    assert again is not None
    assert again.to_dict() == spec.to_dict()


def test_from_dict_rejects_bad_kind_and_tolerates_unknown_keys():
    assert DiagramSpec.from_dict({"kind": "hypercube"}) is None
    assert DiagramSpec.from_dict({}) is None
    spec = DiagramSpec.from_dict({"kind": "flow", "nodes": [{"id": "a", "label": "A"}], "surprise": 1})
    assert spec is not None and len(spec.nodes) == 1


def test_layout_tree_survives_a_malformed_cycle():
    # A → B → A should not infinitely recurse; the renderer must still produce SVG.
    from mediahub.charts.diagrams import DiagramNode

    spec = DiagramSpec(
        kind="org_chart",
        nodes=(DiagramNode("a", "A", parent="b"), DiagramNode("b", "B", parent="a")),
    )
    svg = render_diagram_svg(spec, _RV, embed_fonts=False)
    ET.fromstring(svg)  # did not hang / crash
