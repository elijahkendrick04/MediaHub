"""Season wraps / monthly recap packs (W.8) — the deterministic core.

Everything against tmp_path: fake runs_v4 snapshots in a throwaway runs dir,
drafts persisted under a throwaway DATA_DIR. No network, no LLM — the
aggregator is pure counting, and the scheduler handler's notify is captured
by a fake channel.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from mediahub import scheduler
from mediahub.season_wrap import (
    TASK_TYPE,
    aggregate_window,
    build_monthly_draft,
    build_season_draft,
    list_drafts,
    load_draft,
    monthly_wrap_task_handler,
    register_season_wrap_task,
    save_draft,
)
from mediahub.season_wrap import task as wrap_task

ORG_A = "org-a"
ORG_B = "org-b"


# --- snapshot factory --------------------------------------------------------


def _ra(atype, swimmer, event, *, priority, rank, raw=None, headline=""):
    return {
        "achievement": {
            "type": atype,
            "swimmer_name": swimmer,
            "event": event,
            "headline": headline or f"{swimmer} — {event} ({atype})",
            "raw_facts": raw or {},
        },
        "priority": priority,
        "rank": rank,
    }


def _write_snapshot(runs_dir, run_id, profile_id, meet_name, start_date, ranked, swim_traces=None):
    rr = {"ranked_achievements": ranked}
    if swim_traces is not None:
        rr["swim_traces"] = swim_traces
    payload = {
        "run_id": run_id,
        "profile_id": profile_id,
        "started_at": f"{start_date}T09:00:00+00:00",
        "meet": {"name": meet_name, "start_date": start_date},
        "recognition_report": rr,
    }
    (runs_dir / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture()
def runs_dir(tmp_path):
    d = tmp_path / "runs_v4"
    d.mkdir()

    # Run 1 — org A, 5 June 2026, with swim traces (the true swim count).
    _write_snapshot(
        d,
        "run-a1",
        ORG_A,
        "Swansea Spring Open",
        "2026-06-05",
        [
            _ra(
                "club_record",
                "Owen Hughes",
                "50m Butterfly (LC)",
                priority=0.95,
                rank=1,
                raw={"time_cs": 2599},
            ),
            _ra(
                "pb_confirmed",
                "Maya Patel",
                "100m Freestyle (LC)",
                priority=0.90,
                rank=2,
                raw={"drop_pct": 2.1},
            ),
            _ra("medal_gold", "Maya Patel", "100m Freestyle (LC)", priority=0.80, rank=3),
            _ra("club_debut", "Ffion Davies", "50m Backstroke (LC)", priority=0.40, rank=4),
        ],
        swim_traces=[
            {"swimmer_name": "Maya Patel", "event": "100m Freestyle (LC)"},
            {"swimmer_name": "Maya Patel", "event": "200m IM (LC)"},
            {"swimmer_name": "Maya Patel", "event": "50m Freestyle (LC)"},
            {"swimmer_name": "Owen Hughes", "event": "50m Butterfly (LC)"},
            {"swimmer_name": "Ffion Davies", "event": "50m Backstroke (LC)"},
        ],
    )

    # Run 2 — org A, 20 June 2026, no traces (achievement-count fallback).
    _write_snapshot(
        d,
        "run-a2",
        ORG_A,
        "Cardiff June Meet",
        "2026-06-20",
        [
            _ra(
                "pb_confirmed",
                "Owen Hughes",
                "100m Breaststroke (LC)",
                priority=0.85,
                rank=1,
                raw={"drop_pct": 4.5},
            ),
            _ra(
                "official_pb_confirmed",
                "Maya Patel",
                "200m IM (LC)",
                priority=0.70,
                rank=2,
                raw={"drop_pct": 1.0},
            ),
            _ra("medal_silver", "Ffion Davies", "50m Backstroke (LC)", priority=0.60, rank=3),
            _ra("race_milestone_50", "Maya Patel", "50m Freestyle (LC)", priority=0.50, rank=4),
        ],
    )

    # Org B in the same window — must never leak into org A's wrap.
    _write_snapshot(
        d,
        "run-b1",
        ORG_B,
        "Rival Club Gala",
        "2026-06-10",
        [_ra("medal_gold", "Someone Else", "50m Freestyle (LC)", priority=0.9, rank=1)],
    )

    # Org A but outside June — must be window-filtered out.
    _write_snapshot(
        d,
        "run-a3",
        ORG_A,
        "July Open",
        "2026-07-03",
        [_ra("medal_bronze", "Maya Patel", "100m Freestyle (LC)", priority=0.9, rank=1)],
    )

    # Workflow sidecar + junk file — both skipped silently.
    (d / "run-a1__workflow.json").write_text('{"cards": {}}', encoding="utf-8")
    (d / "broken.json").write_text("not json", encoding="utf-8")
    return d


# --- aggregation -------------------------------------------------------------


def test_window_filtering_and_org_isolation(runs_dir):
    stats = aggregate_window(ORG_A, runs_dir, start="2026-06-01", end="2026-06-30")
    assert stats.n_runs == 2
    assert stats.meet_names == ["Swansea Spring Open", "Cardiff June Meet"]
    # Nothing from org B, nothing from July.
    assert stats.total_achievements == 8
    assert stats.medals_by_colour["bronze"] == 0
    assert all("Rival" not in m for m in stats.meet_names)


def test_counts_exact(runs_dir):
    stats = aggregate_window(ORG_A, runs_dir, start="2026-06-01", end="2026-06-30")
    assert stats.n_pbs == 3  # pb_confirmed x2 + official_pb_confirmed
    assert stats.n_medals == 2
    assert stats.medals_by_colour == {"gold": 1, "silver": 1, "bronze": 0}
    assert stats.n_club_records == 1
    assert stats.n_debuts == 1
    assert stats.n_milestones == 1
    assert stats.n_qual_hits == 0
    assert stats.fastest_club_record["swimmer"] == "Owen Hughes"
    assert stats.fastest_club_record["time_cs"] == 2599


def test_busiest_swimmer_and_biggest_improver(runs_dir):
    stats = aggregate_window(ORG_A, runs_dir, start="2026-06-01", end="2026-06-30")
    # Maya: 3 traced swims (run 1) + 2 achievement-fallback swims (run 2).
    assert stats.busiest_swimmer == {"name": "Maya Patel", "swims": 5}
    assert stats.biggest_improver == {
        "swimmer": "Owen Hughes",
        "event": "100m Breaststroke (LC)",
        "drop_pct": 4.5,
    }


def test_leaderboard_top5_deterministic(runs_dir):
    stats = aggregate_window(ORG_A, runs_dir, start="2026-06-01", end="2026-06-30")
    assert stats.leaderboard == [
        {"swimmer": "Maya Patel", "achievements": 4},
        {"swimmer": "Ffion Davies", "achievements": 2},  # alphabetical tie-break
        {"swimmer": "Owen Hughes", "achievements": 2},
    ]


def test_stat_chips_non_zero_only_and_capped(runs_dir):
    stats = aggregate_window(ORG_A, runs_dir, start="2026-06-01", end="2026-06-30")
    chips = stats.headline_stats()
    assert chips == [
        ("PBs", "3"),
        ("Medals", "2"),
        ("Club records", "1"),
        ("Debuts", "1"),
        ("Milestones", "1"),
    ]
    assert len(chips) <= 6
    assert all(value != "0" for _, value in chips)


def test_empty_window_is_honest_zero(runs_dir):
    stats = aggregate_window(ORG_A, runs_dir, start="2025-01-01", end="2025-01-31")
    assert stats.n_runs == 0
    assert stats.total_achievements == 0
    assert stats.busiest_swimmer is None
    assert stats.biggest_improver is None
    assert stats.headline_stats() == []
    assert stats.to_dict()["meet_names"] == []


# --- drafts ------------------------------------------------------------------


def test_monthly_draft_title_id_window_and_highlights_order(runs_dir):
    draft = build_monthly_draft(ORG_A, runs_dir, year=2026, month=6)
    assert draft["title"] == "June 2026 in numbers"
    assert draft["id"] == "monthly-2026-06"
    assert draft["window"] == {"start": "2026-06-01", "end": "2026-06-30"}
    assert draft["stats"]["n_pbs"] == 3
    assert draft["stat_chips"][0] == ["PBs", "3"]

    highlights = draft["highlights"]
    assert len(highlights) == 8
    # Stored priority desc ordering: club record (0.95) leads, debut (0.40) last.
    assert [h["type"] for h in highlights] == [
        "club_record",
        "pb_confirmed",
        "pb_confirmed",
        "medal_gold",
        "official_pb_confirmed",
        "medal_silver",
        "race_milestone_50",
        "club_debut",
    ]
    assert set(highlights[0]) == {"swimmer", "event", "headline", "type"}
    assert highlights[0]["swimmer"] == "Owen Hughes"


def test_season_draft_shape(runs_dir):
    draft = build_season_draft(ORG_A, runs_dir, season_start="2025-09-01", season_end="2026-07-31")
    assert draft["title"] == "Season wrap 2025-09-01–2026-07-31"
    assert draft["id"] == "season-2025-09-01-2026-07-31"
    # The July org-A meet is inside the season window.
    assert draft["stats"]["n_runs"] == 3
    assert draft["stats"]["medals_by_colour"]["bronze"] == 1


def test_save_list_load_roundtrip(runs_dir, tmp_path):
    data_dir = tmp_path / "data"
    draft = build_monthly_draft(ORG_A, runs_dir, year=2026, month=6)
    path = save_draft(ORG_A, draft, data_dir=data_dir)
    assert path == data_dir / "season_wraps" / ORG_A / "monthly-2026-06.json"
    assert path.exists()

    # Idempotent: saving again overwrites, no second file.
    save_draft(ORG_A, draft, data_dir=data_dir)
    assert len(list(path.parent.glob("*.json"))) == 1

    assert list_drafts(ORG_A, data_dir=data_dir) == [draft]
    assert load_draft(ORG_A, "monthly-2026-06", data_dir=data_dir) == draft
    assert load_draft(ORG_A, "monthly-1999-01", data_dir=data_dir) is None
    assert list_drafts(ORG_B, data_dir=data_dir) == []  # org isolation on disk


def test_draft_paths_are_traversal_safe(tmp_path, runs_dir):
    data_dir = tmp_path / "data"
    draft = build_monthly_draft(ORG_A, runs_dir, year=2026, month=6)
    draft["id"] = "../../escape"
    path = save_draft("../evil", draft, data_dir=data_dir)
    assert data_dir in path.parents  # never escapes DATA_DIR
    assert ".." not in path.parts


# --- scheduler task ----------------------------------------------------------


class _CaptureChannel:
    name = "capture"

    def __init__(self, sent):
        self._sent = sent

    def configured(self):
        return True

    def send(self, n):
        self._sent.append(n)
        return True


def test_monthly_task_handler_writes_draft_and_notifies(runs_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    sent = []
    from mediahub.notify import channels

    monkeypatch.setattr(channels, "all_channels", lambda: [_CaptureChannel(sent)])

    # The handler targets the last *completed* calendar month — plant a run
    # there so the draft has content regardless of when the test runs.
    year, month = wrap_task._last_completed_month(date.today())
    _write_snapshot(
        runs_dir,
        "run-prev",
        ORG_A,
        "Last Month Meet",
        f"{year:04d}-{month:02d}-15",
        [_ra("pb_confirmed", "Maya Patel", "100m Freestyle (LC)", priority=0.9, rank=1)],
    )

    monthly_wrap_task_handler({"profile_id": ORG_A, "runs_dir": str(runs_dir)})

    draft_id = f"monthly-{year:04d}-{month:02d}"
    draft = load_draft(ORG_A, draft_id)
    assert draft is not None
    assert draft["id"] == draft_id
    assert draft["stats"]["n_pbs"] >= 1
    assert "Last Month Meet" in draft["stats"]["meet_names"]

    assert len(sent) == 1
    assert "recap draft is ready" in sent[0].message

    # Idempotent: a re-run overwrites the same deterministic id.
    monthly_wrap_task_handler({"profile_id": ORG_A, "runs_dir": str(runs_dir)})
    folder = Path(tmp_path / "data") / "season_wraps" / ORG_A
    assert [p.name for p in folder.glob("*.json")] == [f"{draft_id}.json"]


def test_task_handler_requires_profile_id():
    with pytest.raises(ValueError):
        monthly_wrap_task_handler({})


def test_register_season_wrap_task_registers_type():
    before = dict(scheduler._REGISTRY)
    try:
        register_season_wrap_task()
        assert scheduler._REGISTRY[TASK_TYPE] is monthly_wrap_task_handler
        assert TASK_TYPE in scheduler.registered_task_types()
    finally:
        scheduler._REGISTRY.clear()
        scheduler._REGISTRY.update(before)
