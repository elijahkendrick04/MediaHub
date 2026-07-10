"""tests/test_status_unavailable_state.py — the public status page is honest
when it can't confirm health (audit finding D-28).

The renderer defaulted operational=True and its except branch also set
operational=True, so a deployment with no heartbeat (or a broken observability
layer) showed a green dot and "Everything is running normally" — telling a
volunteer all was well during an outage the system simply couldn't see.
"""
from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    # Reload the uptime module too, not just web: its DB_PATH is bound at import
    # time, so without this reload the "no heartbeat" premise leaks a populated
    # DB from a prior test (module-level global) and the test becomes
    # order-dependent. Rebind it to this test's fresh DATA_DIR.
    import mediahub.observability.uptime as upt
    import mediahub.web.web as wm

    importlib.reload(upt)
    importlib.reload(wm)
    application = wm.create_app()
    application.config["TESTING"] = True
    return application


def test_no_heartbeat_shows_unavailable_not_green(app):
    """A fresh deployment with no heartbeat must not claim it's operational."""
    c = app.test_client()
    body = c.get("/status").get_data(as_text=True)
    assert "Status unavailable" in body, "no-data path must be neutral, not green (D-28)"
    assert "Website operational" not in body
    assert "Everything is running" not in body


def test_fresh_ok_heartbeat_shows_operational(app):
    from mediahub.observability import uptime as _uptime

    _uptime.record_heartbeat(ok=True, source="test")
    c = app.test_client()
    body = c.get("/status").get_data(as_text=True)
    assert "Website operational" in body
    assert "Status unavailable" not in body
