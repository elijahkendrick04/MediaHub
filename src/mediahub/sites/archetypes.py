"""sites.archetypes — deterministic SiteSpec builders for the four club archetypes.

Each builder turns a :class:`~sites.grounding.SiteFacts` (the source-grounded data)
into a complete, render-ready :class:`~sites.models.SiteSpec` — the skeleton +
real data are computed **in code**; the optional ``prose`` dict carries
AI-drafted, number-validated copy (:mod:`sites.draft`) keyed by section. With no
prose the page still stands on its data alone (CLAUDE.md: a page never invents a
fact, and honest-errors rather than fabricating).

The four archetypes mirror the roadmap's "club pages generated from club data":

  - ``club_home``       — the club's front page (hero, latest content, stats, sponsors)
  - ``link_in_bio``     — a tall single page of tap targets for a social bio link
  - ``meet_microsite``  — one meet: info, programme, recap as it lands, numbers
  - ``event_page``      — one event: details, countdown, RSVP form, tickets, map
"""

from __future__ import annotations

from typing import Callable, Optional

from mediahub.documents.models import heading, kpi_row, text

from .grounding import SiteFacts
from .models import (
    PageSEO,
    SitePage,
    SiteSection,
    SiteSpec,
    card_grid,
    cta_band,
    event_details,
    form_embed,
    hero,
    link_list,
    new_site,
    payment_button,
    social_links,
    sponsor_strip,
    widget_embed,
)

Prose = Optional[dict[str, str]]


def _prose_text(prose: Prose, key: str) -> list:
    """A text block for an AI-drafted section, or nothing if absent/empty."""
    if prose and prose.get(key):
        return [text(str(prose[key]))]
    return []


def _sponsor_section(facts: SiteFacts) -> Optional[SiteSection]:
    if not facts.sponsors:
        return None
    return SiteSection(
        blocks=[sponsor_strip(facts.sponsors, title="Our sponsors")],
        layout="band",
        background="surface",
    )


def _stats_section(facts: SiteFacts, *, lead: str = "By the numbers") -> Optional[SiteSection]:
    if not facts.stats:
        return None
    return SiteSection(blocks=[heading(lead, level=2), kpi_row(facts.stats)], layout="flow")


def _cards_section(facts: SiteFacts, *, lead: str, columns: int = 3) -> Optional[SiteSection]:
    if not facts.cards:
        return None
    return SiteSection(
        blocks=[heading(lead, level=2), card_grid(facts.cards, columns=columns)],
        layout="flow",
    )


def _contact_band(facts: SiteFacts) -> Optional[SiteSection]:
    if facts.contact_email:
        return SiteSection(
            blocks=[cta_band("Get in touch", "Email the club", f"mailto:{facts.contact_email}")],
            layout="band",
            background="primary",
        )
    return None


# ---------------------------------------------------------------------------
# club_home
# ---------------------------------------------------------------------------


def build_club_home(
    facts: SiteFacts,
    *,
    brand_profile_id: str = "",
    prose: Prose = None,
) -> SiteSpec:
    site = new_site(
        facts.club_name or "Our club",
        "club_home",
        brand_profile_id=brand_profile_id,
        tagline=facts.tagline,
    )
    hero_section = SiteSection(
        blocks=[
            hero(
                facts.club_name or "Our club",
                kicker=facts.location,
                subhead=facts.tagline,
                # The hero photo is chosen in the editor; the band stands on the
                # brand gradient until then.
            )
        ],
        layout="hero",
    )
    about_blocks = [heading("About us", level=2)]
    about_blocks += _prose_text(prose, "about") or ([text(facts.about)] if facts.about else [])
    sections = [hero_section]
    if len(about_blocks) > 1:
        sections.append(SiteSection(blocks=about_blocks, layout="flow"))
    sections += [s for s in (_stats_section(facts), _cards_section(facts, lead="Latest")) if s]
    sponsor = _sponsor_section(facts)
    if sponsor:
        sections.append(sponsor)
    contact = _contact_band(facts)
    if contact:
        sections.append(contact)

    home = SitePage(
        title="Home",
        slug="",
        layout="standard",
        sections=sections,
        seo=PageSEO(description=facts.tagline),
    )
    return _attach(site, [home], facts, meta_extra={})


# ---------------------------------------------------------------------------
# link_in_bio
# ---------------------------------------------------------------------------


def build_link_in_bio(
    facts: SiteFacts,
    *,
    brand_profile_id: str = "",
    prose: Prose = None,
) -> SiteSpec:
    site = new_site(
        facts.club_name or "Our club",
        "link_in_bio",
        brand_profile_id=brand_profile_id,
        tagline=facts.tagline,
    )
    blocks = [
        hero(facts.club_name or "Our club", kicker=facts.location, subhead=facts.tagline),
    ]
    intro = _prose_text(prose, "intro")
    if intro:
        blocks += intro
    # Operator-curated links first; otherwise nothing fabricated.
    if facts.links:
        blocks.append(link_list(facts.links))
    if facts.socials:
        blocks.append(social_links(facts.socials))

    page = SitePage(
        title=facts.club_name or "Links",
        slug="",
        layout="link_in_bio",
        sections=[SiteSection(blocks=blocks, layout="centered")],
        seo=PageSEO(description=facts.tagline),
    )
    return _attach(site, [page], facts, meta_extra={})


