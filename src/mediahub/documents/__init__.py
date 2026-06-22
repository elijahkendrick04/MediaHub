"""documents — MediaHub's document engine (roadmap 1.15).

Clubs run on a handful of documents — the **meet programme**, the **season /
committee report**, the **sponsor proposal** and the **AGM deck**. This package
is one engine for all of them: multi-page, brand-tokened compositions assembled
from the same primitives the cards and charts use (text, tables, embedded charts,
KPI tiles, card/photo embeds), rendered to **PDF** (and PNG previews) with the
shared Playwright pipeline.

The intelligence rule holds throughout (CLAUDE.md): the **numbers are sacred** —
data blocks carry exact values from the deterministic fact base
(:mod:`charts.aggregates`, ``season_wrap``, the content pack); the AI drafting
flow only phrases prose around them and *honest-errors* when no provider is set.

Build 1 (this slice) — the deterministic core:
  - ``models``  — ``DocumentSpec → Section → Block`` data model (+ constructors)
  - ``theme``   — brand ``--mh-*`` role vars → a document's ``--doc-*`` CSS + fonts
  - ``render``  — spec → paged HTML → PDF / per-section PNG preview
  - ``cache``   — content-addressed output cache under ``DATA_DIR/document_cache``

Later builds add the club formats + grounded AI drafting (build 2), exports /
imports / PDF utilities (build 3), the deck presenter surface (build 4) and the
web surface (build 5).
"""

from .models import (
    BLOCK_KINDS,
    DOC_FORMATS,
    DOC_KINDS,
    PAGE_GEOMETRIES,
    SECTION_LAYOUTS,
    Block,
    DocumentSpec,
    PageGeometry,
    Section,
    bullet_list,
    card,
    chart,
    columns,
    divider,
    heading,
    kpi_row,
    media,
    new_document,
    quote,
    spacer,
    stat,
    table,
    text,
)
from .draft import default_outline, draft_prose, generate_document
from .formats import (
    FORMAT_BUILDERS,
    build_agm_deck,
    build_document,
    build_meet_programme,
    build_season_report,
    build_sponsor_proposal,
)
from .grounding import DocFacts, facts_from_run, facts_from_runs
from .render import render_document_html, render_document_pdf, render_section_png
from .theme import document_style, resolve_role_vars

__all__ = [
    # models
    "BLOCK_KINDS",
    "DOC_FORMATS",
    "DOC_KINDS",
    "SECTION_LAYOUTS",
    "PAGE_GEOMETRIES",
    "Block",
    "Section",
    "DocumentSpec",
    "PageGeometry",
    "new_document",
    "heading",
    "text",
    "bullet_list",
    "table",
    "chart",
    "card",
    "media",
    "stat",
    "kpi_row",
    "quote",
    "divider",
    "spacer",
    "columns",
    # render
    "render_document_html",
    "render_document_pdf",
    "render_section_png",
    # theme
    "resolve_role_vars",
    "document_style",
    # grounding (build 2)
    "DocFacts",
    "facts_from_run",
    "facts_from_runs",
    # formats (build 2)
    "FORMAT_BUILDERS",
    "build_document",
    "build_meet_programme",
    "build_season_report",
    "build_sponsor_proposal",
    "build_agm_deck",
    # AI drafting (build 2)
    "default_outline",
    "draft_prose",
    "generate_document",
]
