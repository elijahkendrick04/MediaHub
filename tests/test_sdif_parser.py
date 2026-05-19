"""Tests for `mediahub.interpreter.sdif_parser`.

SDIF (`.cl2`/`.sd3`) is the public US-Swimming-defined fixed-width
record format that Hy-Tek exports follow. The parser is deterministic
and depends only on column positions + an ontology lookup; mocking is
not required.

The wider corpus integration is already covered by
`tests/test_hytek_parser.py::test_sdif_parser_against_corpus`. This
file pins the per-function record-level contracts so future column /
tolerance changes are deliberate.
"""
from __future__ import annotations

import pytest

from mediahub.interpreter.sdif_parser import (
    _format_date,
    _normalise_swimmer_name,
    _parse_b1,
    _parse_c1,
    _parse_d0,
    _parse_sdif_time,
    detect_sdif,
    parse_sdif,
)


# ---------------------------------------------------------------------------
# detect_sdif — file-type sniff
# ---------------------------------------------------------------------------


class TestDetectSdif:
    def test_a0_record_detected(self) -> None:
        data = b"A001V3      Hy-Tek MM 8.0                                   "
        assert detect_sdif(data) is True

    def test_a1_record_detected(self) -> None:
        data = b"A1V3 lots of header data here..."
        assert detect_sdif(data) is True

    def test_leading_whitespace_tolerated(self) -> None:
        data = b"   A0V3 header data follows here"
        assert detect_sdif(data) is True

    def test_hy3_b1_first_not_sdif(self) -> None:
        # .hy3 files start with "B1" — must not be misidentified.
        data = b"B1Some Meet Title goes here"
        assert detect_sdif(data) is False

    def test_random_html_not_sdif(self) -> None:
        data = b"<!DOCTYPE html><html><body>not a results file"
        assert detect_sdif(data) is False

    def test_too_short_buffer_not_sdif(self) -> None:
        assert detect_sdif(b"A0") is False
        assert detect_sdif(b"") is False


# ---------------------------------------------------------------------------
# _parse_sdif_time — 8-char time field parser
# ---------------------------------------------------------------------------


class TestParseSdifTime:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("1:19.69 ", "1:19.69"),
            (" 36.71  ", "36.71"),
            ("  1:25.12", "1:25.12"),
            ("59.87   ", "59.87"),
            ("15:25.10", "15:25.10"),
        ],
    )
    def test_valid_times_canonicalised(self, raw: str, expected: str) -> None:
        assert _parse_sdif_time(raw) == expected

    @pytest.mark.parametrize("raw", ["0.00", "00.00", "0", "", "        "])
    def test_zero_and_blank_return_none(self, raw: str) -> None:
        assert _parse_sdif_time(raw) is None

    def test_trailing_course_code_letter_stripped(self) -> None:
        # SDIF sometimes appends a course-code letter (S/L/Y) at the end.
        assert _parse_sdif_time("1:19.69S") == "1:19.69"
        assert _parse_sdif_time(" 36.71L") == "36.71"
        assert _parse_sdif_time("59.87Y") == "59.87"

    def test_lowercase_course_code_also_stripped(self) -> None:
        assert _parse_sdif_time("1:19.69s") == "1:19.69"

    def test_invalid_format_returns_none(self) -> None:
        assert _parse_sdif_time("DQ") is None
        assert _parse_sdif_time("abc.de") is None
        assert _parse_sdif_time("1:2:3.45") is None  # too many colon-segments

    def test_leading_zero_minutes_normalised(self) -> None:
        # "01:19.69" → minutes int() → "1:19.69"
        assert _parse_sdif_time("01:19.69") == "1:19.69"


# ---------------------------------------------------------------------------
# _format_date — 8-digit date validation
# ---------------------------------------------------------------------------


class TestFormatDate:
    def test_valid_dates(self) -> None:
        assert _format_date("05202024") == "05/20/2024"
        assert _format_date("01011990") == "01/01/1990"
        assert _format_date("12312100") == "12/31/2100"

    def test_dates_with_padding_trimmed(self) -> None:
        assert _format_date("  05202024  ") == "05/20/2024"

    def test_out_of_range_year_rejected(self) -> None:
        assert _format_date("01011989") is None
        assert _format_date("12312101") is None

    @pytest.mark.parametrize(
        "raw",
        ["", "0", "12345678", "abcdefgh", "0520202", "052020240"],
    )
    def test_malformed_returns_none(self, raw: str) -> None:
        assert _format_date(raw) is None


# ---------------------------------------------------------------------------
# _normalise_swimmer_name
# ---------------------------------------------------------------------------


