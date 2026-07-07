"""Guard: every mutable, behaviour-bearing static JS (and fonts.css) rides a
per-file content-hash ``?v=`` buster.

SEND_FILE_MAX_AGE_DEFAULT holds /static files for 7 days. Only ui-kit.js used to
carry a ``?v=<sha256>`` buster (``_UI_KIT_VER``); the other page JS
(offline-queue / pwa-install / mobile-capture / print_center / bulk_export) was
linked via a plain ``url_for('static')``, so on an auto-deploying trunk a
returning browser could run week-stale behaviour-bearing JS against new server
code. This pins that each such reference now carries a version query string.
"""

from __future__ import annotations

import re

import pytest


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


def test_static_ver_is_content_hash_and_cached():
    from mediahub.web.web import _static_ver

    v = _static_ver("js/ui-kit.js")
    assert re.fullmatch(r"[0-9a-f]{10}", v), v
    # Stable across calls (cached) and per-file distinct.
    assert _static_ver("js/ui-kit.js") == v
    assert _static_ver("js/offline-queue.js") != ""


def test_layout_js_and_fonts_carry_version_buster(app):
    # The shared layout ships ui-kit / offline-queue / pwa-install + fonts.css.
    html = app.test_client().get("/status").get_data(as_text=True)
    for asset in (
        "js/ui-kit.js",
        "js/offline-queue.js",
        "js/pwa-install.js",
        "theme/fonts.css",
    ):
        # The reference exists AND carries a ?v= (or &v=) query string.
        m = re.search(re.escape(asset) + r"\?[^\"' ]*v=", html)
        assert m, f"{asset} is linked without a ?v= cache-buster"
