"""Tests for the deterministic walker (results_fetch.crawl).

Each test drives a tiny fixture mini-site through a mocked ``fetch_page`` — no
network, no browser. The assertions prove the walker is structural and
sport-agnostic (no site-specific code):

  (a) a SPORTSYSTEMS-shaped frameset → event pages harvested via frame/link
      discovery;
  (b) an SPA whose static HTML is a JS shell and whose results arrive only via
      the rendered DOM's captured JSON API → Tier B harvest reaches the mirror
      (non-HTML data path, non-swim sport);
  (c) scope, robots.txt, and the page cap are honoured honestly.
"""

from __future__ import annotations

from mediahub.results_fetch import ReadResult
from mediahub.results_fetch.crawl import CrawlLimits, crawl_results_site, shape_gate
from mediahub.results_fetch.fetch import FetchedPage, visible_text
from mediahub.results_fetch.rendered import CapturedResponse, RenderedPage


def _static(url: str, html: str) -> ReadResult:
    page = FetchedPage(
        content=html.encode(),
        final_url=url,
        content_type="text/html",
        tier="static",
        text=visible_text(html),
    )
    return ReadResult(url=url, page=page, tier="static", trigger=None)


def _rendered(url: str, dom: str, *, captures=None, shot=b"\xff\xd8\xffjpg") -> ReadResult:
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


def _site_reader(pages: dict[str, ReadResult]):
    """A fetch_page that serves a fixed mini-site; missing URLs → empty result."""

    def _fetch(url: str) -> ReadResult:
        if url in pages:
            return pages[url]
        return ReadResult(url=url, page=None, tier="static", trigger=None)

    return _fetch


def _fast_limits(**kw) -> CrawlLimits:
    limits = CrawlLimits(politeness_delay_s=0.0, respect_robots=False, **kw)
    return limits


# ---------------------------------------------------------------------------
# (a) Frameset — structural frame/link discovery
# ---------------------------------------------------------------------------

_EVENT_HTML = (
    "<html><body><h1>Event {n} 100m</h1><table>"
    "<tr><th>Place</th><th>Name</th><th>YoB</th><th>Club</th><th>Time</th></tr>"
    "<tr><td>1</td><td>Ada Lovelace</td><td>2009</td><td>Bton</td><td>1:02.34</td></tr>"
    "<tr><td>2</td><td>Bea Carr</td><td>2010</td><td>Wgan</td><td>1:03.11</td></tr>"
    "<tr><td>3</td><td>Cy Diaz</td><td>2009</td><td>Hova</td><td>1:04.50</td></tr>"
    "</table></body></html>"
)


def test_frameset_harvests_event_pages():
    base = "https://swim.test/meet/"
    pages = {
        base + "index.htm": _static(
            base + "index.htm",
            '<html><frameset cols="20%,80%">'
            '<frame src="menu.htm"><frame src="event1.htm"></frameset></html>',
        ),
        base + "menu.htm": _static(
            base + "menu.htm",
            '<html><body><a href="event1.htm">E1</a> '
            '<a href="event2.htm">E2</a></body></html>',
        ),
        base + "event1.htm": _static(base + "event1.htm", _EVENT_HTML.format(n=1)),
        base + "event2.htm": _static(base + "event2.htm", _EVENT_HTML.format(n=2)),
    }
    result = crawl_results_site(
        base + "index.htm", limits=_fast_limits(), fetch_page=_site_reader(pages)
    )

    assert result.entry_file == "meet/index.htm"
    kept_names = set(result.files)
    assert "meet/event1.htm" in kept_names
    assert "meet/event2.htm" in kept_names
    # names + marks survive into the kept bytes
    blob = b"\n".join(result.files[k] for k in ("meet/event1.htm", "meet/event2.htm"))
    assert b"Ada Lovelace" in blob and b"1:02.34" in blob
    assert result.kept >= 2
    # provenance is honest about tier
    assert result.provenance["meet/event1.htm"].tier == "static"


# ---------------------------------------------------------------------------
# (b) SPA — Tier B harvest via captured JSON (non-HTML data path, non-swim)
# ---------------------------------------------------------------------------


