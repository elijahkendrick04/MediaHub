"""Roadmap 1.10 build 1 — element catalogue + asset integrity."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mediahub.elements import catalog
from mediahub.elements.models import KINDS, SLOTS, Element

_PACK_ROOT = Path(catalog.__file__).resolve().parent
_SVG_DIR = _PACK_ROOT / "assets" / "svg"


def test_catalog_loads_nonempty():
    items = catalog.load_catalog()
    assert items, "bundled catalogue should not be empty"
    assert all(isinstance(e, Element) for e in items)


def test_every_element_has_a_real_svg_file():
    for el in catalog.load_catalog():
        path = _SVG_DIR / el.svg_file
        assert path.is_file(), f"missing SVG for {el.id}: {el.svg_file}"
        text = path.read_text(encoding="utf-8")
        assert "<svg" in text and "</svg>" in text


def test_element_ids_unique_and_kinds_valid():
    items = catalog.load_catalog()
    ids = [e.id for e in items]
    assert len(ids) == len(set(ids)), "element ids must be unique"
    for el in items:
        assert el.kind in KINDS
        for slot in el.slots:
            assert slot in SLOTS


def test_declared_slots_match_svg_tokens():
    """Each element's declared slots must be exactly the placeholders its SVG uses."""
    token_re = re.compile(r"__([A-Z_]+)__")
    for el in catalog.load_catalog():
        svg = (_SVG_DIR / el.svg_file).read_text(encoding="utf-8")
        used = {t for t in token_re.findall(svg) if t != "UID"}
        declared = set(el.slots)
        assert used == declared, (
            f"{el.id}: SVG uses {sorted(used)} but catalog declares {sorted(declared)}"
        )
        # every used slot is a known role slot
        assert used <= set(SLOTS), f"{el.id} uses unknown slots {used - set(SLOTS)}"


def test_swimming_strokes_present():
    ids = {e.id for e in catalog.load_catalog()}
    for stroke in ("freestyle", "butterfly", "backstroke", "breaststroke"):
        assert f"pictogram.{stroke}" in ids, f"missing stroke pictogram: {stroke}"


def test_filter_by_kind_and_query():
    pictos = catalog.filter_elements(kind="pictogram")
    assert pictos and all(e.kind == "pictogram" for e in pictos)

    chips = catalog.filter_elements(kind="chip")
    assert chips and all(e.kind == "chip" for e in chips)

    # substring query over search text (deterministic, no embedding provider)
    hits = catalog.filter_elements(query="trophy")
    assert any(e.id == "pictogram.trophy" for e in hits)

    relay = catalog.filter_elements(query="relay")
    assert any("podium" in e.id for e in relay)


def test_filter_by_tags_and_mood():
    tagged = catalog.filter_elements(tags=["stroke"])
    assert tagged and all("stroke" in e.tags for e in tagged)

    celebratory = catalog.filter_elements(mood="celebratory")
    assert celebratory and all("celebratory" in e.mood for e in celebratory)


def test_sport_filter_includes_general():
    # a swimming filter should also surface general (sport-agnostic) elements
    swim = catalog.filter_elements(sport="swimming")
    sports = {e.sport for e in swim}
    assert "swimming" in sports
    assert "general" in sports  # general elements always available to a swim club


def test_summary_shape():
    s = catalog.summary()
    assert s["count"] == len(catalog.load_catalog())
    assert set(s["by_kind"]) <= set(KINDS)
    assert isinstance(s["tags"], list) and s["tags"]


def test_carries_text_flag_set_for_text_elements():
    by_id = {e.id: e for e in catalog.load_catalog()}
    for tid in ("pictogram.podium", "chip.pb", "chip.stat", "badge.first"):
        assert by_id[tid].carries_text is True


def test_catalog_json_parses_and_matches_loader():
    raw = json.loads((_PACK_ROOT / "catalog.json").read_text(encoding="utf-8"))
    assert raw["elements"]
    assert len(raw["elements"]) == len(catalog.load_catalog())


def test_org_custom_pack_overrides_and_extends(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    catalog.reload_bundled_cache()
    profile = "club-xyz"
    pack_dir = tmp_path / "element_packs" / profile
    (pack_dir / "svg").mkdir(parents=True)
    # a brand-new org element
    (pack_dir / "svg" / "mascot.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
        '<circle cx="5" cy="5" r="4" fill="__ACCENT__"/></svg>',
        encoding="utf-8",
    )
    (pack_dir / "catalog.json").write_text(
        json.dumps(
            {
                "pack": "club-xyz-custom",
                "elements": [
                    {
                        "id": "sticker.mascot",
                        "name": "Club mascot",
                        "kind": "sticker",
                        "sport": "swimming",
                        "svg_file": "mascot.svg",
                        "tags": ["mascot", "club"],
                        "slots": ["ACCENT"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    base = catalog.load_catalog()
    withorg = catalog.load_catalog(profile)
    assert len(withorg) == len(base) + 1
    mascot = catalog.get_element("sticker.mascot", profile)
    assert mascot is not None and mascot.source == "org_custom"
    svg = catalog.load_svg(mascot, profile)
    assert svg is not None and "__ACCENT__" in svg


def test_unknown_element_returns_none():
    assert catalog.get_element("nope.nothing") is None
