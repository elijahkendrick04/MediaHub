"""Venue-backdrop wiring + motion explainability read surface.

The venue_search package and the motion render manifests existed without a
consumer; these tests pin the routes that now tie them into the product:

  * GET  /api/runs/<id>/venue-search        — defaults q to the run's venue
  * POST /api/runs/<id>/venue-import        — saves a chosen result into the
                                              org's media library (licence +
                                              attribution preserved)
  * GET  /api/runs/<id>/card/<cid>/motion/manifest — the render's sidecar
"""

from __future__ import annotations

import json

import pytest

ORG = "org-venue"


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "runs_v4").mkdir(parents=True, exist_ok=True)
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    return tmp_path


@pytest.fixture
def app(env):
    import mediahub.web.web as wm
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id=ORG, display_name="Venue SC"))
    # The web module binds these at import time; point them at the isolated
    # tree the same way the other run-scoped route tests do.
    wm.RUNS_DIR = env / "runs_v4"
    wm.UPLOADS_DIR = env / "uploads_v4"
    application = wm.create_app()
    application.config["TESTING"] = True
    application.config["SECRET_KEY"] = "test-secret"
    return application


def _seed_run(env, run_id="runV", profile_id=ORG, venue="Ponds Forge"):
    runs = env / "runs_v4"
    (runs / f"{run_id}.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "profile_id": profile_id,
                "meet": {"name": "June Meet", "venue": venue},
                "recognition_report": {"ranked_achievements": []},
            }
        ),
        encoding="utf-8",
    )
    return run_id


def _with_org(client, org_id=ORG):
    with client.session_transaction() as sess:
        sess["active_profile_id"] = org_id


class TestVenueSearchRoute:
    def test_foreign_run_is_refused(self, app, env):
        run_id = _seed_run(env, profile_id="someone-else")
        with app.test_client() as client:
            _with_org(client)
            assert client.get(f"/api/runs/{run_id}/venue-search").status_code == 404

    def test_empty_query_defaults_to_run_venue(self, app, env, monkeypatch):
        run_id = _seed_run(env, venue="Ponds Forge")
        seen = {}

        def fake_search(q, limit=8):
            seen["q"] = q
            return []

        import mediahub.web.web as w

        monkeypatch.setattr(w, "_v8_search_venue", fake_search, raising=False)
        with app.test_client() as client:
            _with_org(client)
            body = client.get(f"/api/runs/{run_id}/venue-search").get_json()
        assert body["query"] == "Ponds Forge"
        assert seen["q"] == "Ponds Forge"

    def test_thumb_url_routed_through_proxy_direct_url_raw(self, app, env, monkeypatch):
        """Cross-origin previews go through the first-party proxy (CSP img-src
        'self') while direct_url stays raw for the server-side import."""
        from urllib.parse import parse_qs, urlparse

        run_id = _seed_run(env)

        def fake_search(q, limit=8):
            return [
                {
                    "title": "Pool",
                    "thumb_url": "https://upload.wikimedia.org/x/thumb.jpg",
                    "direct_url": "https://upload.wikimedia.org/x/full.jpg",
                    "licence": "CC BY-SA 4.0",
                    "attribution": "Snapper",
                }
            ]

        import mediahub.web.web as w

        monkeypatch.setattr(w, "_v8_search_venue", fake_search, raising=False)
        with app.test_client() as client:
            _with_org(client)
            body = client.get(f"/api/runs/{run_id}/venue-search?q=pool").get_json()
        r = body["results"][0]
        parsed = urlparse(r["thumb_url"])
        assert parsed.path == "/api/stock/thumb"
        assert parse_qs(parsed.query)["u"][0] == "https://upload.wikimedia.org/x/thumb.jpg"
        # The import still downloads the raw full-res URL server-side.
        assert r["direct_url"] == "https://upload.wikimedia.org/x/full.jpg"


