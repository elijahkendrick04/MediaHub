"""documents.formats — the four club document formats, built from real facts.

The deterministic half of the engine's club formats (roadmap 1.15). Each builder
turns a :class:`~documents.grounding.DocFacts` (numbers + tables + charts computed
in code) into a brand-tokened :class:`~documents.models.DocumentSpec`. The
structure and every datum are deterministic; the optional ``prose`` dict carries
the AI-drafted, number-validated wording (:mod:`documents.draft`) keyed by section
— pass ``None`` and you get the same document with real data and headings but no
narrative (honest: structure + facts, never fabricated prose).

  - ``meet_programme``  — a gala-night programme/recap from one meet
  - ``season_report``   — the committee/season report (grounded aggregates)
  - ``sponsor_proposal``— a sponsorship pitch (story + packages)
  - ``agm_deck``        — the AGM slide deck (presented; speaker notes from prose)
"""

from __future__ import annotations

from typing import Optional

from . import models as m
from .grounding import DocFacts
from .models import DocumentSpec, Section

# A default sponsorship-tier table. These are *offer definitions* a club sets, not
# facts about results — sensible starters the club edits, never fabricated stats.
DEFAULT_PACKAGES = {
    "columns": ["Package", "Season fee", "What's included"],
    "rows": [
        ["Bronze", "-", "Logo on the club website and season report"],
        ["Silver", "-", "Bronze + logo on result cards and meet programmes"],
        ["Gold", "-", "Silver + named kit/banner sponsor and social shout-outs"],
    ],
    "caption": "Partnership packages (set your own fees)",
}


def _p(prose: Optional[dict], key: str) -> str:
    if not prose:
        return ""
    val = prose.get(key)
    return str(val).strip() if val else ""


def _prose_block(prose: Optional[dict], key: str) -> list[m.Block]:
    txt = _p(prose, key)
    return [m.text(txt)] if txt else []


def _kpi_block(facts: DocFacts) -> list[m.Block]:
    return [m.kpi_row(facts.headline_stats)] if facts.headline_stats else []


def _chart_blocks(facts: DocFacts, *, limit: int = 3) -> list[m.Block]:
    return [m.chart(spec) for spec in facts.chart_specs[:limit]]


def _table_block(facts: DocFacts, name: str) -> list[m.Block]:
    t = facts.tables.get(name)
    if not t:
        return []
    return [m.table(t["columns"], t["rows"], caption=t.get("caption", ""))]


def _highlight_block(facts: DocFacts) -> list[m.Block]:
    return [m.bullet_list(facts.highlights)] if facts.highlights else []


def _cover_section(facts: DocFacts, title: str, *, deck: bool) -> Section:
    blocks = []
    if facts.period:
        blocks.append(m.text(facts.period.upper()))  # kicker (styled by cover layout)
    blocks.append(m.heading(title, 1))
    if facts.club_name:
        blocks.append(m.heading(facts.club_name, 3))
    return Section(blocks=blocks, layout="cover", background="primary" if deck else "")


def _meta(facts: DocFacts) -> dict:
    return {"club_name": facts.club_name, "period": facts.period, "date": facts.period}


# ---------------------------------------------------------------------------
# Season / committee report
# ---------------------------------------------------------------------------


def build_season_report(
    facts: DocFacts, *, brand_profile_id: str = "", prose: Optional[dict] = None
) -> DocumentSpec:
    title = facts.title or "Season report"
    sections: list[Section] = [_cover_section(facts, title, deck=False)]

    glance = (
        [m.heading("The season at a glance", 2)] + _kpi_block(facts) + _prose_block(prose, "intro")
    )
    sections.append(Section(blocks=glance))

    if facts.chart_specs:
        sections.append(
            Section(
                break_before=True, blocks=[m.heading("By the numbers", 2)] + _chart_blocks(facts)
            )
        )

    standout = (
        [m.heading("Standout performances", 2)]
        + _highlight_block(facts)
        + _prose_block(prose, "highlights")
        + _table_block(facts, "pb_makers")
        + _table_block(facts, "medal_table")
    )
    sections.append(Section(break_before=True, blocks=standout))

    if _p(prose, "outlook"):
        sections.append(
            Section(blocks=[m.heading("Looking ahead", 2)] + _prose_block(prose, "outlook"))
        )

    if _p(prose, "thanks"):
        sections.append(Section(blocks=[m.heading("Thank you", 2)] + _prose_block(prose, "thanks")))

    return DocumentSpec(
        title=title,
        subtitle=facts.period,
        kind="document",
        doc_format="season_report",
        geometry="a4",
        brand_profile_id=brand_profile_id,
        meta=_meta(facts),
        source_refs=facts.source_refs,
        sections=sections,
    )


# ---------------------------------------------------------------------------
# Meet programme / recap
# ---------------------------------------------------------------------------


