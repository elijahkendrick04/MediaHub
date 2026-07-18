"""Finding #62 — a trailing time-shaped points column must not overwrite the
achieved race time in the token-path record parser (interpreter/rows.py).

`_TIME_TOKEN` allows up to five integer digits before the decimal, so a
FINA/British-Points column ("430.50") is time-shaped; `_record_to_swim` picked
the LAST non-reaction time as the achieved time, so a trailing points column
demoted the real finals time to the seed slot. A colon-less token with a
3+-digit integer part is unambiguously a points cell (a 100 s+ time is always
mm:ss.cc) and is now excluded from the achieved-time candidates.

Pure synthetic single-line inputs; no corpus ZIPs / PDFs.
"""

from __future__ import annotations

from mediahub.interpreter.rows import _parse_records_from_line


def _one(line: str):
    swims = _parse_records_from_line(line)
    assert len(swims) == 1, f"expected exactly one swim, got {len(swims)}: {swims!r}"
    return swims[0]


def test_trailing_points_column_does_not_overwrite_finals_time():
    s = _one("1 Smith, John 23 Sharks 1:02.34 430.50")
    assert s.time == "1:02.34", f"points column overwrote finals time: {s.time!r}"
    assert s.seed_time is None, f"finals time wrongly demoted to seed: {s.seed_time!r}"


def test_points_column_after_short_time_and_reaction():
    s = _one("2 Doe, Jane 20 Otters 58.42 0.63 512.30")
    assert s.time == "58.42", f"got {s.time!r}"


def test_genuine_seed_plus_finals_still_intact():
    # Two REAL times (seed then finals) must be unaffected by the fix.
    s = _one("Alex Nguyen 23 Club 1:05.00 1:02.34")
    assert s.time == "1:02.34"
    assert s.seed_time == "1:05.00"


def test_degenerate_points_only_row_still_yields_a_swim():
    # Fallback: if the ONLY time-shaped token is points-like, the row still
    # parses (behaviour preserved) rather than silently vanishing.
    s = _one("Solo Runner 23 Club 430.50")
    assert s.time == "430.50"


def test_two_digit_sub_minute_time_is_not_treated_as_points():
    # A colon-less 2-digit integer part stays a real time (the guard only rejects
    # 3+ integer digits), so a genuine 58.42 finals is never mistaken for points.
    from mediahub.interpreter.rows import _is_points_like

    assert _is_points_like("430.50") is True
    assert _is_points_like("1005.40") is True
    assert _is_points_like("58.42") is False
    assert _is_points_like("1:02.34") is False
