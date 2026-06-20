"""
Offline tests for the swimmingresults.org PB adapter.

No network: ``transport.fetch`` is monkeypatched per module with representative
HTML so the parser, name matcher, club/roster resolution, and the end-to-end
snapshot build are all exercised deterministically (the live chain is validated
separately by scripts/probe_swimmingresults.py).
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(_ROOT / "src"))

from mediahub.swimmingresults import names  # noqa: E402
from mediahub.swimmingresults.parse import parse_personal_best, time_to_cs  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixtures (HTML)
# --------------------------------------------------------------------------- #

PB_PAGE = """
<html><head><title>Swim England</title></head><body>
<p class="rnk_sj">Holly Greenslade - ( <a href="biogs_details.php?tiref=1153374">1153374</a> )
  - Torfaen Dolphins Performance</p>
<h2>Personal Best Times - Long Course</h2>
<table>
<tr><th>Stroke</th><th>Time</th><th>Conv</th><th>Pts</th><th>Date</th><th>Meet</th></tr>
<tr><td>50 Freestyle</td><td>30.91</td><td>30.50</td><td>400</td><td>03/04/22</td><td>Welsh Capital Open</td></tr>
<tr><td>100 Freestyle</td><td>1:06.13</td><td>1:05.00</td><td>410</td><td>09/08/21</td><td>Swansea Festival</td></tr>
<tr><td>200 Individual Medley</td><td>2:40.10</td><td>2:39.0</td><td>380</td><td>12/03/22</td><td>Bath L1</td></tr>
</table>
<h2>Personal Best Times - Short Course</h2>
<table>
<tr><th>Stroke</th><th>Time</th><th>Conv</th><th>Pts</th><th>Date</th><th>Meet</th></tr>
<tr><td>50 Freestyle</td><td>31.20</td><td>31.00</td><td>390</td><td>01/12/21</td><td>Cardiff SC</td></tr>
</table>
</body></html>
"""

FORM_PAGE = """
<form name="RankForm">
<select name="Stroke">
  <option value="1">50m Freestyle</option>
  <option value="2">100m Freestyle</option>
  <option value="13">50m Backstroke</option>
  <option value="16">200m Individual Medley</option>
</select>
<select name="TargetClub">
  <option value="XXXX">Please Choose</option>
  <option value="TDOYEWAY">Torfaen Dolphins Performance</option>
  <option value="COCYEWAY">City of Cardiff</option>
</select>
</form>
"""

ROSTER_PAGE = """
<html><body>
<table>
<tr><td>1</td><td><a href="biogs_details.php?tiref=1153374">Holly Greenslade</a></td><td>1:06.13</td></tr>
<tr><td>2</td><td><a href="biogs_details.php?tiref=1339695">Theodora Taylor</a></td><td>1:07.20</td></tr>
<tr><td>3</td><td><a href="biogs_details.php?tiref=1361917">Charlie Sherrard</a></td><td>1:08.00</td></tr>
</table>
</body></html>
"""


def _fake_fetch(url: str, *, timeout=None) -> str:
    if "eventrankings.php" in url:
        return ROSTER_PAGE
    if "personal_best.php" in url:
        return PB_PAGE
    if "/eventrankings/" in url:  # the form page (club register + stroke map)
        return FORM_PAGE
    raise AssertionError(f"unexpected fetch: {url}")


@pytest.fixture(autouse=True)
def _patch_fetch_and_caches(monkeypatch):
    """Route every module's fetch to the fixtures and clear process caches."""
    from mediahub.swimmingresults import clubs, roster, lookup

    monkeypatch.setattr(clubs, "fetch", _fake_fetch)
    monkeypatch.setattr(roster, "fetch", _fake_fetch)
    monkeypatch.setattr(lookup, "fetch", _fake_fetch)
    clubs._CACHE.clear()
    clubs._CACHE_AT = 0.0
    roster._EVENTNO.clear()
    roster._EVENTNO_AT = 0.0
    roster._SLICE_CACHE.clear()
    yield


# --------------------------------------------------------------------------- #
# Parser
# --------------------------------------------------------------------------- #

def test_time_to_cs():
    assert time_to_cs("30.91") == 3091
    assert time_to_cs("1:06.13") == 6613
    assert time_to_cs("15:48.50") == 94850
    assert time_to_cs("nonsense") is None


def test_parse_personal_best_extracts_events_with_course():
    page = parse_personal_best(PB_PAGE, "1153374")
    assert page.swimmer_name == "Holly Greenslade"
    assert "Torfaen Dolphins" in page.club
    keys = {f"{e.distance}{e.stroke}{e.course}" for e in page.entries}
    assert keys == {"50FRLC", "100FRLC", "200IMLC", "50FRSC"}
    lc50 = next(e for e in page.entries if e.distance == 50 and e.course == "LC")
    assert lc50.time_cs == 3091
    assert lc50.time_sec == pytest.approx(30.91)
    assert lc50.date_iso == "2022-04-03"


