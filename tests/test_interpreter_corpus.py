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

    result = interpret_document(
        shell.read_bytes(), hint="html", source_path=shell
    )
    total_swims = sum(len(e.swims) for e in result.events)
    assert total_swims >= 9, (
        f"frameset+sibling aggregation produced only {total_swims} swims"
    )
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
    assert total_swims >= 5, (
        f"header-less PDF extraction yielded {total_swims}; expected \u22655"
    )
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
    shell.write_text(
        "<html><body><h1>See PDF below</h1></body></html>"
    )
    result = interpret_document(
        shell.read_bytes(), hint="html", source_path=shell
    )
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
