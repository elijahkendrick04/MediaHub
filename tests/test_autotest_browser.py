"""B1 (Tier B): cross-browser / mobile selection in the launcher.

Tests engine/device selection and the finding-tagging that keeps a WebKit-only
defect from collapsing into the chromium run's fingerprint — with a fake Playwright,
no real browser.
"""
from __future__ import annotations

import pytest

from autotest import run
from autotest.report import Finding


class _FakeContext:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeBrowser:
    def new_context(self, **kwargs):
        return _FakeContext(**kwargs)


class _FakeType:
    def __init__(self, name):
        self.name = name
        self.launched_headless = None

    def launch(self, headless=True):
        self.launched_headless = headless
        return _FakeBrowser()


class _FakePW:
    def __init__(self):
        self.chromium = _FakeType("chromium")
        self.firefox = _FakeType("firefox")
        self.webkit = _FakeType("webkit")
        self.devices = {"iPhone 13": {"viewport": {"width": 390, "height": 844},
                                      "is_mobile": True}}


def test_default_is_chromium(monkeypatch):
    monkeypatch.delenv("AUTOTEST_BROWSER", raising=False)
    monkeypatch.delenv("AUTOTEST_DEVICE", raising=False)
    _b, _c, engine = run._launch_browser(_FakePW(), headless=True)
    assert engine == "chromium"


@pytest.mark.parametrize("name", ["firefox", "webkit", "chromium"])
def test_selects_named_engine(monkeypatch, name):
    monkeypatch.setenv("AUTOTEST_BROWSER", name)
    monkeypatch.delenv("AUTOTEST_DEVICE", raising=False)
    _b, _c, engine = run._launch_browser(_FakePW(), headless=True)
    assert engine == name


def test_unknown_engine_falls_back_to_chromium(monkeypatch):
    monkeypatch.setenv("AUTOTEST_BROWSER", "lynx")
    _b, _c, engine = run._launch_browser(_FakePW(), headless=True)
    assert engine == "chromium"


def test_device_descriptor_applied(monkeypatch):
    monkeypatch.setenv("AUTOTEST_BROWSER", "webkit")
    monkeypatch.setenv("AUTOTEST_DEVICE", "iPhone 13")
    _b, ctx, engine = run._launch_browser(_FakePW(), headless=True)
    assert engine == "webkit:iPhone 13"
    assert ctx.kwargs.get("is_mobile") is True and ctx.kwargs.get("ignore_https_errors") is True


def test_unknown_device_degrades(monkeypatch):
    monkeypatch.setenv("AUTOTEST_BROWSER", "chromium")
    monkeypatch.setenv("AUTOTEST_DEVICE", "Nokia 3310")
    _b, ctx, engine = run._launch_browser(_FakePW(), headless=True)
    assert engine == "chromium"                       # no crash, no device label
    assert ctx.kwargs == {"ignore_https_errors": True}


# --- finding tagging keeps cross-engine fingerprints distinct ---------------
def _tester(engine):
    from autotest.run import Collector, Tester
    t = Tester(None, "http://x", None, Collector("http://x"), 10)
    t.engine = engine
    return t


def test_non_chromium_engine_tags_evidence():
    t = _tester("webkit")
    f = Finding(category="http_5xx", severity="high", title="t", route="/x",
                expected="e", actual="a", evidence="boom")
    t._add(f, shoot=False)
    assert "[engine=webkit]" in t.findings[0].evidence


def test_chromium_engine_does_not_tag():
    t = _tester("chromium")
    f = Finding(category="http_5xx", severity="high", title="t", route="/x",
                expected="e", actual="a", evidence="boom")
    t._add(f, shoot=False)
    assert "[engine=" not in t.findings[0].evidence


def _finding(**kw):
    base = dict(category="http_5xx", severity="high", title="t", route="/x",
                expected="e", actual="a", evidence="boom")
    base.update(kw)
    return Finding(**base)


def test_onerror_image_404_is_not_flagged_as_network_error():
    """#884 — an <img> that 404s but declares an onerror fallback (MediaHub's
    logo chip → org-initials pattern) is a deliberately-handled degradation, not
    a broken asset. The crawler must skip it while still flagging a genuinely
    broken image that has no onerror."""
    from autotest.run import Collector, Tester

    handled = "http://x/organisation/swansea/logo/abc?bg=1&chip=1"
    broken = "http://x/static/missing.png"

    class _FakePage:
        def eval_on_selector_all(self, selector, script):
            # Only the logo-chip <img> wired an onerror fallback.
            return [handled]

    col = Collector("http://x")
    col.failed = [
        {"url": handled, "status": 404, "type": "image"},
        {"url": broken, "status": 404, "type": "image"},
    ]
    t = Tester(None, "http://x", _FakePage(), col, 10)
    t._shoot = lambda f: None  # no real browser to screenshot with
    t._evaluate("/x", "http://x/x", "x", 200, "", "", from_link=False)

    net = [f for f in t.findings if f.category == "network_error"]
    assert len(net) == 1, "exactly the genuinely-broken image should be flagged"
    assert broken in net[0].actual
    assert not any("logo/abc" in f.actual for f in net)


def test_broken_image_without_onerror_still_flagged():
    """The exemption is narrow: an image 404 whose element has NO onerror is
    still a real broken asset and must be flagged."""
    from autotest.run import Collector, Tester

    class _FakePage:
        def eval_on_selector_all(self, selector, script):
            return []  # no onerror-guarded images on the page

    col = Collector("http://x")
    col.failed = [{"url": "http://x/static/logo.png", "status": 404, "type": "image"}]
    t = Tester(None, "http://x", _FakePage(), col, 10)
    t._shoot = lambda f: None
    t._evaluate("/x", "http://x/x", "x", 200, "", "", from_link=False)

    assert any(f.category == "network_error" for f in t.findings)


def test_engine_tag_changes_fingerprint_even_with_suspect():
    """The tag must reach the fingerprint basis: a finding WITH a suspect (or
    long evidence) previously collapsed with the chromium run's because the
    tag sat at the evidence tail, outside suspect/evidence[:200]."""
    for kw in (
        {"suspect": "axe:color-contrast"},          # suspect wins the basis
        {"evidence": "x" * 300},                    # >200 chars: tail was invisible
        {},                                         # short evidence
    ):
        chromium, webkit = _tester("chromium"), _tester("webkit")
        chromium._add(_finding(**kw), shoot=False)
        webkit._add(_finding(**kw), shoot=False)
        fp_c = chromium.findings[0].fingerprint()
        fp_w = webkit.findings[0].fingerprint()
        assert fp_c != fp_w, f"webkit finding collapsed with chromium for {kw}"
        # chromium fingerprints are unchanged by the tagging logic
        assert fp_c == _finding(**kw).fingerprint()
