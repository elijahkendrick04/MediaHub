"""F09 (section-heading course tracking) regression.

A page laid out as a Long-Course *section heading* row followed by data rows
(event + time only), then a Short-Course heading row and its data rows, must
file each section's times under its own course — the SC time must NOT flatten
onto the LC key (and vice versa). Guards both the table path and the free-text
path of the heuristic extractor.
"""

from mediahub.pb_discovery.fetch_profile import ProfilePage
from mediahub.pb_discovery.parse_pbs import (
    _heuristic_extract_pbs,
    _section_course,
)


def _page(text="", tables=None):
    return ProfilePage(
        url="https://example.test/profile",
        fetched_at="2026-01-01T00:00:00Z",
        text=text,
        tables=tables or [],
        fetch_success=True,
    )


class TestSectionCourseHelper:
    def test_word_headings(self):
        assert _section_course("Long Course") == "LC"
        assert _section_course("Short Course") == "SC"
        assert _section_course("LC") == "LC"
        assert _section_course("SC") == "SC"

    def test_bare_pool_length_headings(self):
        assert _section_course("50m") == "LC"
        assert _section_course("25m") == "SC"
        assert _section_course("50 m pool") == "LC"

    def test_data_row_is_not_a_heading(self):
        # A row carrying a swim time is a data row, never a section heading.
        assert _section_course("100m Freestyle 1:00.10") is None
        assert _section_course("50m Freestyle 24.10") is None

    def test_unmarked_row_is_not_a_heading(self):
        assert _section_course("Personal Bests") is None


class TestSectionHeadingTablePath:
    def test_lc_and_sc_sections_kept_distinct(self):
        # The layout the finding targets: heading rows with only a course marker,
        # then data rows with event + time only.
        page = _page(
            tables=[
                [
                    ["Long Course"],
                    ["100m Freestyle", "1:00.10"],
                    ["Short Course"],
                    ["100m Freestyle", "57.80"],
                ]
            ],
        )
        rows = _heuristic_extract_pbs(page)
        by_time = {r.time_canonical: r.course for r in rows}
        # Both preserved, not flattened onto one course.
        assert by_time.get("1:00.10") == "LC"
        assert by_time.get("57.80") == "SC"
        # And they are genuinely distinct keys (course differs for same event).
        assert {(r.event, r.course) for r in rows} == {
            ("100m Freestyle", "LC"),
            ("100m Freestyle", "SC"),
        }

    def test_headings_in_separate_tables_persist(self):
        # A heading in one table governs data rows in the next.
        page = _page(
            tables=[
                [["Long Course"]],
                [["100m Freestyle", "1:00.10"]],
                [["Short Course"]],
                [["100m Freestyle", "57.80"]],
            ],
        )
        by_time = {r.time_canonical: r.course for r in _heuristic_extract_pbs(page)}
        assert by_time.get("1:00.10") == "LC"
        assert by_time.get("57.80") == "SC"

    def test_inline_marker_still_wins_over_section(self):
        # An inline course token on the data row overrides the section heading.
        page = _page(
            tables=[
                [
                    ["Long Course"],
                    ["100m Freestyle", "57.80", "SC"],
                ]
            ],
        )
        rows = _heuristic_extract_pbs(page)
        assert rows and rows[0].course == "SC"


class TestSectionHeadingFreeTextPath:
    def test_lc_and_sc_sections_kept_distinct(self):
        page = _page(
            text=(
                "Long Course\n"
                "100m Freestyle 1:00.10\n"
                "Short Course\n"
                "100m Freestyle 57.80\n"
            ),
        )
        by_time = {r.time_canonical: r.course for r in _heuristic_extract_pbs(page)}
        assert by_time.get("1:00.10") == "LC"
        assert by_time.get("57.80") == "SC"


def test_unmarked_page_still_defaults_to_lc():
    # No heading, no inline marker, no page marker → the existing "LC" fallback.
    page = _page(tables=[[["100m Freestyle", "58.90"]]])
    rows = _heuristic_extract_pbs(page)
    assert rows and rows[0].course == "LC"
