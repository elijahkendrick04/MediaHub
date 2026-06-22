"""Document engine (roadmap 1.15) — build 1: the DocumentSpec data model."""

from __future__ import annotations

from mediahub.documents import models as m
from mediahub.documents.models import Block, DocumentSpec, Section, new_document


def test_block_constructors_produce_expected_kinds():
    assert m.heading("Hi", 1).kind == "heading"
    assert m.heading("Hi", 1).props["level"] == 1
    assert m.text("body").kind == "text"
    assert m.bullet_list(["a", "b"]).props["items"] == ["a", "b"]
    t = m.table(["A", "B"], [[1, 2], [3, 4]])
    assert t.props["columns"] == ["A", "B"]
    assert t.props["rows"] == [["1", "2"], ["3", "4"]]  # coerced to str
    assert m.stat("12", "PBs").props == {"value": "12", "label": "PBs", "sublabel": ""}
    assert m.divider().kind == "divider"
    assert m.spacer("lg").props["size"] == "lg"


def test_heading_level_is_clamped():
    assert m.heading("x", 9).props["level"] == 3
    assert m.heading("x", 0).props["level"] == 1
    assert m.heading("x", "bad").props["level"] == 2


def test_block_gets_stable_id_and_roundtrips():
    b = m.text("hello")
    assert b.block_id.startswith("blk_")
    again = Block.from_dict(b.to_dict())
    assert again.kind == b.kind
    assert again.props == b.props
    assert again.block_id == b.block_id


def test_kpi_row_drops_invalid_entries():
    blk = m.kpi_row([{"value": "5", "label": "Golds"}, {"label": "no value"}, "junk"])
    assert len(blk.props["stats"]) == 1
    assert blk.props["stats"][0]["value"] == "5"


def test_columns_nest_blocks_as_dicts():
    blk = m.columns([m.heading("L")], [m.text("R")])
    assert len(blk.props["columns"]) == 2
    assert blk.props["columns"][0][0]["kind"] == "heading"
    assert blk.props["columns"][1][0]["kind"] == "text"


def test_section_validates_layout_and_background():
    s = Section(blocks=[m.text("x")], layout="bogus", background="rainbow")
    assert s.layout == "flow"
    assert s.background == ""
    ok = Section(layout="cover", background="primary")
    assert ok.layout == "cover"
    assert ok.background == "primary"


def test_section_roundtrips():
    s = Section(
        blocks=[m.heading("A"), m.text("b")], notes="say hi", layout="cover", break_before=True
    )
    again = Section.from_dict(s.to_dict())
    assert again.notes == "say hi"
    assert again.layout == "cover"
    assert again.break_before is True
    assert [b.kind for b in again.blocks] == ["heading", "text"]


def test_new_document_picks_kind_and_geometry_from_format():
    deck = new_document("AGM 2026", "agm_deck")
    assert deck.kind == "deck"
    assert deck.geometry == "slide_16_9"
    assert deck.is_deck is True

    report = new_document("Season Report", "season_report")
    assert report.kind == "document"
    assert report.geometry == "a4"
    assert report.is_deck is False


def test_unknown_format_falls_back_to_blank_document():
    d = new_document("X", "not_a_format")
    assert d.doc_format == "blank"
    assert d.kind == "document"


def test_unknown_geometry_falls_back_by_kind():
    doc = DocumentSpec(title="x", kind="document", geometry="nope")
    assert doc.geometry == "a4"
    deck = DocumentSpec(title="x", kind="deck", geometry="nope")
    assert deck.geometry == "slide_16_9"


def test_document_roundtrips_and_is_additive():
    spec = DocumentSpec(
        title="Club Report",
        subtitle="2025/26",
        kind="document",
        doc_format="season_report",
        geometry="a4",
        brand_profile_id="club-1",
        meta={"club_name": "Otters SC", "date": "June 2026"},
        source_refs=["run:abc"],
        sections=[Section(blocks=[m.heading("Highlights"), m.text("Great season.")])],
    )
    raw = spec.to_dict()
    raw["unknown_future_key"] = {"ignored": True}  # additive: dropped cleanly
    again = DocumentSpec.from_dict(raw)
    assert again.title == "Club Report"
    assert again.doc_format == "season_report"
    assert again.meta["club_name"] == "Otters SC"
    assert again.source_refs == ["run:abc"]
    assert again.sections[0].blocks[0].props["text"] == "Highlights"
    assert not hasattr(again, "unknown_future_key")


def test_page_geometry_lookup():
    spec = new_document("Deck", "agm_deck")
    g = spec.page_geometry
    assert g.kind == "slide"
    assert g.width == "1280px" and g.height == "720px"
