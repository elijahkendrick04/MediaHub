"""Health / diagnostic endpoints serve their native content type regardless of
Accept or Sec-Fetch-Dest.

``/health``, the ``/healthz`` probes, and ``/static/theme/fonts.css`` once
content-negotiated: a real browser navigation (Accept ranking ``text/html``
above ``*/*``, or ``Sec-Fetch-Dest: document``) received a minimal HTML page
with a ``<title>`` purely to satisfy axe-core's ``document-title`` rule
(WCAG 2.4.2). That finding was a FALSE POSITIVE — the autotest crawler was
running axe-core against the synthetic viewer Chromium renders for non-HTML
responses (JSON / JS / CSS), which is not a real WCAG document. The fix is in
the finder (the a11y audit is now gated to HTML responses), so the
negotiation has been removed: these endpoints always serve JSON (or CSS) — the
same thing the nav badge's ``fetch()``, curl, external monitors, and Render's
liveness probe already required.

This pins that contract: NO client — browser navigation included — gets an
HTML page from these endpoints.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

# Header sets a real browser navigation sends — these previously flipped the
# endpoint to an HTML page; after the revert they must receive JSON/CSS like
# any other client. Plus the generic API/monitoring header sets.
_BROWSER_NAV = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
_SEC_FETCH_DOC = {"Sec-Fetch-Dest": "document"}
_NO_ACCEPT: dict[str, str] = {}
_WILDCARD = {"Accept": "*/*"}
_EXPLICIT_JSON = {"Accept": "application/json"}

_ALL_HEADER_SETS = (_NO_ACCEPT, _WILDCARD, _EXPLICIT_JSON, _BROWSER_NAV, _SEC_FETCH_DOC)
_HEALTHZ_ROUTES = ("/healthz", "/healthz/ping", "/healthz/memory",
                   "/healthz/deps", "/healthz/breaker")


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


def _assert_json(r, *, ok_statuses=(200,)):
    assert r.status_code in ok_statuses, r.status_code
    assert r.content_type.startswith("application/json"), r.content_type
    assert r.get_json() is not None


@pytest.mark.parametrize("headers", _ALL_HEADER_SETS)
def test_health_always_json(client, headers):
    """/health serves JSON for every client — including browser navigations and
    Sec-Fetch-Dest: document. The HTML <title> negotiation has been removed."""
    _assert_json(client.get("/health", headers=headers), ok_statuses=(200, 503))


@pytest.mark.parametrize("route", _HEALTHZ_ROUTES)
@pytest.mark.parametrize("headers", _ALL_HEADER_SETS)
def test_healthz_endpoints_always_json(client, route, headers):
    """Every /healthz probe serves JSON for all clients (no more browser HTML)."""
    _assert_json(client.get(route, headers=headers))


def test_healthz_payloads_keep_their_shape(client):
    """The JSON probes still carry their documented fields after the revert.

    The RSS internals of /healthz/memory are now operator-gated (deep-review
    #29), so the shape is checked against a signed-in operator session; the
    anonymous liveness contract is pinned separately below."""
    assert client.get("/healthz").get_json().get("ok") is True
    assert client.get("/healthz/ping").get_json().get("pong") is True
    with client.session_transaction() as s:
        s["dev_operator"] = True
    _mem = client.get("/healthz/memory").get_json()
    assert "rss_mb" in _mem
    # rss_mb is CURRENT RSS (leak diagnostic); rss_peak_mb is the lifetime
    # high-water mark. On Linux current can never exceed peak.
    assert "rss_peak_mb" in _mem
    assert _mem["rss_peak_mb"] >= _mem["rss_mb"]
    assert "deps" in client.get("/healthz/deps").get_json()


def test_healthz_memory_anonymous_is_liveness_only(client):
    """An anonymous /healthz/memory returns the liveness boolean but none of the
    RSS / concurrency internals — those are operator-only (deep-review #29)."""
    _mem = client.get("/healthz/memory").get_json()
    assert _mem.get("ok") is True
    for leaked in ("rss_mb", "rss_peak_mb", "rss_pct_of_2048",
                   "active_runs", "active_runs_running", "turn_into_jobs"):
        assert leaked not in _mem, f"anonymous /healthz/memory leaked {leaked}"


@pytest.mark.parametrize("headers", _ALL_HEADER_SETS)
def test_fonts_css_always_css(client, headers):
    """/static/theme/fonts.css serves the real CSS for every client — including
    browser navigations. The HTML <title> intercept has been removed."""
    r = client.get("/static/theme/fonts.css", headers=headers)
    assert r.status_code == 200
    assert not r.content_type.startswith("text/html"), r.content_type
    assert "css" in r.content_type, r.content_type


def test_fonts_css_serves_the_real_stylesheet(client):
    """A stylesheet load gets the actual font CSS, not an empty/HTML shell."""
    r = client.get("/static/theme/fonts.css",
                   headers={"Accept": "text/css,*/*;q=0.1", "Sec-Fetch-Dest": "style"})
    assert r.status_code == 200
    assert "css" in r.content_type
    assert "@font-face" in r.data.decode()
