"""email_design — MediaHub's email & newsletter composer (roadmap 1.17).

Clubs already have a list tool (Mailchimp-class). What they don't have is a way
to turn *this period's approved content* — the result recaps, the athlete
spotlights, the upcoming fixtures from the planner, the sponsor slot — into a
branded, send-anywhere newsletter without rebuilding it by hand in Canva. This
package is that composer.

The shape mirrors the document engine (1.15) and the sites engine (1.16):
``NewsletterSpec → Section → EmailBlock``, assembled deterministically from real,
approved facts, with an AI editorial pass that only *phrases* prose around those
facts (and honest-errors when no provider is set). The one thing it does that the
others don't is render to **email-safe HTML** — table-based, inline-styled,
dark-mode aware, with bulletproof buttons and image fallbacks — so the same
newsletter renders in Outlook, Gmail and Apple Mail and as a hosted web page.

**Export-first** (roadmap-explicit): the outputs are a paste-ready ``.html`` for
the club's existing list tool, a plaintext alternative, and a hosted web version.
Direct sending stays out of scope until a provider adapter lands behind the
publish gate — we integrate with a club's list, we do not become a CRM.

Build 1 (this slice) — the deterministic core:
  - ``models`` — ``NewsletterSpec → Section → EmailBlock`` data model (+ formats)
  - ``theme``  — a club's brand → an email-safe flat hex palette
  - ``render`` — spec → email-safe HTML (+ a plaintext alternative)
  - ``store``  — multi-tenant persistence + the hosted-version publish/token index

Later builds add the auto-assembly + grounded AI editorial (build 2) and the web
surface: routes, the composer UI, exports and the hosted view (build 3).
"""

from .models import (
    DEFAULT_FORMAT,
    EMAIL_BLOCK_KINDS,
    NEWSLETTER_FORMATS,
    SECTION_BACKGROUNDS,
    EmailBlock,
    EmailFormat,
    NewsletterSpec,
    Section,
    bullet_list,
    button,
    card,
    divider,
    fixtures,
    format_for,
    heading,
    image,
    new_newsletter,
    quote,
    spacer,
    sponsor,
    stat_row,
    text,
)
from .render import render_email_html, render_plaintext
from .theme import EMAIL_FONT_STACK, email_palette

__all__ = [
    # models
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
    # theme
    "EMAIL_FONT_STACK",
    "email_palette",
    # render
    "render_email_html",
    "render_plaintext",
]
