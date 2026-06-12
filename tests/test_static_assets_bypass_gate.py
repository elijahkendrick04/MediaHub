"""Static assets must never be caught by the org-setup or terms gates.

Regression for the 2026-06-12 incident: an autonomous a11y fix added a CUSTOM
route ``static_fonts_css`` for ``/static/theme/fonts.css`` (to give axe-core a
page ``<title>``), but that route's endpoint name was not in the gate
exemption lists — only the built-in ``static`` endpoint was. So with the
production org gate active, ``/static/theme/fonts.css`` 302-redirected to
``/sign-in`` for anonymous / no-org sessions, the browser got HTML instead of
CSS, every ``@font-face`` failed, and the whole site fell back to system fonts.

The fix exempts the ``/static/`` PATH (not just the endpoint name) in both
gates, so any current or future custom static route is safe. These tests run
with the gate ENFORCED (it is bypassed by default under TESTING) so they
exercise the real redirect behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))


@pytest.fixture
def gated_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("SECRET_KEY", "test-secret-key-for-signed-sessions")
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    app.config["ENFORCE_ORG_GATE"] = True
    app.config["ENFORCE_TERMS_GATE"] = True
    return app.test_client()


def test_org_gate_is_actually_enforced(gated_client):
    # Sanity: a normal content route IS gated — otherwise the assertions below
    # would pass vacuously. With no org set up, the gate redirects.
    r = gated_client.get("/make")
    assert r.status_code in (302, 303)


def test_fonts_css_not_gated(gated_client):
    # The custom static_fonts_css route must be served, not redirected.
    r = gated_client.get("/static/theme/fonts.css")
    assert r.status_code == 200
    assert "/sign-in" not in r.headers.get("Location", "")


def test_font_files_not_gated(gated_client):
    r = gated_client.get("/static/fonts/hanken-latin-normal-400.woff2")
    assert r.status_code == 200
