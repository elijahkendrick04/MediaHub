"""Roadmap 1.10 build 3 — licence-clean stock pool + shared rights ledger."""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest

from mediahub.elements import stock
from mediahub.elements.stock import Licence, StockRightsLedger, StockRightsRecord


@pytest.fixture(autouse=True)
def _isolate_thumb_cache(tmp_path, monkeypatch):
    """fetch_thumb caches under DATA_DIR/stock_thumb_cache — pin DATA_DIR to a
    unique tmp dir per test so cached bytes never leak across tests or into the
    repo. (Web-route tests' app_env sets the same DATA_DIR afterwards.)"""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    stock._THUMB_WARMING.clear()  # the in-flight-warm dedupe set is module-global


# --------------------------------------------------------------------------- #
# licence parsing
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "raw,commercial",
    [
        ("CC0", True),
        ("public domain", True),
        ("CC BY 4.0", True),
        ("CC BY-SA 4.0", True),
        ("CC BY-NC 4.0", False),
        ("CC BY-NC-SA 4.0", False),
        ("all rights reserved", False),
        ("", False),
    ],
)
def test_parse_licence_commercial_gate(raw, commercial):
    lic = stock.parse_licence(raw)
    assert lic.commercial_ok is commercial


def test_parse_licence_spdx_and_fields():
    lic = stock.parse_licence(
        "CC BY-SA 4.0", url="http://x", attribution="Jane", source="wikimedia"
    )
    assert lic.spdx == "CC-BY-SA-4.0"
    assert lic.url == "http://x"
    assert lic.attribution == "Jane"
    assert lic.source == "wikimedia"
    assert isinstance(lic, Licence)


# --------------------------------------------------------------------------- #
# source availability (paid gated on env)
# --------------------------------------------------------------------------- #
def test_available_sources_free_always_on(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    src = stock.available_sources()
    assert src["wikimedia"] and src["openverse"]
    assert src["pexels"] is False and src["pixabay"] is False


def test_available_sources_paid_on_with_key(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "k")
    assert stock.available_sources()["pexels"] is True


# --------------------------------------------------------------------------- #
# search (photo path reuses venue_search; mocked, no network)
# --------------------------------------------------------------------------- #
def _patch_venue(monkeypatch, fn):
    # venue_search/__init__ re-exports `search`, which shadows the submodule name
    # under attribute access — grab the real module object via sys.modules.
    import sys

    import mediahub.venue_search.search  # noqa: F401  (ensure imported)

    _vs_mod = sys.modules["mediahub.venue_search.search"]
    monkeypatch.setattr(_vs_mod, "search", fn)


def _fake_venue_result(licence="CC BY 4.0"):
    return SimpleNamespace(
        title="Pool",
        thumb_url="http://t/x.jpg",
        direct_url="http://d/x.jpg",
        source_url="http://s/x",
        source_site="wikimedia",
        width=800,
        height=600,
        licence=licence,
        licence_url="http://l",
        attribution="Snapper",
        permission_status="approved_public",
        description="a pool",
        confidence=0.8,
    )


def test_search_photos_maps_and_filters(monkeypatch):
    _patch_venue(
        monkeypatch,
        lambda q, limit=8, timeout=8: [
            _fake_venue_result("CC BY 4.0"),
            _fake_venue_result("CC BY-NC 4.0"),  # must be filtered out
        ],
    )
    results = stock.search("swimming pool", kind="photo")
    assert len(results) == 1  # NC dropped by commercial_only
    r = results[0]
    assert r.kind == "photo"
    assert r.licence.commercial_ok is True
    assert r.licence.attribution == "Snapper"
    assert r.source_site == "wikimedia"


def test_search_commercial_only_off_keeps_all(monkeypatch):
    _patch_venue(monkeypatch, lambda q, limit=8, timeout=8: [_fake_venue_result("CC BY-NC 4.0")])
    results = stock.search("x", kind="photo", commercial_only=False)
    assert len(results) == 1


def test_search_empty_query_returns_empty():
    assert stock.search("") == []


def test_search_never_raises_on_source_error(monkeypatch):
    def _boom(q, limit=8, timeout=8):
        raise RuntimeError("network down")

    _patch_venue(monkeypatch, _boom)
    # _search_free_photos swallows source errors → empty, never raises
    assert stock.search("x", kind="photo") == []


def test_search_video_parses_wikimedia(monkeypatch):
    payload = {
        "query": {
            "pages": {
                "1": {
                    "title": "File:Swim.webm",
                    "imageinfo": [
                        {
                            "url": "http://d/swim.webm",
                            "thumburl": "http://t/swim.jpg",
                            "descriptionurl": "http://s/swim",
                            "mime": "video/webm",
                            "width": 1920,
                            "height": 1080,
                            "extmetadata": {
                                "LicenseShortName": {"value": "CC BY-SA 4.0"},
                                "LicenseUrl": {"value": "http://l"},
                                "Artist": {"value": "<a href='x'>Vidder</a>"},
                            },
                        }
                    ],
                }
            }
        }
    }

    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())
    results = stock.search("swimming", kind="video")
    assert len(results) == 1
    v = results[0]
    assert v.kind == "video"
    assert v.direct_url.endswith(".webm")
    assert v.licence.commercial_ok is True
    assert v.licence.attribution == "Vidder"  # HTML stripped


