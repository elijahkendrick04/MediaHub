"""documents.models — the typed data model for a multi-page club document (roadmap 1.15).

A :class:`DocumentSpec` is a fully-resolved, **render-ready** description of one
document: a meet programme, a season/committee report, a sponsor proposal, or an
AGM deck. It is plain, JSON-round-trippable data — *sections → blocks* — that the
renderer (:mod:`documents.render`) turns into brand-tokened paged HTML → PDF (and
per-page PNG previews) deterministically.

The contract mirrors :mod:`charts.models` (CLAUDE.md rule — *facts are code*):

  - **The numbers are sacred.** A document never invents a statistic. Data blocks
    (``table``/``stat``/``chart``) carry exact values supplied by the deterministic
    fact base (:mod:`charts.aggregates`, ``season_wrap``, the content pack); the AI
    drafting flow (:mod:`documents.draft`) only ever phrases prose around them and
    is number-validated.
  - **Deterministic & additive.** Same spec + same brand role vars → byte-identical
    HTML. ``to_dict``/``from_dict`` round-trip through JSON without loss; unknown
    keys are dropped and missing optionals default, so older/newer persisted shapes
    load cleanly (mirrors ``charts.models`` / ``CreativeBrief.from_dict``).

Shape::

    DocumentSpec(kind="document"|"deck")
      └─ sections: [Section]
           └─ blocks: [Block(kind, props)]

A *document* (programme/report/proposal) flows its content and paginates across
sheets; a *deck* (AGM) renders one fixed slide per section with speaker notes.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

# ---------------------------------------------------------------------------
# Vocabularies — tuples (not enums) so persisted specs stay plain JSON and new
# values are purely additive.
# ---------------------------------------------------------------------------

# The two document families the engine renders.
DOC_KINDS: tuple[str, ...] = (
    "document",  # flowing paper document — programme / report / proposal
    "deck",  # slide deck — one fixed slide per section, with speaker notes
)

# The club document formats the AI drafting flow knows how to build (build 2).
DOC_FORMATS: tuple[str, ...] = (
    "meet_programme",  # running order / heat sheet / club info for a gala
    "season_report",  # committee/season report — grounded aggregates + narrative
    "sponsor_proposal",  # sponsorship pitch — reach, audience, packages
    "agm_deck",  # AGM slide deck — the year in review, presented
    "blank",  # an empty document the user fills in
)

# Page geometries. ``css_size`` is the ``@page { size: ... }`` value; width/height
# are the matching CSS box dimensions for each sheet/slide. ``kind`` drives the
# render mode: ``paper`` flows + paginates, ``slide`` is one fixed box per section.
@dataclass(frozen=True)
class PageGeometry:
    name: str
    width: str  # CSS length, e.g. "210mm" or "1280px"
    height: str  # CSS length
    kind: str = "paper"  # "paper" | "slide"
    margin: str = "16mm"  # default content inset


PAGE_GEOMETRIES: dict[str, PageGeometry] = {
    "a4": PageGeometry("a4", "210mm", "297mm", "paper", "16mm"),
    "a4_landscape": PageGeometry("a4_landscape", "297mm", "210mm", "paper", "16mm"),
    "letter": PageGeometry("letter", "216mm", "279mm", "paper", "16mm"),
    "letter_landscape": PageGeometry("letter_landscape", "279mm", "216mm", "paper", "16mm"),
    # Decks are rendered at a fixed pixel slide box (16:9 / 4:3); the renderer
    # maps each section to one slide. 1280×720 keeps a clean 16:9 at print DPI.
    "slide_16_9": PageGeometry("slide_16_9", "1280px", "720px", "slide", "56px"),
    "slide_4_3": PageGeometry("slide_4_3", "1024px", "768px", "slide", "56px"),
}

DEFAULT_GEOMETRY = "a4"
DEFAULT_DECK_GEOMETRY = "slide_16_9"

# The map from a club document format to its natural geometry + document kind.
FORMAT_DEFAULTS: dict[str, tuple[str, str]] = {
    # format: (kind, geometry)
    "meet_programme": ("document", "a4"),
    "season_report": ("document", "a4"),
    "sponsor_proposal": ("document", "a4"),
    "agm_deck": ("deck", "slide_16_9"),
    "blank": ("document", "a4"),
}

# Content block kinds. Renderer dispatches on ``kind``; unknown kinds render as
# nothing (forward-compatible). ``props`` is a plain JSON-able dict per kind.
BLOCK_KINDS: tuple[str, ...] = (
    "heading",  # props: {text, level: 1..3}
    "text",  # props: {text, align?}  — light inline markup (**bold**, *italic*)
    "list",  # props: {items: [str], ordered: bool}
    "table",  # props: {columns: [str], rows: [[str]], caption?}
    "chart",  # props: {chart: ChartSpec-dict}  — embedded as inline brand SVG
    "card",  # props: {src, alt?, caption?}      — a content-pack card image
    "media",  # props: {src, alt?, caption?, fit?}— a photo / logo
    "stat",  # props: {value, label, sublabel?}  — a single KPI tile
    "kpi_row",  # props: {stats: [{value,label,sublabel?}]}
    "quote",  # props: {text, attribution?}
    "divider",  # props: {}
    "spacer",  # props: {size?: sm|md|lg}
    "columns",  # props: {columns: [[block-dict, ...], ...]}  — nested blocks
)

# Section layout intents. ``flow`` is body content; the others are slide/cover
# treatments. Renderer falls back to ``flow`` for unknown layouts.
SECTION_LAYOUTS: tuple[str, ...] = (
    "flow",  # ordinary body content
    "cover",  # title page / opening slide — big title, brand band
    "section_break",  # divider page — section title centred
    "centered",  # vertically + horizontally centred (statement slide)
    "two_col",  # blocks split into two even columns
    "closing",  # outro / thank-you slide
)

# Background roles a slide/section can paint (mapped to brand role vars).
BACKGROUND_ROLES: tuple[str, ...] = ("", "surface", "ground", "primary", "accent")


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:10]}"


def _clamp_level(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 2
    return max(1, min(3, n))


# ---------------------------------------------------------------------------
# Block
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Block:
    """One content block. ``props`` is a kind-specific, JSON-able payload."""

    kind: str
    props: dict[str, Any] = field(default_factory=dict)
    block_id: str = ""

    def __post_init__(self) -> None:
        if not self.block_id:
            object.__setattr__(self, "block_id", _new_id("blk"))
        if not isinstance(self.props, dict):
            object.__setattr__(self, "props", {})

    def to_dict(self) -> dict[str, Any]:
        return {"kind": self.kind, "props": dict(self.props), "block_id": self.block_id}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Block":
        if not isinstance(raw, dict):
            return cls(kind="text", props={"text": ""})
        return cls(
            kind=str(raw.get("kind") or "text"),
            props=dict(raw.get("props") or {}),
            block_id=str(raw.get("block_id") or ""),
        )


# Typed, validated convenience constructors — the authoring surface. Keeping the
# storage a plain dict + helpers (rather than one dataclass per kind) keeps the
# model small and additive while still validating at construction.


def heading(text: str, level: int = 2) -> Block:
    return Block("heading", {"text": str(text), "level": _clamp_level(level)})


def text(body: str, *, align: str = "left") -> Block:
    align = align if align in ("left", "center", "right", "justify") else "left"
    return Block("text", {"text": str(body), "align": align})


def bullet_list(items: list[str], *, ordered: bool = False) -> Block:
    return Block("list", {"items": [str(i) for i in (items or [])], "ordered": bool(ordered)})


def table(columns: list[str], rows: list[list[Any]], *, caption: str = "") -> Block:
    return Block(
        "table",
        {
            "columns": [str(c) for c in (columns or [])],
            "rows": [[("" if c is None else str(c)) for c in r] for r in (rows or [])],
            "caption": str(caption),
        },
    )


def chart(chart_spec: Any) -> Block:
    """Embed a chart. Accepts a ``charts.ChartSpec`` or its ``to_dict()``."""
    spec_dict = chart_spec.to_dict() if hasattr(chart_spec, "to_dict") else dict(chart_spec or {})
    return Block("chart", {"chart": spec_dict})


def card(src: str, *, caption: str = "", alt: str = "") -> Block:
    return Block("card", {"src": str(src), "caption": str(caption), "alt": str(alt)})


def media(src: str, *, caption: str = "", alt: str = "", fit: str = "cover") -> Block:
    fit = fit if fit in ("cover", "contain") else "cover"
    return Block("media", {"src": str(src), "caption": str(caption), "alt": str(alt), "fit": fit})


def stat(value: str, label: str, *, sublabel: str = "") -> Block:
    return Block("stat", {"value": str(value), "label": str(label), "sublabel": str(sublabel)})


def kpi_row(stats: list[dict[str, str]]) -> Block:
    clean = []
    for s in stats or []:
        if isinstance(s, dict) and (s.get("value") is not None):
            clean.append(
                {
                    "value": str(s.get("value", "")),
                    "label": str(s.get("label", "")),
                    "sublabel": str(s.get("sublabel", "")),
                }
            )
    return Block("kpi_row", {"stats": clean})


def quote(text_body: str, *, attribution: str = "") -> Block:
    return Block("quote", {"text": str(text_body), "attribution": str(attribution)})


def divider() -> Block:
    return Block("divider", {})


def spacer(size: str = "md") -> Block:
    size = size if size in ("sm", "md", "lg") else "md"
    return Block("spacer", {"size": size})


def columns(*column_blocks: list[Block]) -> Block:
    cols = [[b.to_dict() for b in col] for col in column_blocks]
    return Block("columns", {"columns": cols})


# ---------------------------------------------------------------------------
# Section
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Section:
    """A run of blocks. One *section* = one slide in a deck; in a document it is a
    logical section that may force a page break before it and otherwise flows."""

    blocks: list[Block] = field(default_factory=list)
    notes: str = ""  # speaker notes (deck) — never printed in the document body
    layout: str = "flow"
    break_before: bool = False  # document: start this section on a new sheet
    background: str = ""  # slide/section background role
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
            "notes": self.notes,
            "layout": self.layout,
            "break_before": self.break_before,
            "background": self.background,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Section":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            blocks=[Block.from_dict(b) for b in (raw.get("blocks") or [])],
            notes=str(raw.get("notes") or ""),
            layout=str(raw.get("layout") or "flow"),
            break_before=bool(raw.get("break_before")),
            background=str(raw.get("background") or ""),
            section_id=str(raw.get("section_id") or ""),
        )


# ---------------------------------------------------------------------------
# DocumentSpec
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentSpec:
    """A complete, render-ready multi-page document."""

    title: str
    sections: list[Section] = field(default_factory=list)
    kind: str = "document"  # DOC_KINDS
    doc_format: str = "blank"  # DOC_FORMATS — informational/provenance
    geometry: str = DEFAULT_GEOMETRY  # PAGE_GEOMETRIES key
    subtitle: str = ""
    brand_profile_id: str = ""
    meta: dict[str, Any] = field(default_factory=dict)  # author/date/club/period…
    source_refs: list[str] = field(default_factory=list)  # provenance (CLAUDE.md)
    doc_id: str = ""

    def __post_init__(self) -> None:
        if not self.doc_id:
            object.__setattr__(self, "doc_id", _new_id("doc"))
        if self.kind not in DOC_KINDS:
            object.__setattr__(self, "kind", "document")
        if self.geometry not in PAGE_GEOMETRIES:
            object.__setattr__(
                self,
                "geometry",
                DEFAULT_DECK_GEOMETRY if self.kind == "deck" else DEFAULT_GEOMETRY,
            )

    @property
    def page_geometry(self) -> PageGeometry:
        return PAGE_GEOMETRIES.get(self.geometry, PAGE_GEOMETRIES[DEFAULT_GEOMETRY])

    @property
    def is_deck(self) -> bool:
        return self.kind == "deck"

    def to_dict(self) -> dict[str, Any]:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "subtitle": self.subtitle,
            "kind": self.kind,
            "doc_format": self.doc_format,
            "geometry": self.geometry,
            "brand_profile_id": self.brand_profile_id,
            "meta": dict(self.meta),
            "source_refs": list(self.source_refs),
            "sections": [s.to_dict() for s in self.sections],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "DocumentSpec":
        if not isinstance(raw, dict):
            return cls(title="Untitled")
        return cls(
            title=str(raw.get("title") or "Untitled"),
            subtitle=str(raw.get("subtitle") or ""),
            kind=str(raw.get("kind") or "document"),
            doc_format=str(raw.get("doc_format") or "blank"),
            geometry=str(raw.get("geometry") or DEFAULT_GEOMETRY),
            brand_profile_id=str(raw.get("brand_profile_id") or ""),
            meta=dict(raw.get("meta") or {}),
            source_refs=[str(s) for s in (raw.get("source_refs") or [])],
            sections=[Section.from_dict(s) for s in (raw.get("sections") or [])],
            doc_id=str(raw.get("doc_id") or ""),
        )


def new_document(
    title: str,
    doc_format: str = "blank",
    *,
    brand_profile_id: str = "",
    subtitle: str = "",
) -> DocumentSpec:
    """Start an empty spec wired to a format's natural kind + geometry."""
    fmt = doc_format if doc_format in DOC_FORMATS else "blank"
    kind, geometry = FORMAT_DEFAULTS.get(fmt, ("document", DEFAULT_GEOMETRY))
    return DocumentSpec(
        title=str(title),
        subtitle=str(subtitle),
        kind=kind,
        doc_format=fmt,
        geometry=geometry,
        brand_profile_id=str(brand_profile_id),
    )


__all__ = [
    "DOC_KINDS",
    "DOC_FORMATS",
    "BLOCK_KINDS",
    "SECTION_LAYOUTS",
    "BACKGROUND_ROLES",
    "PAGE_GEOMETRIES",
    "PageGeometry",
    "FORMAT_DEFAULTS",
    "DEFAULT_GEOMETRY",
    "DEFAULT_DECK_GEOMETRY",
    "Block",
    "Section",
    "DocumentSpec",
    "new_document",
    # block constructors
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
]
