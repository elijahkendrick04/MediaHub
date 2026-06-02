"""
Regression tests for meet level classification.

Bug: "West Wales Regional SC Championships 2024" was misclassified as
'national' because 'championships' was checked against _NATIONAL_KEYWORDS
before 'regional' was checked against _COUNTY_KEYWORDS.
"""
import pytest

from legacy.swim_content_v5.context_profile import _infer_meet_level
from legacy.swim_content_v5.report import _normalise_meet_level


# ---------------------------------------------------------------------------
# _infer_meet_level regression
# ---------------------------------------------------------------------------

class TestInferMeetLevel:
    def test_regional_championships_is_not_national(self):
        """'Regional' qualifier must override the 'championships' keyword."""
        result = _infer_meet_level("West Wales Regional SC Championships 2024", None)
        assert result != "national", (
            f"'West Wales Regional SC Championships 2024' was misclassified as "
            f"'{result}'; expected county (not national)"
        )

    def test_regional_championships_classified_as_county(self):
        result = _infer_meet_level("West Wales Regional SC Championships 2024", None)
        assert result == "county"

    def test_county_championships_classified_as_county(self):
        result = _infer_meet_level("Midland County Championships 2024", None)
        assert result == "county"

    def test_national_championships_still_national(self):
        result = _infer_meet_level("British National Championships 2024", None)
        assert result == "national"

    def test_nationals_keyword_still_national(self):
        result = _infer_meet_level("ASA Nationals 2024", None)
        assert result == "national"

    def test_british_swimming_still_national(self):
        result = _infer_meet_level("British Swimming Championships", None)
        assert result == "national"

    def test_scottish_championships_classified_as_county(self):
        result = _infer_meet_level("Scottish SC Championships 2024", None)
        assert result == "county"

    def test_welsh_championships_classified_as_county(self):
        result = _infer_meet_level("Welsh Swimming Championships", None)
        assert result == "county"

    def test_open_meet(self):
        result = _infer_meet_level("Newtown Open Gala 2024", None)
        assert result == "open"

    def test_unknown_falls_back_to_open(self):
        result = _infer_meet_level("Poolside Sprint Series", None)
        assert result == "open"


# ---------------------------------------------------------------------------
# _normalise_meet_level regression (research-data path)
# ---------------------------------------------------------------------------

class TestNormaliseMeetLevel:
    def test_regional_championships_string_not_national(self):
        """Research returning 'Regional Championships' must not map to national."""
        result = _normalise_meet_level("Regional Championships")
        assert result != "national", (
            f"_normalise_meet_level('Regional Championships') returned '{result}'; "
            f"'Regional Championships' is not a national-level meet"
        )

    def test_regional_championships_string_maps_to_regional(self):
        result = _normalise_meet_level("Regional Championships")
        assert result == "regional"

    def test_national_championships_still_national(self):
        result = _normalise_meet_level("National Championships")
        assert result == "national"

    def test_british_championships_still_national(self):
        result = _normalise_meet_level("British Championships")
        assert result == "national"

    def test_county_championships_maps_to_county(self):
        result = _normalise_meet_level("County Championships")
        assert result == "county"

    def test_level_1_still_national(self):
        result = _normalise_meet_level("Level 1")
        assert result == "national"

    def test_none_returns_none(self):
        result = _normalise_meet_level(None)
        assert result is None

    def test_empty_returns_open(self):
        result = _normalise_meet_level("")
        assert result is None
