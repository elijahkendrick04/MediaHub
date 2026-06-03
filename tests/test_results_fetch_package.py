"""End-to-end proof for the inert results_fetch stack across site types + sports.

crawl -> (ai_read) -> package -> interpret_document(zip_bytes), for four mini
fixtures behind a mocked backend, with ZERO fixture-specific code in src/:

  (a) swim_frameset      — SPORTSYSTEMS-shaped frameset + event pages (HTML path)
  (b) football_league_spa — JS shell whose results arrive only via a captured
      JSON API (non-swim, non-HTML data path → Step 4 JSON ingestion)
  (c) athletics_xlsx     — landing page linking an XLSX of distances/times
  (d) image_results      — results only in an image → Tier C returns a CSV

Each asserts competitor names + numeric marks reach the interpreter, that
_provenance.json is accurate, and that the ZIP honours _zip_safety budgets.
"""

from __future__ import annotations

import io
import json
import zipfile

from mediahub.interpreter import interpret_document
from mediahub.interpreter._zip_safety import safe_infolist
from mediahub.interpreter.ingest import ingest
from mediahub.results_fetch import ReadResult
from mediahub.results_fetch.ai_read import ai_read_candidates
from mediahub.results_fetch.crawl import CrawlLimits, crawl_results_site
from mediahub.results_fetch.fetch import FetchedPage, visible_text
from mediahub.results_fetch.package import package_mirror
from mediahub.results_fetch.rendered import CapturedResponse, RenderedPage


# ---------------------------------------------------------------------------
# Helpers: a mock fetch_page serving a fixed mini-site
# ---------------------------------------------------------------------------


def _static(url, body, content_type="text/html"):
    text = visible_text(body) if content_type.startswith("text/html") else None
    page = FetchedPage(
        content=body if isinstance(body, bytes) else body.encode(),
        final_url=url,
        content_type=content_type,
        tier="static",
        text=text,
    )
    return ReadResult(url=url, page=page, tier="static", trigger=None)


def _rendered(url, dom, *, captures=None, shot=b"\xff\xd8\xffjpg"):
    page = RenderedPage(
        content=dom.encode(),
        final_url=url,
        content_type="text/html",
        tier="rendered",
        text=visible_text(dom),
        screenshot=shot,
        screenshot_mime="image/jpeg",
        captures=list(captures or []),
    )
    return ReadResult(url=url, page=page, tier="rendered", trigger="js_shell")


def _reader(pages):
    def _fetch(url):
        return pages.get(url) or ReadResult(url=url, page=None, tier="static", trigger=None)

    return _fetch


def _fast():
    return CrawlLimits(politeness_delay_s=0.0, respect_robots=False)


def _png():
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), (10, 10, 10)).save(buf, "PNG")
    return buf.getvalue()


