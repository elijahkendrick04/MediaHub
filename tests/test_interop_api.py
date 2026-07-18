"""1.21 interop — API endpoints (palette / bundle / SVG / PSD) + oEmbed."""

from __future__ import annotations

import pytest


@pytest.fixture
def world(web_module, monkeypatch):
    # MEDIAHUB_SCHEDULER is read fresh inside create_app() (scheduler._enabled()),
    # not at web.py import time, so it just needs to land before create_app() runs.
    monkeypatch.setenv("MEDIAHUB_SCHEDULER", "0")

    from mediahub.api_public import _db as api_db

    api_db._initialized.clear()

    from mediahub.web.club_profile import ClubProfile, load_profile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-a",
            display_name="Org A SC",
            public_wall_enabled=True,
            public_wall_token="walltoken123abc",
        )
    )
    save_profile(ClubProfile(profile_id="org-b", display_name="Org B SC"))

    app = web_module.create_app()
    app.config["TESTING"] = True

    from mediahub.api_public.tokens import ApiTokenStore
    from mediahub.brand import kits as K

    kid = K.default_kit_id(load_profile("org-a"))

    class W:
        client = app.test_client()
        kit_id = kid

        @staticmethod
        def token(scopes, org="org-a"):
            _t, secret = ApiTokenStore().create(org, scopes=list(scopes), created_by="o@x.com")
            return {"Authorization": f"Bearer {secret}"}

    return W()


def test_palette_export_formats(world):
    h = world.token(["brand:read"])
    for fmt, sig in (("ase", b"ASEF"), ("gpl", b"GIMP"), ("json", b"{")):
        r = world.client.get(f"/api/v1/brand-kits/{world.kit_id}/palette?format={fmt}", headers=h)
        assert r.status_code == 200, fmt
        assert r.data[:4].startswith(sig[:1]) or r.data[:4] == sig
        assert "attachment" in r.headers.get("Content-Disposition", "")


def test_palette_export_bad_format(world):
    h = world.token(["brand:read"])
    r = world.client.get(f"/api/v1/brand-kits/{world.kit_id}/palette?format=psd", headers=h)
    assert r.status_code == 400


def test_brand_bundle_is_zip(world):
    h = world.token(["brand:read"])
    r = world.client.get(f"/api/v1/brand-kits/{world.kit_id}/bundle", headers=h)
    assert r.status_code == 200 and r.data[:2] == b"PK"


def test_palette_requires_brand_scope(world):
    h = world.token(["runs:read"])
    r = world.client.get(f"/api/v1/brand-kits/{world.kit_id}/palette", headers=h)
    assert r.status_code == 403


def test_unknown_kit_is_404(world):
    h = world.token(["brand:read"])
    r = world.client.get("/api/v1/brand-kits/does-not-exist/palette", headers=h)
    assert r.status_code == 404


def test_svg_import_sanitises_and_stores(world):
    h = world.token(["media:write"])
    dirty = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="12" height="8">'
        '<script>alert(1)</script><rect width="3" height="3"/></svg>'
    ).encode()
    r = world.client.post(
        "/api/v1/media/import-svg?filename=logo.svg",
        headers=h,
        data=dirty,
        content_type="image/svg+xml",
    )
    assert r.status_code == 201
    body = r.get_json()
    assert body["sanitized"] is True and body["width"] == 12


def test_svg_import_rejects_non_svg(world):
    h = world.token(["media:write"])
    r = world.client.post("/api/v1/media/import-svg", headers=h, data=b"<html></html>")
    assert r.status_code == 400


def test_svg_import_requires_media_write(world):
    h = world.token(["brand:read"])
    r = world.client.post("/api/v1/media/import-svg", headers=h, data=b"<svg/>")
    assert r.status_code == 403


def test_psd_import_honest_503_without_backend(world):
    from mediahub.interop import psd_import

    if psd_import.available():
        pytest.skip("psd-tools installed")
    h = world.token(["media:write"])
    r = world.client.post("/api/v1/media/import-psd", headers=h, data=b"8BPS junk")
    assert r.status_code == 503
    assert r.get_json()["error"] == "unavailable"


# --- oEmbed ----------------------------------------------------------------
def test_oembed_returns_iframe_for_enabled_wall(world):
    r = world.client.get("/oembed?url=http://localhost/wall/walltoken123abc&format=json")
    assert r.status_code == 200
    body = r.get_json()
    assert body["type"] == "rich" and body["provider_name"] == "MediaHub"
    assert "<iframe" in body["html"] and "/wall/walltoken123abc/embed" in body["html"]


def test_oembed_unknown_wall_is_404(world):
    r = world.client.get("/oembed?url=http://localhost/wall/nope&format=json")
    assert r.status_code == 404


def test_oembed_bad_url_is_404(world):
    r = world.client.get("/oembed?url=not-a-wall-url")
    assert r.status_code == 404


def test_oembed_xml_not_implemented(world):
    r = world.client.get("/oembed?url=http://localhost/wall/walltoken123abc&format=xml")
    assert r.status_code == 501
