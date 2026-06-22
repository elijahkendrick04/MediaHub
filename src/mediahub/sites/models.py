"""sites.models — the typed data model for a club microsite (roadmap 1.16).

A :class:`SiteSpec` is a fully-resolved, **render-ready** description of one club
microsite: a club home, a link-in-bio page, a meet microsite, or an event page.
It is plain, JSON-round-trippable data — *pages → sections → blocks* — that the
renderer (:mod:`sites.render`) turns into brand-tokened, **static** responsive
HTML deterministically. It deliberately mirrors :mod:`documents.models`
(roadmap 1.15) and **reuses its** :class:`~documents.models.Block` so a page and a
card from one club are unmistakably the same brand and one block vocabulary spans
both engines.

The contract (CLAUDE.md rules):

  - **The numbers are sacred.** A page never invents a statistic. Data blocks carry
    exact values from the deterministic fact base (:mod:`sites.grounding` →
    :mod:`charts.aggregates`); the AI drafting flow (:mod:`sites.draft`) only ever
    phrases prose around them and is number-validated.
  - **Approval-gated & outward-facing.** A site is editable as a *draft* and only
    becomes publicly reachable once the operator **publishes** it (the publish state
    lives in :mod:`sites.store`, not the spec) — a human approves before anything is
    served externally.
  - **Deterministic & additive.** Same spec + same brand role vars + same nonce →
    byte-identical HTML. ``to_dict``/``from_dict`` round-trip through JSON without
    loss; unknown keys drop and missing optionals default, so older/newer persisted
    shapes load cleanly.

Shape::

    SiteSpec(archetype="club_home"|"link_in_bio"|"meet_microsite"|"event_page"|"blank")
      └─ pages: [SitePage(slug)]
           └─ sections: [SiteSection(layout)]
                └─ blocks: [Block(kind, props)]   # documents.models.Block + site kinds
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

# Reuse the document engine's block model verbatim so the two engines share one
# block vocabulary and one set of renderers (sites adds a few site-only kinds).
from mediahub.documents.models import Block

# ---------------------------------------------------------------------------
# Vocabularies — tuples (not enums) so persisted specs stay plain JSON and new
# values are purely additive.
# ---------------------------------------------------------------------------

# The site archetypes the generator knows how to build (:mod:`sites.archetypes`).
SITE_ARCHETYPES: tuple[str, ...] = (
    "club_home",  # the club's front page — hero, latest content, about, sponsors
    "link_in_bio",  # a single tall page of tap targets for a social bio link
    "meet_microsite",  # one meet — entry info, programme, live recap as it lands
    "event_page",  # one event — details, RSVP form, map, countdown
    "blank",  # an empty site the user fills in
)

# Site-specific block kinds, **in addition** to the documents block vocabulary
# (heading/text/list/table/chart/card/media/stat/kpi_row/quote/divider/spacer/
# columns). The renderer dispatches reused kinds to the document renderers and
# these to site renderers; unknown kinds render as nothing (forward-compatible).
SITE_BLOCK_KINDS: tuple[str, ...] = (
    "hero",  # props: {headline, subhead?, kicker?, media_src?, cta?:{label,url}}
    "link_button",  # props: {label, url, style?: primary|secondary, note?}
    "link_list",  # props: {links: [{label, url, note?}]}  — link-in-bio stack
    "social_links",  # props: {links: [{platform, url}]}
    "card_grid",  # props: {cards: [{src, alt?, caption?, href?}], columns?: 2|3|4}
    "cta_band",  # props: {text, button: {label, url}}
    "sponsor_strip",  # props: {title?, logos: [{src, alt?, url?}]}
    "event_details",  # props: {name?, date?, time?, venue?, address?}
    "payment_button",  # props: {label, url, note?}  — link out (no checkout build)
    "form_embed",  # props: {form_id, title?}     — resolved via :mod:`forms`
    "widget_embed",  # props: {widget_id?, widget_type?, config?} — via :mod:`sites.widgets`
    "qr_block",  # props: {data, caption?, label?}— inline SVG via :mod:`sites.qr`
)

# Section layout intents. ``flow`` is ordinary stacked content; the others are
# full-width / hero / banded treatments. Renderer falls back to ``flow``.
SECTION_LAYOUTS: tuple[str, ...] = (
    "flow",  # ordinary stacked body content inside the page container
    "hero",  # full-bleed hero band (big headline over brand/media)
    "band",  # a full-width tinted band (brand colour / surface)
    "grid",  # blocks laid out as a responsive grid
    "centered",  # narrow, horizontally centred column (link-in-bio, statements)
)

# A section/band background role (mapped to brand role vars by the theme).
BACKGROUND_ROLES: tuple[str, ...] = ("", "surface", "ground", "primary", "accent")

# Page layout intents — drive the page container width/treatment.
PAGE_LAYOUTS: tuple[str, ...] = (
    "standard",  # nav + content container + footer
    "landing",  # full-width landing (hero-led)
    "link_in_bio",  # narrow single-column tap-target page, no nav
)

# Colour scheme. Dark-first per the CLAUDE.md UI rules; light is offered for
# print-friendly / bright-brand clubs.
SITE_THEMES: tuple[str, ...] = ("dark", "light")

# The natural archetype → (page layout, theme) defaults.
ARCHETYPE_DEFAULTS: dict[str, tuple[str, str]] = {
    "club_home": ("standard", "dark"),
    "link_in_bio": ("link_in_bio", "dark"),
    "meet_microsite": ("standard", "dark"),
    "event_page": ("standard", "dark"),
    "blank": ("standard", "dark"),
}

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def slugify(value: str, *, default: str = "page") -> str:
    """A url-safe slug: lowercase, hyphenated, ascii-only. Empty → ``default``."""
    s = _SLUG_RE.sub("-", str(value or "").strip().lower()).strip("-")
    return s or default


# ---------------------------------------------------------------------------
# Site-specific block constructors (documents.models supplies the rest)
# ---------------------------------------------------------------------------


def hero(
    headline: str,
    *,
    subhead: str = "",
    kicker: str = "",
    media_src: str = "",
    cta_label: str = "",
    cta_url: str = "",
) -> Block:
    props: dict[str, Any] = {
        "headline": str(headline),
        "subhead": str(subhead),
        "kicker": str(kicker),
        "media_src": str(media_src),
    }
    if cta_label and cta_url:
        props["cta"] = {"label": str(cta_label), "url": str(cta_url)}
    return Block("hero", props)


def link_button(label: str, url: str, *, style: str = "primary", note: str = "") -> Block:
    style = style if style in ("primary", "secondary") else "primary"
    return Block(
        "link_button",
        {"label": str(label), "url": str(url), "style": style, "note": str(note)},
    )


def link_list(links: list[dict[str, str]]) -> Block:
    clean = []
    for item in links or []:
        if isinstance(item, dict) and item.get("label") and item.get("url"):
            clean.append(
                {
                    "label": str(item.get("label", "")),
                    "url": str(item.get("url", "")),
                    "note": str(item.get("note", "")),
                }
            )
    return Block("link_list", {"links": clean})


def social_links(links: list[dict[str, str]]) -> Block:
    clean = []
    for item in links or []:
        if isinstance(item, dict) and item.get("platform") and item.get("url"):
            clean.append(
                {"platform": str(item.get("platform", "")), "url": str(item.get("url", ""))}
            )
    return Block("social_links", {"links": clean})


def card_grid(cards: list[dict[str, str]], *, columns: int = 3) -> Block:
    columns = columns if columns in (2, 3, 4) else 3
    clean = []
    for c in cards or []:
        if isinstance(c, dict) and c.get("src"):
            clean.append(
                {
                    "src": str(c.get("src", "")),
                    "alt": str(c.get("alt", "")),
                    "caption": str(c.get("caption", "")),
                    "href": str(c.get("href", "")),
                }
            )
    return Block("card_grid", {"cards": clean, "columns": columns})


def cta_band(text: str, button_label: str, button_url: str) -> Block:
    return Block(
        "cta_band",
        {"text": str(text), "button": {"label": str(button_label), "url": str(button_url)}},
    )


def sponsor_strip(logos: list[dict[str, str]], *, title: str = "") -> Block:
    clean = []
    for logo in logos or []:
        if isinstance(logo, dict) and logo.get("src"):
            clean.append(
                {
                    "src": str(logo.get("src", "")),
                    "alt": str(logo.get("alt", "")),
                    "url": str(logo.get("url", "")),
                }
            )
    return Block("sponsor_strip", {"title": str(title), "logos": clean})


def event_details(
    *,
    name: str = "",
    date: str = "",
    time: str = "",
    venue: str = "",
    address: str = "",
) -> Block:
    return Block(
        "event_details",
        {
            "name": str(name),
            "date": str(date),
            "time": str(time),
            "venue": str(venue),
            "address": str(address),
        },
    )


def payment_button(label: str, url: str, *, note: str = "") -> Block:
    return Block("payment_button", {"label": str(label), "url": str(url), "note": str(note)})


def form_embed(form_id: str, *, title: str = "") -> Block:
    return Block("form_embed", {"form_id": str(form_id), "title": str(title)})


def widget_embed(
    *, widget_id: str = "", widget_type: str = "", config: dict[str, Any] | None = None
) -> Block:
    return Block(
        "widget_embed",
        {
            "widget_id": str(widget_id),
            "widget_type": str(widget_type),
            "config": dict(config or {}),
        },
    )


def qr_block(data: str, *, caption: str = "", label: str = "") -> Block:
    return Block("qr_block", {"data": str(data), "caption": str(caption), "label": str(label)})


# ---------------------------------------------------------------------------
# SiteSection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SiteSection:
    """A run of blocks rendered as one full-width section of a page."""

    blocks: list[Block] = field(default_factory=list)
    layout: str = "flow"
    background: str = ""
    section_id: str = ""

    def __post_init__(self) -> None:
        if not self.section_id:
            object.__setattr__(self, "section_id", _new_id("sec"))
        if self.layout not in SECTION_LAYOUTS:
            object.__setattr__(self, "layout", "flow")
        if self.background not in BACKGROUND_ROLES:
            object.__setattr__(self, "background", "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "blocks": [b.to_dict() for b in self.blocks],
            "layout": self.layout,
            "background": self.background,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SiteSection":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            blocks=[Block.from_dict(b) for b in (raw.get("blocks") or [])],
            layout=str(raw.get("layout") or "flow"),
            background=str(raw.get("background") or ""),
            section_id=str(raw.get("section_id") or ""),
        )


# ---------------------------------------------------------------------------
# PageSEO
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PageSEO:
    """Per-page SEO controls (roadmap 1.16 SEO layer). ``description`` may be
    AI-suggested but is always human-editable; ``noindex`` keeps a page out of
    the sitemap and adds a robots meta."""

    meta_title: str = ""
    description: str = ""
    og_image: str = ""
    noindex: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "meta_title": self.meta_title,
            "description": self.description,
            "og_image": self.og_image,
            "noindex": self.noindex,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "PageSEO":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            meta_title=str(raw.get("meta_title") or ""),
            description=str(raw.get("description") or ""),
            og_image=str(raw.get("og_image") or ""),
            noindex=bool(raw.get("noindex")),
        )


# ---------------------------------------------------------------------------
# SitePage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SitePage:
    """One page of a site. ``slug`` is the URL path component; the first page (or
    a page with an empty/"index"/"home" slug) is the site's landing page."""

    title: str = "Home"
    slug: str = ""
    sections: list[SiteSection] = field(default_factory=list)
    layout: str = "standard"
    seo: PageSEO = field(default_factory=PageSEO)
    protected: bool = False  # password / members-only gate (applied by the web layer)
    show_in_nav: bool = True
    page_id: str = ""

    def __post_init__(self) -> None:
        if not self.page_id:
            object.__setattr__(self, "page_id", _new_id("pg"))
        object.__setattr__(self, "slug", slugify(self.slug, default=slugify(self.title)))
        if self.layout not in PAGE_LAYOUTS:
            object.__setattr__(self, "layout", "standard")

    @property
    def is_home(self) -> bool:
        return self.slug in ("", "index", "home")

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_id": self.page_id,
            "title": self.title,
            "slug": self.slug,
            "layout": self.layout,
            "protected": self.protected,
            "show_in_nav": self.show_in_nav,
            "seo": self.seo.to_dict(),
            "sections": [s.to_dict() for s in self.sections],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SitePage":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            title=str(raw.get("title") or "Home"),
            slug=str(raw.get("slug") or ""),
            layout=str(raw.get("layout") or "standard"),
            protected=bool(raw.get("protected")),
            show_in_nav=bool(raw.get("show_in_nav", True)),
            seo=PageSEO.from_dict(raw.get("seo") or {}),
            sections=[SiteSection.from_dict(s) for s in (raw.get("sections") or [])],
            page_id=str(raw.get("page_id") or ""),
        )