# --------------------------------------------------------------------------- #
# first-party thumbnail proxy (CSP img-src 'self')
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "host,ok",
    [
        ("upload.wikimedia.org", True),
        ("commons.wikimedia.org", True),
        ("api.openverse.org", True),
        ("images.pexels.com", True),
        ("cdn.pixabay.com", True),
        ("pixabay.com", True),
        ("WIKIMEDIA.ORG", True),  # case-insensitive
        ("evil.com", False),
        ("wikimedia.org.evil.com", False),  # suffix-smuggle attempt
        ("notwikimedia.org", False),
        ("", False),
    ],
)
def test_is_proxy_host_allowlist(host, ok):
    assert stock.is_proxy_host(host) is ok


class _FakeThumbResp:
    def __init__(self, *, status=200, ctype="image/jpeg", body=b"\xff\xd8\xffjpg", location=None):
        self.status_code = status
        self.headers = {"Content-Type": ctype}
        if location:
            self.headers["Location"] = location
        self._body = body

    def iter_content(self, n):
        for i in range(0, len(self._body), n):
            yield self._body[i : i + n]

    def close(self):  # called on the retry path before backoff
        pass


def _allow_ssrf(monkeypatch, allowed=True):
    monkeypatch.setattr("mediahub.web_research.safe_fetch.is_url_safe", lambda u: allowed)


def test_fetch_thumb_happy_path(monkeypatch):
    _allow_ssrf(monkeypatch)
    monkeypatch.setattr("requests.get", lambda *a, **k: _FakeThumbResp(body=b"PNGDATA"))
    data, ctype = stock.fetch_thumb("https://upload.wikimedia.org/x.jpg")
    assert data == b"PNGDATA"
    assert ctype == "image/jpeg"


def test_fetch_thumb_allows_video_content(monkeypatch):
    _allow_ssrf(monkeypatch)
    monkeypatch.setattr(
        "requests.get", lambda *a, **k: _FakeThumbResp(ctype="video/webm", body=b"WEBM")
    )
    data, ctype = stock.fetch_thumb("https://upload.wikimedia.org/x.webm")
    assert data == b"WEBM" and ctype == "video/webm"


def test_fetch_thumb_rejects_offlist_host(monkeypatch):
    # Off-list host must be refused BEFORE any network call.
    monkeypatch.setattr("requests.get", lambda *a, **k: pytest.fail("must not fetch off-list host"))
    data, ctype = stock.fetch_thumb("https://evil.com/x.jpg")
    assert data is None and ctype == ""


def test_fetch_thumb_rejects_ssrf_host(monkeypatch):
    _allow_ssrf(monkeypatch, allowed=False)  # host resolves to a private IP
    monkeypatch.setattr("requests.get", lambda *a, **k: pytest.fail("must not fetch SSRF host"))
    data, ctype = stock.fetch_thumb("https://upload.wikimedia.org/x.jpg")
    assert data is None and ctype == ""


def test_fetch_thumb_rejects_non_media_content(monkeypatch):
    _allow_ssrf(monkeypatch)
    monkeypatch.setattr(
        "requests.get", lambda *a, **k: _FakeThumbResp(ctype="text/html", body=b"<html>")
    )
    data, ctype = stock.fetch_thumb("https://upload.wikimedia.org/x.jpg")
    assert data is None and ctype == ""


