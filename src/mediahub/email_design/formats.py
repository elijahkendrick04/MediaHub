"""email_design.formats — lay a :class:`NewsletterFacts` out into a newsletter.

The deterministic skeleton builders — the newsletter's equivalent of
:mod:`documents.formats`. Each takes the gathered facts (and optionally the AI
editorial prose) and returns a render-ready :class:`NewsletterSpec`. **No numbers
are invented here**: the stat tiles and result cards carry the exact values from
:mod:`email_design.grounding`; the AI only supplies the intro wording, and even
that is number-validated upstream in :mod:`email_design.draft`.

Four formats:

* ``meet_digest``      — one meet: recap cards + spotlights + what's next
* ``monthly_roundup``  — a month: headline numbers + recaps + fixtures + sponsor
* ``season_highlights``— a season window: big numbers + the standout cards
* ``blank``            — a minimal shell to fill in
"""

from __future__ import annotations

from typing import Optional

from . import models as m
from .grounding import NewsletterFacts


def _intro_block(prose: Optional[dict], facts: NewsletterFacts) -> list[m.EmailBlock]:
    """The opening paragraph — AI prose if we have it, else an honest, fact-only
    fallback (so the newsletter reads well even with no AI configured)."""
    intro = ""
    if isinstance(prose, dict):
        intro = str(prose.get("intro") or "").strip()
    if not intro:
        club = facts.club_name or "the club"
        bits = [f"Here's what {club} got up to over {facts.period}."]
        if facts.stats:
            summary = ", ".join(f"{s['value']} {s['label'].lower()}" for s in facts.stats[:3])
            bits.append(f"In numbers: {summary}.")
        intro = " ".join(bits)
    return [m.text(intro)] if intro else []


def _recap_card(r: dict) -> m.EmailBlock:
    return m.card(
        title=r.get("title", ""),
        body=r.get("body", ""),
        src=r.get("image_url", ""),
        alt=r.get("title", ""),
        href=r.get("href", ""),
        cta="See the card" if r.get("href") else "",
        card_ref=r.get("card_ref", ""),
    )


def _spotlight_card(s: dict) -> m.EmailBlock:
    return m.card(title=s.get("name", ""), body=s.get("body", ""), card_ref=s.get("card_ref", ""))


def _stats_section(facts: NewsletterFacts) -> Optional[m.Section]:
    if not facts.stats:
        return None
    return m.Section(background="surface", blocks=[m.stat_row(facts.stats)])


def _recaps_section(facts: NewsletterFacts, *, heading: str, limit: int) -> Optional[m.Section]:
    cards = [_recap_card(r) for r in facts.recaps[:limit]]
    if not cards:
        return None
    return m.Section(blocks=[m.heading(heading, level=2), *cards])


def _spotlights_section(facts: NewsletterFacts) -> Optional[m.Section]:
    if not facts.spotlights:
        return None
    cards = [_spotlight_card(s) for s in facts.spotlights]
    return m.Section(blocks=[m.heading("Athletes to watch", level=2), *cards])


def _fixtures_section(facts: NewsletterFacts) -> Optional[m.Section]:
    if not facts.fixtures:
        return None
    return m.Section(blocks=[m.heading("Up next", level=2), m.fixtures(facts.fixtures)])


def _cta_section(hosted_url: str, label: str = "Read the full recap") -> Optional[m.Section]:
    if not hosted_url:
        return None
    return m.Section(background="accent", blocks=[m.button(label, hosted_url, align="left")])


def _sponsor_section(facts: NewsletterFacts) -> Optional[m.Section]:
    sp = facts.sponsor or {}
    if not sp.get("name") and not sp.get("logo_src"):
        return None
    return m.Section(
        blocks=[
            m.sponsor(
                sp.get("name", ""),
                logo_src=sp.get("logo_src", ""),
                href=sp.get("href", ""),
                label="Proudly supported by",
            )
        ]
    )


def _shell(
    facts: NewsletterFacts,
    *,
    title: str,
    newsletter_format: str,
    brand_profile_id: str,
    prose: Optional[dict],
) -> dict:
    """Common masthead fields + meta shared by every format."""
    preheader = ""
    subject = ""
    if isinstance(prose, dict):
        preheader = str(prose.get("preheader") or "").strip()
        subject = str(prose.get("subject") or "").strip()
    if not preheader:
        if facts.stats:
            preheader = ", ".join(f"{s['value']} {s['label'].lower()}" for s in facts.stats[:3])
        else:
            preheader = f"Your {facts.period} update"
    if not subject:
        club = facts.club_name or "Club"
        subject = f"{club} — {facts.period} update"
    return {
        "kicker": f"{facts.club_name} newsletter".strip() if facts.club_name else "Club newsletter",
        "subtitle": facts.period,
        "preheader": preheader,
        "subject": subject,
        "brand_profile_id": brand_profile_id,
        "meta": {
            "club_name": facts.club_name,
            "period": facts.period,
            "date_range": [facts.date_start, facts.date_end],
        },
        "source_refs": list(facts.source_refs),
    }


