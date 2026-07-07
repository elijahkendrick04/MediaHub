"""Email & newsletter composer (roadmap 1.17) — build 2: content gathering."""

from __future__ import annotations

import json

import pytest

from mediahub.email_design.grounding import NewsletterFacts, gather_facts
from mediahub.workflow.status import CardStatus
from mediahub.workflow.store import WorkflowStore


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("RUNS_DIR", raising=False)
    return tmp_path


def _runs_dir(tmp_path):
    d = tmp_path / "runs_v4"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ach(swim_id, name, event, atype, conf=0.92):
    return {
        "swim_id": swim_id,
        "swimmer_name": name,
        "event": event,
        "time": "1:02.34",
        "type": atype,
        "confidence": conf,
    }


def _make_run(tmp_path, run_id, profile_id, meet_date, achs):
    rd = _runs_dir(tmp_path)
    data = {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Test Meet", "date": meet_date},
        "recognition_report": {
            "ranked_achievements": [
                {"achievement": a, "priority": 1.0 - i * 0.1, "rank": i + 1}
                for i, a in enumerate(achs)
            ]
        },
        "cards": [],
    }
    (rd / f"{run_id}.json").write_text(json.dumps(data))
    return rd


def _approve(rd, run_id, *card_ids):
    ws = WorkflowStore(rd)
    for cid in card_ids:
        ws.set_status(run_id, cid, CardStatus.APPROVED)


def test_gathers_only_approved_cards_in_range(tmp_path):
    rd = _make_run(
        tmp_path, "run1", "club-a", "2026-06-12",
        [_ach("s1", "Maya", "100 Free", "pb_confirmed"),
         _ach("s2", "Tom", "50 Back", "medal_gold"),
         _ach("s3", "Ana", "200 IM", "pb_likely")],
    )
    _approve(rd, "run1", "s1", "s2")  # s3 left in queue
    from datetime import date

    facts = gather_facts("club-a", start=date(2026, 6, 1), end=date(2026, 6, 30), runs_dir=rd)
    titles = " ".join(r["title"] for r in facts.recaps)
    assert len(facts.recaps) == 2
    assert "Maya" in titles and "Tom" in titles and "Ana" not in titles


def test_out_of_range_runs_excluded(tmp_path):
    rd = _make_run(tmp_path, "r_may", "club-a", "2026-05-20", [_ach("s1", "Maya", "100 Free", "pb_confirmed")])
    _approve(rd, "r_may", "s1")
    from datetime import date

    facts = gather_facts("club-a", start=date(2026, 6, 1), end=date(2026, 6, 30), runs_dir=rd)
    # the out-of-range (May) run contributes no approved content
    assert facts.recaps == []
    assert facts.stats == []
    assert facts.spotlights == []


def test_tenant_isolation(tmp_path):
    rd = _make_run(tmp_path, "run1", "club-b", "2026-06-12", [_ach("s1", "Maya", "100 Free", "pb_confirmed")])
    _approve(rd, "run1", "s1")
    from datetime import date

    facts = gather_facts("club-a", start=date(2026, 6, 1), end=date(2026, 6, 30), runs_dir=rd)
    assert facts.recaps == []  # club-a cannot see club-b's run


def test_headline_stats_counted_from_approved(tmp_path):
    rd = _make_run(
        tmp_path, "run1", "club-a", "2026-06-12",
        [_ach("s1", "Maya", "100 Free", "pb_confirmed"),
         _ach("s2", "Tom", "50 Back", "medal_gold"),
         _ach("s3", "Ana", "200 IM", "club_record"),
         _ach("s4", "Maya", "50 Free", "official_pb_confirmed")],
    )
    _approve(rd, "run1", "s1", "s2", "s3", "s4")
    from datetime import date

    facts = gather_facts("club-a", start=date(2026, 6, 1), end=date(2026, 6, 30), runs_dir=rd)
    labels = {s["label"]: s["value"] for s in facts.stats}
    assert labels.get("PBs") == "2"  # s1 + s4 (both pb types)
    assert labels.get("Medal") == "1"
    assert labels.get("Club record") == "1"
    assert labels.get("Swimmers") == "3"  # Maya, Tom, Ana


