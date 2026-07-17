"""Finding #57 — no positional course fallback in the swimmingresults parser.

The parser's no-heading fallback positionally guessed course (first table = LC,
second = SC), contradicting the module docstring ("an entry is dropped if the
course cannot be determined — never silently defaulted"). A guessed course flows
straight into the PB baseline key (`f"{distance}{stroke}{course}"`), so an LC
time could become a wrong PB against an SC baseline. The fallback is removed:
heading-less tables are dropped; heading-ful pages are unaffected.
"""

from __future__ import annotations

from mediahub.swimmingresults.parse import parse_personal_best

_HEADING_LESS = (
    "<table><tr><td>50 Freestyle</td><td>29.00</td>"
    "<td>x</td><td>x</td><td>01/01/24</td></tr></table>"
)

_HEADING_FUL = """
<h2>Personal Best Times - Long Course</h2>
<table>
<tr><th>Stroke</th><th>Time</th><th>Conv</th><th>Pts</th><th>Date</th><th>Meet</th></tr>
<tr><td>50 Freestyle</td><td>29.00</td><td>28.5</td><td>400</td><td>01/01/24</td><td>Meet</td></tr>
</table>
"""


def test_heading_less_table_is_dropped_not_guessed():
    page = parse_personal_best(_HEADING_LESS, "9")
    assert page.entries == [], "an unresolvable-course row must be dropped, not defaulted to LC"


def test_heading_ful_page_still_parses():
    # The fix only drops genuinely ambiguous heading-less tables — a real page
    # with a Long/Short Course heading still yields its entries with the right course.
    page = parse_personal_best(_HEADING_FUL, "9")
    keys = [f"{e.distance}{e.stroke}{e.course}" for e in page.entries]
    assert keys == ["50FRLC"], keys
