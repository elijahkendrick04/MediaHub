"""Email & newsletter composer (roadmap 1.17) — build 1: the data model."""

from __future__ import annotations

from mediahub.email_design import models as m


def test_block_constructors_validate_and_round_trip():
    blocks = [
        m.heading("Results", level=2),
        m.text("Hello", align="center"),
        m.bullet_list(["a", "b"], ordered=True),
        m.button("Read more", "https://x.test", align="center"),
        m.image("https://x.test/p.png", alt="pic", caption="cap", width=300),
        m.card(title="PB!", body="Great swim", src="card:run/cd", cta="See", href="https://x"),
        m.stat_row([{"value": "12", "label": "PBs"}, {"value": "3", "label": "Medals"}]),
        m.quote("Proud day", attribution="Coach"),
        m.fixtures([{"date": "5 Jul", "name": "County", "venue": "Cardiff"}], title="Up next"),
        m.sponsor("AquaCo", logo_src="https://x/l.png", href="https://x"),
        m.divider(),
        m.spacer("lg"),
    ]
    for b in blocks:
        assert b.kind in m.EMAIL_BLOCK_KINDS
        assert b.block_id  # auto id
        round_tripped = m.EmailBlock.from_dict(b.to_dict())
        assert round_tripped.kind == b.kind
        assert round_tripped.props == b.props
        assert round_tripped.block_id == b.block_id


def test_constructors_clamp_and_default_bad_input():
    assert m.heading("x", level=9).props["level"] == 3
    assert m.heading("x", level=0).props["level"] == 1
    assert m.text("x", align="diagonal").props["align"] == "left"
    assert m.spacer("huge").props["size"] == "md"
    # stat_row drops entries with no value; fixtures drops empty rows
    assert m.stat_row([{"label": "x"}]).props["stats"] == []
    assert m.fixtures([{"venue": "only"}]).props["items"] == []


def test_section_round_trip_and_background_validation():
    sec = m.Section(blocks=[m.text("hi")], background="accent")
    assert sec.section_id
    again = m.Section.from_dict(sec.to_dict())
    assert again.background == "accent"
    assert len(again.blocks) == 1 and again.blocks[0].props["text"] == "hi"
    # an invalid band falls back to plain
    assert m.Section(background="rainbow").background == ""


def test_newsletter_spec_round_trip():
    spec = m.NewsletterSpec(
        title="June Roundup",
        kicker="Otters newsletter",
        subtitle="June 2026",
        preheader="Your monthly update",
        subject="Otters — June update",
        newsletter_format="monthly_roundup",
        brand_profile_id="club-a",
        sections=[m.Section(blocks=[m.heading("Results"), m.text("body")])],
        meta={"club_name": "Otters SC", "period": "June 2026"},
        source_refs=["run:abc"],
    )
    assert spec.newsletter_id.startswith("nl_")
    data = spec.to_dict()
    again = m.NewsletterSpec.from_dict(data)
    assert again.title == "June Roundup"
    assert again.newsletter_format == "monthly_roundup"
    assert again.meta["club_name"] == "Otters SC"
    assert again.source_refs == ["run:abc"]
    assert len(again.sections[0].blocks) == 2


def test_unknown_format_falls_back_to_default():
    spec = m.NewsletterSpec(title="x", newsletter_format="not-a-format")
    assert spec.newsletter_format == m.DEFAULT_FORMAT


def test_email_format_width_clamped():
    assert m.EmailFormat(width=99).width == 320
    assert m.EmailFormat(width=9999).width == 700
    assert m.format_for("monthly_roundup").name == "monthly_roundup"
    assert m.format_for("garbage").name == m.DEFAULT_FORMAT
    # spec exposes its email format
    assert m.NewsletterSpec(title="x").email_format.width == 600


def test_new_newsletter_shell():
    spec = m.new_newsletter("Hi", "meet_digest", brand_profile_id="c", kicker="K")
    assert spec.title == "Hi" and spec.newsletter_format == "meet_digest"
    assert spec.kicker == "K" and spec.sections == []