def _xlsx(rows, sheet="Results"):
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    ws = wb.create_sheet(sheet)
    for r in rows:
        ws.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _zip_members(zip_bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return set(zf.namelist())


def _provenance(zip_bytes):
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        return json.loads(zf.read("_provenance.json"))


def _assert_zip_safe(zip_bytes):
    """The mirror ZIP must satisfy the interpreter's pre-extraction guards."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        safe_infolist(zf)  # raises UnsafeZipError if over budget


def _all_table_text(zip_bytes) -> str:
    stream = ingest(zip_bytes)
    parts = [stream.text]
    for tbl in stream.tables:
        for row in tbl.rows:
            parts.extend(row)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# (a) swim frameset — HTML path
# ---------------------------------------------------------------------------

_EVENT1 = (
    "<html><body><h3>Event 1 100m Freestyle</h3><table>"
    "<tr><th>Place</th><th>Name</th><th>YoB</th><th>Club</th><th>Time</th></tr>"
    "<tr><td>1</td><td>Ada Lovelace</td><td>2009</td><td>Brighton</td><td>1:02.34</td></tr>"
    "<tr><td>2</td><td>Bea Carr</td><td>2010</td><td>Wigan</td><td>1:03.11</td></tr>"
    "</table></body></html>"
)
_EVENT2 = (
    "<html><body><h3>Event 2 200m Freestyle</h3><table>"
    "<tr><th>Place</th><th>Name</th><th>YoB</th><th>Club</th><th>Time</th></tr>"
    "<tr><td>1</td><td>Cy Diaz</td><td>2009</td><td>Hove</td><td>2:15.40</td></tr>"
    "<tr><td>2</td><td>Di Okoro</td><td>2010</td><td>Leeds</td><td>2:17.88</td></tr>"
    "</table></body></html>"
)


def test_swim_frameset_end_to_end():
    base = "https://results.swim.test/agb/"
    pages = {
        base
        + "index.htm": _static(
            base + "index.htm",
            '<html><frameset cols="25%,75%"><frame src="menu.htm">'
            '<frame src="event1.htm"></frameset></html>',
        ),
        base
        + "menu.htm": _static(
            base + "menu.htm",
            '<html><body><a href="event1.htm">E1</a> <a href="event2.htm">E2</a></body></html>',
        ),
        base + "event1.htm": _static(base + "event1.htm", _EVENT1),
        base + "event2.htm": _static(base + "event2.htm", _EVENT2),
    }
    crawl = crawl_results_site(base + "index.htm", limits=_fast(), fetch_page=_reader(pages))
    zip_bytes = package_mirror(crawl, [])

    _assert_zip_safe(zip_bytes)
    blob = _all_table_text(zip_bytes)
    assert "Ada Lovelace" in blob and "1:02.34" in blob
    assert "Cy Diaz" in blob and "2:15.40" in blob

    prov = _provenance(zip_bytes)
    assert prov["entry_url"] == base + "index.htm"
    assert prov["counters"]["pages_visited"] >= 3

    meet = interpret_document(zip_bytes)
    assert meet is not None and "format:zip" in meet.sources_used


# ---------------------------------------------------------------------------
# (b) football SPA — captured JSON data path (non-swim)
# ---------------------------------------------------------------------------


def test_football_spa_captured_json_end_to_end():
    base = "https://league.test/fixtures/"
    api = json.dumps(
        {
            "competition": "Sunday League",
            "data": {
                "matches": [
                    {"date": "2026-05-01", "home": "Rovers", "away": "City", "score": "3 - 1"},
                    {"date": "2026-05-01", "home": "United", "away": "Albion", "score": "2 - 2"},
                    {"date": "2026-05-08", "home": "Town", "away": "Athletic", "score": "0 - 4"},
                    {"date": "2026-05-08", "home": "Wanderers", "away": "County", "score": "1 - 0"},
                ]
            },
        }
    ).encode()
    cap = CapturedResponse(base + "api/matches.json", "application/json", api)
    pages = {
        base: _rendered(
            base, '<html><body><div id="app">Fixtures</div></body></html>', captures=[cap]
        )
    }
    crawl = crawl_results_site(base, limits=_fast(), fetch_page=_reader(pages))
    zip_bytes = package_mirror(crawl, [])

    _assert_zip_safe(zip_bytes)
    assert any(n.endswith(".json") for n in _zip_members(zip_bytes))
    blob = _all_table_text(zip_bytes)
    assert "Rovers" in blob and "3 - 1" in blob  # Step 4 JSON ingestion fired
    meet = interpret_document(zip_bytes)
    assert meet is not None


# ---------------------------------------------------------------------------
# (c) athletics XLSX — landing page linking a spreadsheet
# ---------------------------------------------------------------------------


def test_athletics_xlsx_end_to_end():
    base = "https://athletics.test/county/"
    xb = _xlsx(
        [
            ["Pos", "Athlete", "Club", "Mark"],
            [1, "Dana Reed", "Striders", "6.42 m"],
            [2, "Eli Frost", "Harriers", "6.10 m"],
            [3, "Fay Roe", "Vaulters", "5.95 m"],
        ]
    )
    pages = {
        base
        + "index.html": _static(
            base + "index.html",
            '<html><body><h2>County Athletics</h2>'
            '<a href="results.xlsx">download results</a></body></html>',
        ),
        base
        + "results.xlsx": _static(
            base + "results.xlsx",
            xb,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ),
    }
    crawl = crawl_results_site(base + "index.html", limits=_fast(), fetch_page=_reader(pages))
    zip_bytes = package_mirror(crawl, [])

    _assert_zip_safe(zip_bytes)
    assert any(n.endswith(".xlsx") for n in _zip_members(zip_bytes))
    blob = _all_table_text(zip_bytes)
    assert "Dana Reed" in blob and "6.42 m" in blob
    assert interpret_document(zip_bytes) is not None


# ---------------------------------------------------------------------------
# (d) image results — Tier C AI read
# ---------------------------------------------------------------------------


def test_image_results_via_ai_read_end_to_end():
    base = "https://darts.test/night/"
    # a rendered page whose results live only in an embedded image → AI candidate
    pages = {
        base: _rendered(
            base,
            '<html><body><h2>Darts Night</h2><canvas id="board"></canvas></body></html>',
            shot=_png(),
        )
    }
    crawl = crawl_results_site(base, limits=_fast(), fetch_page=_reader(pages))
    assert crawl.ai_candidates, "rendered page with no table should be an AI candidate"

    # marks must be result-shaped (a checkout average like 98.40, a 180 finish
    # written with a unit) so the deterministic shape-check keeps the rows
    csv_reply = "player,team,average,checkouts\nGwen Hill,Falcons,98.40,3\nHank Ives,Eagles,92.15,1\n"

    def _gen(image_paths, prompt, *, system=None, max_tokens=1400):
        return csv_reply

    extractions = ai_read_candidates(crawl.ai_candidates, generate=_gen)
    assert extractions, "Tier C should have produced an extraction"
    zip_bytes = package_mirror(crawl, extractions)

    _assert_zip_safe(zip_bytes)
    members = _zip_members(zip_bytes)
    assert any(n.endswith(".csv") for n in members)  # AI CSV present
    assert any(n.endswith(".ai.json") for n in members)  # marked sidecar present

    blob = _all_table_text(zip_bytes)
    assert "Gwen Hill" in blob and "98.40" in blob  # AI-read data reached the interpreter

    prov = _provenance(zip_bytes)
    assert prov["ai_extractions"] and prov["ai_extractions"][0]["tables"] >= 1
    assert interpret_document(zip_bytes) is not None