# ---------------------------------------------------------------------------
# SiteSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SiteSpec:
    """A complete, render-ready multi-page club microsite (the *draft*; publish
    state lives in :mod:`sites.store`)."""

    title: str
    pages: list[SitePage] = field(default_factory=list)
    archetype: str = "blank"
    theme: str = "dark"
    brand_profile_id: str = ""
    tagline: str = ""
    meta: dict[str, Any] = field(default_factory=dict)  # club_name, contact, socials…
    custom_domain: str = ""  # BYO domain (CNAME target shown in UI; cert is platform-side)
    source_refs: list[str] = field(default_factory=list)
    site_id: str = ""

    def __post_init__(self) -> None:
        if not self.site_id:
            object.__setattr__(self, "site_id", _new_id("site"))
        if self.archetype not in SITE_ARCHETYPES:
            object.__setattr__(self, "archetype", "blank")
        if self.theme not in SITE_THEMES:
            object.__setattr__(self, "theme", "dark")

    @property
    def home_page(self) -> SitePage | None:
        if not self.pages:
            return None
        for p in self.pages:
            if p.is_home:
                return p
        return self.pages[0]

    def page_by_slug(self, slug: str) -> SitePage | None:
        target = slugify(slug, default="") if slug else ""
        if not target:
            return self.home_page
        for p in self.pages:
            if p.slug == target:
                return p
        return None

    def nav_pages(self) -> list[SitePage]:
        """Pages that appear in the site navigation, home first."""
        out = [p for p in self.pages if p.show_in_nav]
        out.sort(key=lambda p: 0 if p.is_home else 1)
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id,
            "title": self.title,
            "tagline": self.tagline,
            "archetype": self.archetype,
            "theme": self.theme,
            "brand_profile_id": self.brand_profile_id,
            "custom_domain": self.custom_domain,
            "meta": dict(self.meta),
            "source_refs": list(self.source_refs),
            "pages": [p.to_dict() for p in self.pages],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "SiteSpec":
        if not isinstance(raw, dict):
            return cls(title="Untitled site")
        return cls(
            title=str(raw.get("title") or "Untitled site"),
            tagline=str(raw.get("tagline") or ""),
            archetype=str(raw.get("archetype") or "blank"),
            theme=str(raw.get("theme") or "dark"),
            brand_profile_id=str(raw.get("brand_profile_id") or ""),
            custom_domain=str(raw.get("custom_domain") or ""),
            meta=dict(raw.get("meta") or {}),
            source_refs=[str(s) for s in (raw.get("source_refs") or [])],
            pages=[SitePage.from_dict(p) for p in (raw.get("pages") or [])],
            site_id=str(raw.get("site_id") or ""),
        )


def new_site(
    title: str,
    archetype: str = "blank",
    *,
    brand_profile_id: str = "",
    tagline: str = "",
) -> SiteSpec:
    """Start an empty site wired to an archetype's natural layout + theme."""
    arch = archetype if archetype in SITE_ARCHETYPES else "blank"
    _layout, theme = ARCHETYPE_DEFAULTS.get(arch, ("standard", "dark"))
    return SiteSpec(
        title=str(title),
        tagline=str(tagline),
        archetype=arch,
        theme=theme,
        brand_profile_id=str(brand_profile_id),
    )


__all__ = [
    "SITE_ARCHETYPES",
    "SITE_BLOCK_KINDS",
    "SECTION_LAYOUTS",
    "BACKGROUND_ROLES",
    "PAGE_LAYOUTS",
    "SITE_THEMES",
    "ARCHETYPE_DEFAULTS",
    "Block",
    "SiteSection",
    "PageSEO",
    "SitePage",
    "SiteSpec",
    "new_site",
    "slugify",
    # site block constructors
    "hero",
    "link_button",
    "link_list",
    "social_links",
    "card_grid",
    "cta_band",
    "sponsor_strip",
    "event_details",
    "payment_button",
    "form_embed",
    "widget_embed",
    "qr_block",
]
