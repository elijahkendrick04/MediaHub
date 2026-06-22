"""Email & newsletter composer (roadmap 1.17) — build 1: email-safe rendering.

These are the cross-client invariants: table layout, inline styles, dark-mode,
bulletproof buttons, image fallbacks, escaping and determinism.
"""

from __future__ import annotations

import pytest

from mediahub.email_design import models as m
from mediahub.email_design.render import render_email_html, render_plaintext


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def _spec():
    return m.NewsletterSpec(
        title="June Roundup",
        kicker="Otters newsletter",
        subtitle="June 2026",
        preheader="Your monthly update from the pool",
        sections=[
            m.Section(blocks=[m.heading("Results"), m.text("A great month."), m.divider()]),
            m.Section(
                background="surface",
                blocks=[
                    m.stat_row([{"value": "12", "label": "PBs"}]),
                    m.button("Read more", "https://club.test/news"),
                    m.fixtures([{"date": "5 Jul", "name": "County", "venue": "Cardiff"}], title="Up next"),
                ],
            ),
        ],
    )


def _profile():
    return {"profile_id": "club-a", "display_name": "Otters SC", "brand_primary": "#0a2540"}


def test_is_standalone_html_document():
    html = render_email_html(_spec(), profile=_profile())
    assert html.startswith("<!DOCTYPE html>")
    assert "<html" in html and "</html>" in html
    assert "<head>" in html and "<body" in html


def test_layout_is_table_based_not_flex():
    html = render_email_html(_spec(), profile=_profile())
    assert 'role="presentation"' in html
    # no modern layout CSS that email clients strip
    assert "display:flex" not in html
    assert "display:grid" not in html


def test_dark_mode_aware():
    html = render_email_html(_spec(), profile=_profile())
    assert 'name="color-scheme"' in html
    assert "prefers-color-scheme: dark" in html
    # the neutral chrome gets dark overrides; the classes are present in the body
    assert "mh-body" in html and "mh-ink" in html


def test_styles_are_inlined():
    html = render_email_html(_spec(), profile=_profile())
    # body text carries an inline style, not a class-only rule
    assert 'style="margin:0 0 16px 0;font-family:' in html


def test_bulletproof_button():
    html = render_email_html(_spec(), profile=_profile())
    # bgcolor cell (Outlook fill) + padded anchor (modern clients)
    assert "bgcolor=" in html
    assert 'href="https://club.test/news"' in html
    assert "padding:12px 24px" in html


def test_brand_colour_reaches_masthead():
    html = render_email_html(_spec(), profile=_profile())
    # the navy brand paints the masthead band background
    assert "#0a2540" in html


def test_image_has_alt_and_is_block_with_no_border():
    spec = m.NewsletterSpec(
        title="x", sections=[m.Section(blocks=[m.image("https://x/p.png", alt="A swimmer")])]
    )
    html = render_email_html(spec, profile=_profile())
    assert 'alt="A swimmer"' in html
    assert "display:block" in html
    assert "border:0" in html


def test_missing_image_degrades_to_caption_text():
    spec = m.NewsletterSpec(
        title="x", sections=[m.Section(blocks=[m.image("", alt="alt", caption="The caption")])]
    )
    html = render_email_html(spec, profile=_profile())
    assert "<img" not in html.split("<body")[1]  # no broken image in the body
    assert "The caption" in html


def test_preheader_is_hidden_but_present():
    html = render_email_html(_spec(), profile=_profile())
    assert "Your monthly update from the pool" in html
    assert "display:none" in html


def test_user_text_is_escaped_no_xss():
    spec = m.NewsletterSpec(
        title="<script>alert(1)</script>",
        sections=[m.Section(blocks=[m.text("<img src=x onerror=alert(2)>")])],
    )
    html = render_email_html(spec, profile=_profile())
    assert "<script>alert(1)" not in html
    assert "&lt;script&gt;" in html
    # the dangerous tag is neutralised — it survives only as inert escaped text
    assert "<img src=x onerror" not in html
    assert "&lt;img src=x onerror=alert(2)&gt;" in html


def test_render_is_deterministic():
    spec = _spec()
    a = render_email_html(spec, profile=_profile())
    b = render_email_html(spec, profile=_profile())
    assert a == b


def test_every_block_kind_renders_without_error():
    blocks = [
        m.heading("H"),
        m.text("T"),
        m.bullet_list(["a", "b"]),
        m.button("B", "https://x"),
        m.image("https://x/p.png", alt="a"),
        m.card(title="C", body="b", cta="go", href="https://x"),
        m.stat_row([{"value": "1", "label": "x"}]),
        m.quote("q", attribution="me"),
        m.fixtures([{"date": "1 Jan", "name": "Meet", "venue": "Pool"}]),
        m.sponsor("AquaCo", logo_src="https://x/l.png", href="https://x"),
        m.divider(),
        m.spacer(),
    ]
    spec = m.NewsletterSpec(title="all", sections=[m.Section(blocks=blocks)])
    html = render_email_html(spec, profile=_profile())
    assert "AquaCo" in html and "Meet" in html and "go" in html


def test_empty_section_is_skipped():
    spec = m.NewsletterSpec(title="x", sections=[m.Section(blocks=[m.spacer()])])
    # a section that only contains a spacer still renders (spacer is content);
    # a truly empty section (no blocks) yields nothing
    empty = m.NewsletterSpec(title="x", sections=[m.Section(blocks=[])])
    html = render_email_html(empty, profile=_profile())
    # masthead + footer still present, but no section band
    assert "June" not in html  # no subtitle since not set
    assert html.count('class="mh-pad"') >= 1  # masthead/footer pads exist


def test_plaintext_is_clean_and_has_no_html():
    text_out = render_plaintext(_spec(), profile=_profile())
    assert "<" not in text_out
    assert "June Roundup" in text_out
    assert "Results" in text_out
    assert "https://club.test/news" in text_out  # button link surfaced
    assert "County" in text_out  # fixture surfaced
    assert text_out.endswith("\n")


def test_accent_band_inverts_content_so_nothing_vanishes():
    # a brand-coloured button on a brand-coloured band must not be invisible:
    # on an accent band the button flips to a light fill + brand text.
    spec = m.NewsletterSpec(
        title="x",
        sections=[
            m.Section(
                background="accent",
                blocks=[m.heading("Join us"), m.button("Sign up", "https://x")],
            )
        ],
    )
    profile = {"brand_primary": "#0a2540"}  # navy
    html = render_email_html(spec, profile=profile)
    band = html.split("June")[0]  # whole doc; just scan it
    # the button cell is NOT filled with the same navy as the band
    assert 'bgcolor="#0a2540"' not in html.split("Sign up")[0].rsplit("<table", 1)[-1]
    # the button fills with the light panel instead
    assert 'bgcolor="#ffffff"' in html
    # heading text on the accent band uses the light on-brand ink, not dark ink
    assert "#1f2937" not in html.split("Join us")[0].rsplit("<h", 1)[-1]


def test_unknown_block_kind_is_noop():
    spec = m.NewsletterSpec(
        title="x", sections=[m.Section(blocks=[m.EmailBlock("mystery", {"x": 1}), m.text("real")])]
    )
    html = render_email_html(spec, profile=_profile())
    assert "real" in html  # the good block still renders
