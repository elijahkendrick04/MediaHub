"""I-7 — the install chip's dismiss must be keyboard-accessible.

The "Install MediaHub" / iOS A2HS chip was one <button> with a × span inside;
dismissal was detected via e.target === close (a mouse click on the ×). A
keyboard user tabbing to the chip and pressing Enter always installed, and the ×
(aria-hidden, no role) had no keyboard path. The chip is now a container of two
real buttons: an install action and a separate Dismiss.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import mediahub.web.web as wm

    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    return app.test_client()


def test_install_chip_has_two_real_buttons(client):
    js = client.get("/static/js/pwa-install.js").get_data(as_text=True)
    # The chip is a container, not a single button.
    assert 'createElement("div")' in js
    assert 'className = "mh-install-action"' in js
    # A real, labelled Dismiss button (not an aria-hidden span).
    assert 'setAttribute("aria-label", "Dismiss")' in js
    assert 'createElement("button")' in js


def test_old_mouse_only_dismiss_gone(client):
    js = client.get("/static/js/pwa-install.js").get_data(as_text=True)
    # The mouse-only e.target === close branch and aria-hidden × are gone.
    assert "e.target === close" not in js
    assert 'setAttribute("aria-hidden", "true")' not in js
