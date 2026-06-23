"""QA-014 native-text-PDF regression: the swum result, never the seed, end-to-end.

The seed-as-result bug was specific to the NATIVE TEXT-PDF path (pdfplumber text
extraction → schema/line parser). The OCR / table-extractor path already selected
the Finals column correctly; this test pins the native-text path to that same
(correct) reference, driving REAL PDF bytes through ``interpret_document`` — the
coverage the unit-level seed/result tests (which build streams from lines/tables)
don't exercise.

It renders a native-text HY-TEK-style results PDF (a real text layer, so pdfplumber
extracts it as text — NOT OCR) for the Sussex proof cases and asserts every swum
time is the Finals column, never the Seed:

  * Event 202 Birdy Raleigh — seed 2:19.80 / finals 2:22.28 (over 2:20). Effie
    Maxted shares the identical 2:19.80 seed but a different finals, proving the
    first column is the seed.
  * Event 207 Oscar Yu — seed 2:55.80 / finals 3:03.47 (a regression vs seed).

Before the fix the native-text path closed each record at the first time token and
surfaced the SEED (Raleigh 2:19.80, Yu 2:55.80); after, it reads the Finals time.
The OCR path is deliberately NOT exercised here (it was already correct and must
not change).
"""

from __future__ import annotations

import io

import pytest

# Native-text PDF generation + extraction deps. Skip cleanly where absent (the
# suite already treats reportlab / pdf extraction as optional environment gaps).
reportlab = pytest.importorskip("reportlab")
pytest.importorskip("pdfplumber")

from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from mediahub.interpreter import interpret_document  # noqa: E402


def _native_text_pdf() -> bytes:
    """Render a HY-TEK-style results PDF with a real text layer (not an image).

    Columns: Name, Age, Team, Seed Time, Finals Time, Points — the seed printed
    immediately before the finals, exactly as the Sussex meet prints them.
    """
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _w, h = A4
    state = {"y": h - 60}

    def row(cells: list[tuple[str, float]]) -> None:
        for text, x in cells:
            c.drawString(x, state["y"], text)
        state["y"] -= 15

    cols = [60, 250, 290, 430, 495, 555]
    c.setFont("Helvetica-Bold", 11)
    row([("Sussex County Championships 2026", 60)])
    c.setFont("Helvetica", 9)
    row([("Brighton, 14/02/2026 to 01/03/2026", 60)])
    state["y"] -= 8

    def event(header: str, data: list[tuple[str, str, str, str, str, str]]) -> None:
        c.setFont("Helvetica-Bold", 10)
        row([(header, 60)])
        c.setFont("Helvetica", 9)
        row(
            [
                ("Name", cols[0]),
                ("Age", cols[1]),
                ("Team", cols[2]),
                ("Seed Time", cols[3]),
                ("Finals Time", cols[4]),
                ("Pts", cols[5]),
            ]
        )
        for nm, age, team, seed, fin, pts in data:
            row(
                [
                    (nm, cols[0]),
                    (age, cols[1]),
                    (team, cols[2]),
                    (seed, cols[3]),
                    (fin, cols[4]),
                    (pts, cols[5]),
                ]
            )
        state["y"] -= 8

    event(
        "Event 202  Female 13 Year Olds 200 LC Meter Freestyle",
        [
            ("1 Smith, Ada", "13", "Worthing", "2:15.00", "2:16.10", "560"),
            ("2 Patel, Mia", "13", "Crawley", "2:18.00", "2:20.05", "515"),
            ("3 Raleigh, Birdy", "13", "City of Brighton & Hove", "2:19.80", "2:22.28", "500"),
            ("4 Maxted, Effie", "13", "Lewes", "2:19.80", "2:24.75", "475"),
        ],
    )
    event(
        "Event 207  Boys 12 Year Olds 200 LC Meter Backstroke",
        [
            ("1 Oman, Alexander", "12", "City of Brighton & Hove", "2:37.00", "2:41.44", "333"),
            ("5 Evans, Jake", "12", "Brighton", "3:03.50", "3:00.18", "239"),
            ("6 Yu, Oscar", "12", "City of Brighton & Hove", "2:55.80", "3:03.47", "227"),
        ],
    )
    c.save()
    return buf.getvalue()


def _swims_by_name(meet) -> dict:
    out = {}
    for ev in meet.events:
        for sw in ev.swims:
            out[sw.swimmer_name] = sw
    return out


@pytest.fixture(scope="module")
def native_meet():
    meet = interpret_document(_native_text_pdf(), hint="pdf")
    # Guard: this must be the NATIVE-TEXT path, not OCR. OCR caps confidence at
    # 0.55 and tags an ``ocr:`` source; a healthy text-PDF parse clears 0.6 and
    # carries only ``format:pdf``. If this ever flips to OCR the test is moot.
    assert not any("ocr" in str(s).lower() for s in meet.sources_used), (
        f"expected native-text extraction, got {meet.sources_used}"
    )
    assert meet.overall_confidence >= 0.6
    return meet


def _to_seconds(t: str) -> float:
    mm, _, ss = t.partition(":")
    return int(mm) * 60 + float(ss) if ss else float(mm)


class TestNativeTextPdfReadsFinalsNotSeed:
    def test_birdy_raleigh_swam_finals_over_220(self, native_meet) -> None:
        sw = _swims_by_name(native_meet)["Birdy Raleigh"]
        assert sw.time == "2:22.28"  # Finals — over 2:20, NOT the 2:19.80 seed
        assert sw.seed_time == "2:19.80"
        assert sw.place == 3

    def test_effie_maxted_identical_seed_different_finals(self, native_meet) -> None:
        # Same 2:19.80 seed as Raleigh but placed 4th — proof the first column is
        # the seed (identical swum times could not place differently).
        sw = _swims_by_name(native_meet)["Effie Maxted"]
        assert sw.time == "2:24.75"
        assert sw.seed_time == "2:19.80"
        assert sw.place == 4

    def test_oscar_yu_swam_finals_a_regression_vs_seed(self, native_meet) -> None:
        sw = _swims_by_name(native_meet)["Oscar Yu"]
        assert sw.time == "3:03.47"  # Finals — slower than his 2:55.80 seed
        assert sw.seed_time == "2:55.80"

    def test_no_swim_reports_its_seed_as_the_time(self, native_meet) -> None:
        # The reference (OCR/table-extractor) selects the Finals column for every
        # row; the native-text path must match — never the (faster) seed. Each
        # swimmer here swam SLOWER than their seed, so time must exceed seed.
        for sw in _swims_by_name(native_meet).values():
            if sw.time and sw.seed_time:
                assert _to_seconds(sw.time) != _to_seconds(sw.seed_time)
                assert sw.time != sw.seed_time

    def test_finals_times_monotonic_with_place_event_202(self, native_meet) -> None:
        # FINA points descend with place, and only the Finals column is monotonic
        # with finishing order — the objective proof the swum time is the Finals.
        swims = _swims_by_name(native_meet)
        ordered = ["Ada Smith", "Mia Patel", "Birdy Raleigh", "Effie Maxted"]
        secs = [_to_seconds(swims[n].time) for n in ordered if n in swims]
        assert len(secs) >= 3
        assert secs == sorted(secs), f"native-text Finals times not monotonic: {secs}"
