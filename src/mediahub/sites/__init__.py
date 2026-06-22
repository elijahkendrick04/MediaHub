"""mediahub.sites — club microsites, link-in-bio & event pages (roadmap 1.16).

**Club pages generated from club data**, not a blank website builder. A
:class:`~sites.models.SiteSpec` (pages → sections → blocks, reusing the document
engine's :class:`~documents.models.Block`) is built from a source-grounded
:class:`~sites.grounding.SiteFacts` by one of four archetype builders
(:mod:`sites.archetypes`), optionally given AI copy (:mod:`sites.draft`, honest-
erroring without a provider), rendered to **static** responsive HTML
(:mod:`sites.render`) and saved per-club (:mod:`sites.store`). A site is editable as
a draft and only reachable publicly once the operator **publishes** it — a human
approves before anything is served externally (CLAUDE.md: approval before external
publishing, always).

The companion engines fill in over Builds 2–3: :mod:`mediahub.forms` (form embeds →
data-hub rows), :mod:`sites.widgets` (the vetted interactive-widget catalogue),
:mod:`sites.qr` (brand-safe QR), :mod:`sites.seo` and :mod:`sites.insights`.
"""

from __future__ import annotations

from .archetypes import (
    build_club_home,
    build_event_page,
    build_link_in_bio,
    build_meet_microsite,
    build_site,
)
from .draft import draft_copy, generate_site, suggest_alt_text, suggest_seo_description
from .grounding import SiteFacts, site_facts_with_performance
from .models import (
    SITE_ARCHETYPES,
    PageSEO,
    SitePage,
    SiteSection,
    SiteSpec,
    new_site,
    slugify,
)
from .render import render_page_html, render_site_page

__all__ = [
    "SiteSpec",
    "SitePage",
    "SiteSection",
    "PageSEO",
    "SiteFacts",
    "SITE_ARCHETYPES",
    "new_site",
    "slugify",
    "site_facts_with_performance",
    "build_site",
    "build_club_home",
    "build_link_in_bio",
    "build_meet_microsite",
    "build_event_page",
    "generate_site",
    "draft_copy",
    "suggest_seo_description",
    "suggest_alt_text",
    "render_page_html",
    "render_site_page",
]
