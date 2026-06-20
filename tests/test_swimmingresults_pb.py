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

def _row(tiref, name, yob, swimid, time):
    return (
        f'<tr><td>1</td>'
        f'<td><a href="/individualbest/personal_best.php?tiref={tiref}&mode=A">{name}</a></td>'
        f'<td>Torfaen D</td><td>{yob}</td><td>Meet</td><td>01/01/24</td>'
        f'<td><a href="/splits/index.php?swimid={swimid}" class="splits-lightbox"> {time}</a></td></tr>'
    )


def _row_plain(tiref, name, yob, time):
    """A ranking row whose time is PLAIN TEXT (no splits link) — what the great
    majority of real rows look like. Only swimmers with recorded splits get the
    lightbox link; reading the time solely from that link dropped ~80% of a
    club's roster (the 54/79 production regression)."""
    return (
        f'<tr><td>1</td>'
        f'<td><a href="/individualbest/personal_best.php?tiref={tiref}&mode=A">{name}</a></td>'
        f'<td>Torfaen D</td><td>{yob}</td><td>Meet</td><td>02/02/24</td>'
        f'<td>{time}</td></tr>'
    )


# Two same-surname siblings (Tincombe) to exercise time-based disambiguation
# without any first-name nickname rule.
ROSTER_PAGE = (
    "<html><body><table>"
    + _row("1153374", "Holly Greenslade", "09", "111", "1:06.13")
    + _row("1339695", "Theodora Taylor", "09", "112", "1:07.20")
    + _row("1361917", "Charlie Sherrard", "10", "113", "1:08.00")
    + _row("2001", "Raffaelle Tincombe", "11", "114", "1:05.00")
    + _row("2002", "Matilda Tincombe", "12", "115", "1:20.00")
    # A swimmer whose time is plain text (no splits link) — the common case.
    + _row_plain("3001", "Maisie Pugh", "11", "1:09.50")
    + "</table></body></html>"
)


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
    lookup._ROSTER_CACHE.clear()
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


def test_roster_slice_reads_name_and_time():
    from mediahub.swimmingresults.roster import roster_slice, event_number

    assert event_number(100, "FR") == "2"
    sl = roster_slice("TDOYEWAY", "F", 13, 100, "FR", "LC")
    name, time_cs, date_iso, meet = sl["1153374"]
    assert name == "Holly Greenslade"
    assert time_cs == 6613  # 1:06.13 parsed from the splits link
    assert date_iso == "2024-01-01"  # 01/01/24 parsed from the row
    assert "1339695" in sl


def test_roster_slice_captures_plain_text_time():
    """Regression (the 54/79 production drop): a ranking row whose time is plain
    text — no splits link — must still yield the time. Only swimmers with
    recorded splits get the lightbox link, so reading time solely from the link
    left ~80% of the roster with empty times, and those swimmers were dropped at
    the ``if snap.pb_times`` guard."""
    from mediahub.swimmingresults.roster import roster_slice

    sl = roster_slice("TDOYEWAY", "F", 13, 100, "FR", "LC")
    name, time_cs, date_iso, meet = sl["3001"]
    assert name == "Maisie Pugh"
    assert time_cs == 6950  # 1:09.50 read from PLAIN TEXT, not a splits link
    assert date_iso == "2024-02-02"


# --------------------------------------------------------------------------- #
# End-to-end: meet swimmers -> BridgedSnapshot
# --------------------------------------------------------------------------- #

def _sw(key, first, last, gender="F", age=None, asa=None):
    return types.SimpleNamespace(
        swimmer_key=key, first_name=first, last_name=last, gender=gender,
        age_at_meet=age, dob=None, asa_id=asa, club_code=None,
        club_name="Torfaen Dolphins",
    )