def test_fetch_thumb_rejects_bad_scheme():
    assert stock.fetch_thumb("ftp://upload.wikimedia.org/x.jpg") == (None, "")
    assert stock.fetch_thumb("") == (None, "")


def test_fetch_thumb_size_capped(monkeypatch):
    _allow_ssrf(monkeypatch)
    monkeypatch.setattr(stock, "_THUMB_MAX_BYTES", 8)
    monkeypatch.setattr("requests.get", lambda *a, **k: _FakeThumbResp(body=b"x" * 64))
    data, ctype = stock.fetch_thumb("https://upload.wikimedia.org/big.jpg")
    assert data is None and ctype == ""


def test_fetch_thumb_revalidates_host_on_redirect(monkeypatch):
    # A 302 from an allow-listed host onto an off-list host must be refused at
    # the next hop (the redirect can't smuggle the fetch off the allowlist).
    _allow_ssrf(monkeypatch)
    calls = {"n": 0}

    def _get(url, *a, **k):
        calls["n"] += 1
        return _FakeThumbResp(status=302, location="https://evil.com/x.jpg")

    monkeypatch.setattr("requests.get", _get)
    data, ctype = stock.fetch_thumb("https://upload.wikimedia.org/x.jpg")
    assert data is None and ctype == ""
    assert calls["n"] == 1  # stopped at the redirect target's host check


def test_fetch_thumb_serves_from_disk_cache(monkeypatch):
    """Second view of the same URL is served from the on-disk cache — no refetch.

    This is what keeps a busy gallery from re-hammering the source (and getting
    rate-limited) on every page load."""
    _allow_ssrf(monkeypatch)
    monkeypatch.setattr("requests.get", lambda *a, **k: _FakeThumbResp(body=b"CACHED"))
    u = "https://upload.wikimedia.org/cacheme.jpg"
    assert stock.fetch_thumb(u) == (b"CACHED", "image/jpeg")
    # A second call must hit the cache, never the network.
    monkeypatch.setattr("requests.get", lambda *a, **k: pytest.fail("should serve from cache"))
    assert stock.fetch_thumb(u) == (b"CACHED", "image/jpeg")


def test_fetch_thumb_retries_then_succeeds_on_429(monkeypatch):
    """A transient 429 (rate limit) is ridden out with a backoff retry."""
    _allow_ssrf(monkeypatch)
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)  # no real backoff in tests
    seq = [_FakeThumbResp(status=429), _FakeThumbResp(status=429), _FakeThumbResp(body=b"OK")]
    calls = {"n": 0}

    def _get(*a, **k):
        i = min(calls["n"], len(seq) - 1)
        calls["n"] += 1
        return seq[i]

    monkeypatch.setattr("requests.get", _get)
    data, ctype = stock.fetch_thumb("https://upload.wikimedia.org/retry.jpg")
    assert data == b"OK" and ctype == "image/jpeg"
    assert calls["n"] == 3  # two 429s, then the 200


def test_fetch_thumb_gives_up_after_persistent_429(monkeypatch):
    """Persistent 429 exhausts retries and degrades to a clean (None, '')."""
    _allow_ssrf(monkeypatch)
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)
    monkeypatch.setattr("requests.get", lambda *a, **k: _FakeThumbResp(status=429))
    assert stock.fetch_thumb("https://upload.wikimedia.org/always429.jpg") == (None, "")


# --------------------------------------------------------------------------- #
# request-path: cache-only serve + background warm (never blocks a worker thread)
# --------------------------------------------------------------------------- #
class _SyncPool:
    """A ThreadPoolExecutor stand-in that runs submitted work inline, so the
    background warmer is deterministic in tests."""

    def submit(self, fn, *a, **k):
        fn(*a, **k)
        return None


def test_serve_thumb_cache_hit(monkeypatch):
    """A cached tile is served without touching the network."""
    stock._thumb_cache_put(
        stock._thumb_cache_key("https://upload.wikimedia.org/c.jpg"), b"HIT", "image/jpeg"
    )
    monkeypatch.setattr("requests.get", lambda *a, **k: pytest.fail("cache hit must not fetch"))
    assert stock.serve_thumb("https://upload.wikimedia.org/c.jpg") == (b"HIT", "image/jpeg")


