"""tests/test_logo_mirror.py — first-party logo mirror for the sign-in picker.

Root cause this pins: the app CSP sets ``img-src 'self'``, so a club's
website-detected logo (``ClubProfile.brand_logo_url`` — an EXTERNAL origin)
can never render inside our own pages. The browser blocks the cross-origin
<img> and the sign-in card shows a broken-image icon. That is the reported
"sometimes the logos don't load on the sign-in cards": orgs with an uploaded
logo (served first-party) worked; orgs that only had a detected website logo
did not.

The fix serves every on-card logo FIRST-PARTY: an uploaded logo via the
per-profile route, else the detected logo mirrored to our own origin
(``brand.logos.mirror_external_logo`` + the ``/organisation/<pid>/brand-logo``
route), else the org initials. An ``onerror`` handler swaps in the initials if
anything still fails, so a broken-image icon never reaches the user.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_PNG = b"\x89PNG\r\n\x1a\nfake-but-typed-as-png"


class _FakeResp:
    """Minimal stand-in for a streamed ``requests`` response."""

    def __init__(self, *, status_code=200, headers=None, chunks=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._chunks = chunks if chunks is not None else [_PNG]

    def iter_content(self, _n):
        for c in self._chunks:
            yield c


@pytest.fixture
def logos_mod(tmp_path, monkeypatch):
    """``brand.logos`` rebound to a temp DATA_DIR, with the SSRF gate open."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    import mediahub.brand.logos as logos
    importlib.reload(logos)
    # Open the SSRF gate (no real DNS in tests). Individual tests that need it
    # closed override this.
    import mediahub.web_research.safe_fetch as sf
    monkeypatch.setattr(sf, "is_url_safe", lambda _u: True)
    return logos, tmp_path


# ---------------------------------------------------------------------------
# mirror_external_logo — the SSRF-safe download/cache primitive
# ---------------------------------------------------------------------------


class TestMirrorExternalLogo:
    def test_downloads_and_caches(self, logos_mod, monkeypatch):
        logos, _ = logos_mod
        calls = {"n": 0}

        def fake_get(url, **kw):
            calls["n"] += 1
            return _FakeResp(headers={"Content-Type": "image/png"})

        import requests
        monkeypatch.setattr(requests, "get", fake_get)

        path = logos.mirror_external_logo("acme", "https://club.example/logo.png")
        assert path is not None
        assert path.exists()
        assert path.read_bytes() == _PNG
        assert path.suffix == ".png"
        assert calls["n"] == 1

        # Second call is a cache hit — no further network.
        again = logos.mirror_external_logo("acme", "https://club.example/logo.png")
        assert again == path
        assert calls["n"] == 1

    def test_rejects_non_image_content_type(self, logos_mod, monkeypatch):
        logos, _ = logos_mod
        import requests
        monkeypatch.setattr(
            requests, "get",
            lambda url, **kw: _FakeResp(headers={"Content-Type": "text/html"},
                                        chunks=[b"<html>nope</html>"]),
        )
        # An error page served at the logo URL must NOT be cached as a logo.
        assert logos.mirror_external_logo("acme", "https://club.example/oops") is None

    def test_blocked_by_ssrf_guard(self, logos_mod, monkeypatch):
        logos, _ = logos_mod
        import mediahub.web_research.safe_fetch as sf
        monkeypatch.setattr(sf, "is_url_safe", lambda _u: False)

        def boom(*a, **k):  # must never be reached
            raise AssertionError("network attempted despite SSRF block")

        import requests
        monkeypatch.setattr(requests, "get", boom)
        assert logos.mirror_external_logo("acme", "http://169.254.169.254/x.png") is None

    def test_rejects_non_http_scheme(self, logos_mod):
        logos, _ = logos_mod
        assert logos.mirror_external_logo("acme", "file:///etc/passwd") is None
        assert logos.mirror_external_logo("acme", "ftp://h/x.png") is None
        assert logos.mirror_external_logo("acme", "") is None

    def test_size_cap(self, logos_mod, monkeypatch):
        logos, _ = logos_mod
        monkeypatch.setattr(logos, "_MIRROR_MAX_BYTES", 16)
        import requests
        monkeypatch.setattr(
            requests, "get",
            lambda url, **kw: _FakeResp(headers={"Content-Type": "image/png"},
                                        chunks=[b"x" * 64]),
        )
        assert logos.mirror_external_logo("acme", "https://club.example/huge.png") is None

    def test_follows_redirect_and_revalidates(self, logos_mod, monkeypatch):
        logos, _ = logos_mod

        def fake_get(url, **kw):
            if url.endswith("/start.png"):
                return _FakeResp(status_code=302,
                                 headers={"Location": "https://cdn.example/real.png"})
            return _FakeResp(headers={"Content-Type": "image/png"})

        import requests
        monkeypatch.setattr(requests, "get", fake_get)
        path = logos.mirror_external_logo("acme", "https://club.example/start.png")
        assert path is not None and path.exists()

    def test_content_type_uses_url_ext_when_header_missing(self, logos_mod, monkeypatch):
        logos, _ = logos_mod
        import requests
        # No usable Content-Type header — fall back to the URL path extension.
        monkeypatch.setattr(
            requests, "get",
            lambda url, **kw: _FakeResp(headers={"Content-Type": ""}),
        )
        path = logos.mirror_external_logo("acme", "https://club.example/crest.webp")
        assert path is not None
        assert path.suffix == ".webp"

    def test_failed_fetch_is_negative_cached(self, logos_mod, monkeypatch):
        logos, tmp_path = logos_mod
        calls = {"n": 0}

        def fake_get(url, **kw):
            calls["n"] += 1
            return _FakeResp(status_code=404)

        import requests
        monkeypatch.setattr(requests, "get", fake_get)

        assert logos.mirror_external_logo("acme", "https://club.example/dead.png") is None
        assert calls["n"] == 1
        # A miss marker was written next to where the logo would live.
        misses = list((tmp_path / "club_logo_cache" / "acme").glob("*.miss"))
        assert len(misses) == 1
        # Second call inside the TTL: no network attempt.
        assert logos.mirror_external_logo("acme", "https://club.example/dead.png") is None
        assert calls["n"] == 1

    def test_miss_marker_expires_and_refetches(self, logos_mod, monkeypatch):
        logos, tmp_path = logos_mod
        import os
        import requests
        monkeypatch.setattr(requests, "get",
                            lambda url, **kw: _FakeResp(status_code=503))
        assert logos.mirror_external_logo("acme", "https://club.example/flaky.png") is None
        (miss,) = (tmp_path / "club_logo_cache" / "acme").glob("*.miss")
        # Age the marker past the TTL — the next call retries the fetch.
        old = miss.stat().st_mtime - logos._MIRROR_MISS_TTL - 10
        os.utime(miss, (old, old))
        monkeypatch.setattr(
            requests, "get",
            lambda url, **kw: _FakeResp(headers={"Content-Type": "image/png"}),
        )
        path = logos.mirror_external_logo("acme", "https://club.example/flaky.png")
        assert path is not None and path.exists()
        assert not miss.exists()

    def test_mirror_content_type_maps_extension(self, logos_mod):
        logos, _ = logos_mod
        assert logos.mirror_content_type(Path("a/b.png")) == "image/png"
        assert logos.mirror_content_type(Path("a/b.jpg")) == "image/jpeg"
        assert logos.mirror_content_type(Path("a/b.webp")) == "image/webp"


