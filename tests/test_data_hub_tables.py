"""data_hub.tables — read-only canonical views over the engine stores (1.13)."""

from __future__ import annotations

import json

import pytest

from mediahub.athletes import registry as areg
from mediahub.club_records import store as crs
from mediahub.data_hub import tables
from mediahub.data_hub.models import Provenance


def _run_payload(profile_id="club-a"):
    return {
        "run_id": "run1",
        "profile_id": profile_id,
        "file_name": "meet.hy3",
        "our_swim_count": 2,
        "recognition_report": {"n_achievements": 5},
        "meet": {
            "name": "Spring Open 2026",
            "venue": "Wales NPC",
            "course": "LC",
            "start_date": "2026-03-14",
            "clubs": {
                "ABCD": {"code": "ABCD", "name": "Aqua Club", "is_host": True, "aliases": ["Aqua"]},
            },
            "swimmers": {
                "s1": {
                    "first_name": "Maya",
                    "last_name": "Patel",
                    "gender": "F",
                    "age_at_meet": 14,
                    "club_name": "Aqua Club",
                    "asa_id": "123",
                    "identity_confidence": "high",
                },
                "s2": {
                    "first_name": "Sam",
                    "last_name": "Okafor",
                    "gender": "M",
                    "identity_confidence": "low",
                },
            },
            "results": [
                {
                    "swimmer_key": "s1",
                    "distance": 100,
                    "stroke": "FR",
                    "course": "LC",
                    "age_band": "13-14",
                    "finals_time_cs": 6532,
                    "place": 1,
                    "status": "completed",
                    "swim_date": "2026-03-14",
                },
                {
                    "swimmer_key": "s2",
                    "distance": 50,
                    "stroke": "BK",
                    "course": "LC",
                    "finals_time_cs": None,
                    "status": "dq",
                },
            ],
            "warnings": [
                {"code": "x", "message": "Age missing for one swimmer", "severity": "warn"},
            ],
        },
    }


@pytest.fixture()
def runs_dir(tmp_path):
    d = tmp_path / "runs_v4"
    d.mkdir()
    (d / "run1.json").write_text(json.dumps(_run_payload()), encoding="utf-8")
    return d


def test_results_table_shape_and_flags(runs_dir):
    t = tables.results_table("club-a", "run1", runs_dir=runs_dir)
    assert t is not None
    assert t.row_count == 2
    assert t.cell(0, "swimmer").display == "Maya Patel"
    assert t.cell(0, "time").display == "1:05.32"
    assert t.cell(0, "time").provenance == Provenance.PARSED
    # The DQ swim has no finishing time → flagged, shown as status not a time.
    assert t.cell(1, "time").flagged is True
    assert t.cell(1, "time").display == "DQ"
    # Meet-level parse warning surfaced on the table.
    assert any("Age missing" in w.message for w in t.warnings)


def test_results_table_tenant_isolation(runs_dir):
    # A different org cannot read this run's results.
    assert tables.results_table("club-b", "run1", runs_dir=runs_dir) is None


def test_swimmers_table_low_confidence_flagged(runs_dir):
    t = tables.swimmers_table("club-a", "run1", runs_dir=runs_dir)
    assert t.row_count == 2
    low = [r for r in range(t.row_count) if t.cell(r, "name").display == "Sam Okafor"][0]
    assert t.cell(low, "identity").flagged is True


def test_clubs_table(runs_dir):
    t = tables.clubs_table("club-a", "run1", runs_dir=runs_dir)
    assert t.row_count == 1
    assert t.cell(0, "name").display == "Aqua Club"
    assert t.cell(0, "is_host").display == "Yes"


def test_meets_table_lists_runs(runs_dir):
    t = tables.meets_table("club-a", runs_dir=runs_dir)
    assert t.row_count == 1
    assert t.cell(0, "meet").display == "Spring Open 2026"
    assert t.cell(0, "our_swims").value == 2
    assert t.cell(0, "achievements").value == 5


def test_athletes_and_records_tables(tmp_path):
    db = tmp_path / "data.db"
    areg.get_or_create("club-a", "Maya Patel", db_path=db)
    crs.upsert_record(
        "club-a",
        distance=100,
        stroke="FR",
        course="LC",
        gender="F",
        age_group="open",
        time_cs=6532,
        holder="Maya Patel",
        source="csv-import",
        db_path=db,
    )
    at = tables.athletes_table("club-a", db_path=db)
    assert at.row_count == 1
    assert at.cell(0, "name").display == "Maya Patel"

    rt = tables.records_table("club-a", db_path=db)
    assert rt.row_count == 1
    assert rt.cell(0, "time").display == "1:05.32"
    # csv-import source → IMPORTED provenance badge.
    assert rt.cell(0, "time").provenance == Provenance.IMPORTED


def test_dispatcher_resolves_ids(runs_dir, tmp_path):
    db = tmp_path / "data.db"
    assert tables.get_canonical_table("club-a", "meets", runs_dir=runs_dir, db_path=db).kind == "meets"
    assert (
        tables.get_canonical_table("club-a", "results:run1", runs_dir=runs_dir, db_path=db).kind
        == "results"
    )
    assert tables.get_canonical_table("club-a", "unknown:thing", runs_dir=runs_dir) is None
    assert tables.get_canonical_table("club-a", "org:whatever", runs_dir=runs_dir) is None


def test_list_canonical_tables_includes_singletons(runs_dir, tmp_path):
    db = tmp_path / "data.db"
    listed = tables.list_canonical_tables("club-a", runs_dir=runs_dir, db_path=db)
    ids = {t["table_id"] for t in listed}
    assert {"athletes", "records", "meets"} <= ids
    assert "results:run1" in ids
