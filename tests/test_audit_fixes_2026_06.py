"""Regression tests for the 2026-06-03 usability audit fixes.

Covers, under the *enforced* org gate (the real signed-out condition):
  I1 — /sw.js, manifest, favicon must be reachable (200), not redirected,
       so the service worker can register. Gated content routes still redirect.
  I3 — server-rendered pages must not contain double-escaped HTML entities
       (&amp;middot; / &amp;mdash;).
  I5 — the /upload step-1 submit must not be permanently disabled and must
       carry an inline no-file validation message.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def gated_client(app):
    app.config["ENFORCE_ORG_GATE"] = True  # gate ACTIVE: no ready org
    with app.test_client() as c:
        yield c


class TestI1ServiceWorkerExemptFromGate:
    def test_sw_js_not_redirected_when_gated(self, gated_client):
        r = gated_client.get("/sw.js")
        assert r.status_code == 200, "service worker must serve, not redirect, or it can't register"
        assert "javascript" in (r.headers.get("Content-Type") or "")

    def test_manifest_and_favicon_not_redirected_when_gated(self, gated_client):
        for ep in ("/manifest.webmanifest", "/favicon.svg", "/favicon.ico"):
            assert gated_client.get(ep).status_code == 200, f"{ep} must bypass the gate"

    def test_gated_content_route_still_redirects(self, gated_client):
        # Control: a real content route must still be gated.
        r = gated_client.get("/make")
        assert r.status_code in (
            301,
            302,
        ), "content routes must still redirect when no org is ready"


class TestI3NoDoubleEscapedEntities:
    def test_settings_status_no_double_escape(self, gated_client):
        body = gated_client.get("/settings").get_data(as_text=True)
        assert "&amp;mdash;" not in body
        assert "&amp;middot;" not in body


class TestI5UploadValidation:
    def test_upload_submit_not_hard_disabled_and_has_validation(self, gated_client, monkeypatch):
        # Need the gate to allow /upload: temporarily disable enforcement so we
        # can inspect the rendered upload form markup itself.
        import mediahub.web.web as wm

        app = wm.create_app()
        app.config["TESTING"] = True  # gate bypassed -> /upload renders
        with app.test_client() as c:
            body = c.get("/upload").get_data(as_text=True)
        assert "mh-upload-submit" in body
        # The submit button must not ship permanently disabled.
        import re

        m = re.search(r'<button[^>]*id="mh-upload-submit"[^>]*>', body)
        assert m, "upload submit button not found"
        assert "disabled" not in m.group(0), "submit must not be hard-disabled"
        assert "Please choose a results file" in body
        assert "mh-upload-error" in body
