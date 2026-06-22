"""Document engine (roadmap 1.15) — build 2: grounded facts + format builders."""

from __future__ import annotations

import pytest

from mediahub.documents import formats
from mediahub.documents.grounding import facts_from_run, facts_from_runs
from mediahub.documents.render import render_document_html

_RV = {
    "--mh-primary": "#A30D2D",
    "--mh-accent": "#F2C14E",
    "--mh-surface": "#0B1B2E",
    "--mh-on-primary": "#FFFFFF",
    "--mh-on-surface": "#FFFFFF",
}


def _run(name="County Champs"):
    return {
        "canonical_meet": {
            "name": name,
            "swimmers": {"s1": {}, "s2": {}, "s3": {}},
            "results": [{"swimmer_key": "s1"}, {"swimmer_key": "s2"}, {"swimmer_key": "s3"}],
        },
        "recognition_report": {
            "meet_name": name,
            "meet_date": "June 2026",
            "n_swims_analysed": 18,
            "ranked_achievements": [
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Tunde Adeyemi", "swimmer_id": "s1", "event": "100m Free", "swim_id": "a1", "raw_facts": {"drop_seconds": 1.42}}},
                {"achievement": {"type": "pb_confirmed", "swimmer_name": "Jess Smith", "swimmer_id": "s2", "event": "200m Free", "swim_id": "a2", "raw_facts": {"drop_seconds": 2.6}}},
                {"achievement": {"type": "medal_gold", "swimmer_name": "Tunde Adeyemi", "swimmer_id": "s1", "event": "100m Free", "swim_id": "a1"}},
                {"achievement": {"type": "medal_silver", "swimmer_name": "Jess Smith", "swimmer_id": "s2", "event": "200m Free", "swim_id": "a2"}},
            ],
        },
    }


# ---------------------------------------------------------------------------
# Grounding
# ---------------------------------------------------------------------------


def test_facts_from_run_carries_real_numbers_and_tables():
    f = facts_from_run(_run(), club_name="Otters SC", run_id="r1")
    assert f.scope == "meet"
    assert f.club_name == "Otters SC"
    assert f.numbers["personal_bests"] == 2
    assert f.numbers["medals_total"] == 2
    assert "pb_makers" in f.tables
    assert "medal_table" in f.tables
    assert any("personal best" in h.lower() for h in f.highlights)
    assert "run:r1" in f.source_refs


def test_facts_allowed_numbers_includes_period_year():
    f = facts_from_run(_run(), club_name="Otters SC")
    allowed = f.allowed_numbers()
    assert 2.0 in allowed  # the PB / medal counts
    assert 2026.0 in allowed  # the period year, for prose


def test_facts_from_runs_merges_season():
    f = facts_from_runs([_run("Meet A"), _run("Meet B")], club_name="Otters SC", period="2025/26")
    assert f.scope == "season"
    assert f.numbers["meets"] == 2
    assert f.numbers["personal_bests"] == 4  # 2 + 2 across the window
    assert f.numbers["medals_total"] == 4
    assert "pb_makers" in f.tables


# ---------------------------------------------------------------------------
# Format builders (deterministic — no AI)
# ---------------------------------------------------------------------------


def test_season_report_structure_and_data():
    f = facts_from_run(_run(), club_name="Otters SC", run_id="r1")
    spec = formats.build_season_report(f, brand_profile_id="club-1")
    assert spec.kind == "document"
    assert spec.doc_format == "season_report"
    assert spec.brand_profile_id == "club-1"
    kinds = [b.kind for s in spec.sections for b in s.blocks]
    assert "kpi_row" in kinds
    assert "table" in kinds
    assert "run:r1" in spec.source_refs


def test_agm_deck_is_a_deck_with_cover_and_closing():
    f = facts_from_run(_run(), club_name="Otters SC")
    spec = formats.build_agm_deck(f)
    assert spec.kind == "deck"
    assert spec.geometry == "slide_16_9"
    assert spec.sections[0].layout == "cover"
    assert spec.sections[-1].layout == "closing"


def test_sponsor_proposal_has_default_packages():
    f = facts_from_run(_run(), club_name="Otters SC")
    spec = formats.build_sponsor_proposal(f)
    assert spec.doc_format == "sponsor_proposal"
    tables = [b for s in spec.sections for b in s.blocks if b.kind == "table"]
    assert any("Package" in t.props["columns"] for t in tables)


def test_meet_programme_builds():
    f = facts_from_run(_run(), club_name="Otters SC")
    spec = formats.build_meet_programme(f)
    assert spec.doc_format == "meet_programme"
    assert spec.kind == "document"


def test_build_document_dispatch_and_unknown():
    f = facts_from_run(_run())
    assert formats.build_document("agm_deck", f).kind == "deck"
    with pytest.raises(ValueError):
        formats.build_document("not_a_format", f)


def test_prose_is_injected_when_provided():
    f = facts_from_run(_run(), club_name="Otters SC")
    spec = formats.build_season_report(f, prose={"intro": "What a season it was.", "thanks": "Thank you all."})
    html = render_document_html(spec, role_vars=_RV)
    assert "What a season it was." in html
    assert "Thank you all." in html


def test_built_report_renders_to_html_with_real_numbers():
    f = facts_from_run(_run(), club_name="Otters SC", run_id="r1")
    spec = formats.build_season_report(f)
    html = render_document_html(spec, role_vars=_RV)
    assert "Otters SC" in html
    assert ">2<" in html  # a real KPI value (PBs / medals)
    assert "Top personal-best makers" in html  # table caption
    assert "Tunde Adeyemi" in html  # real swimmer name from the data