def test_spa_harvests_captured_json_api():
    base = "https://league.test/fixtures/"
    api_json = (
        b'{"data":{"matches":['
        b'{"home":"Rovers","away":"City","score":"3 - 1"},'
        b'{"home":"United","away":"Albion","score":"2 - 2"},'
        b'{"home":"Town","away":"Athletic","score":"0 - 4"},'
        b'{"home":"Wanderers","away":"County","score":"1 - 0"}]}}'
    )
    cap = CapturedResponse(
        url=base + "api/matches.json", content_type="application/json", body=api_json
    )
    pages = {
        # static shell would be a JS shell; the reader returns the rendered page
        base: _rendered(
            base,
            '<html><body><div id="app">Fixtures</div></body></html>',
            captures=[cap],
        ),
    }
    result = crawl_results_site(base, limits=_fast_limits(), fetch_page=_site_reader(pages))

    # the captured JSON API reached the mirror as a .json file
    json_files = {k: v for k, v in result.files.items() if k.endswith(".json")}
    assert json_files, "captured JSON API did not reach the mirror"
    body = next(iter(json_files.values()))
    assert b"Rovers" in body and b"3 - 1" in body
    # provenance marks it as a capture
    cap_path = next(iter(json_files))
    assert result.provenance[cap_path].tier == "capture"
    # a screenshot rode along for the rendered page
    assert result.screenshots


def test_spa_rendered_shell_becomes_ai_candidate():
    base = "https://canvas.test/scoreboard/"
    pages = {
        base: _rendered(
            base, '<html><body><canvas id="board"></canvas></body></html>', captures=[]
        ),
    }
    result = crawl_results_site(base, limits=_fast_limits(), fetch_page=_site_reader(pages))
    # rendered HTML with no machine-readable table → handed to the Tier-C reader
    assert len(result.ai_candidates) == 1
    assert result.ai_candidates[0].page.tier == "rendered"


# ---------------------------------------------------------------------------
# (c) scope / robots / caps
# ---------------------------------------------------------------------------


def test_offscope_and_offhost_links_are_not_followed():
    base = "https://site.test/results/"
    pages = {
        base + "index.htm": _static(
            base + "index.htm",
            '<html><body>'
            '<a href="heat1.htm">in scope</a>'
            '<a href="/admin/secret.htm">off prefix</a>'
            '<a href="https://evil.test/x.htm">off host</a>'
            "</body></html>",
        ),
        base + "heat1.htm": _static(base + "heat1.htm", _EVENT_HTML.format(n=1)),
        "https://site.test/admin/secret.htm": _static(
            "https://site.test/admin/secret.htm", _EVENT_HTML.format(n=9)
        ),
        "https://evil.test/x.htm": _static("https://evil.test/x.htm", _EVENT_HTML.format(n=8)),
    }
    result = crawl_results_site(
        base + "index.htm", limits=_fast_limits(), fetch_page=_site_reader(pages)
    )
    fetched = {p.source_url for p in result.provenance.values()}
    assert base + "heat1.htm" in fetched
    assert "https://site.test/admin/secret.htm" not in fetched  # off path-prefix
    assert "https://evil.test/x.htm" not in fetched  # off host


def test_robots_disallow_blocks_pages():
    base = "https://site.test/results/"
    pages = {
        base + "index.htm": _static(
            base + "index.htm",
            '<html><body><a href="private/secret.htm">x</a>'
            '<a href="heat1.htm">y</a></body></html>',
        ),
        base + "private/secret.htm": _static(base + "private/secret.htm", _EVENT_HTML.format(n=5)),
        base + "heat1.htm": _static(base + "heat1.htm", _EVENT_HTML.format(n=1)),
    }
    limits = CrawlLimits(politeness_delay_s=0.0, respect_robots=True)
    result = crawl_results_site(
        base + "index.htm",
        limits=limits,
        fetch_page=_site_reader(pages),
        robots_txt="User-agent: *\nDisallow: /results/private/",
    )
    fetched = {p.source_url for p in result.provenance.values()}
    assert base + "heat1.htm" in fetched
    assert base + "private/secret.htm" not in fetched
    assert result.blocked >= 1


