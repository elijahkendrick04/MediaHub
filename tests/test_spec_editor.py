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
    assert se.has_structured_editor("nope") is False
