"""F09 residual — bare pool-length section heading is context-gated.

The section-heading course detector treats a whole-cell bare pool length
("50m"/"25m") as a course marker (50m -> LC, 25m -> SC). On a *distance*-organised
PB table, a "50m" is a distance-GROUP heading, not a course marker, so flipping
the running section course to LC would mislabel the rows that follow (bounded —
only a label, never a fabricated PB, but still wrong).

The fix: a bare pool-length flips the running course only when the surrounding
page corroborates a course reading (it names LC/SC / Long/Short Course / a pool
somewhere). A genuine course heading — a course word, or "50m Pool" — is
unambiguous and still sets the course with no corroboration needed.

Guards both the table path and the free-text path, and keeps
tests/test_gapfix_f09-course.py's isolated-helper behaviour intact (the helper
called with no page context preserves the historical length->course mapping).
"""

from mediahub.pb_discovery.fetch_profile import ProfilePage
from mediahub.pb_discovery.parse_pbs import (
    _heuristic_extract_pbs,
    _page_corroborates_course,
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


class TestBareLengthHeadingIsContextGated:
    def test_bare_50m_with_no_course_context_does_not_flip(self):
        # With page context supplied and NO course signal anywhere, a bare "50m"
        # heading is treated as a distance group, not an LC marker.
        assert _section_course("50m", page_text="") is None
        assert _section_course("25m", page_text="Distances\n50m\n100m\n200m") is None

    def test_bare_50m_with_corroborating_context_still_flips(self):
        # The page elsewhere clearly names a course, so the bare length is a
        # genuine pool-length course heading again.
        assert _section_course("50m", page_text="Long Course records\n50m") == "LC"
        assert _section_course("25m", page_text="Short Course\n25m") == "SC"
        assert _section_course("50m", page_text="Records (LC)\n50m") == "LC"
        assert _section_course("50m", page_text="Olympic Pool\n50m") == "LC"

    def test_helper_with_no_page_arg_preserves_historical_mapping(self):
        # test_gapfix_f09-course.py calls the helper this way; must stay LC/SC.
        assert _section_course("50m") == "LC"
        assert _section_course("25m") == "SC"

    def test_course_word_heading_never_needs_corroboration(self):
        # Word / abbreviation headings are unambiguous even with a bare page.
        assert _section_course("Long Course", page_text="") == "LC"
        assert _section_course("Short Course", page_text="") == "SC"
        assert _section_course("LC", page_text="") == "LC"
        assert _section_course("50m Pool", page_text="") == "LC"


class TestCorroborationHelper:
    def test_signals_detected(self):
        assert _page_corroborates_course("Long Course results")
        assert _page_corroborates_course("Short Course results")
        assert _page_corroborates_course("Records (LC)")
        assert _page_corroborates_course("splits SC 2024")
        assert _page_corroborates_course("50m pool")
        assert _page_corroborates_course("Training Pool")

    def test_no_signal(self):
        assert not _page_corroborates_course("")
        assert not _page_corroborates_course(None)
        assert not _page_corroborates_course("50m\n100m\n200m\n400m")


class TestDistanceOrganisedTablePath:
    def test_bare_50m_group_heading_does_not_mislabel_following_rows(self):
        # A distance-organised table: a "50m" distance-GROUP heading, then event
        # rows under it. Page text carries no course signal, so the following
        # rows must NOT be flipped to LC by the group heading — they fall through
        # to the default "LC" only via the final fallback, and critically the
        # section course is never *set* to LC by the "50m" heading (which would
        # otherwise mislabel a "25m" group's rows on the same table as LC too).
        page = _page(
            tables=[
                [
                    ["50m"],
                    ["50m Freestyle", "24.10"],
                    ["25m"],
                    ["50m Freestyle", "26.30"],
                ]
            ],
        )
        rows = _heuristic_extract_pbs(page)
        by_time = {r.time_canonical: r.course for r in rows}
        # The "25m" group's row must NOT inherit an SC label from the preceding
        # "25m" distance-group heading (the mislabel the residual describes) — it
        # falls through to the honest default course instead of a group flip.
        assert by_time.get("26.30") == "LC"  # default fallback, not flipped by "25m" group
        # Both rows land under the honest default course, not a group-heading flip.
        assert by_time.get("24.10") == "LC"

    def test_distance_group_50m_does_not_flip_a_later_sc_context(self):
        # The concrete harm: a bare "50m" distance group heading followed by a
        # "25m" group. If "50m" were read as LC and "25m" as SC, the two same-
        # event rows would split across courses purely from distance grouping.
        page = _page(
            tables=[
                [
                    ["50m"],
                    ["100m Freestyle", "1:02.00"],
                    ["25m"],
                    ["100m Freestyle", "1:00.50"],
                ]
            ],
        )
        rows = _heuristic_extract_pbs(page)
        courses = {r.course for r in rows}
        # No spurious LC/SC split from the distance-group headings.
        assert courses == {"LC"}


class TestGenuineCourseHeadingStillWorks:
    def test_long_course_word_heading_sets_lc(self):
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
        by_time = {r.time_canonical: r.course for r in _heuristic_extract_pbs(page)}
        assert by_time.get("1:00.10") == "LC"
        assert by_time.get("57.80") == "SC"

    def test_50m_pool_heading_still_sets_lc(self):
        # A genuine "50m Pool" section heading (the phrase _LC_RE recognises)
        # still marks the following rows Long Course — no regression.
        page = _page(
            tables=[
                [
                    ["50m Pool"],
                    ["100m Freestyle", "1:00.10"],
                ]
            ],
        )
        rows = _heuristic_extract_pbs(page)
        assert rows and rows[0].course == "LC"

    def test_bare_length_heading_with_page_course_signal_sets_lc(self):
        # Course-organised page whose section headings happen to be bare pool
        # lengths, but the page text names the course elsewhere → still honoured.
        page = _page(
            text="Long Course Records",
            tables=[
                [
                    ["50m"],
                    ["100m Freestyle", "1:00.10"],
                ]
            ],
        )
        rows = _heuristic_extract_pbs(page)
        assert rows and rows[0].course == "LC"