class TestVenueImportRoute:
    def test_rejects_non_http_url(self, app, env):
        run_id = _seed_run(env)
        with app.test_client() as client:
            _with_org(client)
            resp = client.post(
                f"/api/runs/{run_id}/venue-import",
                json={"direct_url": "file:///etc/passwd"},
            )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "bad_image_url"

    def test_foreign_run_is_refused(self, app, env):
        run_id = _seed_run(env, profile_id="someone-else")
        with app.test_client() as client:
            _with_org(client)
            resp = client.post(
                f"/api/runs/{run_id}/venue-import",
                json={"direct_url": "https://example.org/pool.jpg"},
            )
        assert resp.status_code == 404

    def test_import_saves_asset_with_licence_and_attribution(self, app, env, monkeypatch):
        run_id = _seed_run(env)

        class FakeRaw:
            def read(self, n, decode_content=True):
                return b"\x89PNG fake-bytes"

        class FakeResp:
            status_code = 200
            headers = {"Content-Type": "image/png"}
            raw = FakeRaw()

            def raise_for_status(self):
                return None

            def close(self):
                return None

        import requests as real_requests

        import mediahub.web_research.safe_fetch as _sf

        monkeypatch.setattr(_sf, "is_url_safe", lambda u: True)
        monkeypatch.setattr(real_requests, "get", lambda *a, **k: FakeResp())
        with app.test_client() as client:
            _with_org(client)
            resp = client.post(
                f"/api/runs/{run_id}/venue-import",
                json={
                    "direct_url": "https://example.org/pool.png",
                    "title": "Ponds Forge International",
                    "licence": "CC BY-SA 4.0",
                    "attribution": "Photo: A. Photographer",
                    "source_url": "https://commons.wikimedia.org/wiki/File:PF.png",
                },
            )
        body = resp.get_json()
        assert resp.status_code == 200 and body["ok"] is True
        from mediahub.media_library.store import get_store

        asset_id = body["asset"]["id"]
        a = get_store().get(asset_id)
        assert a is not None
        assert a.type == "venue_photo"
        assert a.source_licence == "CC BY-SA 4.0"
        assert a.source_attribution == "Photo: A. Photographer"
        assert a.linked_venue == "Ponds Forge"

    def test_rejects_ssrf_metadata_url_without_fetching(self, app, env, monkeypatch):
        """A direct_url pointed at a private / metadata address is refused with
        400 and no file written — is_url_safe gates it before any fetch."""
        run_id = _seed_run(env)
        import mediahub.web_research.safe_fetch as _sf
        import requests as real_requests

        monkeypatch.setattr(_sf, "is_url_safe", lambda u: False)
        monkeypatch.setattr(
            real_requests, "get", lambda *a, **k: pytest.fail("must not fetch unsafe host")
        )
        with app.test_client() as client:
            _with_org(client)
            resp = client.post(
                f"/api/runs/{run_id}/venue-import",
                json={"direct_url": "http://169.254.169.254/latest/meta-data/"},
            )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "bad_image_url"

    def test_rejects_redirect_to_private_host(self, app, env, monkeypatch):
        """A public URL that 302-redirects to a private host is refused: each
        redirect hop is re-validated before it is followed."""
        run_id = _seed_run(env)
        import mediahub.web_research.safe_fetch as _sf
        import requests as real_requests

        # First hop safe, the redirect target private.
        monkeypatch.setattr(
            _sf, "is_url_safe", lambda u: "169.254" not in u and "internal" not in u
        )

        class RedirectResp:
            status_code = 302
            headers = {"Location": "http://169.254.169.254/"}

            def close(self):
                return None

        monkeypatch.setattr(real_requests, "get", lambda *a, **k: RedirectResp())
        with app.test_client() as client:
            _with_org(client)
            resp = client.post(
                f"/api/runs/{run_id}/venue-import",
                json={"direct_url": "https://cdn.example.org/pic.jpg"},
            )
        assert resp.status_code == 400
        assert resp.get_json()["error"] == "bad_image_url"


class TestMotionManifestRoute:
    def test_404_until_rendered_and_reads_sidecar(self, app, env):
        run_id = _seed_run(env)
        with app.test_client() as client:
            _with_org(client)
            url = f"/api/runs/{run_id}/card/c1/motion/manifest"
            assert client.get(url).status_code == 404
            sidecar_dir = env / "runs_v4" / run_id / "motion"
            sidecar_dir.mkdir(parents=True, exist_ok=True)
            (sidecar_dir / "c1.json").write_text(
                json.dumps({"kind": "story", "card": {"archetype": "stat-led"}}),
                encoding="utf-8",
            )
            body = client.get(url).get_json()
            assert body["card"]["archetype"] == "stat-led"

    def test_foreign_run_is_refused(self, app, env):
        run_id = _seed_run(env, profile_id="someone-else")
        with app.test_client() as client:
            _with_org(client)
            url = f"/api/runs/{run_id}/card/c1/motion/manifest"
            assert client.get(url).status_code == 404
