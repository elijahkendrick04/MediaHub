"""Finding #69 — 2-digit year pivot must never resolve to a future date.

Year-of-birth (``interpreter/rows.py``) and swim-result dates
(``swimmingresults/parse.py`` and ``swimmingresults/roster.py``) are
deterministic parsers. The old frozen constants — ``<= 30`` for the YOB and an
unconditional ``2000 + yy`` for dates — produced impossible future years
(YOB 2030, date 2099). These regression tests fail on the old constants (they
also fail to import ``_expand_year`` on the pre-fix tree) and pass once the
2-digit year pivots on the current year.

Tiny synthetic inputs only — no corpus ZIPs / PDFs.
"""
from __future__ import annotations

import datetime

from mediahub.interpreter.rows import _normalise_yob
from mediahub.swimmingresults.parse import _expand_year, _parse_date
from mediahub.swimmingresults.roster import _row_date_iso


def test_two_digit_yob_is_never_in_the_future() -> None:
    this_year = datetime.date.today().year
    for yy in range(0, 100):
        v, _ = _normalise_yob(f"{yy:02d}")
        assert v is not None
        # Every expansion preserves the 2-digit tail...
        assert v % 100 == yy
        # ...and no year-of-birth may sit in the future.
        assert v <= this_year, f"YOB {yy:02d} -> {v} is in the future"


def test_yob_recent_two_digit_year_stays_2000s() -> None:
    # A just-past 2-digit year still resolves into the 2000s (regression guard
    # so the pivot does not over-correct recent births into the 1900s).
    two = (datetime.date.today().year - 1) % 100
    v, _ = _normalise_yob(f"{two:02d}")
    assert v == 2000 + two


def test_parse_date_two_digit_year_is_never_future() -> None:
    # Old code mapped every 2-digit year to 2000+yy, so 99 -> 2099.
    assert _parse_date("05/06/99") == "1999-06-05"
    assert _parse_date("12-May-99") == "1999-05-12"


def test_parse_date_recent_two_digit_year_stays_2000s() -> None:
    this_year = datetime.date.today().year
    yy = this_year % 100
    assert _parse_date(f"01/01/{yy:02d}") == f"{this_year}-01-01"


def test_expand_year_passes_through_four_digit() -> None:
    assert _expand_year(2023) == 2023
    assert _expand_year(1987) == 1987


def test_roster_row_date_is_never_future() -> None:
    # roster.py's sibling parser carried the identical bug (99 -> 2099).
    assert _row_date_iso("05/06/99") == "1999-06-05"
