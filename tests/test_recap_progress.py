"""Unit tests for the customer-facing progress mapping
(``mediahub.web.recap_progress``).

The meet-recap progress page shows a developer the raw engineer-facing step log
but shows a customer only a percentage bar + a plain-English phase. This module
is the pure mapping that powers the customer view, so it must be deterministic,
monotonic, and never leak raw step/error text into the phase label.
"""

from __future__ import annotations

from mediahub.web.recap_progress import recap_progress

# The full set of friendly phase labels the mapping may emit.
_FRIENDLY = {
    "Getting started",
    "Reading your results file",
    "Matching your swimmers",
    "Researching personal bests",
    "Finding the standout moments",
    "Designing your content",
    "Ready",
}


def test_done_is_100_ready_regardless_of_log():
    assert recap_progress(["anything"], "done") == (100, "Ready")
    assert recap_progress([], "done") == (100, "Ready")


def test_empty_running_log_is_getting_started():
    pct, phase = recap_progress([], "running")
    assert phase == "Getting started"
    assert 0 < pct < 100


def test_phase_progression_reading_to_design():
    assert recap_progress(["Interpreting document"], "running")[1] == "Reading your results file"
    assert recap_progress(["Filtered to 'Test SC': 12 swims"], "running")[1] == "Matching your swimmers"
    assert recap_progress(["V5 recognition: 7 achievements."], "running")[1] == "Finding the standout moments"
    assert recap_progress(["V3 stubs synthesised from 4 V5 achievements."], "running")[1] == "Designing your content"


def test_percent_increases_through_phases():
    read = recap_progress(["Interpreting document"], "running")[0]
    match = recap_progress(["Filtered to 'X': 1 swims"], "running")[0]
    recog = recap_progress(["V5 recognition: 7 achievements."], "running")[0]
    design = recap_progress(["V3 stubs synthesised from 4 V5 achievements."], "running")[0]
    assert read < match < recog < design < 100


def test_pb_phase_interpolates_by_swimmer_count():
    start = recap_progress(["Looking up personal bests for 10 swimmers (6 in parallel)…"], "running")[0]
    half = recap_progress(["Looking up personal bests 5/10: Jane Doe"], "running")[0]
    near = recap_progress(["Still researching personal bests (9/10 done)…"], "running")[0]
    assert start < half < near
    # All inside the PB band, below the recognise phase.
    assert start >= 32
    assert near < recap_progress(["V5 recognition: 1 achievements."], "running")[0]


def test_pb_lookup_error_line_stays_in_pb_phase():
    # The reported bug surfaced "PB lookup error for NAME: …" on the page. The
    # customer mapping must keep that in the PB phase, never crash or regress.
    pct, phase = recap_progress(
        [
            "Looking up personal bests for 2 swimmers (2 in parallel)…",
            "PB lookup error for Isabelle David: [Errno 13] Permission denied",
        ],
        "running",
    )
    assert phase == "Researching personal bests"
    assert 32 <= pct < 70


def test_never_reaches_100_until_done():
    log = [
        "Interpreting document",
        "Filtered to 'X': 9 swims",
        "Looking up personal bests 10/10: Z",
        "V5 recognition: 5 achievements.",
        "V3 stubs synthesised from 5 V5 achievements.",
    ]
    pct, _ = recap_progress(log, "running")
    assert pct < 100


def test_error_keeps_progress_does_not_jump_to_100():
    log = ["Interpreting document", "Looking up personal bests 5/10: Z"]
    pct, phase = recap_progress(log, "error")
    assert pct < 100
    assert phase in _FRIENDLY


def test_monotonic_as_log_grows():
    growing = [
        "Interpreting document",
        "Bridging interpreted output → canonical meet",
        "Filtered to 'X': 9 swims",
        "Looking up personal bests for 4 swimmers (4 in parallel)…",
        "Looking up personal bests 2/4: B",
        "Looking up personal bests 4/4: D",
        "Researching meet identity and recognising achievements…",
        "V5 recognition: 3 achievements.",
        "V3 stubs synthesised from 3 V5 achievements.",
    ]
    last = -1
    for i in range(1, len(growing) + 1):
        pct, phase = recap_progress(growing[:i], "running")
        assert pct >= last, f"percent went backwards at step {i}"
        assert phase in _FRIENDLY
        last = pct


def test_phase_is_always_friendly_never_raw_text():
    # Even a log full of raw error lines must only ever yield friendly phases.
    for status in ("queued", "running", "error", "unknown"):
        _, phase = recap_progress(
            ["PB lookup error for X: [Errno 13] Permission denied: '/app/src/mediahub/data'"],
            status,
        )
        assert phase in _FRIENDLY