def test_serve_thumb_miss_warms_then_hits(monkeypatch):
    """A miss returns (None, '') and schedules a background warm; once warmed,
    a subsequent serve is a cache hit."""
    _allow_ssrf(monkeypatch)
    monkeypatch.setattr(stock, "_THUMB_WARM_POOL", _SyncPool())  # warm inline
    monkeypatch.setattr("requests.get", lambda *a, **k: _FakeThumbResp(body=b"WARMED"))
    u = "https://upload.wikimedia.org/warm.jpg"
    assert stock.serve_thumb(u) == (None, "")  # miss → schedules warm (run inline)
    # Warmer populated the cache, so the next serve is a hit (no network).
    monkeypatch.setattr("requests.get", lambda *a, **k: pytest.fail("should be cached now"))
    assert stock.serve_thumb(u) == (b"WARMED", "image/jpeg")


def test_serve_thumb_offlist_never_warms(monkeypatch):
    """An off-list host is refused and never scheduled for warming."""
    monkeypatch.setattr(
        stock, "_THUMB_WARM_POOL", _SyncPool()
    )  # would run inline if (wrongly) scheduled
    monkeypatch.setattr("requests.get", lambda *a, **k: pytest.fail("off-list host must not fetch"))
    assert stock.serve_thumb("https://evil.com/x.jpg") == (None, "")
    assert not stock._THUMB_WARMING


def test_prewarm_skips_cached_and_offlist(monkeypatch):
    """prewarm only schedules allow-listed, not-yet-cached URLs."""
    _allow_ssrf(monkeypatch)
    monkeypatch.setattr(stock, "_THUMB_WARM_POOL", _SyncPool())
    monkeypatch.setattr("requests.get", lambda *a, **k: _FakeThumbResp(body=b"X"))
    stock._thumb_cache_put(
        stock._thumb_cache_key("https://upload.wikimedia.org/already.jpg"), b"X", "image/jpeg"
    )
    scheduled = stock.prewarm_thumbs(
        [
            "https://upload.wikimedia.org/already.jpg",  # cached → skip
            "https://evil.com/x.jpg",  # off-list → skip
            "ftp://upload.wikimedia.org/x.jpg",  # bad scheme → skip
            "https://upload.wikimedia.org/new.jpg",  # eligible → 1
        ]
    )
    assert scheduled == 1


# --------------------------------------------------------------------------- #
# rights ledger (shared Licence vocabulary, persisted)
# --------------------------------------------------------------------------- #
def test_rights_ledger_roundtrip(tmp_path):
    ledger = StockRightsLedger(db_path=tmp_path / "data.db")
    rec = StockRightsRecord(
        asset_id="a1",
        profile_id="club-1",
        source="wikimedia",
        source_url="http://s/x",
        kind="photo",
        licence=Licence(name="CC BY 4.0", spdx="CC-BY-4.0", attribution="Jane", commercial_ok=True),
    )
    saved = ledger.record(rec)
    assert saved.imported_at  # stamped
    got = ledger.get("a1")
    assert got is not None
    assert got.licence.name == "CC BY 4.0"
    assert got.licence.attribution == "Jane"
    assert got.safe_for_commercial() is True


def test_rights_ledger_list_and_delete(tmp_path):
    ledger = StockRightsLedger(db_path=tmp_path / "data.db")
    for i in range(3):
        ledger.record(
            StockRightsRecord(
                asset_id=f"a{i}",
                profile_id="club-1",
                source="openverse",
                source_url="u",
                kind="photo",
                licence=Licence(name="CC0", commercial_ok=True),
            )
        )
    assert len(ledger.list_for_profile("club-1")) == 3
    assert ledger.delete("a0") is True
    assert len(ledger.list_for_profile("club-1")) == 2


def test_rights_ledger_shares_data_db_with_audio(tmp_path):
    """The stock_rights table lives in the same data.db as audio_rights."""
    import sqlite3

    db = tmp_path / "data.db"
    StockRightsLedger(db_path=db).record(
        StockRightsRecord(
            asset_id="a1",
            profile_id="p",
            source="wikimedia",
            source_url="u",
            kind="photo",
            licence=Licence(name="CC0", commercial_ok=True),
        )
    )
    conn = sqlite3.connect(str(db))
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    conn.close()
    assert "stock_rights" in tables


