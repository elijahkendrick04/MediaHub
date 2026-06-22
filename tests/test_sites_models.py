"""Microsite engine (roadmap 1.16) — build 1: the typed data model."""

from __future__ import annotations

from mediahub.documents.models import Block
from mediahub.sites import models as m


def test_slugify():
    assert m.slugify("Meet Day 1!") == "meet-day-1"
    assert m.slugify("  ") == "page"
    assert m.slugify("", default="home") == "home"
    assert m.slugify("Ñandú & Co") == "and-co"  # non-ascii dropped, not transliterated


def test_site_block_constructors_are_blocks():
    assert isinstance(m.hero("Hi", subhead="x"), Block)
    assert m.hero("Hi", cta_label="Join", cta_url="/join").props["cta"] == {
        "label": "Join",
        "url": "/join",
    }
    # incomplete CTA is dropped
    assert "cta" not in m.hero("Hi", cta_label="Join").props
    assert m.link_button("L", "u", style="weird").props["style"] == "primary"
    assert m.card_grid([{"src": "a.png"}], columns=9).props["columns"] == 3
    # malformed entries are filtered out
    assert m.link_list([{"label": "x"}, {"label": "y", "url": "u"}]).props["links"] == [
        {"label": "y", "url": "u", "note": ""}
    ]


def test_section_roundtrip_and_defaults():
    sec = m.SiteSection(blocks=[m.hero("T")], layout="bogus", background="nope")
    assert sec.layout == "flow"  # unknown → flow
    assert sec.background == ""  # unknown → ""
    again = m.SiteSection.from_dict(sec.to_dict())
    assert again.section_id == sec.section_id
    assert again.blocks[0].kind == "hero"


def test_page_slug_home_and_seo_roundtrip():
    p = m.SitePage(title="About Us", slug="")
    assert p.slug == "about-us"  # derived from title
    home = m.SitePage(title="Home", slug="index")
    assert home.is_home
    p2 = m.SitePage.from_dict({"title": "Join", "seo": {"description": "d", "noindex": True}})
    assert p2.seo.description == "d" and p2.seo.noindex is True


def test_sitespec_roundtrip_and_helpers():
    spec = m.SiteSpec(
        title="Otters",
        archetype="club_home",
        pages=[
            m.SitePage(title="Home", slug=""),
            m.SitePage(title="Results", slug="results"),
            m.SitePage(title="Secret", slug="secret", show_in_nav=False),
        ],
    )
    assert spec.home_page.title == "Home"
    assert spec.page_by_slug("results").title == "Results"
    assert spec.page_by_slug("") is spec.home_page
    assert spec.page_by_slug("missing") is None
    nav = spec.nav_pages()
    assert [p.title for p in nav] == ["Home", "Results"]  # Secret hidden, Home first
    again = m.SiteSpec.from_dict(spec.to_dict())
    assert again.site_id == spec.site_id
    assert len(again.pages) == 3


def test_new_site_defaults_by_archetype():
    s = m.new_site("Bio", "link_in_bio")
    assert s.archetype == "link_in_bio" and s.theme == "dark"
    blank = m.new_site("X", "nonsense")
    assert blank.archetype == "blank"


def test_from_dict_is_forward_compatible():
    # extra/unknown keys are ignored; missing optionals default
    spec = m.SiteSpec.from_dict({"title": "T", "futuristic_field": 1, "pages": [{}]})
    assert spec.title == "T"
    assert len(spec.pages) == 1
    assert spec.theme == "dark"