def test_page_cap_is_enforced():
    base = "https://big.test/r/"
    # a hub linking to many event pages
    links = " ".join(f'<a href="e{i}.htm">e{i}</a>' for i in range(20))
    pages = {base + "index.htm": _static(base + "index.htm", f"<html><body>{links}</body></html>")}
    for i in range(20):
        pages[base + f"e{i}.htm"] = _static(base + f"e{i}.htm", _EVENT_HTML.format(n=i))

    result = crawl_results_site(
        base + "index.htm",
        limits=_fast_limits(max_pages=5),
        fetch_page=_site_reader(pages),
    )
    assert result.pages_visited <= 5


# ---------------------------------------------------------------------------
# (d) Trailing-slash discovery base — rendered final_url drops the slash
# ---------------------------------------------------------------------------


# A minimal but valid PDF the keep-on-sight path accepts as results.
_TINY_PDF = (
    b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[]/Count 0>>endobj\n"
    b"trailer<</Root 1 0 R>>\n%%EOF\n"
)


def _pdf(url: str) -> ReadResult:
    page = FetchedPage(
        content=_TINY_PDF,
        final_url=url,
        content_type="application/pdf",
        tier="static",
        text=None,
    )
    return ReadResult(url=url, page=page, tier="static", trigger=None)


def test_rendered_entry_drops_trailing_slash_keeps_relative_links_in_scope():
    """A meet hub whose rendered final_url loses the requested directory's
    trailing slash must still resolve RELATIVE child links against the slashed
    directory — otherwise urljoin drops the directory segment and every child
    escapes scope. Mirrors results.rar-timing.co.uk/2025/sw-masters-lc/."""
    entry = "https://meet.test/2025/champs/"
    child = "https://meet.test/2025/champs/results/e1.pdf"
    pages = {
        # Rendered escalation reports final_url WITHOUT the trailing slash.
        entry: _rendered(
            entry.rstrip("/"),  # final_url == ".../champs" (no slash)
            '<html><body><a href="results/e1.pdf">Event 1</a></body></html>',
        ),
        child: _pdf(child),
    }
    result = crawl_results_site(entry, limits=_fast_limits(), fetch_page=_site_reader(pages))

    fetched = {p.source_url for p in result.provenance.values()}
    assert child in fetched, "relative child link escaped scope (trailing slash dropped)"
    kept_pdf = {k for k in result.files if k.endswith(".pdf")}
    assert kept_pdf, "the child PDF was not kept"


def test_genuine_no_slash_entry_still_resolves_links():
    """An entry URL that legitimately has no trailing slash (a page, not a
    directory) must keep resolving relative links as before — the fix only
    restores a slash the request actually carried. Mirrors
    swimresults.co.uk/results/639/events."""
    entry = "https://meet.test/results/639/events"
    child = "https://meet.test/results/639/heat1.pdf"
    pages = {
        entry: _static(
            entry,
            '<html><body><a href="heat1.pdf">Heat 1</a></body></html>',
        ),
        child: _pdf(child),
    }
    result = crawl_results_site(entry, limits=_fast_limits(), fetch_page=_site_reader(pages))
    fetched = {p.source_url for p in result.provenance.values()}
    assert child in fetched


# ---------------------------------------------------------------------------
# shape_gate unit checks (sport-agnostic, structure + tokens)
# ---------------------------------------------------------------------------


def test_shape_gate_requires_structure_and_tokens():
    html_results = _EVENT_HTML.format(n=1).encode()
    assert shape_gate(html_results, "text/html") is True
    # a prose page with a stray number → no structure / not enough tokens
    assert shape_gate(b"<html><body><p>About the club, est 1999.</p></body></html>", "text/html") is False
    # JSON array of objects with score tokens
    js = b'[{"a":"3 - 1"},{"a":"2 - 0"},{"a":"1 - 4"},{"a":"5 - 2"}]'
    assert shape_gate(js, "application/json") is True
    # JSON without an object array → not structural
    assert shape_gate(b'{"note":"3 - 1, 2 - 0, 1 - 4, 5 - 2"}', "application/json") is False
