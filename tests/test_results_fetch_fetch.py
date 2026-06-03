"""Tests for results_fetch Tier A (static) + Tier B (rendered) + escalation.

Everything here runs offline: the static backend's HTTP is mocked, the SSRF
validator is stubbed for redirect cases (real loopback refusal is exercised
without a network), and the rendered backend is driven through a fake
Playwright page so no Chromium is launched. The security-critical decisions —
SSRF refusal, content-type allowlist, byte caps, browser-level scope
interception, network-capture filtering/caps, and the hard render budget — are
each asserted directly.
"""

from __future__ import annotations

import pytest

from mediahub.results_fetch import (
    ReadResult,
    RenderedBackend,
    StaticBackend,
    count_result_shaped_tokens,
    read_page,
    render_trigger,
)
from mediahub.results_fetch import fetch as fetchmod
from mediahub.results_fetch.fetch import FetchedPage, FetchLimits
from mediahub.results_fetch.rendered import (
    CapturedResponse,
    RenderedPage,
    Scope,
    in_scope,
    same_host,
    scope_for,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeResponse:
    """Minimal stand-in for a streamed ``requests`` response."""

    def __init__(self, status_code=200, headers=None, body=b"", location=None):
        self.status_code = status_code
        self.headers = headers or {}
        if location is not None:
            self.headers["Location"] = location
        self._body = body
        self.closed = False

    def iter_content(self, chunk_size=65536):
        for i in range(0, len(self._body), chunk_size):
            yield self._body[i : i + chunk_size]

    def close(self):
        self.closed = True


def _install_requests(monkeypatch, handler):
    """Patch ``requests.get`` (imported lazily inside StaticBackend.fetch)."""
    import requests

    def fake_get(url, **kwargs):
        return handler(url, kwargs)

    monkeypatch.setattr(requests, "get", fake_get)


def _allow_all_hosts(monkeypatch):
    """Stub the SSRF validator so redirect/allowlist tests need no DNS."""
    monkeypatch.setattr(
        fetchmod, "is_url_safe", lambda url: "internal" not in url and "127.0.0.1" not in url
    )


class FakeRequest:
    def __init__(self, url, resource_type):
        self.url = url
        self.resource_type = resource_type


class FakeNetworkResponse:
    def __init__(self, url, resource_type, content_type, body):
        self.url = url
        self.request = FakeRequest(url, resource_type)
        self.headers = {"content-type": content_type}
        self._body = body

    def body(self):
        return self._body


class FakePage:
    """A scripted Playwright page: records handlers, replays canned output.

    ``responses`` are fed to the registered response handler during ``goto`` so
    the real capture path is exercised. ``dom``/``text``/``shot`` are returned
    verbatim. Tracks whether it was closed.
    """

    def __init__(self, *, url="https://x", dom="<html></html>", text="hi",
                 shot=b"jpg", responses=None):
        self._url = url
        self._dom = dom
        self._text = text
        self._shot = shot
        self._responses = responses or []
        self._route_handler = None
        self._response_handler = None
        self.closed = False

    @property
    def url(self):
        return self._url

    def route(self, pattern, handler):
        self._route_handler = handler

    def on(self, event, handler):
        if event == "response":
            self._response_handler = handler

    def goto(self, url, **kwargs):
        if self._response_handler:
            for r in self._responses:
                self._response_handler(r)
        return None

    def wait_for_load_state(self, *a, **k):
        return None

    def content(self):
        return self._dom

    def inner_text(self, selector):
        return self._text

    def screenshot(self, **kwargs):
        return self._shot

    def close(self):
        self.closed = True


class SpyBackend:
    """A FetchBackend that returns a queued page and counts calls."""

    def __init__(self, page, tier="static"):
        self._page = page
        self.tier = tier
        self.calls = 0

    def fetch(self, url):
        self.calls += 1
        return self._page


# ---------------------------------------------------------------------------
# Static backend — SSRF, allowlist, caps
# ---------------------------------------------------------------------------


def test_static_refuses_loopback_without_network():
    """A loopback URL is refused by the real SSRF validator (no requests call)."""
    out = StaticBackend().fetch("http://127.0.0.1/secret")
    assert out is None


def test_static_fetches_html_and_extracts_text(monkeypatch):
    _allow_all_hosts(monkeypatch)
    html = b"<html><body><table><tr><td>1</td><td>Ada</td><td>58.21</td></tr></table></body></html>"
    _install_requests(
        monkeypatch,
        lambda url, kw: FakeResponse(200, {"Content-Type": "text/html; charset=utf-8"}, html),
    )
    page = StaticBackend().fetch("https://results.example/heat1.htm")
    assert page is not None
    assert page.tier == "static"
    assert page.content_type == "text/html"
    assert page.content == html
    assert "Ada" in (page.text or "")


def test_static_redirect_to_internal_is_refused(monkeypatch):
    """A public URL that 302s to an internal host is refused at the next hop."""
    _allow_all_hosts(monkeypatch)

    def handler(url, kw):
        if "internal" in url:
            pytest.fail("internal host should never be requested")
        return FakeResponse(302, {}, location="http://internal.svc/admin")

    _install_requests(monkeypatch, handler)
    assert StaticBackend().fetch("https://public.example/start") is None


def test_static_follows_safe_redirect(monkeypatch):
    _allow_all_hosts(monkeypatch)
    final = b"<html><body>" + b"x" * 500 + b"</body></html>"

    def handler(url, kw):
        if url.endswith("/start"):
            return FakeResponse(302, {}, location="https://public.example/final.htm")
        return FakeResponse(200, {"Content-Type": "text/html"}, final)

    _install_requests(monkeypatch, handler)
    page = StaticBackend().fetch("https://public.example/start")
    assert page is not None and page.final_url.endswith("/final.htm")


def test_static_rejects_disallowed_content_type(monkeypatch):
    _allow_all_hosts(monkeypatch)
    _install_requests(
        monkeypatch,
        lambda url, kw: FakeResponse(200, {"Content-Type": "video/mp4"}, b"\x00\x00\x00 ftyp"),
    )
    assert StaticBackend().fetch("https://x.example/clip") is None


def test_static_sniffs_pdf_when_mislabelled(monkeypatch):
    _allow_all_hosts(monkeypatch)
    pdf = b"%PDF-1.7\n" + b"x" * 100
    _install_requests(
        monkeypatch,
        lambda url, kw: FakeResponse(200, {"Content-Type": "application/octet-stream"}, pdf),
    )
    page = StaticBackend().fetch("https://x.example/results")
    assert page is not None and page.content_type == "application/pdf"
    assert page.text is None  # opaque binary, no cheap text


def test_static_enforces_byte_cap(monkeypatch):
    _allow_all_hosts(monkeypatch)
    limits = FetchLimits(max_page_bytes=1024)
    big = b"<html>" + b"a" * 4096 + b"</html>"
    _install_requests(
        monkeypatch, lambda url, kw: FakeResponse(200, {"Content-Type": "text/html"}, big)
    )
    assert StaticBackend(limits).fetch("https://x.example/big") is None


def test_static_non_200_returns_none(monkeypatch):
    _allow_all_hosts(monkeypatch)
    _install_requests(monkeypatch, lambda url, kw: FakeResponse(404, {}, b"nope"))
    assert StaticBackend().fetch("https://x.example/missing") is None


# ---------------------------------------------------------------------------
# Shape vocabulary + escalation triggers
# ---------------------------------------------------------------------------


def test_count_result_shaped_tokens_is_sport_agnostic():
    assert count_result_shaped_tokens("1:23.45 and 58.21") >= 2  # times
    assert count_result_shaped_tokens("Final score 3 - 1") >= 1  # scores
    assert count_result_shaped_tokens("finished 1st and 14th") >= 2  # placings
    assert count_result_shaped_tokens("6.42 m, 5 km, 980 pts") >= 3  # distances/points
    assert count_result_shaped_tokens("just some prose with no numbers") == 0


def _html_page(body_text, *, content_type="text/html"):
    raw = f"<html><body>{body_text}</body></html>".encode()
    return FetchedPage(content=raw, final_url="https://x", content_type=content_type, text=body_text)


def test_trigger_thin_body():
    assert render_trigger(_html_page("tiny"), FetchLimits()) == "thin_body"


def test_trigger_js_shell():
    body = "Please enable JavaScript to view the results. " * 8  # > thin threshold
    page = FetchedPage(
        content=b'<html><body><div id="root"></div></body></html>',
        final_url="https://x",
        content_type="text/html",
        text=body,
    )
    assert render_trigger(page, FetchLimits()) == "js_shell"


def test_trigger_no_result_shape():
    prose = "About our club. " * 40  # long, but zero result-shaped tokens
    assert render_trigger(_html_page(prose), FetchLimits()) == "no_result_shape"


def test_trigger_none_for_real_results_table():
    rows = " ".join(f"{i} Swimmer{i} 2009 ClubX {i}:0{i}.21" for i in range(1, 12))
    assert render_trigger(_html_page(rows), FetchLimits()) is None


def test_trigger_none_for_pdf():
    page = FetchedPage(content=b"%PDF-1.7", final_url="https://x", content_type="application/pdf")
    assert render_trigger(page, FetchLimits()) is None


# ---------------------------------------------------------------------------
# read_page orchestration (static → rendered escalation)
# ---------------------------------------------------------------------------


def _results_html_page():
    rows = " ".join(f"{i} Swimmer{i} 2009 ClubX {i}:0{i}.21" for i in range(1, 12))
    return _html_page(rows)


def test_read_page_no_escalation_when_static_is_enough():
    static = SpyBackend(_results_html_page())
    rendered = RenderedBackend(host_safe=lambda u: True, page_provider=lambda: FakePage())
    rendered_spy_calls = []
    orig = rendered.fetch
    rendered.fetch = lambda url: (rendered_spy_calls.append(url) or orig(url))  # type: ignore

    res = read_page("https://x.example/r/", static=static, rendered=rendered)
    assert isinstance(res, ReadResult)
    assert res.tier == "static" and res.trigger is None
    assert rendered_spy_calls == []  # browser never touched


def test_read_page_escalates_to_rendered():
    shell = FetchedPage(
        content=b'<html><body><div id="app"></div></body></html>',
        final_url="https://x.example/r/",
        content_type="text/html",
        text="Please enable JavaScript to view results. " * 8,
    )
    static = SpyBackend(shell)
    rendered_page = RenderedPage(
        content=b"<html>rendered</html>",
        final_url="https://x.example/r/",
        content_type="text/html",
        tier="rendered",
        text="1 Ada 58.21 2 Bo 59.10",
    )
    rendered = SpyBackend(rendered_page, tier="rendered")

    res = read_page("https://x.example/r/", static=static, rendered=rendered)
    assert res.tier == "rendered"
    assert res.trigger == "js_shell"
    assert rendered.calls == 1
    assert res.page is rendered_page


def test_read_page_render_failure_falls_back_honestly():
    shell = FetchedPage(
        content=b'<html><body><div id="root"></div></body></html>',
        final_url="https://x.example/r/",
        content_type="text/html",
        text="Please enable JavaScript. " * 12,
    )
    static = SpyBackend(shell)
    rendered = SpyBackend(None, tier="rendered")  # render yields nothing

    res = read_page("https://x.example/r/", static=static, rendered=rendered)
    assert res.tier == "static"
    assert res.trigger == "js_shell"
    assert res.render_failed is True
    assert res.page is shell  # kept the static page rather than crashing


def test_read_page_static_failure_returns_empty():
    static = SpyBackend(None)
    res = read_page("https://x.example/r/", static=static, rendered=None)
    assert res.page is None and res.ok is False


# ---------------------------------------------------------------------------
# Scope helpers
# ---------------------------------------------------------------------------


def test_scope_for_uses_directory_prefix():
    scope = scope_for("https://r.example/swimming/2026/index.htm")
    assert scope.host == "r.example"
    assert scope.path_prefix == "/swimming/2026/"
    assert in_scope("https://r.example/swimming/2026/heat1.htm", scope)
    assert not in_scope("https://r.example/other/x.htm", scope)
    assert not in_scope("https://elsewhere.example/swimming/2026/x.htm", scope)
    assert same_host("https://r.example/api/results.json", scope)
    assert not same_host("https://cdn.other/results.json", scope)


# ---------------------------------------------------------------------------
# Rendered backend — scope interception (the browser-level SSRF/scope guard)
# ---------------------------------------------------------------------------


def _rb(**kw):
    return RenderedBackend(host_safe=kw.pop("host_safe", lambda u: True), **kw)


def test_route_blocks_off_origin_document_navigation():
    scope = scope_for("https://site.test/results/")
    rb = _rb()
    assert rb.route_decision("https://evil.test/x", "document", scope) == "abort"
    assert rb.route_decision("https://site.test/results/heat2.htm", "document", scope) == "continue"


def test_route_blocks_off_scope_document_same_host():
    scope = scope_for("https://site.test/results/")
    rb = _rb()
    # same host but outside the path prefix → not a crawl navigation target
    assert rb.route_decision("https://site.test/admin/", "document", scope) == "abort"


def test_route_blocks_internal_host_even_for_assets():
    scope = scope_for("https://site.test/results/")
    rb = _rb(host_safe=lambda u: "10.0.0" not in u)
    assert rb.route_decision("http://10.0.0.5/metadata", "xhr", scope) == "abort"
    assert rb.route_decision("http://10.0.0.5/x.png", "image", scope) == "abort"


def test_route_allows_off_origin_public_assets():
    scope = scope_for("https://site.test/results/")
    rb = _rb()
    assert rb.route_decision("https://cdn.other/app.js", "script", scope) == "continue"
    assert rb.route_decision("https://cdn.other/logo.png", "image", scope) == "continue"


def test_route_allows_data_uri_blocks_file_scheme():
    scope = scope_for("https://site.test/results/")
    rb = _rb()
    assert rb.route_decision("data:image/png;base64,iVBORw0K", "image", scope) == "continue"
    assert rb.route_decision("file:///etc/passwd", "document", scope) == "abort"
    assert rb.route_decision("ftp://x/y", "xhr", scope) == "abort"


# ---------------------------------------------------------------------------
# Rendered backend — network capture filtering + caps
# ---------------------------------------------------------------------------


def test_capture_keeps_inscope_json_filters_the_rest():
    scope = scope_for("https://site.test/results/")
    rb = _rb()
    captures: list[CapturedResponse] = []
    totals = [0]

    keep = FakeNetworkResponse("https://site.test/api/r.json", "xhr", "application/json", b'{"a":1}')
    wrong_type = FakeNetworkResponse("https://site.test/page", "xhr", "text/html", b"<html>")
    wrong_rtype = FakeNetworkResponse("https://site.test/x.json", "stylesheet", "application/json", b"{}")
    off_host = FakeNetworkResponse("https://cdn.other/r.json", "fetch", "application/json", b"{}")
    plus_json = FakeNetworkResponse("https://site.test/api/v", "fetch", "application/ld+json", b'{"x":2}')

    for r in (keep, wrong_type, wrong_rtype, off_host, plus_json):
        rb._maybe_capture(r, scope, captures, totals)

    urls = {c.url for c in captures}
    assert urls == {"https://site.test/api/r.json", "https://site.test/api/v"}


def test_capture_enforces_per_body_and_total_caps():
    scope = scope_for("https://site.test/results/")
    rb = _rb()
    rb.limits = FetchLimits(capture_max_bytes=10, capture_total_max_bytes=15)
    captures: list[CapturedResponse] = []
    totals = [0]

    too_big = FakeNetworkResponse("https://site.test/big.json", "xhr", "application/json", b"x" * 50)
    ok1 = FakeNetworkResponse("https://site.test/a.json", "xhr", "application/json", b"x" * 8)
    ok2_over_total = FakeNetworkResponse("https://site.test/b.json", "xhr", "application/json", b"x" * 8)

    rb._maybe_capture(too_big, scope, captures, totals)  # over per-body cap → skip
    rb._maybe_capture(ok1, scope, captures, totals)  # 8 ≤ 15 → keep
    rb._maybe_capture(ok2_over_total, scope, captures, totals)  # 8+8 > 15 → skip

    assert [c.url for c in captures] == ["https://site.test/a.json"]


# ---------------------------------------------------------------------------
# Rendered backend — render budget + full fetch through a fake page
# ---------------------------------------------------------------------------


def test_render_budget_caps_a_crawl():
    limits = FetchLimits(max_renders=2)
    rb = RenderedBackend(limits, host_safe=lambda u: True, page_provider=lambda: FakePage())
    a = rb.fetch("https://site.test/results/1")
    b = rb.fetch("https://site.test/results/2")
    c = rb.fetch("https://site.test/results/3")
    assert a is not None and b is not None
    assert c is None
    assert rb.renders_done == 2
    assert rb.budget_hit is True


def test_render_refuses_internal_host():
    rb = RenderedBackend(host_safe=lambda u: False, page_provider=lambda: FakePage())
    assert rb.fetch("http://10.0.0.5/") is None
    assert rb.renders_done == 0  # never even rendered


def test_fetch_through_fake_page_captures_and_reads():
    scope_url = "https://site.test/results/"
    keep = FakeNetworkResponse("https://site.test/api/r.json", "xhr", "application/json", b'{"ok":1}')
    skip = FakeNetworkResponse("https://cdn.other/r.json", "xhr", "application/json", b"{}")
    fake = FakePage(
        url="https://site.test/results/",
        dom="<html>rendered dom</html>",
        text="1 Ada 58.21",
        shot=b"\xff\xd8\xffjpeg",
        responses=[keep, skip],
    )
    rb = RenderedBackend(host_safe=lambda u: True, page_provider=lambda: fake)
    page = rb.fetch(scope_url)
    assert isinstance(page, RenderedPage)
    assert page.tier == "rendered"
    assert page.content == b"<html>rendered dom</html>"
    assert page.text == "1 Ada 58.21"
    assert page.screenshot == b"\xff\xd8\xffjpeg" and page.screenshot_mime == "image/jpeg"
    assert [c.url for c in page.captures] == ["https://site.test/api/r.json"]
    assert fake.closed is True  # page/context cleaned up
