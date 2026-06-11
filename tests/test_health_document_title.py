"""tests/test_health_document_title.py — regression for axe-core document-title
violation on /health.

The /health endpoint performs content negotiation:
  * Accept: application/json (or no Accept) → plain JSON, status 200/503
  * Accept: text/html → a minimal HTML page with a valid <title>, same status

This pins the a11y fix: browsers must see a <title> element so axe-core's
document-title rule (WCAG 2.4.2) is satisfied.
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
