"""refactor-15 (finding #15, step 1) — pure helpers hoisted out of ``create_app``.

These formatting/parsing helpers used to be inner ``def``s nested inside the
~48k-line ``create_app`` closure, so they could not be reached without building
the whole Flask app. Hoisting them to module level makes them importable and
unit-testable in isolation — which is exactly what this file does: it imports
each helper directly and exercises it, with **no** ``create_app()`` call and no
``importlib.reload`` of the monolith. Behaviour must be byte-identical to the
pre-hoist closure versions.
"""

from __future__ import annotations

from mediahub.web.web import (
    _format_uptime_pct,
    _humanize_duration,
    _humanize_when,
    _nl_range,
    _org_calendar_sport,
    _parse_month_param,
    _pence_str,
    _pounds_to_pence,
    _safe_filename,
)


class TestFormatUptimePct:
    def test_no_data_is_dash(self):
        assert _format_uptime_pct({"has_data": False}) == "&mdash;"

    def test_perfect_window_is_100(self):
        assert (
            _format_uptime_pct({"has_data": True, "uptime_pct": 1.0, "downtime_seconds": 0})
            == "100%"
        )

    def test_near_perfect_with_downtime_never_rounds_to_100(self):
        # A window with real counted downtime must not read as a bare "100%".
        assert (
            _format_uptime_pct({"has_data": True, "uptime_pct": 0.99998, "downtime_seconds": 5})
            == "99.99%"
        )

    def test_precision_tiers(self):
        assert _format_uptime_pct({"has_data": True, "uptime_pct": 0.9995}) == "99.950%"
        assert _format_uptime_pct({"has_data": True, "uptime_pct": 0.97}) == "97.00%"
        assert _format_uptime_pct({"has_data": True, "uptime_pct": 0.5}) == "50.0%"


class TestHumanizeDuration:
    def test_seconds(self):
        assert _humanize_duration(0) == "0s"
        assert _humanize_duration(45) == "45s"

    def test_minutes(self):
        assert _humanize_duration(120) == "2 min"

    def test_hours_and_minutes(self):
        assert _humanize_duration(3725) == "1h 2m"
        assert _humanize_duration(7200) == "2h"

    def test_days_and_hours(self):
        assert _humanize_duration(90000) == "1d 1h"
        assert _humanize_duration(172800) == "2d"

    def test_negative_clamped_to_zero(self):
        assert _humanize_duration(-10) == "0s"


class TestHumanizeWhen:
    def test_empty_is_dash(self):
        assert _humanize_when(None) == "&mdash;"
        assert _humanize_when("") == "&mdash;"

    def test_relative_recent(self):
        # A far-future timestamp yields the escaped raw prefix (secs < 0 branch).
        assert _humanize_when("2999-01-01T00:00:00Z") == "2999-01-01T00:00:00"

    def test_unparseable_falls_back_to_escaped_prefix(self):
        assert _humanize_when("not-a-date") == "not-a-date"


class TestMoney:
    def test_pounds_to_pence(self):
        assert _pounds_to_pence("£12.34") == 1234
        assert _pounds_to_pence("12.34") == 1234
        assert _pounds_to_pence("  £5  ") == 500

    def test_pounds_to_pence_invalid_is_negative(self):
        assert _pounds_to_pence("abc") == -1
        assert _pounds_to_pence("") == -1

    def test_pence_str(self):
        assert _pence_str(1234) == "£12.34"
        assert _pence_str(0) == "£0.00"

    def test_pence_str_invalid_is_dash(self):
        assert _pence_str(-1) == "—"
        assert _pence_str(None) == "—"


class TestSafeFilename:
    def test_slugifies_and_lowercases(self):
        assert _safe_filename("Hello World! Report", "pdf") == "hello-world-report.pdf"

    def test_empty_title_defaults(self):
        assert _safe_filename("", "docx") == "document.docx"
        assert _safe_filename("!!!", "txt") == "document.txt"


class TestParseMonthParam:
    def test_valid(self):
        assert _parse_month_param("2026-03") == (2026, 3)

    def test_invalid_falls_back_to_today(self):
        from mediahub.content_engine.calendar import today_utc

        t = today_utc()
        assert _parse_month_param("garbage") == (t.year, t.month)
        assert _parse_month_param("2026-13") == (t.year, t.month)


class TestNlRange:
    def test_last_30_spans_30_days(self):
        start, end = _nl_range("last_30", {})
        assert (end - start).days == 30

    def test_custom_uses_body(self):
        start, end = _nl_range("custom", {"start": "2026-01-01", "end": "2026-01-31"})
        assert (start.year, start.month, start.day) == (2026, 1, 1)
        assert (end.year, end.month, end.day) == (2026, 1, 31)

    def test_default_is_month_to_date(self):
        start, _ = _nl_range("this_month", {})
        assert start.day == 1


class TestOrgCalendarSport:
    def test_falls_back_when_unmapped(self):
        class _Prof:
            org_type = "definitely-not-a-real-org-type"

        assert _org_calendar_sport(_Prof(), fallback="swimming") == "swimming"
