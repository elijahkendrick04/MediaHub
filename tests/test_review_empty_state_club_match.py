"""Regression test for the review-page "zero cards" dead-end.

When a meet file parses fine but none of its swims match the run's club, the
recognition engine has nothing to rank and the review page produces no cards.
The page used to show a generic "No standout swims" message implying the
swimmers simply had no good results — hiding the real cause (a club-name
mismatch / no club selected) and giving the volunteer no way forward.

This is the post-judging "review page is empty with no explanation" cluster the
LLM-council chair prioritised (autotest/reports/BUGS.md). The fix surfaces an
honest, actionable empty state. These tests pin the three distinct outcomes.

Display/empty-state only — the deterministic recognition engine is untouched.
"""
import json

import pytest

from mediahub.web import web as webmod


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    webmod.DATA_DIR = tmp_path
    webmod.RUNS_DIR = tmp_path / "runs"
    webmod.RUNS_DIR.mkdir(parents=True, exist_ok=True)
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _write_run(run_id, payload):
    (webmod.RUNS_DIR / f"{run_id}.json").write_text(json.dumps(payload), encoding="utf-8")


def _review_body(client, run_id):
    resp = client.get(f"/review/{run_id}")
    assert resp.status_code == 200, f"review page not reachable (status {resp.status_code})"
    return resp.get_data(as_text=True)


# A truthy recognition report with no ranked achievements: the run WAS judged
# (so the route reaches the "engine produced no cards" empty state) but nothing
# was ranked. An empty {} would be falsy and hit the earlier "No report yet"
# branch instead, so it must be a non-empty dict.
_JUDGED_EMPTY = {"ranked_achievements": [], "n_achievements": 0, "n_swims_analysed": 0}


def test_zero_matched_club_explains_mismatch(client):
    _write_run("nomatch", {
        "file_name": "meet.hy3",
        "meet": {"name": "West Wales Regional LC"},
        "cards": [],
        "recognition_report": dict(_JUDGED_EMPTY),
        "parsed_swim_count": 120,
        "our_swim_count": 0,
        "club_filter": "Swansea University Swimming Team",
        "parse_warnings": [],
    })
    body = _review_body(client, "nomatch")
    assert "No swims matched your club" in body
    assert "No standout swims" not in body
    # The honest count is shown so the volunteer sees the file *was* read.
    assert "120" in body


def test_no_club_selected_prompts_to_pick_one(client):
    _write_run("nofilter", {
        "file_name": "meet.hy3",
        "meet": {"name": "Spring Meet"},
        "cards": [],
        "recognition_report": dict(_JUDGED_EMPTY),
        "parsed_swim_count": 80,
        "our_swim_count": 0,
        "club_filter": "",
        "parse_warnings": [
            {"code": "no_club_filter", "message": "Pick a club.", "severity": "warn"}
        ],
    })
    body = _review_body(client, "nofilter")
    assert "No swims matched your club" in body
    assert "No standout swims" not in body


def test_matched_but_nothing_ranked_keeps_standout_message(client):
    # Swims matched the club, the engine ranked them, nothing cleared the bar:
    # this is the genuine "no standout swims" case and must be preserved.
    _write_run("standout", {
        "file_name": "meet.hy3",
        "meet": {"name": "Spring Meet"},
        "cards": [],
        "recognition_report": dict(_JUDGED_EMPTY),
        "parsed_swim_count": 80,
        "our_swim_count": 40,
        "club_filter": "Swansea",
        "parse_warnings": [],
    })
    body = _review_body(client, "standout")
    assert "No standout swims" in body
    assert "No swims matched your club" not in body
