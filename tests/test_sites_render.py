"""Microsite engine (roadmap 1.16) — build 1: the static HTML renderer."""

from __future__ import annotations

from mediahub.documents.models import heading, kpi_row, text
from mediahub.sites import models as m
from mediahub.sites.render import render_page_html, render_site_page


def _spec(**kw):
    return m.SiteSpec(
        title="Otters SC",
        tagline="Swansea's friendliest club",
        meta={"club_name": "Otters SC"},
        pages=[
            m.SitePage(
                title="Home",
                slug="",
                sections=[m.SiteSection(blocks=kw.get("blocks", [m.hero("Welcome")]))],
            )
        ],
    )


def test_renders_full_document():
    html = render_site_page(_spec())
    assert html.startswith("<!DOCTYPE html>")
    assert "<title>Otters SC</title>" in html
    assert "friendliest club" in html  # tagline → meta description (apostrophe escaped)
    assert "site-hero" in html and "Welcome" in html
    assert "Made with MediaHub" in html  # footer


def test_escapes_user_text_xss():
    blocks = [m.hero("<script>alert(1)</script>"), text("<img src=x onerror=alert(2)>")]
    html = render_page_html(_spec(blocks=blocks), _spec(blocks=blocks).pages[0])
    # dangerous tags are neutralised into inert escaped text
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;" in html
    assert "<img src=x onerror=alert(2)>" not in html  # no live tag
    assert "&lt;img" in html  # rendered as escaped text instead


def test_self_contained_no_cdn():
    html = render_site_page(_spec())
    assert "fonts.googleapis.com" not in html
    assert "gstatic" not in html
    # only inline <style>, no external stylesheet link
    assert "<link rel='stylesheet'" not in html


def test_nav_for_multipage_and_none_for_link_in_bio():
    multi = m.SiteSpec(
        title="Club",
        pages=[
            m.SitePage(title="Home", slug=""),
            m.SitePage(title="Results", slug="results"),
        ],
    )
    html = render_page_html(multi, multi.home_page)
    assert '<nav class="site-nav"' in html
    assert ">Results<" in html
    # link-in-bio page → no nav chrome (the CSS class still appears in <style>)
    bio = m.SiteSpec(
        title="Bio",
        pages=[m.SitePage(title="Bio", slug="", layout="link_in_bio")],
    )
    assert '<nav class="site-nav"' not in render_page_html(bio, bio.home_page)


def test_site_blocks_render():
    blocks = [
        m.link_button("Join us", "/join", style="primary"),
        m.link_list([{"label": "Results", "url": "/r"}]),
        m.social_links([{"platform": "Instagram", "url": "https://insta/x"}]),
        m.card_grid([{"src": "/a.png", "caption": "PB!"}]),
        m.sponsor_strip([{"src": "/logo.png", "alt": "Acme"}], title="Sponsors"),
        m.event_details(name="Gala", date="1 July", venue="LC Pool", address="Swansea SA1"),
        m.payment_button("Buy tickets", "https://store/x"),
    ]
    page = m.SitePage(title="Home", slug="", sections=[m.SiteSection(blocks=blocks)])
    html = render_page_html(m.SiteSpec(title="S", pages=[page]), page)
    assert "bio-link primary" in html and "Join us" in html
    assert "social-row" in html and "Instagram" in html
    assert "card-grid" in html and "PB!" in html
    assert "sponsor-strip" in html and "Sponsors" in html
    assert "event-card" in html and "LC Pool" in html
    assert "Open in maps" in html  # privacy-respecting address link, not an iframe
    assert "Buy tickets" in html


def test_reused_document_blocks_render():
    blocks = [heading("Numbers"), kpi_row([{"value": "42", "label": "Swims"}]), text("Hi")]
    page = m.SitePage(title="Home", slug="", sections=[m.SiteSection(blocks=blocks)])
    html = render_page_html(m.SiteSpec(title="S", pages=[page]), page)
    assert "doc-kpis" in html and "42" in html
    assert "Numbers" in html


def test_qr_block_renders_svg():
    # sites.qr (build 3) is available → the block renders a real brand QR SVG.
    blocks = [m.qr_block("https://club.example/site/abc", caption="Scan me")]
    page = m.SitePage(title="Home", slug="", sections=[m.SiteSection(blocks=blocks)])
    html = render_page_html(m.SiteSpec(title="S", pages=[page]), page)
    assert "qr-block" in html
    assert "<svg" in html
    assert "Scan me" in html


def test_qr_block_degrades_to_link_on_error(monkeypatch):
    # the defensive branch: if QR rendering fails, fall back to an honest link.
    import mediahub.sites.qr as qr

    def _boom(*a, **k):
        raise RuntimeError("qr down")

    monkeypatch.setattr(qr, "qr_svg", _boom)
    blocks = [m.qr_block("https://club.example/site/abc", caption="Scan me")]
    page = m.SitePage(title="Home", slug="", sections=[m.SiteSection(blocks=blocks)])
    html = render_page_html(m.SiteSpec(title="S", pages=[page]), page)
    assert "https://club.example/site/abc" in html  # honest link, never a broken image


def test_form_and_widget_use_injected_resolvers():
    blocks = [m.form_embed("f1", title="RSVP"), m.widget_embed(widget_type="countdown")]
    page = m.SitePage(title="Home", slug="", sections=[m.SiteSection(blocks=blocks)])
    spec = m.SiteSpec(title="S", pages=[page])

    # no resolver → the form shows a labelled placeholder (it needs a real submit
    # URL); the widget falls back to the built-in catalogue renderer and renders live.
    plain = render_page_html(spec, page)
    assert "site-form-placeholder" in plain
    assert "mhw-countdown" in plain

    # resolver wired → live HTML, and the CSP nonce is threaded through
    html = render_page_html(
        spec,
        page,
        nonce="N0NCE",
        render_form=lambda fid, nonce: f"<form data-id='{fid}' data-n='{nonce}'></form>",
        render_widget=lambda props, nonce: (
            f"<div class='w' data-n='{nonce}'>{props['widget_type']}</div>"
        ),
    )
    assert "<form data-id='f1' data-n='N0NCE'>" in html
    assert "data-n='N0NCE'>countdown</div>" in html


def test_asset_and_page_url_callbacks():
    blocks = [m.card_grid([{"src": "card.png"}])]
    pages = [m.SitePage(title="Home", slug=""), m.SitePage(title="Info", slug="info")]
    pages[0] = m.SitePage(title="Home", slug="", sections=[m.SiteSection(blocks=blocks)])
    spec = m.SiteSpec(title="S", pages=pages)
    html = render_page_html(
        spec,
        spec.home_page,
        asset_url=lambda src: f"https://cdn/{src}",
        page_url=lambda slug: f"/site/TKN/{slug}" if slug else "/site/TKN/",
    )
    assert "https://cdn/card.png" in html
    assert "/site/TKN/info" in html  # nav link built via page_url


def test_render_is_deterministic():
    rv = {"--mh-primary": "#0A2540", "--mh-accent": "#FFB81C"}
    a = render_site_page(_spec(), role_vars=rv)
    b = render_site_page(_spec(blocks=[m.hero("Welcome")]), role_vars=rv)
    # same content + roles → byte-identical (site_id differs only in store, not render)
    assert a == b