def _assemble(title: str, newsletter_format: str, shell: dict, sections: list) -> m.NewsletterSpec:
    sections = [s for s in sections if s is not None]
    return m.NewsletterSpec(
        title=title,
        newsletter_format=newsletter_format,
        sections=sections,
        **shell,
    )


# ---------------------------------------------------------------------------
# Format builders
# ---------------------------------------------------------------------------


def build_meet_digest(
    facts: NewsletterFacts,
    *,
    brand_profile_id: str = "",
    prose: Optional[dict] = None,
    hosted_url: str = "",
) -> m.NewsletterSpec:
    shell = _shell(
        facts, title="Meet recap", newsletter_format="meet_digest",
        brand_profile_id=brand_profile_id, prose=prose,
    )
    sections = [
        m.Section(blocks=_intro_block(prose, facts)),
        _stats_section(facts),
        _recaps_section(facts, heading="Standout swims", limit=6),
        _spotlights_section(facts),
        _fixtures_section(facts),
        _cta_section(hosted_url),
        _sponsor_section(facts),
    ]
    return _assemble("Meet recap", "meet_digest", shell, sections)


def build_monthly_roundup(
    facts: NewsletterFacts,
    *,
    brand_profile_id: str = "",
    prose: Optional[dict] = None,
    hosted_url: str = "",
) -> m.NewsletterSpec:
    title = f"{facts.period} roundup" if facts.period else "Monthly roundup"
    shell = _shell(
        facts, title=title, newsletter_format="monthly_roundup",
        brand_profile_id=brand_profile_id, prose=prose,
    )
    sections = [
        m.Section(blocks=_intro_block(prose, facts)),
        _stats_section(facts),
        _recaps_section(facts, heading="Highlights", limit=4),
        _fixtures_section(facts),
        _cta_section(hosted_url, label="Read more on the club site"),
        _sponsor_section(facts),
    ]
    return _assemble(title, "monthly_roundup", shell, sections)


def build_season_highlights(
    facts: NewsletterFacts,
    *,
    brand_profile_id: str = "",
    prose: Optional[dict] = None,
    hosted_url: str = "",
) -> m.NewsletterSpec:
    shell = _shell(
        facts, title="Season highlights", newsletter_format="season_highlights",
        brand_profile_id=brand_profile_id, prose=prose,
    )
    sections = [
        m.Section(blocks=_intro_block(prose, facts)),
        # season puts the numbers front and centre on an accent band
        m.Section(background="surface", blocks=[m.stat_row(facts.stats)]) if facts.stats else None,
        _recaps_section(facts, heading="The swims we'll remember", limit=6),
        _spotlights_section(facts),
        _cta_section(hosted_url, label="See the full season"),
        _sponsor_section(facts),
    ]
    return _assemble("Season highlights", "season_highlights", shell, sections)


def build_blank(
    facts: NewsletterFacts,
    *,
    brand_profile_id: str = "",
    prose: Optional[dict] = None,
    hosted_url: str = "",
) -> m.NewsletterSpec:
    shell = _shell(
        facts, title="Newsletter", newsletter_format="blank",
        brand_profile_id=brand_profile_id, prose=prose,
    )
    sections = [m.Section(blocks=_intro_block(prose, facts) or [m.text("")])]
    return _assemble("Newsletter", "blank", shell, sections)


_BUILDERS = {
    "meet_digest": build_meet_digest,
    "monthly_roundup": build_monthly_roundup,
    "season_highlights": build_season_highlights,
    "blank": build_blank,
}


def build_newsletter(
    newsletter_format: str,
    facts: NewsletterFacts,
    *,
    brand_profile_id: str = "",
    prose: Optional[dict] = None,
    hosted_url: str = "",
) -> m.NewsletterSpec:
    """Dispatch to the right format builder (deterministic skeleton + real data)."""
    fn = _BUILDERS.get(newsletter_format, build_blank)
    return fn(facts, brand_profile_id=brand_profile_id, prose=prose, hosted_url=hosted_url)


__all__ = [
    "build_meet_digest",
    "build_monthly_roundup",
    "build_season_highlights",
    "build_blank",
    "build_newsletter",
]
