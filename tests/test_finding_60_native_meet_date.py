"""Finding #60 — OfficialPBDetector Rule 0 works on HY3/SDIF native runs.

The HY3/SDIF interpreter parsers emit meet dates as an ambiguous ``xx/xx/yyyy``
display string. Rule 0 parsed ``ctx.start_date`` with the strict ISO helper
(``date.fromisoformat``), which returns None for ``xx/xx/yyyy`` — so the meet
date never resolved and Rule 0 (the strongest PB confirmation) was permanently
inert for natively-parsed meets. ``_parse_meet_date`` now accepts both ISO and
the native format, disambiguating mm/dd vs dd/mm by the >12 test (day-first
default when genuinely ambiguous).
"""

from __future__ import annotations

from datetime import date

from mediahub.recognition_swim.achievements.official_pb import (
    _parse_iso_date,
    _parse_meet_date,
)


def test_iso_still_parses():
    assert _parse_meet_date("2024-07-15") == date(2024, 7, 15)
    # The canonical/pb_discovery ISO contract is preserved verbatim.
    assert _parse_meet_date("2024-07-15") == _parse_iso_date("2024-07-15")


def test_native_us_and_uk_orderings_resolve():
    # US mm/dd and UK dd/mm both resolve to the same calendar date when a
    # component > 12 disambiguates.
    assert _parse_meet_date("07/15/2024") == date(2024, 7, 15)  # mm/dd, dd=15>12
    assert _parse_meet_date("15/07/2024") == date(2024, 7, 15)  # dd/mm, dd=15>12
    assert _parse_meet_date("31/12/2024") == date(2024, 12, 31)
    assert _parse_meet_date("12/31/2024") == date(2024, 12, 31)


def test_genuinely_ambiguous_defaults_day_first():
    # Both components <= 12: read day-first (documented, reproducible).
    assert _parse_meet_date("05/07/2024") == date(2024, 7, 5)


def test_dash_and_dot_separators():
    assert _parse_meet_date("15.07.2024") == date(2024, 7, 15)
    assert _parse_meet_date("15-07-2024") == date(2024, 7, 15)


def test_empty_and_garbage_return_none():
    assert _parse_meet_date("") is None
    assert _parse_meet_date(None) is None
    assert _parse_meet_date("garbage") is None
    assert _parse_meet_date("13/13/2024") is None  # no valid ordering


def test_strict_iso_helper_still_rejects_native_format():
    # The discriminator: the OLD path (strict ISO) rejected the native format,
    # which is exactly why Rule 0 was inert. _parse_meet_date rescues it.
    assert _parse_iso_date("07/15/2024") is None
    assert _parse_meet_date("07/15/2024") is not None