# ---------------------------------------------------------------------------
# Web surface — the route and the sign-in picker
# ---------------------------------------------------------------------------


@pytest.fixture
def app_client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm
    importlib.reload(cp)
    importlib.reload(wm)
    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c, wm, cp, tmp_path


def _seed(cp, **kw):
    from mediahub.web.club_profile import ClubProfile, save_profile
    prof = ClubProfile(**kw)
    save_profile(prof)
    return prof


class TestBrandLogoRoute:
    def test_404_when_profile_has_no_detected_url(self, app_client):
        client, _, cp, _ = app_client
        _seed(cp, profile_id="nourl", display_name="No URL Club")
        assert client.get("/organisation/nourl/brand-logo").status_code == 404

    def test_404_for_unknown_profile(self, app_client):
        client, _, _, _ = app_client
        assert client.get("/organisation/ghost/brand-logo").status_code == 404

    def test_serves_mirrored_bytes_first_party(self, app_client, monkeypatch):
        client, wm, cp, tmp_path = app_client
        _seed(cp, profile_id="acme", display_name="Acme SC",
              brand_logo_url="https://club.example/logo.png")

        # Stand in for the network: drop a real cached file and hand its path
        # back, exactly as a successful mirror would.
        cached = tmp_path / "club_logo_cache" / "acme" / "deadbeef.png"
        cached.parent.mkdir(parents=True, exist_ok=True)
        cached.write_bytes(_PNG)
        import mediahub.brand.logos as logos
        monkeypatch.setattr(logos, "mirror_external_logo", lambda pid, url: cached)

        resp = client.get("/organisation/acme/brand-logo")
        assert resp.status_code == 200
        assert resp.data == _PNG
        assert resp.headers["Content-Type"] == "image/png"
        assert "max-age" in resp.headers.get("Cache-Control", "")

    def test_404_when_mirror_fails(self, app_client, monkeypatch):
        client, _, cp, _ = app_client
        _seed(cp, profile_id="dead", display_name="Dead Logo Club",
              brand_logo_url="https://club.example/gone.png")
        import mediahub.brand.logos as logos
        monkeypatch.setattr(logos, "mirror_external_logo", lambda pid, url: None)
        assert client.get("/organisation/dead/brand-logo").status_code == 404


class TestSignInPickerLogo:
    def test_detected_logo_uses_mirror_route_not_external_url(self, app_client):
        client, _, cp, _ = app_client
        _seed(cp, profile_id="ext", display_name="External Logo Club",
              brand_logo_url="https://club.example/badge.png")
        body = client.get("/sign-in").get_data(as_text=True)
        # First-party mirror src (the KEYED ?bg=1&chip=1 silhouette), never the raw
        # cross-origin URL (CSP would block it). The unified chip carries a built-in
        # initials span and wires its own onerror→initials net.
        assert "/organisation/ext/brand-logo" in body
        assert "https://club.example/badge.png" not in body
        assert "mh-logo-chip__initials" in body  # the rendered initials span
        assert "classList.add('is-empty')" in body  # the chip onerror handler

    def test_no_logo_renders_initials_no_broken_img(self, app_client):
        client, _, cp, _ = app_client
        _seed(cp, profile_id="solo", display_name="Solo Swim Club")
        body = client.get("/sign-in").get_data(as_text=True)
        # No logo of any kind → no logo route is emitted, and the tile shows a clean
        # org-initials chip (the unified component's fallback) — never a broken img.
        assert "/organisation/solo/brand-logo" not in body
        assert "mh-logo-chip__initials" in body
        assert ">SC<" in body  # Solo Swim Club → "SC"
        assert "Solo Swim Club" in body
