"""Microsite engine (roadmap 1.16) — build 1: the four archetype builders."""

from __future__ import annotations

from mediahub.sites import archetypes as a
from mediahub.sites.grounding import SiteFacts
from mediahub.sites.render import render_site_page


def _rich_facts():
    return SiteFacts(
        club_name="Otters SC",
        tagline="Swansea's friendliest club",
        location="Swansea",
        contact_email="hi@otters.example",
        socials=[{"platform": "Instagram", "url": "https://insta/otters"}],
        sponsors=[{"src": "/sponsor.png", "alt": "Acme"}],
        cards=[{"src": "/card1.png", "caption": "PB!"}],
        links=[{"label": "Latest results", "url": "/results"}],
        stats=[{"value": "42", "label": "Swims"}, {"value": "6", "label": "PBs"}],
        event_name="County Champs",
        event_date="1 July 2026",
        venue="Wales National Pool",
        address="Swansea SA1 8QG",
    )


def _kinds(spec):
    return {b.kind for p in spec.pages for s in p.sections for b in s.blocks}


def test_club_home_uses_data():
    spec = a.build_club_home(_rich_facts())
    assert spec.archetype == "club_home"
    kinds = _kinds(spec)
    assert "hero" in kinds
    assert "kpi_row" in kinds  # stats
    assert "card_grid" in kinds  # latest cards
    assert "sponsor_strip" in kinds
    assert "cta_band" in kinds  # contact
    assert render_site_page(spec)  # renders without error


def test_link_in_bio_is_single_narrow_page():
    spec = a.build_link_in_bio(_rich_facts())
    assert spec.archetype == "link_in_bio"
    assert len(spec.pages) == 1
    assert spec.pages[0].layout == "link_in_bio"
    kinds = _kinds(spec)
    assert "link_list" in kinds and "social_links" in kinds
    html = render_site_page(spec)
    assert '<nav class="site-nav"' not in html  # no nav chrome on a bio page


def test_meet_microsite_has_event_details_and_recap():
    spec = a.build_meet_microsite(_rich_facts())
    kinds = _kinds(spec)
    assert "hero" in kinds
    assert "event_details" in kinds
    assert "card_grid" in kinds  # "results as they land"
    assert "kpi_row" in kinds  # meet in numbers
    assert render_site_page(spec)


def test_event_page_has_countdown_form_and_tickets():
    spec = a.build_event_page(_rich_facts(), rsvp_form_id="form_rsvp", ticket_url="https://store/x")
    kinds = _kinds(spec)
    assert "event_details" in kinds
    assert "widget_embed" in kinds  # countdown
    assert "form_embed" in kinds  # RSVP
    assert "payment_button" in kinds  # tickets
    # the countdown targets the event date
    widgets = [
        b for p in spec.pages for s in p.sections for b in s.blocks if b.kind == "widget_embed"
    ]
    assert widgets[0].props["config"]["target"] == "1 July 2026"
    assert render_site_page(spec)


def test_dispatch_and_empty_facts_are_safe():
    for arch in ("club_home", "link_in_bio", "meet_microsite", "event_page"):
        spec = a.build_site(arch, SiteFacts())  # no data at all
        assert spec.pages  # still a renderable shell
        assert render_site_page(spec)
    # unknown archetype falls back to club_home
    assert a.build_site("???", SiteFacts()).archetype == "club_home"


def test_prose_is_injected_when_supplied():
    spec = a.build_club_home(_rich_facts(), prose={"about": "We are a community club."})
    texts = [
        b.props.get("text", "")
        for p in spec.pages
        for s in p.sections
        for b in s.blocks
        if b.kind == "text"
    ]
    assert any("community club" in t for t in texts)
