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

DEV_KEY = "operator-key-for-cache-tests"
PASSWORD = "twelve-chars-long"


def _make_app(monkeypatch, tmp_path, *, dev_key=DEV_KEY):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    if dev_key is None:
        monkeypatch.delenv("MEDIAHUB_DEV_KEY", raising=False)
    else:
        monkeypatch.setenv("MEDIAHUB_DEV_KEY", dev_key)
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
    app = _make_app(monkeypatch, tmp_path, dev_key=None)
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
