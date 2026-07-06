"""Regression test for the free-text club filter dead-end on clubless files.

PR 483's configure page offers a free-text club input when the parser found no
clubs (e.g. a distance-splits page), promising "we'll match its swimmers". But
the filter can only ever match on club codes/names — all empty in exactly that
scenario — so every typed value yielded our_swim_count == 0 and the review
empty-state advised "check the club name matches the file": advice that could
never succeed.

The fix: when the meet carries NO club data at all and a filter was given, the
pipeline features the whole meet with an explicit `no_club_data_whole_meet`
warning, leaving the human review/approve gate to reject non-club swimmers.
"""

from __future__ import annotations

import pytest


_CLUBLESS_TXT = (
    "Spring Distance Meet\n"
    "\n"
    "Event 1 Male 1500m Freestyle\n"
    "1 Smith, John 15:10.79\n"
    "2 Jones, Bob 15:13.55\n"
)

_CLUBBED_TXT = (
    "Spring Sprint Meet\n"
    "\n"
    "Event 1 Male 50m Freestyle\n"
    "1 Smith, John 14 Otter SC 28.40\n"
    "2 Jones, Bob 15 Beacon SC 29.10\n"
)


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # The V5 recognition step researches meet identity online — stub it so the
    # test stays deterministic and offline.
    import swim_content_v5.report as v5report

    monkeypatch.setattr(
        v5report,
        "build_recognition_report_for_run",
        lambda run: {"ranked_achievements": [], "n_achievements": 0, "n_swims_analysed": 0},
    )
    from mediahub.pipeline.pipeline_v4 import run_pipeline_v4

    return run_pipeline_v4


def test_clubless_meet_with_typed_filter_features_whole_meet(pipeline):
    run = pipeline(
        file_bytes=_CLUBLESS_TXT.encode(),
        filename="splits.txt",
        club_filter="Otter SC",
        fetch_pbs=False,
        run_id="test-clubless-filter",
    )
    assert run.error is None
    assert run.parsed_swim_count > 0
    # Whole meet included — the review page is not dead-ended at 0 swims.
    assert run.our_swim_count == run.parsed_swim_count
    codes = [w.get("code") for w in run.parse_warnings]
    assert "no_club_data_whole_meet" in codes


def test_clubbed_meet_with_wrong_filter_still_matches_nothing(pipeline):
    # When the file DOES carry club data, a non-matching filter must keep
    # yielding zero swims (the honest mismatch case) — no whole-meet fallback.
    run = pipeline(
        file_bytes=_CLUBBED_TXT.encode(),
        filename="sprint.txt",
        club_filter="Swansea University",
        fetch_pbs=False,
        run_id="test-clubbed-filter",
    )
    assert run.error is None
    assert run.parsed_swim_count > 0
    assert run.our_swim_count == 0
    codes = [w.get("code") for w in run.parse_warnings]
    assert "no_club_data_whole_meet" not in codes
