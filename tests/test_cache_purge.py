"""Site-wide cache purge — engine helper + operator route.

Covers the deployment-level "clear the cache for the entire site, for all
runs" operation:

- ``purge_all_caches`` removes every re-derivable cache root but leaves source
  data (runs, uploads, the SQLite DBs, ledgers) untouched.
- The ``/operator/cache/purge`` route is operator-only (anon + plain users are
  bounced to the developer sign-in) and clears the on-disk caches.
"""

from __future__ import annotations

from pathlib import Path

import pytest

PASSWORD = "twelve-chars-long"


def _make_app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app


def _seed_caches(tmp_path: Path):
    """Write a file into every re-derivable cache root and a sentinel into a
    source-of-truth directory that must survive."""
    from mediahub.privacy.cache_purge import cache_roots

    roots = cache_roots()
    for _label, p in roots:
        p.mkdir(parents=True, exist_ok=True)
        (p / "entry.json").write_text('{"cached": true}', encoding="utf-8")
    # Source data that must NOT be touched.
    runs = tmp_path / "runs_v4"
    runs.mkdir(parents=True, exist_ok=True)
    (runs / "run-123.json").write_text('{"keep": true}', encoding="utf-8")
    return roots, runs


def test_purge_all_caches_clears_every_root_but_keeps_source(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.privacy.cache_purge import purge_all_caches

    roots, runs = _seed_caches(tmp_path)
    report = purge_all_caches()

    assert report["files_deleted"] >= len(roots)
    assert report["bytes_reclaimed"] > 0
    # Every cache root is gone (or at least empty of cached files).
    for _label, p in roots:
        assert not p.exists() or not any(p.rglob("*.json")), p
    # Source data survives the purge.
    assert (runs / "run-123.json").exists()


def test_purge_all_caches_tolerates_empty_deployment(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.privacy.cache_purge import purge_all_caches

    report = purge_all_caches()
    assert report["files_deleted"] == 0
    assert report["bytes_reclaimed"] == 0
    assert isinstance(report["sections"], dict) and report["sections"]


def test_route_requires_operator(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    c = app.test_client()

    # Anonymous → bounced to developer sign-in, nothing purged.
    r = c.post("/operator/cache/purge")
    assert r.status_code in (302, 303)
    assert "/developer" in r.headers["Location"]

    # A signed-in regular user is still not the operator.
    c.post("/signup", data={"email": "user@club.org", "password": PASSWORD, "accept_terms": "1"})
    r = c.post("/operator/cache/purge")
    assert r.status_code in (302, 303)
    assert "/developer" in r.headers["Location"]


def test_operator_purge_clears_caches(monkeypatch, tmp_path):
    app = _make_app(monkeypatch, tmp_path)
    roots, runs = _seed_caches(tmp_path)
    c = app.test_client()
    with c.session_transaction() as s:
        s["dev_operator"] = True

    r = c.post("/operator/cache/purge")
    assert r.status_code in (302, 303)
    assert "/settings/developer" in r.headers["Location"]

    for _label, p in roots:
        assert not p.exists() or not any(p.rglob("*.json")), p
    # Source data untouched by the route.
    assert (runs / "run-123.json").exists()


def test_purge_clears_graphic_render_cache_on_disk(monkeypatch, tmp_path):
    """The still-graphic renderer's HTML→PNG cache is a purge root.

    Regression: before this was wired in, "Clear all caches" promised graphic
    renders but left every rendered card PNG on disk.
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.privacy.cache_purge import cache_roots, purge_all_caches

    labels = [label for label, _ in cache_roots()]
    assert "graphic_render_cache" in labels

    render_cache = tmp_path / "render_cache"
    render_cache.mkdir(parents=True, exist_ok=True)
    (render_cache / "deadbeef.png").write_bytes(b"\x89PNG\r\n\x1a\n fake")

    report = purge_all_caches()

    assert "graphic_render_cache" in report["sections"]
    assert report["sections"]["graphic_render_cache"]["files_deleted"] >= 1
    assert not (render_cache / "deadbeef.png").exists()


def test_purge_covers_newer_cache_roots(monkeypatch, tmp_path):
    """document_cache, site_cache, asr_cache and stock_thumb_cache are all
    re-derivable and must be enrolled in the site-wide purge.

    Regression: these roots were added after the purge shipped and were
    silently skipped (and under-counted on the settings card).
    """
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.privacy.cache_purge import cache_roots, purge_all_caches

    labels = {label for label, _ in cache_roots()}
    expected = {"document_cache", "site_cache", "asr_cache", "stock_thumb_cache"}
    assert expected <= labels

    for name in ("document_cache", "site_cache", "asr_cache", "stock_thumb_cache"):
        d = tmp_path / name
        d.mkdir(parents=True, exist_ok=True)
        (d / "entry.bin").write_bytes(b"cached")

    report = purge_all_caches()

    for name in expected:
        assert name in report["sections"], name
        assert report["sections"][name]["files_deleted"] >= 1, name
        assert not (tmp_path / name / "entry.bin").exists()


def test_purge_clears_in_process_module_caches(monkeypatch, tmp_path):
    """A disk purge must also drop the matching in-process caches from memory,
    or the worker keeps serving them (and its RSS never falls)."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from mediahub.privacy.cache_purge import purge_all_caches
    from mediahub.graphic_renderer import render_cache as rc
    from mediahub.graphic_renderer import render as R

    # Seed the in-memory base64 asset-URI cache and the preprocessed-logo cache.
    rc._asset_cache[("/some/photo.jpg", 1, 2)] = "data:image/jpeg;base64,AAAA"
    R._LOGO_PREP_CACHE[("/some/logo.png", 1, 2)] = ("data:image/png;base64,BBBB", None)
    assert len(rc._asset_cache) >= 1
    assert len(R._LOGO_PREP_CACHE) >= 1

    report = purge_all_caches()

    # Both in-process caches are emptied and reported.
    assert len(rc._asset_cache) == 0
    assert len(R._LOGO_PREP_CACHE) == 0
    assert "graphic_render_asset_cache" in report["inprocess_cleared"]
    assert "logo_prep_cache" in report["inprocess_cleared"]


def test_operator_route_clears_studio_render_cache(monkeypatch, tmp_path):
    """The operator route drops web.py's own in-process render-preview cache
    (the design-studio cache), not just the disk caches."""
    app = _make_app(monkeypatch, tmp_path)
    from mediahub.web.web import _studio_render_cache

    _studio_render_cache.clear()
    _studio_render_cache["sig-abc"] = {"preview": "data:...", "sidecar": {}}
    assert len(_studio_render_cache) == 1

    c = app.test_client()
    with c.session_transaction() as s:
        s["dev_operator"] = True
    r = c.post("/operator/cache/purge")
    assert r.status_code in (302, 303)

    assert len(_studio_render_cache) == 0
