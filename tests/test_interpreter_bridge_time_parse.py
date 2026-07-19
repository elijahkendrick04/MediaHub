"""Regression for deep-review #63 — native-path time parsing.

The bridge time regex used to accept a colon as the centisecond separator
(`[.:]`), so a bare mm:ss like "23:45" parsed as 23.45s — a ~60x error that
would fabricate an impossible swim time. The fraction separator is now a period
only; a time with no centiseconds is rejected (None) rather than mis-read.
"""

from __future__ import annotations

from mediahub.pipeline.interpreter_bridge import _time_to_cs


def test_valid_times_parse_to_centiseconds():
    assert _time_to_cs("30.91") == 3091  # ss.cc
    assert _time_to_cs("23.45") == 2345
    assert _time_to_cs("1:05.00") == 6500  # mm:ss.cc
    assert _time_to_cs("1:23.45") == 8345
    assert _time_to_cs("2:40.10") == 16010


def test_bare_mm_ss_is_rejected_not_read_as_seconds():
    # "23:45" is not ss.cc — it must NOT be parsed as 23.45s (the old 100x bug).
    assert _time_to_cs("23:45") is None
    assert _time_to_cs("1:30") is None  # mm:ss with no centiseconds → rejected


def test_empty_and_garbage_are_none():
    assert _time_to_cs("") is None
    assert _time_to_cs(None) is None
    assert _time_to_cs("DQ") is None