def _rr(key, dist=100, stroke="FR", course="LC", band="13", cs=9999):
    return types.SimpleNamespace(
        swimmer_key=key, age_band=band, distance=dist, stroke=stroke,
        course=course, gender="F", finals_time_cs=cs,
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


def test_match_by_unique_surname_without_nickname():
    """A first name with no nickname rule still resolves when the surname is
    unique in the club — the first name is not load-bearing."""
    from mediahub.swimmingresults import lookup_official_pbs

    swimmers = {"s1": _sw("s1", "Zzqq", "Greenslade", age=13)}  # nonsense first name
    meet = types.SimpleNamespace(
        swimmers=swimmers, results=[_rr("s1")], start_date="2024-01-01", end_date=None
    )
    snaps = lookup_official_pbs(meet, {"s1"}, "Torfaen Dolphins")
    assert "s1" in snaps  # matched Holly Greenslade by unique surname, no nickname


def test_siblings_disambiguated_by_time_not_nickname():
    """Two same-surname siblings, a first name with no nickname rule ("Raffy"):
    the meet time picks the right one (Raffaelle, tiref 2001 — 1:05 — not Matilda
    at 1:20)."""
    from mediahub.swimmingresults import lookup_official_pbs

    swimmers = {"s1": _sw("s1", "Raffy", "Tincombe", age=13)}
    meet = types.SimpleNamespace(
        swimmers=swimmers, results=[_rr("s1", cs=6550)], start_date="2024-01-01", end_date=None
    )
    snaps = lookup_official_pbs(meet, {"s1"}, "Torfaen Dolphins")
    assert "s1" in snaps
    assert "tiref=2001" in (snaps["s1"].source_url or "")  # Raffaelle, by time


def test_plain_text_row_swimmer_gets_snapshot():
    """End-to-end regression for the 54/79 drop: a swimmer whose ranking row
    carries a plain-text time (no splits link) still produces a PB snapshot from
    the rankings. Before the fix these were resolved to a tiref but then dropped
    because their roster ``events`` were empty, so ``snap.pb_times`` was empty."""
    from mediahub.swimmingresults import lookup_official_pbs

    swimmers = {"s1": _sw("s1", "Maisie", "Pugh", age=13)}
    meet = types.SimpleNamespace(
        swimmers=swimmers, results=[_rr("s1")], start_date="2024-01-01", end_date=None
    )
    snaps = lookup_official_pbs(meet, {"s1"}, "Torfaen Dolphins")
    assert "s1" in snaps  # not dropped — the plain-text time gave it a PB
    assert "100FRLC" in snaps["s1"].pb_times
    assert snaps["s1"].pb_times["100FRLC"][0]["time_sec"] == pytest.approx(69.50)


def test_unmatched_report_distinguishes_missing_surname_from_ambiguous():
    """The unmatched report must give each gap a data-grounded reason from the
    swept roster: a surname absent from the club's rankings (a genuine "not
    ranked" miss) reads differently from a same-surname set that didn't resolve
    (a disambiguation that fell through) — so the operator never has to guess."""
    from mediahub.swimmingresults.lookup import _unmatched_report

    roster = {
        "1": {"name": "Holly Greenslade", "events": {}},
        "2a": {"name": "Raffaelle Tincombe", "events": {}},
        "2b": {"name": "Matilda Tincombe", "events": {}},
    }
    swimmers = {
        "a": types.SimpleNamespace(first_name="Nobody", last_name="Nemo"),
        "b": types.SimpleNamespace(first_name="Zzz", last_name="Tincombe"),
    }
    rep = dict(_unmatched_report({"a", "b"}, {}, swimmers, roster))
    assert "no ranked swimmer with that surname" in rep["Nobody Nemo"]
    assert "same-surname candidate" in rep["Zzz Tincombe"]  # two Tincombes on roster


def test_lookup_logs_unmatched_swimmers_by_name():
    """End-to-end: the resolution summary names the swimmers it could not match
    (here the off-roster "Nobody Nemo"), so the exact gaps surface in the logs."""
    from mediahub.swimmingresults import lookup_official_pbs

    swimmers = {
        "s1": _sw("s1", "Holly", "Greenslade", asa="1153374"),  # matches by id
        "s3": _sw("s3", "Nobody", "Nemo", age=13),  # not on the roster
    }
    meet = types.SimpleNamespace(
        swimmers=swimmers,
        results=[_rr("s1"), _rr("s3")],
        start_date="2023-03-01",
        end_date=None,
    )
    lines: list[str] = []
    lookup_official_pbs(meet, set(swimmers), "Torfaen Dolphins", step=lines.append)
    assert any("unmatched" in ln.lower() and "Nobody Nemo" in ln for ln in lines)


def test_match_one_resolves_diminutive_and_spelling_variants():
    """The matcher resolves a diminutive (Vivi->Vivienne, a clean prefix) and a
    1-edit spelling variant (Mia<->Miya, both directions) when the lone
    same-surname candidate is in the searched pool — surname + a real
    nickname/prefix/spelling relationship, no first-name dictionary needed."""
    from mediahub.swimmingresults.lookup import _match_one

    peel = {"P": {"name": "Vivienne Peel", "events": {"100FRLC": {"time_cs": 7000}}, "sex": "F"}}
    assert _match_one("Vivi", "Peel", {"100FRLC": 7200}, peel) == "P"

    croft = {"C": {"name": "Miya Croft", "events": {"50FRLC": {"time_cs": 3000}}, "sex": "F"}}
    assert _match_one("Mia", "Croft", {"50FRLC": 3100}, croft) == "C"
    croft2 = {"C": {"name": "Mia Croft", "events": {"50FRLC": {"time_cs": 3000}}, "sex": "F"}}
    assert _match_one("Miya", "Croft", {"50FRLC": 3100}, croft2) == "C"


def test_match_one_does_not_force_genuinely_different_same_surname():
    """Two same-surname candidates, neither a nickname/prefix of the meet first
    name, with times that don't single one out → no match (never a false match)."""
    from mediahub.swimmingresults.lookup import _match_one

    roster = {
        "A": {"name": "George Peel", "events": {"100FRLC": {"time_cs": 6000}}, "sex": "M"},
        "B": {"name": "Harold Peel", "events": {"100FRLC": {"time_cs": 6010}}, "sex": "M"},
    }
    assert _match_one("Vivi", "Peel", {"100FRLC": 9000}, roster) is None


def test_resolved_but_no_roster_time_recovered_via_pb_page(monkeypatch):
    """A swimmer confidently resolved by name+club+age but whose all-time ranking
    rows carried no usable time (here a DQ-only row → empty roster events) is NOT
    dropped: we fall back to the authoritative personal_best.php for the resolved
    member id and recover her PBs."""
    from mediahub.swimmingresults import clubs, lookup
    from mediahub.swimmingresults import roster as roster_mod
    from mediahub.swimmingresults import lookup_official_pbs

    notime_roster = (
        "<html><body><table>"
        '<tr><td>1</td>'
        '<td><a href="/individualbest/personal_best.php?tiref=1153374&mode=A">Holly Greenslade</a></td>'
        "<td>Torfaen D</td><td>09</td><td>Meet</td><td>01/01/24</td><td>DQ</td></tr>"
        "</table></body></html>"
    )

    def fake(url, *, timeout=None):
        if "eventrankings.php" in url:
            return notime_roster
        if "personal_best.php" in url:
            return PB_PAGE  # the authoritative record DOES carry PBs
        if "/eventrankings/" in url:
            return FORM_PAGE
        raise AssertionError(f"unexpected fetch: {url}")

    monkeypatch.setattr(clubs, "fetch", fake)
    monkeypatch.setattr(roster_mod, "fetch", fake)
    monkeypatch.setattr(lookup, "fetch", fake)

    swimmers = {"s1": _sw("s1", "Holly", "Greenslade", age=13)}
    meet = types.SimpleNamespace(
        swimmers=swimmers, results=[_rr("s1")], start_date="2024-01-01", end_date=None
    )
    snaps = lookup_official_pbs(meet, {"s1"}, "Torfaen Dolphins")
    assert "s1" in snaps  # resolved off the timeless roster, recovered via the PB page
    assert "50FRLC" in snaps["s1"].pb_times  # PBs came from personal_best.php


def test_unmatched_report_flags_sex_mismatch():
    """When the lone same-surname candidate is the opposite sex to the swimmer's
    parsed gender, the report shows BOTH — so a gender-parse bug (the cause hides
    behind a generic 'none resolved') is obvious in the logs."""
    from mediahub.swimmingresults.lookup import _unmatched_report

    roster = {"P": {"name": "Vivienne Peel", "events": {}, "sex": "F"}}
    swimmers = {"s1": types.SimpleNamespace(first_name="Vivi", last_name="Peel", gender="M")}
    r = dict(_unmatched_report({"s1"}, {}, swimmers, roster))["Vivi Peel"]
    assert "sex=F" in r and "gender=M" in r and "Vivienne Peel" in r


def test_unmatched_report_flags_resolved_but_empty():
    """A swimmer resolved to a tiref but with no recoverable PB is reported as
    'resolved … but no usable PB time', distinct from an unresolved name."""
    from mediahub.swimmingresults.lookup import _unmatched_report

    roster = {"P": {"name": "Vivienne Peel", "events": {}, "sex": "F"}}
    swimmers = {"s1": types.SimpleNamespace(first_name="Vivi", last_name="Peel", gender="F")}
    r = dict(_unmatched_report({"s1"}, {}, swimmers, roster, {"s1": "P"}))["Vivi Peel"]
    assert "resolved to Vivienne Peel" in r and "no usable PB time" in r


def test_lookup_skips_when_club_not_found():
    from mediahub.swimmingresults import lookup_official_pbs

    swimmers = {"s1": _sw("s1", "Holly", "Greenslade", age=13)}
    meet = types.SimpleNamespace(
        swimmers=swimmers, results=[_rr("s1")], start_date="2023-03-01", end_date=None
    )
    # A club name not in the register -> no roster path, no snapshot, no crash.
    snaps = lookup_official_pbs(meet, {"s1"}, "Some Australian Club")
    assert snaps == {}
