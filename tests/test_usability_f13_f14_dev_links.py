"""F-13/F-14 — the operator "Developer" link belongs only on the sign-in page,
not in the customer landing footer or elsewhere.

Per owner decision: keep "Developer sign-in →" on the customer /login page, but
remove "Developer access →" from the global/landing footer (it read as internal
tooling on the marketing landing).
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
    app.config.update(TESTING=True, SECRET_KEY="x")
    return app.test_client()


def test_landing_footer_has_no_developer_access_link(client):
    html = client.get("/").get_data(as_text=True)
    assert "Developer access" not in html
    assert "mh-footer-devlink" not in html


def test_login_page_keeps_developer_signin_link(client):
    html = client.get("/login").get_data(as_text=True)
    assert "Developer sign-in" in html


def test_footer_devlink_css_removed(client):
    # The now-unused footer devlink CSS class was swept.
    import pathlib

    src = pathlib.Path("src/mediahub/web/web.py").read_text(encoding="utf-8")
    assert ".mh-footer-devlink" not in src
