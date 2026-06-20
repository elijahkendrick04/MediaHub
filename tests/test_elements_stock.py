"""Roadmap 1.10 build 3 — licence-clean stock pool + shared rights ledger."""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace

import pytest

from mediahub.elements import stock
from mediahub.elements.stock import Licence, StockRightsLedger, StockRightsRecord


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
    lic = stock.parse_licence("CC BY-SA 4.0", url="http://x", attribution="Jane", source="wikimedia")
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
    _patch_venue(
        monkeypatch, lambda q, limit=8, timeout=8: [_fake_venue_result("CC BY-NC 4.0")]
    )
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