def test_spotlight_for_swimmer_with_multiple_cards(tmp_path):
    rd = _make_run(
        tmp_path, "run1", "club-a", "2026-06-12",
        [_ach("s1", "Maya", "100 Free", "pb_confirmed"),
         _ach("s2", "Maya", "50 Free", "medal_gold")],
    )
    _approve(rd, "run1", "s1", "s2")
    from datetime import date

    facts = gather_facts("club-a", start=date(2026, 6, 1), end=date(2026, 6, 30), runs_dir=rd)
    assert any(s["name"] == "Maya" and s["n"] == 2 for s in facts.spotlights)


def test_sponsor_resolved_from_profile_registry(tmp_path):
    from datetime import date

    profile = {
        "profile_id": "club-a",
        "display_name": "Otters SC",
        "sponsors": [{"name": "AquaCo", "website": "https://aquaco.test", "active_from": "", "active_until": ""}],
    }
    facts = gather_facts(
        "club-a", start=date(2026, 6, 1), end=date(2026, 6, 30), runs_dir=_runs_dir(tmp_path), profile=profile
    )
    assert facts.club_name == "Otters SC"
    assert facts.sponsor and facts.sponsor["name"] == "AquaCo"
    assert facts.sponsor["href"] == "https://aquaco.test"


def test_legacy_sponsor_name_fallback(tmp_path):
    from datetime import date

    profile = {"display_name": "Otters", "sponsor_name": "Old Sponsor Ltd", "sponsors": []}
    facts = gather_facts(
        "club-a", start=date(2026, 6, 1), end=date(2026, 6, 30), runs_dir=_runs_dir(tmp_path), profile=profile
    )
    assert facts.sponsor and facts.sponsor["name"] == "Old Sponsor Ltd"


def test_period_label_single_month(tmp_path):
    from datetime import date

    facts = gather_facts("club-a", start=date(2026, 6, 1), end=date(2026, 6, 30), runs_dir=_runs_dir(tmp_path))
    assert facts.period == "June 2026"


def test_allowed_numbers_includes_stats_and_years(tmp_path):
    facts = NewsletterFacts(
        date_start="2026-06-01", date_end="2026-06-30",
        stats=[{"value": "12", "label": "PBs"}, {"value": "3", "label": "Medals"}],
    )
    allowed = facts.allowed_numbers()
    assert 12.0 in allowed and 3.0 in allowed and 2026.0 in allowed


def test_consent_blocked_swimmer_dropped_from_facts(tmp_path, monkeypatch):
    rd = _make_run(
        tmp_path, "run1", "club-a", "2026-06-12",
        [_ach("s1", "Maya", "100 Free", "pb_confirmed"),
         _ach("s2", "Tom", "50 Back", "medal_gold"),
         _ach("s3", "Tom", "100 Back", "pb_confirmed")],
    )
    _approve(rd, "run1", "s1", "s2", "s3")
    import mediahub.compliance.gate as gate

    monkeypatch.setattr(
        gate, "consent_block_reason",
        lambda profile_id, name, **kw: "no consent on file" if name == "Tom" else None,
    )
    from datetime import date

    facts = gather_facts("club-a", start=date(2026, 6, 1), end=date(2026, 6, 30), runs_dir=rd)
    blob = json.dumps(facts.recaps) + json.dumps(facts.spotlights) + facts.facts_block()
    assert "Tom" not in blob  # blocked athlete's name never ships in public text
    assert any("Maya" in r["title"] for r in facts.recaps)
    labels = {s["label"]: s["value"] for s in facts.stats}
    assert labels.get("Swimmers") == "1"  # only Maya counted


def test_card_image_resolver_is_used(tmp_path):
    rd = _make_run(tmp_path, "run1", "club-a", "2026-06-12", [_ach("s1", "Maya", "100 Free", "pb_confirmed")])
    _approve(rd, "run1", "s1")
    from datetime import date

    facts = gather_facts(
        "club-a", start=date(2026, 6, 1), end=date(2026, 6, 30), runs_dir=rd,
        card_image_url=lambda run_id, card_id: f"https://cdn.test/{run_id}/{card_id}.png",
    )
    assert facts.recaps[0]["image_url"] == "https://cdn.test/run1/s1.png"
