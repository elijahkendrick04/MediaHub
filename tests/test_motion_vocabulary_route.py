"""The web surfaces for the motion vocabulary (1.5): the served stylesheet and
the reference gallery that actually consumes it."""
from __future__ import annotations

import pytest


def _app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app


def test_motion_vocabulary_css_is_served(monkeypatch, tmp_path):
    client = _app(monkeypatch, tmp_path).test_client()
    resp = client.get("/static/theme/motion-vocabulary.css")
    assert resp.status_code == 200
    assert "css" in resp.headers.get("Content-Type", "")
    body = resp.get_data(as_text=True)
    assert "@keyframes mh-" in body
    assert "prefers-reduced-motion" in body


def test_gallery_renders_every_preset(monkeypatch, tmp_path):
    from mediahub.motion import vocabulary as v

    client = _app(monkeypatch, tmp_path).test_client()
    resp = client.get("/motion/vocabulary")
    assert resp.status_code == 200
    assert resp.headers["Content-Type"].startswith("text/html")
    html = resp.get_data(as_text=True)
    # links the compiled stylesheet…
    assert "motion-vocabulary.css" in html
    # …and the self-hosted brand fonts (never the system fallback / a CDN):
    # the gallery styles with 'Hanken Grotesk', so it must load fonts.css.
    assert "theme/fonts.css" in html
    assert "'Inter'" not in html
    # …and shows a tile (with its anim class) for every preset.
    for name in v.names():
        assert f"mh-anim-{name.replace('_', '-')}" in html, name
    # families are sectioned
    for family in v.FAMILIES:
        assert f">{family} " in html


def test_gallery_mentions_reduce_motion(monkeypatch, tmp_path):
    client = _app(monkeypatch, tmp_path).test_client()
    html = client.get("/motion/vocabulary").get_data(as_text=True)
    assert "reduce motion" in html.lower()