def build_meet_programme(
    facts: DocFacts, *, brand_profile_id: str = "", prose: Optional[dict] = None
) -> DocumentSpec:
    title = facts.title or "Meet programme"
    sections: list[Section] = [_cover_section(facts, title, deck=False)]

    summary = [m.heading("Meet summary", 2)] + _kpi_block(facts) + _prose_block(prose, "intro")
    sections.append(Section(blocks=summary))

    results = (
        [m.heading("Results & standouts", 2)]
        + _highlight_block(facts)
        + _table_block(facts, "pb_makers")
        + _table_block(facts, "medal_table")
    )
    sections.append(Section(break_before=True, blocks=results))

    if facts.chart_specs:
        sections.append(Section(blocks=[m.heading("In charts", 2)] + _chart_blocks(facts, limit=2)))

    if _p(prose, "about"):
        sections.append(
            Section(blocks=[m.heading("About the club", 2)] + _prose_block(prose, "about"))
        )

    return DocumentSpec(
        title=title,
        subtitle=facts.period,
        kind="document",
        doc_format="meet_programme",
        geometry="a4",
        brand_profile_id=brand_profile_id,
        meta=_meta(facts),
        source_refs=facts.source_refs,
        sections=sections,
    )


# ---------------------------------------------------------------------------
# Sponsor proposal
# ---------------------------------------------------------------------------


def build_sponsor_proposal(
    facts: DocFacts,
    *,
    brand_profile_id: str = "",
    prose: Optional[dict] = None,
    packages: Optional[dict] = None,
) -> DocumentSpec:
    club = facts.club_name or "our club"
    title = f"Partner with {club}"
    sections: list[Section] = [_cover_section(facts, title, deck=False)]

    why = (
        [m.heading(f"Why partner with {club}", 2)]
        + _prose_block(prose, "pitch")
        + _kpi_block(facts)
    )
    sections.append(Section(blocks=why))

    season = [m.heading("Our season", 2)] + _highlight_block(facts) + _chart_blocks(facts, limit=2)
    sections.append(Section(break_before=True, blocks=season))

    pkg = packages or DEFAULT_PACKAGES
    pkg_blocks = [
        m.heading("Partnership packages", 2),
        m.table(pkg["columns"], pkg["rows"], caption=pkg.get("caption", "")),
    ] + _prose_block(prose, "packages")
    sections.append(Section(break_before=True, blocks=pkg_blocks))

    contact = _p(prose, "contact") or "Get in touch to discuss a partnership that works for you."
    sections.append(Section(blocks=[m.heading("Get in touch", 2), m.text(contact)]))

    return DocumentSpec(
        title=title,
        subtitle=facts.period,
        kind="document",
        doc_format="sponsor_proposal",
        geometry="a4",
        brand_profile_id=brand_profile_id,
        meta=_meta(facts),
        source_refs=facts.source_refs,
        sections=sections,
    )


# ---------------------------------------------------------------------------
# AGM deck
# ---------------------------------------------------------------------------


def build_agm_deck(
    facts: DocFacts, *, brand_profile_id: str = "", prose: Optional[dict] = None
) -> DocumentSpec:
    title = facts.title or "AGM"
    sections: list[Section] = [
        Section(
            blocks=[m.heading(title, 1), m.heading(facts.period or "", 3)]
            if facts.period
            else [m.heading(title, 1)],
            layout="cover",
            background="primary",
            notes=_p(prose, "cover"),
        )
    ]

    sections.append(
        Section(
            blocks=[m.heading("The year in numbers", 2)] + _kpi_block(facts),
            notes=_p(prose, "numbers"),
        )
    )

    if facts.highlights:
        sections.append(
            Section(
                blocks=[m.heading("Highlights", 2), m.bullet_list(facts.highlights)],
                notes=_p(prose, "highlights"),
            )
        )

    if facts.chart_specs:
        sections.append(
            Section(
                blocks=[m.heading("By the numbers", 2), m.chart(facts.chart_specs[0])],
                notes=_p(prose, "chart"),
            )
        )

    if facts.tables.get("medal_table"):
        t = facts.tables["medal_table"]
        sections.append(
            Section(
                blocks=[m.heading("Medal table", 2), m.table(t["columns"], t["rows"])],
                notes=_p(prose, "medals"),
            )
        )

    sections.append(
        Section(
            blocks=[m.heading("Thank you", 1)],
            layout="closing",
            background="accent",
            notes=_p(prose, "thanks"),
        )
    )

    return DocumentSpec(
        title=title,
        subtitle=facts.period,
        kind="deck",
        doc_format="agm_deck",
        geometry="slide_16_9",
        brand_profile_id=brand_profile_id,
        meta=_meta(facts),
        source_refs=facts.source_refs,
        sections=sections,
    )


FORMAT_BUILDERS = {
    "meet_programme": build_meet_programme,
    "season_report": build_season_report,
    "sponsor_proposal": build_sponsor_proposal,
    "agm_deck": build_agm_deck,
}


def build_document(doc_format: str, facts: DocFacts, **kwargs) -> DocumentSpec:
    """Dispatch to the right format builder (deterministic skeleton + real data)."""
    builder = FORMAT_BUILDERS.get(doc_format)
    if builder is None:
        raise ValueError(f"unknown document format: {doc_format!r}")
    return builder(facts, **kwargs)


__all__ = [
    "DEFAULT_PACKAGES",
    "FORMAT_BUILDERS",
    "build_document",
    "build_meet_programme",
    "build_season_report",
    "build_sponsor_proposal",
    "build_agm_deck",
]