# ---------------------------------------------------------------------------
# meet_microsite
# ---------------------------------------------------------------------------


def build_meet_microsite(
    facts: SiteFacts,
    *,
    brand_profile_id: str = "",
    prose: Prose = None,
) -> SiteSpec:
    name = facts.event_name or "Meet"
    site = new_site(
        name, "meet_microsite", brand_profile_id=brand_profile_id, tagline=facts.tagline
    )
    subhead = " · ".join([x for x in (facts.event_date, facts.venue) if x])
    sections = [
        SiteSection(blocks=[hero(name, kicker="Meet microsite", subhead=subhead)], layout="hero"),
    ]
    if any((facts.event_date, facts.event_time, facts.venue, facts.address)):
        sections.append(
            SiteSection(
                blocks=[
                    heading("Meet information", level=2),
                    event_details(
                        name=name,
                        date=facts.event_date,
                        time=facts.event_time,
                        venue=facts.venue,
                        address=facts.address,
                    ),
                ],
                layout="flow",
            )
        )
    info = _prose_text(prose, "info")
    if info:
        sections.append(SiteSection(blocks=[heading("About the meet", level=2), *info]))
    recap = _cards_section(facts, lead="Results as they land")
    if recap:
        sections.append(recap)
    stats = _stats_section(facts, lead="Meet in numbers")
    if stats:
        sections.append(stats)
    sponsor = _sponsor_section(facts)
    if sponsor:
        sections.append(sponsor)

    page = SitePage(
        title="Home",
        slug="",
        layout="standard",
        sections=sections,
        seo=PageSEO(description=subhead or facts.tagline),
    )
    return _attach(site, [page], facts, meta_extra={"event_name": name})


# ---------------------------------------------------------------------------
# event_page
# ---------------------------------------------------------------------------


def build_event_page(
    facts: SiteFacts,
    *,
    brand_profile_id: str = "",
    prose: Prose = None,
    rsvp_form_id: str = "",
    ticket_url: str = "",
    ticket_label: str = "Get tickets",
) -> SiteSpec:
    name = facts.event_name or "Event"
    site = new_site(name, "event_page", brand_profile_id=brand_profile_id, tagline=facts.tagline)
    subhead = " · ".join([x for x in (facts.event_date, facts.venue) if x])
    sections = [
        SiteSection(blocks=[hero(name, kicker="Event", subhead=subhead)], layout="hero"),
    ]
    detail_blocks = [
        heading("Details", level=2),
        event_details(
            name=name,
            date=facts.event_date,
            time=facts.event_time,
            venue=facts.venue,
            address=facts.address,
        ),
    ]
    if facts.event_date:
        detail_blocks.append(
            widget_embed(
                widget_type="countdown", config={"target": facts.event_date, "label": name}
            )
        )
    sections.append(SiteSection(blocks=detail_blocks, layout="flow"))
    info = _prose_text(prose, "info")
    if info:
        sections.append(SiteSection(blocks=[*info]))
    if ticket_url:
        sections.append(
            SiteSection(
                blocks=[
                    payment_button(ticket_label, ticket_url, note="Secure checkout on our store")
                ],
                layout="centered",
            )
        )
    if rsvp_form_id:
        sections.append(
            SiteSection(
                blocks=[
                    heading("RSVP", level=2),
                    form_embed(rsvp_form_id, title="Let us know you're coming"),
                ],
                layout="flow",
                background="surface",
            )
        )

    page = SitePage(
        title="Home",
        slug="",
        layout="standard",
        sections=sections,
        seo=PageSEO(description=subhead or facts.tagline),
    )
    return _attach(site, [page], facts, meta_extra={"event_name": name})


# ---------------------------------------------------------------------------
# shared finalisation + dispatch
# ---------------------------------------------------------------------------


def _attach(
    site: SiteSpec, pages: list[SitePage], facts: SiteFacts, *, meta_extra: dict
) -> SiteSpec:
    meta = {
        "club_name": facts.club_name,
        "logo_src": facts.logo_src,
        "contact_email": facts.contact_email,
        "location": facts.location,
        "socials": facts.socials,
    }
    meta.update(meta_extra)
    return SiteSpec(
        title=site.title,
        pages=pages,
        archetype=site.archetype,
        theme=site.theme,
        brand_profile_id=site.brand_profile_id,
        tagline=site.tagline,
        meta=meta,
        source_refs=list(facts.source_refs),
        site_id=site.site_id,
    )


ARCHETYPE_BUILDERS: dict[str, Callable[..., SiteSpec]] = {
    "club_home": build_club_home,
    "link_in_bio": build_link_in_bio,
    "meet_microsite": build_meet_microsite,
    "event_page": build_event_page,
}


def build_site(archetype: str, facts: SiteFacts, **kwargs) -> SiteSpec:
    """Dispatch to the builder for ``archetype`` (defaults to ``club_home``)."""
    builder = ARCHETYPE_BUILDERS.get(archetype, build_club_home)
    return builder(facts, **kwargs)


__all__ = [
    "build_club_home",
    "build_link_in_bio",
    "build_meet_microsite",
    "build_event_page",
    "build_site",
    "ARCHETYPE_BUILDERS",
]
