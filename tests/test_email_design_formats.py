"""Email & newsletter composer (roadmap 1.17) — build 2: format assembly."""

from __future__ import annotations

import re

import pytest

from mediahub.email_design.formats import (
    build_meet_digest,
    build_monthly_roundup,
    build_newsletter,
    build_season_highlights,
)
from mediahub.email_design.grounding import NewsletterFacts
from mediahub.email_design.render import render_email_html


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def _facts():
    return NewsletterFacts(
        club_name="Otters SC",
        period="June 2026",
        date_start="2026-06-01",
        date_end="2026-06-30",
        recaps=[
            {"title": "Maya — 100 Free PB", "body": "A big swim.", "card_ref": "r/c1", "href": "", "image_url": ""},
            {"title": "Tom — gold", "body": "First gold.", "card_ref": "r/c2", "href": "", "image_url": ""},
        ],
        spotlights=[{"name": "Maya", "body": "2 standout swims.", "card_ref": "r/c1", "n": 2}],
        stats=[{"value": "12", "label": "PBs"}, {"value": "3", "label": "Medals"}],
        fixtures=[{"date": "5 Jul", "name": "County", "venue": "Cardiff"}],
        sponsor={"name": "AquaCo", "href": "https://aquaco.test", "logo_src": ""},
    )


def _all_text(spec):
    bits = []
    for sec in spec.sections:
        for b in sec.blocks:
            bits.append(str(b.props))
    return " ".join(bits)


def test_monthly_roundup_has_all_expected_sections():
    spec = build_monthly_roundup(_facts(), brand_profile_id="club-a", hosted_url="https://club.test/recap")
    assert spec.newsletter_format == "monthly_roundup"
    assert "June 2026 roundup" in spec.title
    assert spec.subject and spec.preheader
    text = _all_text(spec)
    assert "PBs" in text  # stat row
    assert "Maya" in text  # recap card
    assert "County" in text  # fixtures
    assert "AquaCo" in text  # sponsor
    # a CTA accent band exists because a hosted_url was supplied
    assert any(s.background == "accent" for s in spec.sections)
    assert any(s.background == "surface" for s in spec.sections)


def test_meet_digest_includes_spotlights():
    spec = build_meet_digest(_facts())
    text = _all_text(spec)
    assert spec.newsletter_format == "meet_digest"
    assert "Athletes to watch" in text or "Maya" in text


def test_season_highlights_leads_with_numbers():
    spec = build_season_highlights(_facts())
    assert spec.newsletter_format == "season_highlights"
    assert "12" in _all_text(spec)


def test_no_hosted_url_means_no_cta_band():
    spec = build_monthly_roundup(_facts(), hosted_url="")
    assert not any(s.background == "accent" for s in spec.sections)


def test_dispatch_unknown_format_falls_back_to_blank():
    spec = build_newsletter("nonsense", _facts())
    assert spec.newsletter_format == "blank"


def test_fallback_intro_only_states_grounded_numbers():
    # with no AI prose, the deterministic intro must not invent a number
    spec = build_monthly_roundup(_facts(), prose=None)
    intro = ""
    for b in spec.sections[0].blocks:
        if b.kind == "text":
            intro = b.props.get("text", "")
    assert intro
    allowed = _facts().allowed_numbers()
    for tok in re.findall(r"\d+(?:\.\d+)?", intro):
        assert any(abs(float(tok) - a) < 0.6 or int(a) == int(float(tok)) for a in allowed), tok


def test_ai_prose_intro_is_used_when_supplied():
    prose = {"intro": "What a month for the squad.", "subject": "Big June", "preheader": "Read on"}
    spec = build_monthly_roundup(_facts(), prose=prose)
    assert "What a month for the squad." in _all_text(spec)
    assert spec.subject == "Big June"
    assert spec.preheader == "Read on"


def test_empty_facts_still_build_a_valid_newsletter():
    spec = build_monthly_roundup(NewsletterFacts(club_name="Otters", period="June 2026"))
    assert spec.title and spec.sections  # intro at least
    # and it renders without error
    html = render_email_html(spec, profile={"display_name": "Otters"})
    assert html.startswith("<!DOCTYPE html>")


def test_format_assembles_and_renders_end_to_end():
    spec = build_monthly_roundup(_facts(), hosted_url="https://club.test/recap")
    html = render_email_html(spec, profile={"display_name": "Otters SC", "brand_primary": "#0a2540"})
    assert "Maya" in html and "County" in html and "AquaCo" in html
    assert "https://club.test/recap" in html  # CTA button link
