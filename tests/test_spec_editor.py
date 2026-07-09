"""H-5 — the structured spec editor (pure descriptor engine).

apply_structured must edit only the whitelisted text/link props named in the
submitted form, addressed by stable id, and leave everything else — advanced
blocks, ids, seo, publish flags, per-link notes — byte-for-byte untouched, so the
JSON hatch stays authoritative for anything the structured form doesn't expose.
render_structured must escape every id and value.
"""

from __future__ import annotations

from mediahub.documents.models import Block
from mediahub.sites.models import SiteSection, SitePage, SiteSpec
from mediahub.web import spec_editor as se


def _spec() -> SiteSpec:
    return SiteSpec(
        title="Cardiff Swim",
        tagline="Fast fish",
        archetype="club_home",
        pages=[
            SitePage(
                title="Home",
                slug="",
                sections=[
                    SiteSection(
                        background="surface",
                        blocks=[
                            Block("hero", {"headline": "Welcome", "subhead": "the club", "kicker": "est"}),
                            Block("heading", {"text": "Our results", "level": 2}),
                            Block(
                                "link_list",
                                {
                                    "links": [
                                        {"label": "Instagram", "url": "https://ig/x", "note": "main"},
                                        {"label": "Facebook", "url": "https://fb/x"},
                                    ]
                                },
                            ),
                            Block("cta_band", {"text": "Join", "button": {"label": "Sign up", "url": "https://j"}}),
                            # non-whitelisted advanced block — must survive verbatim
                            Block("card_grid", {"cards": [{"src": "a.jpg", "caption": "team"}], "columns": 3}),
                        ],
                    )
                ],
            )
        ],
    )


def _blocks(d):
    return d["pages"][0]["sections"][0]["blocks"]


def _by_kind(d, kind):
    return next(b for b in _blocks(d) if b["kind"] == kind)


def test_edits_only_the_named_prop():
    d = _spec().to_dict()
    hero = _by_kind(d, "hero")
    heading = _by_kind(d, "heading")
    form = {
        f"block__{hero['block_id']}__headline": "New headline",
        f"block__{heading['block_id']}__text": "Results 2026",
    }
    out = se.apply_structured(d, form, "site")
    assert _by_kind(out, "hero")["props"]["headline"] == "New headline"
    # untouched hero props survive
    assert _by_kind(out, "hero")["props"]["subhead"] == "the club"
    assert _by_kind(out, "hero")["props"]["kicker"] == "est"
    assert _by_kind(out, "heading")["props"]["text"] == "Results 2026"
    # heading.level (not whitelisted) is preserved
    assert _by_kind(out, "heading")["props"]["level"] == 2


def test_non_whitelisted_block_preserved_verbatim():
    d = _spec().to_dict()
    before = _by_kind(d, "card_grid")
    # A form that (maliciously or accidentally) names card_grid props is ignored.
    form = {f"block__{before['block_id']}__cards": "hacked"}
    out = se.apply_structured(d, form, "site")
    assert _by_kind(out, "card_grid")["props"] == {"cards": [{"src": "a.jpg", "caption": "team"}], "columns": 3}


def test_nested_prop_dotted_path():
    d = _spec().to_dict()
    cta = _by_kind(d, "cta_band")
    form = {
        f"block__{cta['block_id']}__button.label": "Join now",
        f"block__{cta['block_id']}__button.url": "https://join.new",
        f"block__{cta['block_id']}__text": "Come swim",
    }
    out = se.apply_structured(d, form, "site")
    props = _by_kind(out, "cta_band")["props"]
    assert props["button"] == {"label": "Join now", "url": "https://join.new"}
    assert props["text"] == "Come swim"


def test_link_list_rebuild_preserves_note_and_drops_empty():
    d = _spec().to_dict()
    ll = _by_kind(d, "link_list")
    bid = ll["block_id"]
    form = {
        f"block__{bid}__link__0__label": "Insta",  # edit row 0 (note must survive)
        f"block__{bid}__link__0__url": "https://ig/new",
        f"block__{bid}__link__1__label": "",  # clear row 1 -> dropped
        f"block__{bid}__link__1__url": "",
        f"block__{bid}__link__2__label": "TikTok",  # the blank "add" row -> appended
        f"block__{bid}__link__2__url": "https://tt/x",
    }
    out = se.apply_structured(d, form, "site")
    links = _by_kind(out, "link_list")["props"]["links"]
    assert links == [
        {"label": "Insta", "url": "https://ig/new", "note": "main"},
        {"label": "TikTok", "url": "https://tt/x"},
    ]


def test_spec_and_section_chrome_and_page_title():
    d = _spec().to_dict()
    sid = d["pages"][0]["sections"][0]["section_id"]
    pid = d["pages"][0]["page_id"]
    form = {
        "spec__title": "New Club Name",
        "spec__tagline": "Faster fish",
        f"page__{pid}__title": "Front",
        f"section__{sid}__background": "accent",
    }
    out = se.apply_structured(d, form, "site")
    assert out["title"] == "New Club Name"
    assert out["tagline"] == "Faster fish"
    assert out["pages"][0]["title"] == "Front"
    assert out["pages"][0]["sections"][0]["background"] == "accent"


def test_identity_and_ids_never_change():
    spec = _spec()
    d = spec.to_dict()
    site_id = d["site_id"]
    pid = d["pages"][0]["page_id"]
    bid = _by_kind(d, "hero")["block_id"]
    # A form trying to set site_id, plus a normal edit.
    form = {"spec__site_id": "evil", f"block__{bid}__headline": "ok"}
    out = se.apply_structured(d, form, "site")
    assert out["site_id"] == site_id  # not writable via the structured form
    assert out["pages"][0]["page_id"] == pid  # ids stable
    assert _by_kind(out, "hero")["block_id"] == bid


def test_round_trips_through_from_dict_without_loss():
    d = _spec().to_dict()
    hero = _by_kind(d, "hero")
    out = se.apply_structured(d, {f"block__{hero['block_id']}__headline": "Hi"}, "site")
    # from_dict must accept the mutated dict and preserve the advanced block.
    spec2 = SiteSpec.from_dict(out)
    kinds = [b.kind for b in spec2.pages[0].sections[0].blocks]
    assert kinds == ["hero", "heading", "link_list", "cta_band", "card_grid"]
    assert spec2.pages[0].sections[0].blocks[0].props["headline"] == "Hi"
    assert spec2.title == "Cardiff Swim"


def test_render_escapes_values_and_ids():
    spec = _spec()
    # inject a hostile value into a text prop
    spec.pages[0].sections[0].blocks[1].props["text"] = '<script>alert(1)</script>'
    html = se.render_structured(spec.to_dict(), "site")
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html
    # the form input names use the stable addressing scheme
    hid = spec.pages[0].sections[0].blocks[0].block_id
    assert f"block__{hid}__headline" in html


def test_render_shows_only_whitelisted_kinds():
    html = se.render_structured(_spec().to_dict(), "site")
    # whitelisted kinds appear as fieldset legends; card_grid does not.
    assert ">hero<" in html
    assert ">cta band<" in html
    assert "card grid" not in html


def test_has_structured_editor_flags_supported_surfaces():
    assert se.has_structured_editor("site") is True
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
