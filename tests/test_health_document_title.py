"""tests/test_health_document_title.py — regression for axe-core document-title
violation on /health.

The /health endpoint performs content negotiation:
  * Accept: application/json, */*, or no Accept → plain JSON, status 200/503
  * Accept ranking text/html strictly above */* (a real browser navigation),
    or Sec-Fetch-Dest: document → a minimal HTML page with a valid <title>

This pins the a11y fix (browsers must see a <title> element so axe-core's
document-title rule, WCAG 2.4.2, is satisfied) AND the API contract for
generic clients: fetch(), curl, and python-requests all send ``Accept: */*``
and must receive JSON — the nav badge's bare fetch() once got HTML back,
r.json() threw, and the badge painted "offline" on a perfectly healthy site.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


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


def test_health_html_has_title(client):
    """Browser requests (Accept: text/html) must receive an HTML page with a
    <title> element — the axe-core document-title rule requires this."""
    r = client.get("/health", headers={"Accept": "text/html"})
    assert r.status_code in (200, 503)
    assert r.content_type.startswith("text/html")
    body = r.data.decode()
    assert "<title>" in body
    assert "MediaHub Health" in body


def test_health_html_title_reflects_status(client):
    """The HTML <title> contains the status label (OK or Degraded) so the
    page is usable as a dashboard tab."""
    r = client.get("/health", headers={"Accept": "text/html"})
    body = r.data.decode()
    # One of the two labels must appear in the title.
    assert "OK" in body or "Degraded" in body


def test_health_json_by_default(client):
    """Clients that send no Accept header (monitoring tools, curl) must still
    receive JSON — the HTML path must not break the existing API contract."""
    r = client.get("/health")
    assert r.status_code in (200, 503)
    assert r.content_type.startswith("application/json")
    payload = r.get_json()
    assert "ok" in payload


def test_health_json_explicit_accept(client):
    """Explicit Accept: application/json must return JSON, not HTML."""
    r = client.get("/health", headers={"Accept": "application/json"})
    assert r.status_code in (200, 503)
    assert r.content_type.startswith("application/json")
    assert r.get_json() is not None


def test_health_wildcard_accept_returns_json(client):
    """Accept: */* (fetch(), curl, python-requests defaults) must return JSON.

    best_match() used to break the */* tie by list order and hand these API
    callers the HTML page instead.
    """
    r = client.get("/health", headers={"Accept": "*/*"})
    assert r.status_code in (200, 503)
    assert r.content_type.startswith("application/json")
    assert r.get_json() is not None


def test_health_browser_accept_returns_html(client):
    """A real browser navigation Accept header (text/html ranked above
    */*;q=0.8) must still receive the HTML page."""
    r = client.get(
        "/health",
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        },
    )
    assert r.status_code in (200, 503)
    assert r.content_type.startswith("text/html")
    assert "<title>" in r.data.decode()


# ---------------------------------------------------------------------------
# /healthz — same content-negotiation contract
# ---------------------------------------------------------------------------


def test_healthz_html_has_title(client):
    """Browser requests to /healthz must receive an HTML page with a <title>
    element — the axe-core document-title rule (WCAG 2.4.2) requires this."""
    r = client.get("/healthz", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert r.content_type.startswith("text/html")
    body = r.data.decode()
    assert "<title>" in body
    assert "MediaHub Health" in body


def test_healthz_json_by_default(client):
    """Clients that send no Accept header must still receive JSON from /healthz
    — the HTML path must not break the existing liveness-probe contract."""
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.content_type.startswith("application/json")
    payload = r.get_json()
    assert payload is not None
    assert payload.get("ok") is True


def test_healthz_json_explicit_accept(client):
    """Explicit Accept: application/json must return JSON from /healthz."""
    r = client.get("/healthz", headers={"Accept": "application/json"})
    assert r.status_code == 200
    assert r.content_type.startswith("application/json")
    assert r.get_json() is not None


def test_healthz_wildcard_accept_returns_json(client):
    """Accept: */* must return JSON from /healthz — this is exactly what the
    nav badge's fetch(HEALTH_URL) sends. When best_match() resolved */* to
    text/html, r.json() threw on the HTML and the badge showed "offline"
    every 30s on a healthy deployment."""
    r = client.get("/healthz", headers={"Accept": "*/*"})
    assert r.status_code == 200
    assert r.content_type.startswith("application/json")
    payload = r.get_json()
    assert payload is not None
    assert payload.get("ok") is True


def test_healthz_browser_accept_returns_html(client):
    """A real browser navigation Accept header must still get the HTML page
    (axe-core document-title, WCAG 2.4.2)."""
    r = client.get(
        "/healthz",
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        },
    )
    assert r.status_code == 200
    assert r.content_type.startswith("text/html")
    assert "<title>" in r.data.decode()


def test_healthz_sec_fetch_dest_document_returns_html(client):
    """Sec-Fetch-Dest: document (sent by Chromium/Firefox on page.goto) must
    trigger the HTML path even when the Accept header is absent or generic —
    this guards against reverse-proxy stripping of the Accept header."""
    r = client.get("/healthz", headers={"Sec-Fetch-Dest": "document"})
    assert r.status_code == 200
    assert r.content_type.startswith("text/html")
    body = r.data.decode()
    assert "<title>" in body
    assert "MediaHub Health" in body


def test_healthz_vary_header_present(client):
    """Both HTML and JSON responses from /healthz must carry Vary: Accept,
    Sec-Fetch-Dest so that caching proxies store separate entries per
    browser/API client rather than serving a cached JSON to browsers."""
    html_r = client.get("/healthz", headers={"Accept": "text/html"})
    json_r = client.get("/healthz", headers={"Accept": "application/json"})
    for r in (html_r, json_r):
        vary = r.headers.get("Vary", "")
        assert "Accept" in vary, f"Vary missing 'Accept': {vary}"
        assert "Sec-Fetch-Dest" in vary, f"Vary missing 'Sec-Fetch-Dest': {vary}"


# ---------------------------------------------------------------------------
# /healthz/breaker — same content-negotiation contract (axe document-title)
# ---------------------------------------------------------------------------


def test_healthz_breaker_html_has_title(client):
    """Browser requests to /healthz/breaker must receive an HTML page with a
    <title> element — regression for axe-core document-title (WCAG 2.4.2)."""
    r = client.get("/healthz/breaker", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert r.content_type.startswith("text/html")
    body = r.data.decode()
    assert "<title>" in body
    assert "MediaHub Health" in body


def test_healthz_breaker_json_by_default(client):
    """Clients that send no Accept header must receive JSON from /healthz/breaker
    — the HTML path must not break the existing monitoring contract."""
    r = client.get("/healthz/breaker")
    assert r.status_code == 200
    assert r.content_type.startswith("application/json")
    payload = r.get_json()
    assert payload is not None
    assert payload.get("ok") is True


def test_healthz_breaker_sec_fetch_dest_document_returns_html(client):
    """Sec-Fetch-Dest: document must trigger HTML from /healthz/breaker even
    when Accept is absent — guards against proxies stripping Accept."""
    r = client.get("/healthz/breaker", headers={"Sec-Fetch-Dest": "document"})
    assert r.status_code == 200
    assert r.content_type.startswith("text/html")
    body = r.data.decode()
    assert "<title>" in body
    assert "MediaHub Health" in body


def test_healthz_breaker_wildcard_accept_returns_json(client):
    """Accept: */* (curl/fetch default) must return JSON from
    /healthz/breaker — same tie-break bug as /healthz."""
    r = client.get("/healthz/breaker", headers={"Accept": "*/*"})
    assert r.status_code == 200
    assert r.content_type.startswith("application/json")
    payload = r.get_json()
    assert payload is not None
    assert payload.get("ok") is True


# ---------------------------------------------------------------------------
# /healthz/deps — same content-negotiation contract (axe html-has-lang)
# ---------------------------------------------------------------------------


def test_healthz_deps_html_has_lang(client):
    """Browser requests to /healthz/deps must receive an HTML page whose
    <html> element carries lang="en" — regression for axe-core html-has-lang
    (WCAG 3.1.1, serious)."""
    r = client.get("/healthz/deps", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert r.content_type.startswith("text/html")
    body = r.data.decode()
    assert 'lang="en"' in body


def test_healthz_deps_html_has_title(client):
    """Browser requests to /healthz/deps must include a <title> element
    — regression for axe-core document-title (WCAG 2.4.2)."""
    r = client.get("/healthz/deps", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert r.content_type.startswith("text/html")
    body = r.data.decode()
    assert "<title>" in body
    assert "MediaHub Health" in body


def test_healthz_deps_json_by_default(client):
    """Clients that send no Accept header must still receive JSON from
    /healthz/deps — the HTML path must not break the existing monitoring
    contract."""
    r = client.get("/healthz/deps")
    assert r.status_code == 200
    assert r.content_type.startswith("application/json")
    payload = r.get_json()
    assert payload is not None
    assert "ok" in payload
    assert "deps" in payload


def test_healthz_deps_wildcard_accept_returns_json(client):
    """Accept: */* (curl/fetch default) must return JSON from /healthz/deps
    — the /api/settings/llm-status consumer sends */* and must not get HTML."""
    r = client.get("/healthz/deps", headers={"Accept": "*/*"})
    assert r.status_code == 200
    assert r.content_type.startswith("application/json")
    payload = r.get_json()
    assert payload is not None
    assert "ok" in payload


def test_healthz_deps_sec_fetch_dest_document_returns_html(client):
    """Sec-Fetch-Dest: document must trigger HTML from /healthz/deps even
    when Accept is absent — guards against reverse-proxy stripping of Accept."""
    r = client.get("/healthz/deps", headers={"Sec-Fetch-Dest": "document"})
    assert r.status_code == 200
    assert r.content_type.startswith("text/html")
    body = r.data.decode()
    assert 'lang="en"' in body
    assert "<title>" in body


# ---------------------------------------------------------------------------
# /healthz/memory — same content-negotiation contract (axe html-has-lang)
# ---------------------------------------------------------------------------


def test_healthz_memory_html_has_lang(client):
    """Browser requests to /healthz/memory must receive an HTML page whose
    <html> element carries lang="en" — regression for axe-core html-has-lang
    (WCAG 3.1.1, serious)."""
    r = client.get("/healthz/memory", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert r.content_type.startswith("text/html")
    body = r.data.decode()
    assert 'lang="en"' in body


def test_healthz_memory_html_has_title(client):
    """Browser requests to /healthz/memory must include a <title> element
    — regression for axe-core document-title (WCAG 2.4.2)."""
    r = client.get("/healthz/memory", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert r.content_type.startswith("text/html")
    body = r.data.decode()
    assert "<title>" in body
    assert "MediaHub Health" in body


def test_healthz_memory_json_by_default(client):
    """Clients that send no Accept header must still receive JSON from
    /healthz/memory — the HTML path must not break the existing monitoring
    contract."""
    r = client.get("/healthz/memory")
    assert r.status_code == 200
    assert r.content_type.startswith("application/json")
    payload = r.get_json()
    assert payload is not None
    assert payload.get("ok") is True
    assert "rss_mb" in payload


def test_healthz_memory_wildcard_accept_returns_json(client):
    """Accept: */* (curl/fetch default) must return JSON from /healthz/memory."""
    r = client.get("/healthz/memory", headers={"Accept": "*/*"})
    assert r.status_code == 200
    assert r.content_type.startswith("application/json")
    payload = r.get_json()
    assert payload is not None
    assert payload.get("ok") is True


def test_healthz_memory_sec_fetch_dest_document_returns_html(client):
    """Sec-Fetch-Dest: document must trigger HTML from /healthz/memory even
    when Accept is absent — guards against reverse-proxy stripping of Accept."""
    r = client.get("/healthz/memory", headers={"Sec-Fetch-Dest": "document"})
    assert r.status_code == 200
    assert r.content_type.startswith("text/html")
    body = r.data.decode()
    assert 'lang="en"' in body
    assert "<title>" in body


# ---------------------------------------------------------------------------
# /healthz/ping — content-negotiation contract (axe document-title)
# ---------------------------------------------------------------------------


def test_healthz_ping_html_has_title(client):
    """Browser requests to /healthz/ping must receive an HTML page with a
    <title> element — regression for axe-core document-title (WCAG 2.4.2)."""
    r = client.get("/healthz/ping", headers={"Accept": "text/html"})
    assert r.status_code == 200
    assert r.content_type.startswith("text/html")
    body = r.data.decode()
    assert "<title>" in body
    assert "MediaHub Health" in body


def test_healthz_ping_json_by_default(client):
    """Clients that send no Accept header must receive JSON from /healthz/ping
    — the HTML path must not break the existing monitoring contract."""
    r = client.get("/healthz/ping")
    assert r.status_code == 200
    assert r.content_type.startswith("application/json")
    payload = r.get_json()
    assert payload is not None
    assert payload.get("pong") is True


def test_healthz_ping_json_explicit_accept(client):
    """Explicit Accept: application/json must return JSON from /healthz/ping."""
    r = client.get("/healthz/ping", headers={"Accept": "application/json"})
    assert r.status_code == 200
    assert r.content_type.startswith("application/json")
    assert r.get_json() is not None


def test_healthz_ping_wildcard_accept_returns_json(client):
    """Accept: */* (curl/fetch default) must return JSON from /healthz/ping."""
    r = client.get("/healthz/ping", headers={"Accept": "*/*"})
    assert r.status_code == 200
    assert r.content_type.startswith("application/json")
    payload = r.get_json()
    assert payload is not None
    assert payload.get("pong") is True


def test_healthz_ping_browser_accept_returns_html(client):
    """A real browser navigation Accept header must get the HTML page from
    /healthz/ping (axe-core document-title, WCAG 2.4.2)."""
    r = client.get(
        "/healthz/ping",
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
        },
    )
    assert r.status_code == 200
    assert r.content_type.startswith("text/html")
    assert "<title>" in r.data.decode()


def test_healthz_ping_sec_fetch_dest_document_returns_html(client):
    """Sec-Fetch-Dest: document must trigger HTML from /healthz/ping even when
    Accept is absent — guards against reverse-proxy stripping of Accept."""
    r = client.get("/healthz/ping", headers={"Sec-Fetch-Dest": "document"})
    assert r.status_code == 200
    assert r.content_type.startswith("text/html")
    body = r.data.decode()
    assert "<title>" in body
    assert "MediaHub Health" in body