class TestNormaliseSwimmerName:
    def test_last_first_swapped(self) -> None:
        assert _normalise_swimmer_name("Smith, Jane") == "Jane Smith"

    def test_last_first_middle(self) -> None:
        assert _normalise_swimmer_name("Smith, Jane M") == "Jane M Smith"

    def test_already_first_last_preserved(self) -> None:
        assert _normalise_swimmer_name("Jane Smith") == "Jane Smith"

    def test_handles_extra_whitespace(self) -> None:
        assert _normalise_swimmer_name("  Smith ,   Jane  ") == "Jane Smith"

    def test_unicode_preserved(self) -> None:
        # Non-ASCII surnames must round-trip exactly.
        assert _normalise_swimmer_name("Müller, Lena") == "Lena Müller"
        assert _normalise_swimmer_name("Łopatka, Aniela") == "Aniela Łopatka"

    def test_empty_string(self) -> None:
        assert _normalise_swimmer_name("") == ""

    def test_only_comma_does_not_crash(self) -> None:
        assert _normalise_swimmer_name(",") == ""


# ---------------------------------------------------------------------------
# Record parsers — _parse_b1 / _parse_c1 / _parse_d0
# ---------------------------------------------------------------------------


def _b1_line(
    *,
    meet_name: str = "Spring City Championships",
    venue: str = "Aquatics Centre 1                  ",
    city: str = "Birmingham         ",
    start: str = "05012024",
    end: str = "05032024",
) -> str:
    # Build a B1 record with the SDIF column layout used by the parser.
    line = list(" " * 200)
    line[0:2] = list("B1")
    line[11:11 + len(meet_name)] = list(meet_name)
    line[58:58 + len(venue)] = list(venue)
    line[128:128 + len(city)] = list(city)
    line[148:156] = list(start)
    line[156:164] = list(end)
    return "".join(line)


def _c1_line(*, team_code: str = "AB-XYZ", team_name: str = "Aquatic Sharks SC") -> str:
    line = list(" " * 60)
    line[0:2] = list("C1")
    line[11:11 + len(team_code)] = list(team_code)
    line[17:17 + len(team_name)] = list(team_name)
    return "".join(line)


class TestParseB1:
    def test_extracts_meet_name_and_venue(self) -> None:
        parsed = _parse_b1(_b1_line())
        assert parsed["meet_name"] == "Spring City Championships"
        assert parsed["venue"] == "Aquatics Centre 1"
        assert parsed["start_date"] == "05012024"
        assert parsed["end_date"] == "05032024"
        assert parsed["city"] == "Birmingham"

    def test_missing_venue_falls_back_to_secondary(self) -> None:
        # If primary address1 is blank, parser keeps trying — but _parse_b1
        # returns raw fields; the venue-or-city fallback is in `parse_sdif`.
        line = _b1_line(venue=" " * 35)
        parsed = _parse_b1(line)
        assert parsed["venue"] == ""  # raw field


class TestParseC1:
    def test_extracts_team_name_and_code(self) -> None:
        parsed = _parse_c1(_c1_line())
        assert parsed["team_code"] == "AB-XYZ"
        assert parsed["team_name"] == "Aquatic Sharks SC"

    def test_missing_team_name_is_empty(self) -> None:
        parsed = _parse_c1(_c1_line(team_name=""))
        assert parsed["team_name"] == ""


# ---------------------------------------------------------------------------
# parse_sdif end-to-end with synthesised buffers
# ---------------------------------------------------------------------------


def _build_minimal_sdif() -> bytes:
    """Compose a multi-line SDIF byte buffer with one meet, one team."""
    a0 = ("A0" + " " * 5).ljust(170)
    b1 = _b1_line(
        meet_name="Test Champs                                    ",
        venue="Test Pool Complex                  ",
        city="Cardiff             ",
        start="06012024",
        end="06022024",
    ).ljust(170)
    c1 = _c1_line(team_name="Test Aquatics Club  ").ljust(170)
    return ("\n".join([a0, b1, c1]) + "\n").encode("latin-1")


class TestParseSdifIntegration:
    def test_meet_metadata_captured(self) -> None:
        meet = parse_sdif(_build_minimal_sdif())
        assert meet.meet_name == "Test Champs"
        assert meet.venue == "Test Pool Complex"
        assert meet.dates == ("06/01/2024", "06/02/2024")

    def test_empty_buffer_yields_meet_with_no_events(self) -> None:
        meet = parse_sdif(b"")
        assert meet.meet_name in (None, "")
        # Events list should be empty (or absent).
        events = getattr(meet, "events", None) or []
        assert len(events) == 0

    def test_b1_missing_dates_still_parses(self) -> None:
        b1 = _b1_line(start="00000000", end="00000000").ljust(170)
        buf = ("\n".join(["A0".ljust(170), b1]) + "\n").encode("latin-1")
        meet = parse_sdif(buf)
        assert meet.meet_name == "Spring City Championships"
        # When dates fail to parse, the parser leaves them None.
        assert meet.dates is None
