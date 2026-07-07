"""
tests_v75/test_interpreter_corpus.py
====================================

Synthetic fixtures that exercise the V7.5 interpreter's hardened paths:

  1. Frameset HTML pointing to sibling event pages on disk.
  2. Multi-line row PDF (place+name parent line followed by a split-times line).
  3. Header-less PDF (pure data rows, no column header text).

These tests use ``source_path`` so the interpreter can follow on-disk siblings,
and they only assert structural shapes — never any swim vocabulary literal.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from mediahub.interpreter import interpret_document
from mediahub.interpreter.ingest import ingest


# ---------------------------------------------------------------------------
# 1. Frameset HTML + sibling event pages
# ---------------------------------------------------------------------------

_FRAMESET_SHELL = b"""<!DOCTYPE html>
<html>
<head><title>Meet</title></head>
<frameset cols="200,*">
  <frame src="menu.html" name="MenuFrame">
  <frame src="main.html" name="MainFrame">
</frameset>
</html>"""

_EVENT_PAGE_TEMPLATE = """<!DOCTYPE html>
<html><body>
<h2>Event {n}: Female 50m Freestyle</h2>
<table>
<tr><th>Place</th><th>Name</th><th>YOB</th><th>Club</th><th>Time</th></tr>
<tr><td>1</td><td>Alpha Beta</td><td>2010</td><td>Test SC</td><td>28.45</td></tr>
<tr><td>2</td><td>Gamma Delta</td><td>2010</td><td>Other SC</td><td>29.12</td></tr>
<tr><td>3</td><td>Epsilon Zeta</td><td>2011</td><td>Test SC</td><td>30.55</td></tr>
<tr><td>4</td><td>Eta Theta</td><td>2010</td><td>Third SC</td><td>31.01</td></tr>
</table>
</body></html>"""


def test_frameset_with_sibling_event_pages(tmp_path: Path):
    """Thin frameset shell + sibling RG*.HTM-style files must aggregate."""
    shell = tmp_path / "results.html"
    shell.write_bytes(_FRAMESET_SHELL)
    # Create sibling event pages with the structural filename shape
    for n in (101, 102, 103):
        sib = tmp_path / f"RG{n}.HTM"
        sib.write_text(_EVENT_PAGE_TEMPLATE.format(n=n))

    result = interpret_document(shell.read_bytes(), hint="html", source_path=shell)
    total_swims = sum(len(e.swims) for e in result.events)
    assert total_swims >= 9, f"frameset+sibling aggregation produced only {total_swims} swims"
    # At least one event should have been induced from the headers
    assert len(result.events) >= 1


# ---------------------------------------------------------------------------
# 2. Multi-line row PDF (Hytek split-time pattern)
# ---------------------------------------------------------------------------


def _build_multiline_pdf_bytes() -> bytes:
    """Build a tiny PDF where each result row spans two visual lines.

    Layout::

        Event 1 Female 50m Freestyle
        Place Name             AaD Club           Time
        1     Alpha Beta       12  Test SC      28.45
              13.10 28.45
        2     Gamma Delta      12  Other SC     29.12
              13.50 29.12
    """
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
    except ImportError:
        pytest.skip("reportlab not installed")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Courier", 10)
    y = 720
    rows = [
        "Event 1 Female 50m Freestyle",
        "Place Name              AaD Club          Time",
        "1     Alpha Beta        12  Test SC       28.45",
        "                                    13.10 28.45",
        "2     Gamma Delta       12  Other SC      29.12",
        "                                    13.50 29.12",
        "3     Epsilon Zeta      12  Third SC      30.55",
        "                                    14.20 30.55",
        "4     Eta Theta         12  Fourth SC     31.10",
        "                                    14.70 31.10",
    ]
    for row in rows:
        c.drawString(72, y, row)
        y -= 14
    c.showPage()
    c.save()
    return buf.getvalue()


def test_multiline_row_pdf_extraction(tmp_path: Path):
    pdf_bytes = _build_multiline_pdf_bytes()
    pdf_path = tmp_path / "synth.pdf"
    pdf_path.write_bytes(pdf_bytes)

    result = interpret_document(pdf_bytes, hint="pdf", source_path=pdf_path)
    total_swims = sum(len(e.swims) for e in result.events)
    assert total_swims >= 4, (
        f"multi-line PDF extraction yielded {total_swims} swims; expected \u22654"
    )
    # Times must be present and in canonical shape
    flat = [s for e in result.events for s in e.swims]
    times = [s.time for s in flat if s.time]
    assert all(":" in t or "." in t for t in times)


# ---------------------------------------------------------------------------
# 3. Header-less PDF (pure data, no column-header line)
# ---------------------------------------------------------------------------


def _build_headerless_pdf_bytes() -> bytes:
    try:
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter
    except ImportError:
        pytest.skip("reportlab not installed")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Courier", 10)
    y = 720
    rows = [
        "Event 1 Female 50m Freestyle",
        # NOTE: no header row at all
        "1   Alpha Beta        12  Test SC       28.45",
        "2   Gamma Delta       12  Other SC      29.12",
        "3   Epsilon Zeta      12  Third SC      30.55",
        "4   Eta Theta         12  Fourth SC     31.10",
        "5   Iota Kappa        12  Fifth SC      32.20",
    ]
    for row in rows:
        c.drawString(72, y, row)
        y -= 14
    c.showPage()
    c.save()
    return buf.getvalue()


def test_headerless_pdf_extraction(tmp_path: Path):
    pdf_bytes = _build_headerless_pdf_bytes()
    pdf_path = tmp_path / "headerless.pdf"
    pdf_path.write_bytes(pdf_bytes)

    result = interpret_document(pdf_bytes, hint="pdf", source_path=pdf_path)
    total_swims = sum(len(e.swims) for e in result.events)
    assert total_swims >= 5, f"header-less PDF extraction yielded {total_swims}; expected \u22655"
    flat = [s for e in result.events for s in e.swims]
    # Names and times should be populated for each row
    assert all(s.swimmer_name for s in flat)
    assert all(s.time for s in flat)


# ---------------------------------------------------------------------------
# 4. Sibling-PDF aggregation when HTML body is empty
# ---------------------------------------------------------------------------


def test_thin_html_with_sibling_pdf(tmp_path: Path):
    """A landing-page HTML with no useful content should follow sibling PDFs."""
    pdf_bytes = _build_headerless_pdf_bytes()
    (tmp_path / "results_s1.pdf").write_bytes(pdf_bytes)
    shell = tmp_path / "results.html"
    shell.write_text("<html><body><h1>See PDF below</h1></body></html>")
    result = interpret_document(shell.read_bytes(), hint="html", source_path=shell)
    total_swims = sum(len(e.swims) for e in result.events)
    assert total_swims >= 5, (
        f"thin-html + sibling PDF yielded {total_swims} swims; expected \u22655"
    )


# ---------------------------------------------------------------------------
# 5. Source-path None should still work (bytes-only callers)
# ---------------------------------------------------------------------------


def test_bytes_only_caller_still_extracts():
    """Callers without source_path must still get useful output for plain HTML."""
    body = _EVENT_PAGE_TEMPLATE.format(n=1).encode()
    result = interpret_document(body, hint="html")
    total_swims = sum(len(e.swims) for e in result.events)
    assert total_swims >= 4


# ---------------------------------------------------------------------------
# 6. Year-of-birth must never leak into the club field (British "Name (YoB)
#    Club" format read by AI into a single club-mapped column).
# ---------------------------------------------------------------------------


def test_year_of_birth_does_not_become_the_club():
    """A YoB that slips into the club cell must not surface as a club — the
    club picker was filling with '(04)', '(05)', … instead of club names."""
    # Bare (YoB) in the only club-mapped column → no fake club.
    csv_bare = b"placing,competitor,team,mark\n1,Tom DAVIES,(04),50.12\n2,Sam JONES,(05),50.98\n"
    res = interpret_document(csv_bare, hint="csv")
    clubs = {s.club for e in res.events for s in e.swims}
    assert clubs == {None}, f"YoB leaked into club: {clubs}"

    # (YoB) prefixed onto the real club → the real club is recovered.
    csv_merged = (
        b"placing,competitor,affiliation,mark\n"
        b"1,Tom DAVIES,(04) City of Sheffield,50.12\n"
        b"2,Sam JONES,(05) Loughborough,50.98\n"
    )
    res2 = interpret_document(csv_merged, hint="csv")
    clubs2 = {s.club for e in res2.events for s in e.swims}
    assert clubs2 == {"City of Sheffield", "Loughborough"}, clubs2


def test_split_rows_do_not_become_phantom_results():
    """On a distance event the page lists cumulative splits under each swimmer.
    Those split rows (a time but no competitor name) must not become nameless
    'results' — only the overall time per swimmer is kept."""
    csv = (
        b"placing,competitor,affiliation,mark\n"
        b"1,Tom DAVIES,City of Sheffield,15:23.45\n"
        b",,1350m,13:53.80\n"  # a split/continuation row — no name
        b"2,Sam JONES,Loughborough,15:40.10\n"
        b",,1350m,14:08.03\n"
    )
    res = interpret_document(csv, hint="csv")
    swims = [s for e in res.events for s in e.swims]
    assert all(s.swimmer_name for s in swims), "a nameless split row leaked in as a result"
    assert {s.swimmer_name for s in swims} == {"Tom DAVIES", "Sam JONES"}
    assert {s.time for s in swims} == {"15:23.45", "15:40.10"}  # overall times only


def test_british_paren_yob_format_parses_with_correct_event_pairing():
    """British results print "Place Name (YoB) Club Time" with the year of birth
    parenthesised between the name and the club. Previously no row pattern matched
    it, so these lines were dropped and the run fell back to unreliable AI reads
    (wrong events/times). The deterministic parser must now read them and pair
    each swimmer with the right event and overall time."""
    txt = (
        "Aquatics GB Championships 2026\n\n"
        "Event 12 Mens 100m Breaststroke\n"
        "Place Name              YoB Club              Time\n"
        "1     Maxwell Anderson  (04) City of Sheffield 1:03.34\n"
        "2     Mari Gibson       (05) Loughborough      1:04.10\n\n"
        "Event 18 Mens 1500m Freestyle\n"
        "Place Name              YoB Club              Time\n"
        "1     Vinnie Owen       (06) Bath             15:10.79\n"
        "2     Max Geysen-Holley (06) Stockport        15:13.55\n"
    )
    res = interpret_document(txt.encode(), hint="txt")
    by_event = {(e.distance_m, e.stroke): e for e in res.events}
    assert (100, "Breaststroke") in by_event, [(e.distance_m, e.stroke) for e in res.events]
    assert (1500, "Freestyle") in by_event

    breast = by_event[(100, "Breaststroke")]
    names_times = {(s.swimmer_name, s.time, s.yob, s.club) for s in breast.swims}
    # Maxwell Anderson is on 100m Breaststroke (not Backstroke), with his real time.
    assert ("Maxwell Anderson", "1:03.34", 2004, "City of Sheffield") in names_times

    free = by_event[(1500, "Freestyle")]
    free_times = {s.time for s in free.swims}
    assert free_times == {"15:10.79", "15:13.55"}  # 1500m times, not 400m splits


def test_hytek_license_banner_is_not_the_meet_name():
    """HY-TEK MEET MANAGER stamps a licensee/software/timestamp/page banner on
    the first line of every results page. That banner must NOT become the meet
    title (it was leaking "… HY-TEK's MEET MANAGER 8.0 … Page 1" into the
    headline) — the real meet name on the next line is used instead, with its
    trailing date range stripped."""
    txt = (
        "Sussex County ASA- LC Champ - Organization License HY-TEK's MEET MANAGER 8.0 - 6:29 PM 15/02/2026 Page 1\n"
        "Sussex County Long Course Championships 26 - 14/02/2026 to 01/03/2026\n"
        "\n"
        "Event 202 Female 13 Year Olds 200 LC Meter Freestyle\n"
        "1 Raleigh, Birdy 13 City of Brighton & Hove 2:24.51 2:19.80\n"
    )
    res = interpret_document(txt.encode(), hint="txt")
    assert res.meet_name == "Sussex County Long Course Championships 26"
    # None of the software/license/page boilerplate survives in the title.
    for boilerplate in ("HY-TEK", "MEET MANAGER", "Organization License", "Page 1", "6:29 PM"):
        assert boilerplate not in (res.meet_name or "")


def test_hytek_banner_only_header_strips_boilerplate_to_recover_name():
    """If the licensee banner is the only title-bearing line, the boilerplate is
    stripped to recover the licensee/meet prefix rather than surfacing the raw
    "… HY-TEK's MEET MANAGER … Page 1" string as the title."""
    txt = (
        "City of Cardiff Open Meet - Organization License HY-TEK's MEET MANAGER 8.0 - 9:01 AM 03/05/2026 Page 1\n"
        "\n"
        "Event 1 Female 50 LC Meter Freestyle\n"
        "1 Jones, Amy 14 Cardiff 28.40\n"
    )
    res = interpret_document(txt.encode(), hint="txt")
    assert res.meet_name == "City of Cardiff Open Meet"
    assert "HY-TEK" not in (res.meet_name or "")
    assert "Page" not in (res.meet_name or "")


def test_dotted_date_title_line_is_still_the_meet_name():
    """A title line carrying a dotted date tail ("… - 14.02.2026") must not be
    rejected as a result row: the dd.mm token is race-time-shaped, but the date
    tail is stripped before the race-time check, so the real title wins instead
    of the venue line below it."""
    txt = (
        "Winter Open Meet - 14.02.2026\n"
        "Ponds Forge, Sheffield\n"
        "\n"
        "Event 1 Female 50 LC Meter Freestyle\n"
        "1 Jones, Amy 14 Cardiff 28.40\n"
    )
    res = interpret_document(txt.encode(), hint="txt")
    assert res.meet_name == "Winter Open Meet"
    assert res.venue == "Ponds Forge, Sheffield"


def test_no_time_seed_does_not_create_phantom_clubs():
    """"NT" is the No-Time SEED value, not club text. The team-name parser must
    not absorb it into the club, or the picker fills with phantom "<Club> NT"
    clubs (City of Brighton & Hove NT, Beacon SC NT, …)."""
    txt = (
        "Event 202 Female 13 Year Olds 200 LC Meter Freestyle\n"
        "1 Raleigh, Birdy 13 City of Brighton & Hove NT 2:24.51\n"
        "2 Carden, Izzy 13 Beacon SC NT 2:28.90\n"
        "3 Patel, Mia 13 Atlantis SC NT 2:31.10\n"
    )
    res = interpret_document(txt.encode(), hint="txt")
    clubs = {s.club for e in res.events for s in e.swims if s.club}
    assert clubs == {"City of Brighton & Hove", "Beacon SC", "Atlantis SC"}, clubs
    # No phantom "<Club> NT" club anywhere.
    assert not any(c.upper().endswith(" NT") for c in clubs), clubs


def test_implausible_time_for_event_is_flagged_not_trusted():
    """A time physically impossible for the event's distance (a wrong event/time
    pairing) is flagged for review and de-confidenced — never shown as fact —
    while realistic times in the same event stay trusted."""
    txt = (
        "Event 1 Womens 100m Breaststroke\n"
        "1 Mari Gibson (05) Loughborough 33.64\n"  # 33.64 = a 50m time, impossible for 100m
        "2 Real Swimmer (06) Bath 1:08.20\n"  # realistic 100m breaststroke
        "\n"
        "Event 2 Mens 1500m Freestyle\n"
        "1 Vinnie Owen (06) Bath 4:10.79\n"  # 4:10 = a 400m time, impossible for 1500m
        "2 Proper Distance (05) Leeds 15:30.10\n"  # realistic 1500m
    )
    res = interpret_document(txt.encode(), hint="txt")
    flagged = [n for n in res.needs_review if n.get("reason") == "implausible-time-for-event"]
    flagged_detail = " ".join(n["detail"] for n in flagged)
    assert "Mari Gibson" in flagged_detail
    assert "Vinnie Owen" in flagged_detail
    by_name = {s.swimmer_name: s for e in res.events for s in e.swims}
    assert by_name["Mari Gibson"].confidence <= 0.2
    assert by_name["Vinnie Owen"].confidence <= 0.2
    # Realistic times are NOT flagged and keep normal confidence.
    assert "Real Swimmer" not in flagged_detail
    assert by_name["Real Swimmer"].confidence > 0.5
    assert by_name["Proper Distance"].confidence > 0.5


def _build_wide_column_pdf_bytes() -> bytes:
    """A multi-event results PDF whose columns are spaced far apart (the
    SportSystems 'Place Name (YoB) Club Time WA Pts' layout). The wide gap
    between the name and the (YoB) creates a vertical whitespace corridor that
    the column-band detector used to mistake for a real column boundary —
    splitting every row so the place/name was dropped and the row never parsed."""
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
    except ImportError:
        pytest.skip("reportlab not installed")

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setFont("Courier", 10)
    cx = [55, 120, 330, 390, 540]  # place | name | (yob) | club | time — wide gaps

    def row(y, place, name, yob, club, t):
        c.drawString(cx[0], y, place)
        c.drawString(cx[1], y, name)
        c.drawString(cx[2], y, yob)
        c.drawString(cx[3], y, club)
        c.drawString(cx[4], y, t)

    y = 740
    c.drawString(55, y, "EVENT 101 Women's 50m Breaststroke")
    y -= 16
    c.drawString(55, y, "Place Name YoB Club Time")
    y -= 16
    for p, n, yo, cl, t in [
        ("1.", "Alpha Beta", "(08)", "Mt Kelly", "30.82"),
        ("2.", "Gamma Delta", "(03)", "Edinburgh Un", "30.90"),
        ("3.", "Delta Echo", "(05)", "Repton", "31.20"),
    ]:
        row(y, p, n, yo, cl, t)
        y -= 16
    y -= 18
    c.drawString(55, y, "EVENT 104 Men's 100m Backstroke")
    y -= 16
    c.drawString(55, y, "Place Name YoB Club Time")
    y -= 16
    for p, n, yo, cl, t in [
        ("1.", "Foxtrot Golf", "(04)", "Millfield", "55.10"),
        ("2.", "Hotel India", "(06)", "Mt Kelly", "55.80"),
    ]:
        row(y, p, n, yo, cl, t)
        y -= 16
    c.showPage()
    c.save()
    return buf.getvalue()


def test_wide_column_pdf_keeps_rows_whole_and_events_separate():
    """Regression for the SportSystems multi-column PDF: every swimmer must be
    extracted (place+name not dropped) and paired with the correct event, not
    collapsed onto the first event or lost to a false column split."""
    res = interpret_document(_build_wide_column_pdf_bytes(), hint="pdf")
    by_event = {(e.distance_m, e.stroke): e for e in res.events}
    assert (50, "Breaststroke") in by_event, [(e.distance_m, e.stroke) for e in res.events]
    assert (100, "Backstroke") in by_event

    breast_names = {s.swimmer_name for s in by_event[(50, "Breaststroke")].swims}
    back_names = {s.swimmer_name for s in by_event[(100, "Backstroke")].swims}
    assert {"Alpha Beta", "Gamma Delta", "Delta Echo"} <= breast_names
    # The 100m Backstroke swimmers land under THEIR event, not the first one.
    assert {"Foxtrot Golf", "Hotel India"} <= back_names
    assert "Foxtrot Golf" not in breast_names
    # Names survived the wide-gap layout (the bug dropped them entirely).
    a = next(s for s in by_event[(50, "Breaststroke")].swims if s.swimmer_name == "Alpha Beta")
    assert a.time == "30.82" and a.yob == 2008 and a.club == "Mt Kelly"
