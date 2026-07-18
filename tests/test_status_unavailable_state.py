"""tests/test_status_unavailable_state.py — the public status page is honest
when it can't confirm health (audit finding D-28).

The renderer defaulted operational=True and its except branch also set
operational=True, so a deployment with no heartbeat (or a broken observability
layer) showed a green dot and "Everything is running normally" — telling a
volunteer all was well during an outage the system simply couldn't see.
"""

from __future__ import annotations

import pytest


@pytest.fixture
def app(web_module, tmp_path, monkeypatch):
    # web.py is already isolated onto this test's DATA_DIR by the shared
    # ``web_module`` fixture. The uptime store binds ``DB_PATH`` at import time
    # and the canonical fixtures never reload it, so repoint its path globals at
    # this test's fresh DATA_DIR — otherwise the "no heartbeat" premise would
    # leak a populated DB from a prior test (module-level global) and the test
    # would become order-dependent.
    import mediahub.observability.uptime as upt

    monkeypatch.setattr(upt, "DATA_DIR", tmp_path)
    monkeypatch.setattr(upt, "DB_PATH", tmp_path / "data.db")

    application = web_module.create_app()
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