def test_parse_drops_entry_without_resolvable_course():
    # No course heading anywhere → fallback assumes first table is LC.
    html = "<table><tr><td>50 Freestyle</td><td>29.00</td><td>x</td><td>x</td><td>01/01/24</td></tr></table>"
    page = parse_personal_best(html, "9")
    assert [f"{e.distance}{e.stroke}{e.course}" for e in page.entries] == ["50FRLC"]


# --------------------------------------------------------------------------- #
# Name matching
# --------------------------------------------------------------------------- #

@pytest.mark.parametrize(
    "fa,la,fb,lb,expected",
    [
        ("Holly", "Greenslade", "Holly", "Greenslade", True),
        ("Charlie", "Smith", "Charles", "Smith", True),   # nickname
        ("Sam", "Jones", "Samuel", "Jones", True),        # nickname
        ("Ben", "Carter", "Benjamin", "Carter", True),    # prefix
        ("Sophie", "Lee", "Sofie", "Lee", True),          # 1-edit spelling
        ("Holly", "Greenslade", "Holly", "Greenwood", False),  # surname differs
        ("John", "Smith", "Jane", "Smith", False),        # distinct first names
        ("", "Smith", "John", "Smith", False),            # missing name
    ],
)
def test_name_match(fa, la, fb, lb, expected):
    assert names.name_match(fa, la, fb, lb) is expected


# --------------------------------------------------------------------------- #
# Club + roster resolution
# --------------------------------------------------------------------------- #

def test_resolve_club_code_fuzzy():
    from mediahub.swimmingresults.clubs import resolve_club_code

    assert resolve_club_code("Torfaen Dolphins") == "TDOYEWAY"
    assert resolve_club_code("Torfaen Dolphins Performance") == "TDOYEWAY"
    assert resolve_club_code("City of Cardiff") == "COCYEWAY"
    assert resolve_club_code("Nonexistent SC") is None


def test_roster_slice_reads_tiref_pairs():
    from mediahub.swimmingresults.roster import roster_slice, event_number

    assert event_number(100, "FR") == "2"
    sl = roster_slice("TDOYEWAY", "F", 13, 100, "FR", "LC")
    assert sl["1153374"] == "Holly Greenslade"
    assert "1339695" in sl


# --------------------------------------------------------------------------- #
# End-to-end: meet swimmers -> BridgedSnapshot
# --------------------------------------------------------------------------- #

def _sw(key, first, last, gender="F", age=None, asa=None):
    return types.SimpleNamespace(
        swimmer_key=key, first_name=first, last_name=last, gender=gender,
        age_at_meet=age, dob=None, asa_id=asa, club_code=None,
        club_name="Torfaen Dolphins",
    )


def _rr(key, dist=100, stroke="FR", course="LC", band="13"):
    return types.SimpleNamespace(
        swimmer_key=key, age_band=band, distance=dist, stroke=stroke,
        course=course, gender="F", finals_time_cs=9999,
    )


def test_lookup_official_pbs_asa_and_roster_and_miss():
    from mediahub.swimmingresults import lookup_official_pbs

    swimmers = {
        "s1": _sw("s1", "Holly", "Greenslade", asa="1153374"),   # asa fast path
        "s2": _sw("s2", "Charlie", "Sherrard", age=13),          # roster + nickname
        "s3": _sw("s3", "Nobody", "Nemo", age=13),               # not on roster
    }
    results = [_rr("s1"), _rr("s2"), _rr("s3")]
    meet = types.SimpleNamespace(
        swimmers=swimmers, results=results, start_date="2023-03-01", end_date="2023-03-01"
    )

    snaps = lookup_official_pbs(meet, set(swimmers), "Torfaen Dolphins")

    # s1 resolved by member id, s2 by name+club+age (Charlie≈Charles? here exact),
    # s3 unresolved -> no snapshot (honest miss, never a guessed baseline).
    assert set(snaps) == {"s1", "s2"}
    s1 = snaps["s1"]
    assert s1.source_domain == "swimmingresults.org"
    assert "50FRLC" in s1.pb_times and "100FRLC" in s1.pb_times
    assert s1.pb_times["50FRLC"][0]["time_sec"] == pytest.approx(30.91)
    assert s1.pb_times["50FRLC"][0]["date_iso"] == "2022-04-03"
    assert s1.tiref == "s1"  # snapshot is keyed by the canonical swimmer_key


def test_lookup_skips_when_club_not_found():
    from mediahub.swimmingresults import lookup_official_pbs

    swimmers = {"s1": _sw("s1", "Holly", "Greenslade", age=13)}
    meet = types.SimpleNamespace(
        swimmers=swimmers, results=[_rr("s1")], start_date="2023-03-01", end_date=None
    )
    # A club name not in the register -> no roster path, no snapshot, no crash.
    snaps = lookup_official_pbs(meet, {"s1"}, "Some Australian Club")
    assert snaps == {}
