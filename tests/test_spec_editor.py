"""H-5 — the structured spec editor (pure descriptor engine).

apply_structured must edit only the whitelisted text props named in the submitted
form, addressed by stable id, and leave everything else — advanced blocks, ids,
publish flags — byte-for-byte untouched, so the JSON hatch stays authoritative for
anything the structured form doesn't expose. render_structured must escape every id
and value.
"""

from __future__ import annotations

from mediahub.web import spec_editor as se


def test_has_structured_editor_flags_supported_surfaces():
    assert se.has_structured_editor("newsletter") is True
    assert se.has_structured_editor("document") is True
    assert se.has_structured_editor("nope") is False


# --- newsletter surface (top-level sections, no page layer) ------------------


def _nl():
    from mediahub.email_design.models import EmailBlock, NewsletterSpec, Section

    return NewsletterSpec(
        title="March news",
        subject="",
        sections=[
            Section(
                background="",
                blocks=[
                    EmailBlock("heading", {"text": "Results"}),
                    EmailBlock("button", {"label": "Read", "href": "https://x", "align": "center"}),
                    EmailBlock("card", {"title": "Win", "body": "Great meet", "src": "a.jpg"}),
                    EmailBlock("image", {"src": "b.jpg", "alt": "x"}),  # non-whitelisted
                ],
            )
        ],
    )


def _nl_block(d, kind):
    return next(b for b in d["sections"][0]["blocks"] if b["kind"] == kind)


def test_newsletter_edits_text_and_link_and_preserves_image():
    d = _nl().to_dict()
    card = _nl_block(d, "card")
    btn = _nl_block(d, "button")
    form = {
        "spec__subject": "Big wins in March",
        f"block__{card['block_id']}__title": "Huge win",
        f"block__{card['block_id']}__body": "Records tumbled",
        f"block__{btn['block_id']}__href": "https://new",
    }
    out = se.apply_structured(d, form, "newsletter")
    assert out["subject"] == "Big wins in March"
    assert _nl_block(out, "card")["props"]["title"] == "Huge win"
    assert _nl_block(out, "card")["props"]["body"] == "Records tumbled"
    # the card image (src) is not whitelisted → preserved
    assert _nl_block(out, "card")["props"]["src"] == "a.jpg"
    assert _nl_block(out, "button")["props"]["href"] == "https://new"
    # button align (not whitelisted) survives
    assert _nl_block(out, "button")["props"]["align"] == "center"
    # the image block is untouched
    assert _nl_block(out, "image")["props"] == {"src": "b.jpg", "alt": "x"}


def test_newsletter_round_trips_through_from_dict():
    from mediahub.email_design.models import NewsletterSpec

    d = _nl().to_dict()
    h = _nl_block(d, "heading")
    out = se.apply_structured(d, {f"block__{h['block_id']}__text": "Season review"}, "newsletter")
    spec2 = NewsletterSpec.from_dict(out)
    assert [b.kind for b in spec2.sections[0].blocks] == ["heading", "button", "card", "image"]
    assert spec2.sections[0].blocks[0].props["text"] == "Season review"


# --- document surface (top-level sections, notes/layout chrome) --------------


def _doc():
    from mediahub.documents.models import Block, DocumentSpec, Section, heading, quote, text

    return DocumentSpec(
        title="AGM report",
        sections=[
            Section(
                notes="",
                layout="flow",
                blocks=[
                    heading("Overview"),
                    text("Body"),
                    quote("Nice season", attribution="Coach"),
                    Block("table", {"columns": ["A"], "rows": [["1"]]}),  # non-whitelisted
                ],
            )
        ],
    )


def _doc_block(d, kind):
    return next(b for b in d["sections"][0]["blocks"] if b["kind"] == kind)


def test_document_edits_text_and_section_notes_preserves_table():
    d = _doc().to_dict()
    sid = d["sections"][0]["section_id"]
    heading_b = _doc_block(d, "heading")
    form = {
        "spec__title": "Annual report 2026",
        f"section__{sid}__notes": "say hello",
        f"block__{heading_b['block_id']}__text": "Year in review",
    }
    out = se.apply_structured(d, form, "document")
    assert out["title"] == "Annual report 2026"
    assert out["sections"][0]["notes"] == "say hello"
    assert _doc_block(out, "heading")["props"]["text"] == "Year in review"
    # the table (non-whitelisted) is byte-for-byte intact
    assert _doc_block(out, "table")["props"] == {"columns": ["A"], "rows": [["1"]]}


def test_document_out_of_range_enum_clamped_by_from_dict():
    from mediahub.documents.models import DocumentSpec

    d = _doc().to_dict()
    sid = d["sections"][0]["section_id"]
    out = se.apply_structured(d, {f"section__{sid}__layout": "bogus"}, "document")
    # apply_structured writes the raw value; from_dict clamps it to the default.
    spec2 = DocumentSpec.from_dict(out)
    assert spec2.sections[0].layout == "flow"


def test_document_identity_and_ids_never_change():
    d = _doc().to_dict()
    before_keys = set(d.keys())
    sid = d["sections"][0]["section_id"]
    heading_b = _doc_block(d, "heading")
    bid = heading_b["block_id"]
    # A form trying to set a non-chrome top-level field, plus a normal edit.
    form = {"spec__doc_id": "evil", f"block__{bid}__text": "ok"}
    out = se.apply_structured(d, form, "document")
    # a field not in SPEC_CHROME is never written (no stray/forged identity key)
    assert set(out.keys()) == before_keys
    assert out.get("doc_id", "") != "evil"
    # ids are stable, and the whitelisted edit still applies
    assert out["sections"][0]["section_id"] == sid
    assert _doc_block(out, "heading")["block_id"] == bid
    assert _doc_block(out, "heading")["props"]["text"] == "ok"


def test_document_render_escapes_values_and_ids():
    d = _doc().to_dict()
    hb = _doc_block(d, "heading")
    # inject a hostile value into a whitelisted text prop
    hb["props"]["text"] = "<script>alert(1)</script>"
    html = se.render_structured(d, "document")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    # the form input names use the stable addressing scheme
    assert f"block__{hb['block_id']}__text" in html


def test_document_render_shows_only_whitelisted_kinds():
    html = se.render_structured(_doc().to_dict(), "document")
    # whitelisted kinds appear as fieldset legends; the table block does not.
    assert ">heading<" in html
    assert ">quote<" in html
    assert "table" not in html