# --------------------------------------------------------------------------- #
# web routes
# --------------------------------------------------------------------------- #
@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)
    for var in ("PEXELS_API_KEY", "PIXABAY_API_KEY", "GEMINI_API_KEY", "ANTHROPIC_API_KEY"):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    # Point the media-library store singleton at tmp so the import lands there
    # (its default DB is package-local) — keeps the repo's data.db untouched.
    import mediahub.media_library.store as mls

    mls._default_store = mls.MediaLibraryStore(
        db_path=tmp_path / "data.db", uploads_dir=tmp_path / "uploads_v4" / "media_library"
    )
    app = wm.create_app()
    app.config["TESTING"] = True
    return app, wm, tmp_path


def _signin(client, profile_id="alpha", name="Alpha SC"):
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=profile_id, display_name=name))
    client.post("/api/organisation/active", data={"profile_id": profile_id})


def test_stock_search_route(app_env, monkeypatch):
    app, _wm, _ = app_env
    _patch_venue(monkeypatch, lambda q, limit=8, timeout=8: [_fake_venue_result("CC0")])
    with app.test_client() as c:
        resp = c.get("/api/stock/search?q=pool")
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["results"] and data["results"][0]["licence"]["commercial_ok"] is True
    assert data["sources"]["wikimedia"] is True


def test_stock_page_renders(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        resp = c.get("/stock")
    assert resp.status_code == 200
    assert b"Stock library" in resp.data
    assert b"sb-grid" in resp.data
    # Tiles must load through the first-party proxy (CSP img-src 'self'), not the
    # raw cross-origin CDN URL, and no longer embed a heavy cross-origin <video>.
    assert b"/api/stock/thumb" in resp.data
    assert b"proxyUrl" in resp.data
    assert b"<video" not in resp.data


def test_stock_thumb_route_serves_cache_hit(app_env, monkeypatch):
    app, _wm, _ = app_env
    monkeypatch.setattr(stock, "serve_thumb", lambda u: (b"IMG-BYTES", "image/png"))
    with app.test_client() as c:
        resp = c.get("/api/stock/thumb?u=https://upload.wikimedia.org/x.jpg")
    assert resp.status_code == 200
    assert resp.data == b"IMG-BYTES"
    assert resp.headers["Content-Type"].startswith("image/png")
    assert "max-age" in resp.headers.get("Cache-Control", "")


def test_stock_thumb_route_404_on_miss(app_env, monkeypatch):
    # Cache miss / refusal → 404 (the client retries while the warmer fills in).
    app, _wm, _ = app_env
    monkeypatch.setattr(stock, "serve_thumb", lambda u: (None, ""))
    with app.test_client() as c:
        resp = c.get("/api/stock/thumb?u=https://evil.com/x.jpg")
    assert resp.status_code == 404


def test_import_stock_creates_asset_and_rights(app_env, monkeypatch):
    app, _wm, tmp_path = app_env

    class _Resp:
        headers = {"Content-Type": "image/jpeg"}

        def raise_for_status(self):
            pass

        @property
        def raw(self):
            return self

        def read(self, n, decode_content=True):
            return b"\xff\xd8\xff" + b"0" * 100  # tiny fake jpeg

    monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())

    with app.test_client() as c:
        _signin(c)
        resp = c.post(
            "/api/media-library/import-stock",
            json={
                "direct_url": "https://example.org/x.jpg",
                "title": "Pool",
                "source_url": "https://example.org/file",
                "source_site": "wikimedia",
                "licence": "CC BY 4.0",
                "attribution": "Snapper",
            },
        )
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["ok"] is True
    asset_id = data["asset"]["id"]
    # rights recorded in the shared ledger
    rec = stock.StockRightsLedger(db_path=tmp_path / "data.db").get(asset_id)
    assert rec is not None
    assert rec.licence.attribution == "Snapper"
    assert rec.safe_for_commercial() is True


def test_import_stock_rejects_non_commercial(app_env, monkeypatch):
    app, _wm, _ = app_env
    monkeypatch.setattr("requests.get", lambda *a, **k: pytest.fail("must not download NC asset"))
    with app.test_client() as c:
        _signin(c)
        resp = c.post(
            "/api/media-library/import-stock",
            json={"direct_url": "https://example.org/x.jpg", "licence": "CC BY-NC 4.0"},
        )
    assert resp.status_code == 409
    assert resp.get_json()["error"] == "licence_not_clear"


def test_import_stock_requires_signin(app_env):
    app, _wm, _ = app_env
    with app.test_client() as c:
        resp = c.post(
            "/api/media-library/import-stock",
            json={"direct_url": "https://example.org/x.jpg", "licence": "CC0"},
        )
    assert resp.status_code == 403
