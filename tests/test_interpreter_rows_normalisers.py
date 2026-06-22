"""Tests for the field normalisers in `mediahub.interpreter.rows`.

These are the pure (raw_str → typed value + confidence) helpers the
table-row interpreter uses to coerce each column value. They have no
external dependencies and are the deterministic, sport-agnostic core of
the parsing layer per CLAUDE.md.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from mediahub.interpreter.rows import (
    _normalise_club,
    _normalise_name,
    _normalise_place,
    _normalise_reaction,
    _normalise_time,
    _normalise_yob,
)


# ---------------------------------------------------------------------------
# _normalise_time
# ---------------------------------------------------------------------------


class TestNormaliseTime:
    @pytest.mark.parametrize(
        "raw, canonical, conf",
        [
            ("59.87", "59.87", 0.85),
            ("1:02.34", "1:02.34", 0.95),
            ("15:25.10", "15:25.10", 0.95),
            ("0.50", "0.50", 0.85),
        ],
    )
    def test_valid_time_canonicalised(self, raw: str, canonical: str, conf: float) -> None:
        v, c = _normalise_time(raw)
        assert v == canonical
        assert c == pytest.approx(conf)

    def test_whitespace_stripped(self) -> None:
        v, c = _normalise_time("  1:02.34  ")
        assert v == "1:02.34"
        assert c == pytest.approx(0.95)

    @pytest.mark.parametrize(
        "raw",
        ["", "DNF", "abc.de", "1.2", "1.234"],
    )
    def test_invalid_returns_none(self, raw: str) -> None:
        v, c = _normalise_time(raw)
        assert v is None
        assert c == 0.0

    def test_colon_form_higher_confidence_than_plain(self) -> None:
        # MM:SS.cc is more constrained → higher confidence than SS.cc
        _, plain = _normalise_time("59.87")
        _, colon = _normalise_time("1:00.34")
        assert colon > plain


# ---------------------------------------------------------------------------
# _normalise_place
# ---------------------------------------------------------------------------


class TestNormalisePlace:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("1", 1),
            ("12", 12),
            ("100", 100),
            ("=1", 1),
            ("=12", 12),
            # Trailing-dot places ("1." / "2.") are how some results services
            # render the place column — parse them rather than reject them.
            ("1.", 1),
            ("3.", 3),
        ],
    )
    def test_digits_and_equals_prefix(self, raw: str, expected: int) -> None:
        v, c = _normalise_place(raw)
        assert v == expected
        assert c == pytest.approx(0.90)

    @pytest.mark.parametrize("raw", ["", "DQ", "first", "abc", "1.5", "1a"])
    def test_non_digit_returns_none(self, raw: str) -> None:
        v, c = _normalise_place(raw)
        assert v is None
        assert c == 0.0

    def test_strips_whitespace(self) -> None:
        v, _ = _normalise_place("   3   ")
        assert v == 3


# ---------------------------------------------------------------------------
# _normalise_yob
# ---------------------------------------------------------------------------


class TestNormaliseYob:
    @pytest.mark.parametrize(
        "raw, expected, conf",
        [
            ("1995", 1995, 0.90),
            ("2008", 2008, 0.90),
            ("1940", 1940, 0.90),
        ],
    )
    def test_full_year_form(self, raw: str, expected: int, conf: float) -> None:
        v, c = _normalise_yob(raw)
        assert v == expected
        assert c == pytest.approx(conf)

    def test_two_digit_year_disambiguation(self) -> None:
        # Years 00–30 → 2000s; 31–99 → 1900s.
        v, c = _normalise_yob("05")
        assert v == 2005
        assert c == pytest.approx(0.70)
        v, _ = _normalise_yob("85")
        assert v == 1985
        v, _ = _normalise_yob("30")
        assert v == 2030
        v, _ = _normalise_yob("31")
        assert v == 1931

    @pytest.mark.parametrize("raw", ["1939", "2040", "abc", "1", "12345", ""])
    def test_out_of_range_returns_none(self, raw: str) -> None:
        v, c = _normalise_yob(raw)
        assert v is None
        assert c == 0.0


# ---------------------------------------------------------------------------
# _normalise_reaction
# ---------------------------------------------------------------------------


class TestNormaliseReaction:
    @pytest.mark.parametrize("raw", ["0.65", "0.700", "0.81", "0.99"])
    def test_valid_reaction_times(self, raw: str) -> None:
        v, c = _normalise_reaction(raw)
        assert v == raw
        assert c == pytest.approx(0.90)

    @pytest.mark.parametrize(
        "raw",
        ["", "1.50", "0.5", "0.5000", "abc", "-0.65"],
    )
    def test_invalid_reaction_returns_none(self, raw: str) -> None:
        v, c = _normalise_reaction(raw)
        assert v is None
        assert c == 0.0


# ---------------------------------------------------------------------------
# _normalise_name
# ---------------------------------------------------------------------------


class TestNormaliseName:
    @pytest.mark.parametrize(
        "raw",
        ["Jane Smith", "O'Connor", "Anne-Marie", "X Y"],  # 3+ chars w/ letters
    )
    def test_valid_names(self, raw: str) -> None:
        v, c = _normalise_name(raw)
        assert v == raw.strip()
        assert c == pytest.approx(0.80)

    def test_strips_whitespace(self) -> None:
        v, _ = _normalise_name("  Jane Smith  ")
        assert v == "Jane Smith"

    @pytest.mark.parametrize("raw", ["", "AB", "12", "  "])
    def test_too_short_or_no_letter_returns_none(self, raw: str) -> None:
        v, c = _normalise_name(raw)
        assert v is None
        assert c == 0.0

    @pytest.mark.parametrize("raw", ["H-7 L", "Heat 7", "Lane 4", "H-7", "1. Foo"])
    def test_names_with_digits_are_rejected(self, raw: str) -> None:
        # Heat/lane/relay-leg fragments (which contain digits) are not swimmers
        # and must never surface as results (the "H-7 L" in the review summary).
        v, c = _normalise_name(raw)
        assert v is None
        assert c == 0.0


# ---------------------------------------------------------------------------
# _normalise_club
# ---------------------------------------------------------------------------


class TestNormaliseClub:
    def test_returns_stripped_string(self) -> None:
        v, c = _normalise_club("  Aquatic Sharks  ")
        assert v == "Aquatic Sharks"
        assert c == pytest.approx(0.75)

    def test_empty_returns_none(self) -> None:
        v, c = _normalise_club("")
        assert v is None
        assert c == 0.0

    def test_whitespace_only_returns_none(self) -> None:
        v, c = _normalise_club("   ")
        assert v is None
        assert c == 0.0

    @pytest.mark.parametrize("raw", ["(04)", "(99)", "04", "(2004)", "2004", "  (10)  "])
    def test_bare_year_of_birth_is_not_a_club(self, raw: str) -> None:
        # British results print "Name (YoB) Club"; a column slip can drop the
        # (YoB) into the club cell. A lone year of birth is never a club, so it
        # must not surface in the club picker (was showing '(04)' etc).
        v, _ = _normalise_club(raw)
        assert v is None

    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("(04) City of Sheffield", "City of Sheffield"),
            ("(99) Loughborough", "Loughborough"),
            ("2004 Bath Dolphins", "Bath Dolphins"),
            ("04 Otter SC", "Otter SC"),
        ],
    )
    def test_strips_leading_year_keeps_real_club(self, raw: str, expected: str) -> None:
        v, c = _normalise_club(raw)
        assert v == expected
        assert c == pytest.approx(0.75)

    @pytest.mark.parametrize("raw", ["100 Club", "1st City SC", "City of Sheffield", "Otter SC"])
    def test_real_club_names_are_untouched(self, raw: str) -> None:
        # Names that merely start with digits must not be truncated.
        v, _ = _normalise_club(raw)
        assert v == raw

    @pytest.mark.parametrize(
        "raw",
        [
            "1350m 13:53.80",  # distance + lap time (1500m splits page)
            "1350m",  # distance marker alone
            "13:53.80",  # lap/cumulative time alone
            "50 m",  # spaced distance token
            "[M",  # bracketed leg/stroke marker
            "[pull]",
            "(M",
        ],
    )
    def test_race_data_is_not_a_club(self, raw: str) -> None:
        # Split times / distances / leg markers from a splits-heavy page must
        # never surface as clubs (the picker was filling with '1350m 13:53.80').
        v, _ = _normalise_club(raw)
        assert v is None

    @pytest.mark.parametrize(
        "raw,expected",
        [
            # Para "Class" column (S14/SM14 etc.) absorbed into the club: fold the
            # para sub-group into its parent club.
            ("Co Cardiff 14", "Co Cardiff"),
            ("Swansea Uni 14", "Swansea Uni"),
            ("Team Bath AS 6", "Team Bath AS"),
            ("UoAPS 10", "UoAPS"),
        ],
    )
    def test_para_class_suffix_folds_into_parent_club(self, raw: str, expected: str) -> None:
        v, _ = _normalise_club(raw)
        assert v == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            # A whole "Name AaD Club" row collapsed into the club cell — recover
            # the actual club (the text after the age), so a swimmer never shows
            # up as a club in the picker.
            ("Dion Edwards 19 Swansea Uni", "Swansea Uni"),
            ("Chloe Morris 15 Millfield", "Millfield"),
            ("Donatas Dragasius 22 Chelsea&West", "Chelsea&West"),
        ],
    )
    def test_collapsed_name_age_club_recovers_club(self, raw: str, expected: str) -> None:
        v, _ = _normalise_club(raw)
        assert v == expected

    @pytest.mark.parametrize(
        "raw,expected",
        [
            # "NT" (No Time) is the seed-time placeholder. In a
            # "Name AaD Club Seed Finals" row it sits right after the club and
            # gets absorbed into the club cell — a trailing No-Time marker must
            # be stripped so it never spawns a phantom "<Club> NT" club.
            ("City of Brighton & Hove NT", "City of Brighton & Hove"),
            ("Beacon SC NT", "Beacon SC"),
            ("Atlantis SC NT", "Atlantis SC"),
            ("Worthing SC N.T.", "Worthing SC"),
            ("Brighton SC nt", "Brighton SC"),
        ],
    )
    def test_no_time_seed_marker_is_stripped_from_club(self, raw: str, expected: str) -> None:
        v, _ = _normalise_club(raw)
        assert v == expected

    @pytest.mark.parametrize("raw", ["City of Kent", "Trent SC", "Brent Dolphins", "Notts SC"])
    def test_club_ending_in_nt_letters_is_untouched(self, raw: str) -> None:
        # The No-Time strip needs a standalone trailing "NT" token; a real club
        # whose name merely ends in those letters (Kent, Trent) must survive.
        v, _ = _normalise_club(raw)
        assert v == raw

    def test_bare_no_time_marker_is_not_a_club(self) -> None:
        # A seed cell mis-mapped to the club column that holds only "NT" must
        # not surface as a club.
        v, _ = _normalise_club("NT")
        assert v is None
