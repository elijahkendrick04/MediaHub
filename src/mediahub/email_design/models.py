"""email_design.models — the newsletter data model (roadmap 1.17).

A newsletter is a small, email-safe cousin of a :mod:`documents` document:
``NewsletterSpec → Section → EmailBlock``. The block vocabulary is a deliberate
**subset** of the document blocks — only the kinds that compile cleanly to the
table-based, inline-styled HTML email clients actually render (Outlook's Word
engine, Gmail's stripping, Apple Mail's dark mode) — plus a few email-native
kinds (a bulletproof ``button``, a content ``card``, an ``fixtures`` list and a
``sponsor`` slot).

Storage is a plain ``(kind, props)`` dict like the document model: small,
additive, JSON-round-trippable, validated at construction by the typed
constructor helpers below. The masthead (logo + kicker + title + period) and the
footer (org line + unsubscribe placeholder) are spec-level *chrome*, not blocks,
exactly like the existing :mod:`brand.newsletter_renderer` — the body is what is
built from blocks.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Vocabularies
# ---------------------------------------------------------------------------

# The email-safe block kinds. A subset of documents.BLOCK_KINDS (heading/text/
# list/divider/spacer/quote/stat_row≈kpi_row/image≈media) plus email-native
# kinds (button/card/fixtures/sponsor). Kinds the email surface deliberately
# drops: chart (SVG support is patchy in email), columns (nested flex), table
# (re-expressed as fixtures/card where it matters).
EMAIL_BLOCK_KINDS: tuple[str, ...] = (
    "heading",  # {text, level: 1..3}
    "text",  # {text, align}
    "list",  # {items: [str], ordered: bool}
    "button",  # {label, href, align}            — bulletproof CTA
    "image",  # {src, alt, href, caption, width} — a photo / logo / banner
    "card",  # {src, alt, title, body, href, cta} — a result recap / spotlight
    "stat_row",  # {stats: [{value, label}]}        — KPI tiles (season highlights)
    "quote",  # {text, attribution}
    "fixtures",  # {items: [{date, name, venue}]}    — upcoming fixtures (planner)
    "sponsor",  # {name, logo_src, href, label}     — sponsor slot
    "divider",  # {}
    "spacer",  # {size: sm|md|lg}
)

# Section background bands — email-safe tints applied to the whole section td.
SECTION_BACKGROUNDS: tuple[str, ...] = ("", "surface", "accent")

# The newsletter formats (informational/provenance + auto-assembly default, like
# documents.DOC_FORMATS). The composition per format lives in
# :mod:`email_design.formats`; this is the canonical name list.
NEWSLETTER_FORMATS: tuple[str, ...] = (
    "meet_digest",  # one meet → recap + spotlights + next up
    "monthly_roundup",  # a window of approved content + fixtures + sponsor
    "season_highlights",  # a season window → headline stats + standout cards
    "blank",  # an empty newsletter the user fills in
)

DEFAULT_FORMAT = "blank"


# ---------------------------------------------------------------------------
# EmailFormat — the email "FormatSpec" (content geometry, like PageGeometry)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmailFormat:
    """The email layout envelope: the fixed content column width (600px is the
    universal email standard) the renderer lays the table scaffold out at, plus
    the format name for provenance. Kept tiny on purpose — email geometry is not
    a free variable the way a print page is."""

    name: str = DEFAULT_FORMAT
    width: int = 600

    def __post_init__(self) -> None:
        # 320..700 keeps the column inside the safe range every client honours.
        w = int(self.width or 600)
        object.__setattr__(self, "width", max(320, min(700, w)))


def format_for(name: str) -> EmailFormat:
    """Resolve a format name to its :class:`EmailFormat` (tolerant of unknowns)."""
    name = name if name in NEWSLETTER_FORMATS else DEFAULT_FORMAT
    return EmailFormat(name=name)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _clamp_level(level: Any) -> int:
    try:
        n = int(level)
    except (TypeError, ValueError):
        return 2
    return max(1, min(3, n))


# ---------------------------------------------------------------------------
# EmailBlock
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class EmailBlock:
    """One email content block. ``props`` is a kind-specific, JSON-able payload."""

    kind: str
    props: dict[str, Any] = field(default_factory=dict)
    block_id: str = ""

    def __post_init__(self) -> None:
        if not self.block_id:
            object.__setattr__(self, "block_id", _new_id("eb"))
        if not isinstance(self.props, dict):
            object.__setattr__(self, "props", {})

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "props": dict(self.props), "block_id": self.block_id}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EmailBlock":
        if not isinstance(raw, dict):
            return cls(kind="text", props={"text": ""})
        return cls(
            kind=str(raw.get("kind") or "text"),
            props=dict(raw.get("props") or {}),
            block_id=str(raw.get("block_id") or ""),
        )


# Typed, validated convenience constructors — the authoring surface.


def heading(text: str, level: int = 2) -> EmailBlock:
    return EmailBlock("heading", {"text": str(text), "level": _clamp_level(level)})


def text(body: str, *, align: str = "left") -> EmailBlock:
    align = align if align in ("left", "center", "right") else "left"
    return EmailBlock("text", {"text": str(body), "align": align})


def bullet_list(items: list[str], *, ordered: bool = False) -> EmailBlock:
    return EmailBlock("list", {"items": [str(i) for i in (items or [])], "ordered": bool(ordered)})


def button(label: str, href: str, *, align: str = "left") -> EmailBlock:
    align = align if align in ("left", "center", "right") else "left"
    return EmailBlock("button", {"label": str(label), "href": str(href), "align": align})


def image(
    src: str, *, alt: str = "", href: str = "", caption: str = "", width: int = 0
) -> EmailBlock:
    return EmailBlock(
        "image",
        {
            "src": str(src),
            "alt": str(alt),
            "href": str(href),
            "caption": str(caption),
            "width": max(0, int(width or 0)),
        },
    )


def card(
    *,
    title: str,
    body: str = "",
    src: str = "",
    alt: str = "",
    href: str = "",
    cta: str = "",
    card_ref: str = "",
) -> EmailBlock:
    """A content card — a result recap or athlete spotlight: optional image on
    top, a title, body copy, and an optional call-to-action link.

    ``card_ref`` (``"<run_id>/<card_id>"``) lets the web layer fill ``src`` with
    the right *public* image URL at render time — an authenticated route in the
    editor preview, the published token route in the hosted/exported email — so a
    card image is only ever served behind a proper access check, never baked in."""
    return EmailBlock(
        "card",
        {
            "title": str(title),
            "body": str(body),
            "src": str(src),
            "alt": str(alt),
            "href": str(href),
            "cta": str(cta),
            "card_ref": str(card_ref),
        },
    )


def stat_row(stats: list[dict[str, str]]) -> EmailBlock:
    clean = []
    for s in stats or []:
        if isinstance(s, dict) and (s.get("value") is not None):
            clean.append({"value": str(s.get("value", "")), "label": str(s.get("label", ""))})
    return EmailBlock("stat_row", {"stats": clean})


def quote(text_body: str, *, attribution: str = "") -> EmailBlock:
    return EmailBlock("quote", {"text": str(text_body), "attribution": str(attribution)})


def fixtures(items: list[dict[str, str]], *, title: str = "") -> EmailBlock:
    """Upcoming fixtures from the planner: a list of ``{date, name, venue}``."""
    clean = []
    for it in items or []:
        if isinstance(it, dict) and (it.get("name") or it.get("date")):
            clean.append(
                {
                    "date": str(it.get("date", "")),
                    "name": str(it.get("name", "")),
                    "venue": str(it.get("venue", "")),
                }
            )
    return EmailBlock("fixtures", {"items": clean, "title": str(title)})


def sponsor(name: str, *, logo_src: str = "", href: str = "", label: str = "") -> EmailBlock:
    return EmailBlock(
        "sponsor",
        {
            "name": str(name),
            "logo_src": str(logo_src),
            "href": str(href),
            "label": str(label),
        },
    )


def divider() -> EmailBlock:
    return EmailBlock("divider", {})


def spacer(size: str = "md") -> EmailBlock:
    size = size if size in ("sm", "md", "lg") else "md"
    return EmailBlock("spacer", {"size": size})


# ---------------------------------------------------------------------------
# Section
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Section:
    """A run of blocks rendered into one table row of the email. An optional
    ``background`` tints the whole section band (alternating surface/accent
    bands give a branded rhythm without leaving table-safe HTML)."""

    blocks: list[EmailBlock] = field(default_factory=list)
    background: str = ""  # SECTION_BACKGROUNDS
    section_id: str = ""

    def __post_init__(self) -> None:
        if not self.section_id:
            object.__setattr__(self, "section_id", _new_id("sec"))
        if self.background not in SECTION_BACKGROUNDS:
            object.__setattr__(self, "background", "")

    def to_dict(self) -> dict[str, Any]:
        return {
            "section_id": self.section_id,
            "blocks": [b.to_dict() for b in self.blocks],
            "background": self.background,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Section":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            blocks=[EmailBlock.from_dict(b) for b in (raw.get("blocks") or [])],
            background=str(raw.get("background") or ""),
            section_id=str(raw.get("section_id") or ""),
        )


# ---------------------------------------------------------------------------
# NewsletterSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NewsletterSpec:
    """A complete, render-ready newsletter.

    The masthead is assembled from ``kicker`` + ``title`` + ``subtitle`` (the
    period/date line) + the brand logo; the body is ``sections``; the footer
    line names the club (``meta['club_name']``). ``preheader`` is the hidden
    inbox-preview text inboxes show beside the subject."""

    title: str
    sections: list[Section] = field(default_factory=list)
    newsletter_format: str = DEFAULT_FORMAT  # NEWSLETTER_FORMATS — provenance
    subtitle: str = ""  # period / date line under the title in the masthead
    kicker: str = ""  # small uppercase label above the title
    preheader: str = ""  # hidden inbox-preview text
    subject: str = ""  # the email subject line (export hint, not rendered in body)
    brand_profile_id: str = ""
    meta: dict[str, Any] = field(default_factory=dict)  # club_name/period/date_range…
    source_refs: list[str] = field(default_factory=list)  # provenance (CLAUDE.md)
    newsletter_id: str = ""

    def __post_init__(self) -> None:
        if not self.newsletter_id:
            object.__setattr__(self, "newsletter_id", _new_id("nl"))
        if self.newsletter_format not in NEWSLETTER_FORMATS:
            object.__setattr__(self, "newsletter_format", DEFAULT_FORMAT)

    @property
    def email_format(self) -> EmailFormat:
        return format_for(self.newsletter_format)

    def to_dict(self) -> dict[str, Any]:
        return {
            "newsletter_id": self.newsletter_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "kicker": self.kicker,
            "preheader": self.preheader,
            "subject": self.subject,
            "newsletter_format": self.newsletter_format,
            "brand_profile_id": self.brand_profile_id,
            "sections": [s.to_dict() for s in self.sections],
            "meta": dict(self.meta),
            "source_refs": list(self.source_refs),
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "NewsletterSpec":
        if not isinstance(raw, dict):
            return cls(title="Newsletter")
        return cls(
            title=str(raw.get("title") or "Newsletter"),
            sections=[Section.from_dict(s) for s in (raw.get("sections") or [])],
            newsletter_format=str(raw.get("newsletter_format") or DEFAULT_FORMAT),
            subtitle=str(raw.get("subtitle") or ""),
            kicker=str(raw.get("kicker") or ""),
            preheader=str(raw.get("preheader") or ""),
            subject=str(raw.get("subject") or ""),
            brand_profile_id=str(raw.get("brand_profile_id") or ""),
            meta=dict(raw.get("meta") or {}),
            source_refs=list(raw.get("source_refs") or []),
            newsletter_id=str(raw.get("newsletter_id") or ""),
        )


def new_newsletter(
    title: str,
    newsletter_format: str = DEFAULT_FORMAT,
    *,
    brand_profile_id: str = "",
    subtitle: str = "",
    kicker: str = "",
) -> NewsletterSpec:
    """Construct an empty newsletter shell for a format."""
    return NewsletterSpec(
        title=str(title),
        sections=[],
        newsletter_format=newsletter_format,
        brand_profile_id=brand_profile_id,
        subtitle=subtitle,
        kicker=kicker,
    )


__all__ = [
    "EMAIL_BLOCK_KINDS",
    "SECTION_BACKGROUNDS",
    "NEWSLETTER_FORMATS",
    "DEFAULT_FORMAT",
    "EmailFormat",
    "format_for",
    "EmailBlock",
    "Section",
    "NewsletterSpec",
    "new_newsletter",
    # constructors
    "heading",
    "text",
    "bullet_list",
    "button",
    "image",
    "card",
    "stat_row",
    "quote",
    "fixtures",
    "sponsor",
    "divider",
    "spacer",
]
