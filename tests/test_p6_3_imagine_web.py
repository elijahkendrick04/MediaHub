"""P6.3 — web routes: gating, tenancy, generate, subject-lift, honest errors.

Mocks the Imagen client so nothing hits the network; uses a tmp media store +
tmp ledger DB so each test is isolated.
"""

from __future__ import annotations

import importlib
import io

import pytest


def _png_bytes(color=(10, 20, 30)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    for d in ("uploads_v4", "club_profiles", "runs_v4"):
        (tmp_path / d).mkdir(parents=True, exist_ok=True)
    # Clear keys/quota for a known baseline.
    for var in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "MEDIAHUB_IMAGINE_PROVIDER",
        "MEDIAHUB_IMAGINE_QUOTA_MONTHLY",
        "MEDIAHUB_IMAGINE_LOCAL_ENDPOINT",
        "MEDIAHUB_IMAGINE_LOCAL_TOKEN",
        "MEDIAHUB_IMAGINE_LOCAL_CAPABILITIES",
    ):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.secrets_store as ss
    import mediahub.observability.imagine_usage as iu
    import mediahub.media_library.store as st

    importlib.reload(ss)
    importlib.reload(iu)
    # Isolated tmp store sharing the same data.db the ledger uses.
    st._default_store = st.MediaLibraryStore(
        db_path=tmp_path / "data.db",
        uploads_dir=tmp_path / "uploads_v4" / "media_library",
    )

    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-x", display_name="Club X"))
    save_profile(ClubProfile(profile_id="club-y", display_name="Club Y"))

    app = wm.create_app()
    app.config["TESTING"] = True
    if not app.secret_key:
        app.secret_key = "test-secret"
    return app, wm, tmp_path, iu, st


def _client(app, profile_id="club-x"):
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = profile_id
    return c


def _seed_asset(st, tmp_path, profile_id="club-x"):
    from mediahub.media_library.models import MediaAsset

    p = tmp_path / "uploads_v4" / "media_library" / profile_id / "seed.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_png_bytes())
    return st.get_store().save(
        MediaAsset(
            id="", filename="seed.png", path=str(p), type="athlete_action", profile_id=profile_id
        )
    )


# --- info -------------------------------------------------------------------


def test_info_requires_profile(app_env):
    app, wm, *_ = app_env
    c = app.test_client()  # no session pin
    r = c.get("/api/media-library/imagine/info")
    assert r.status_code == 403


def test_info_honest_when_no_provider(app_env):
    app, wm, tmp_path, iu, st = app_env
    c = _client(app)
    r = c.get("/api/media-library/imagine/info")
    assert r.status_code == 200
    j = r.get_json()
    assert j["available"] is False
    assert j["operations"] == ["subject_lift"]
    assert j["quota"]["limit"] == 100


def test_routes_gated_by_flag(app_env, monkeypatch):
    app, wm, *_ = app_env
    monkeypatch.setattr(wm, "_imagine_ok", False)
    c = _client(app)
    r = c.get("/api/media-library/imagine/info")
    assert r.status_code == 503


# --- generate ---------------------------------------------------------------


def test_generate_empty_prompt_400(app_env, monkeypatch):
    app, wm, *_ = app_env
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    c = _client(app)
    r = c.post("/api/media-library/imagine/generate", json={"prompt": "  "})
    assert r.status_code == 400
    assert r.get_json()["error"] == "empty_prompt"


def test_generate_no_provider_503(app_env):
    app, wm, *_ = app_env
    c = _client(app)
    r = c.post("/api/media-library/imagine/generate", json={"prompt": "a backdrop"})
    assert r.status_code == 503
    assert r.get_json()["error"] == "provider_not_configured"


def test_generate_success_creates_stamped_asset(app_env, monkeypatch):
    app, wm, tmp_path, iu, st = app_env
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    import mediahub.media_ai.imagine_providers.gemini_imagine as g

    png = _png_bytes((200, 150, 50))
    monkeypatch.setattr(g, "imagen_predict", lambda *a, **k: [png])

    c = _client(app)
    r = c.post(
        "/api/media-library/imagine/generate",
        json={"prompt": "navy and gold poolside backdrop", "style": "abstract", "aspect": "9:16"},
    )
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert j["ok"] is True
    asset = j["asset"]
    assert asset["type"] == "ai_generated"
    assert asset["profile_id"] == "club-x"
    assert "ai-generated" in asset["tags"]
    # Quota counter advanced.
    assert j["quota"]["used"] == 1
    assert iu.count_for_org("club-x") == 1

    # Provenance: the stored file carries the IPTC AI term + a sidecar manifest.
    from pathlib import Path
    from mediahub.graphic_renderer import metadata_embed as me

    stored = Path(st.get_store().get(asset["id"]).path)
    assert stored.exists()
    assert "trainedAlgorithmicMedia" in me.read_metadata(stored).digital_source_type
    sidecar = stored.with_suffix(stored.suffix + ".imagine.json")
    assert sidecar.exists()
    # The manifest is also persisted on the asset record.
    assert asset["description_parsed"]["imagine"]["operation"] == "generate"


def test_generate_quota_exceeded_429(app_env, monkeypatch):
    app, wm, tmp_path, iu, st = app_env
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("MEDIAHUB_IMAGINE_QUOTA_MONTHLY", "0")
    c = _client(app)
    r = c.post("/api/media-library/imagine/generate", json={"prompt": "x"})
    assert r.status_code == 429
    assert r.get_json()["error"] == "quota_exceeded"


def test_operator_bypasses_imagine_quota(app_env, monkeypatch):
    """The signed-in developer/operator has no AI quotas: even a zero imagery
    limit doesn't block, and their generations aren't metered against the org."""
    app, wm, tmp_path, iu, st = app_env
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    monkeypatch.setenv("MEDIAHUB_IMAGINE_QUOTA_MONTHLY", "0")  # would block any normal user
    import mediahub.media_ai.imagine_providers.gemini_imagine as g
    from mediahub.web import auth

    monkeypatch.setattr(g, "imagen_predict", lambda *a, **k: [_png_bytes()])
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = "club-x"
        s[auth._DEV_SESSION_KEY] = True  # operator session
    r = c.post("/api/media-library/imagine/generate", json={"prompt": "x"})
    assert r.status_code == 200, r.get_json()
    # Operator generation is not charged to the club's imagery ledger.
    assert iu.count_for_org("club-x") == 0


def test_generate_isolates_orgs(app_env, monkeypatch):
    app, wm, tmp_path, iu, st = app_env
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    import mediahub.media_ai.imagine_providers.gemini_imagine as g

    monkeypatch.setattr(g, "imagen_predict", lambda *a, **k: [_png_bytes()])
    _client(app, "club-x").post("/api/media-library/imagine/generate", json={"prompt": "x"})
    assert iu.count_for_org("club-x") == 1
    assert iu.count_for_org("club-y") == 0


# --- subject lift -----------------------------------------------------------


def test_subject_lift_not_found(app_env):
    app, wm, *_ = app_env
    c = _client(app)
    r = c.post("/api/media-library/nope/imagine/subject-lift", json={})
    assert r.status_code == 404


def test_subject_lift_forbidden_cross_org(app_env):
    app, wm, tmp_path, iu, st = app_env
    a = _seed_asset(st, tmp_path, profile_id="club-y")
    c = _client(app, "club-x")  # pinned to a different org
    r = c.post(f"/api/media-library/{a.id}/imagine/subject-lift", json={})
    assert r.status_code == 403


def test_subject_lift_success(app_env, monkeypatch):
    app, wm, tmp_path, iu, st = app_env
    a = _seed_asset(st, tmp_path, profile_id="club-x")

    # Stub the cutout helper + saliency so no model runs.
    def fake_ensure(asset):
        from pathlib import Path

        out = Path(asset.path).with_name("cut.png")
        import os

        from PIL import Image

        Image.frombytes("RGBA", (128, 128), os.urandom(128 * 128 * 4)).save(out)
        return out, "generated"

    monkeypatch.setattr(wm, "_v8_ensure_cutout", fake_ensure)
    import mediahub.graphic_renderer.saliency as sal

    monkeypatch.setattr(sal, "focus_position", lambda p, ratio="4:5": "50% 30%")

    c = _client(app, "club-x")
    r = c.post(f"/api/media-library/{a.id}/imagine/subject-lift", json={"ratio": "9:16"})
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert j["ok"] is True
    assert j["focus_position"] == "50% 30%"


# --- edit-family honest errors ---------------------------------------------


def test_unknown_op_404(app_env, monkeypatch):
    app, wm, tmp_path, iu, st = app_env
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    a = _seed_asset(st, tmp_path)
    c = _client(app)
    r = c.post(f"/api/media-library/{a.id}/imagine/frobnicate", json={})
    assert r.status_code == 404
    assert r.get_json()["error"] == "unknown_op"


def test_edit_unsupported_501(app_env, monkeypatch):
    app, wm, tmp_path, iu, st = app_env
    monkeypatch.setenv("GEMINI_API_KEY", "k")  # gemini available but can't edit
    a = _seed_asset(st, tmp_path)
    c = _client(app)
    r = c.post(f"/api/media-library/{a.id}/imagine/edit", json={"instruction": "x"})
    assert r.status_code == 501
    assert r.get_json()["error"] == "unsupported"


def test_remove_no_provider_503(app_env):
    app, wm, tmp_path, iu, st = app_env
    a = _seed_asset(st, tmp_path)
    c = _client(app)
    r = c.post(f"/api/media-library/{a.id}/imagine/remove", json={})
    assert r.status_code == 503


# --- edit family lit up by the in-house local backend (roadmap 1.1) ---------


def _fake_local_post(monkeypatch, png):
    """Patch requests.post so the local diffusion endpoint returns ``png``."""
    import base64

    import requests

    class _R:
        status_code = 200
        headers = {"Content-Type": "application/json"}
        text = ""

        @staticmethod
        def json():
            return {"images": [base64.b64encode(png).decode()]}

    monkeypatch.setattr(requests, "post", lambda *a, **k: _R())


def test_info_reflects_local_backend(app_env, monkeypatch):
    app, wm, *_ = app_env
    monkeypatch.setenv("MEDIAHUB_IMAGINE_LOCAL_ENDPOINT", "http://imagine:8800")
    c = _client(app)
    j = c.get("/api/media-library/imagine/info").get_json()
    assert j["available"] is True
    assert j["provider"] == "local"
    for op in ("generate", "edit", "expand", "remove", "style_match"):
        assert op in j["operations"]


def test_edit_via_local_creates_composite_asset(app_env, monkeypatch):
    app, wm, tmp_path, iu, st = app_env
    monkeypatch.setenv("MEDIAHUB_IMAGINE_LOCAL_ENDPOINT", "http://imagine:8800")
    a = _seed_asset(st, tmp_path)
    _fake_local_post(monkeypatch, _png_bytes((120, 90, 30)))
    c = _client(app)
    r = c.post(
        f"/api/media-library/{a.id}/imagine/edit",
        json={"instruction": "add a lane rope"},
    )
    assert r.status_code == 200, r.get_json()
    asset = r.get_json()["asset"]
    assert asset["type"] == "ai_generated"
    imagine = asset["description_parsed"]["imagine"]
    assert imagine["operation"] == "edit"
    assert imagine["provider"] == "local"
    assert imagine["model"] == "flux.1-schnell"
    # Composite provenance (a real photo with AI-edited pixels) on the file.
    from pathlib import Path

    from mediahub.graphic_renderer import metadata_embed as me

    stored = Path(st.get_store().get(asset["id"]).path)
    assert "compositeWithTrainedAlgorithmicMedia" in me.read_metadata(stored).digital_source_type
    assert iu.count_for_org("club-x") == 1


def test_remove_via_local(app_env, monkeypatch):
    app, wm, tmp_path, iu, st = app_env
    monkeypatch.setenv("MEDIAHUB_IMAGINE_LOCAL_ENDPOINT", "http://imagine:8800")
    a = _seed_asset(st, tmp_path)
    _fake_local_post(monkeypatch, _png_bytes((7, 7, 7)))
    c = _client(app)
    r = c.post(f"/api/media-library/{a.id}/imagine/remove", json={})
    assert r.status_code == 200, r.get_json()
    assert r.get_json()["asset"]["description_parsed"]["imagine"]["operation"] == "remove"


def test_generate_via_local_no_cloud_key(app_env, monkeypatch):
    """The headline of 1.1: generation runs with no cloud key configured."""
    app, wm, tmp_path, iu, st = app_env
    monkeypatch.setenv("MEDIAHUB_IMAGINE_LOCAL_ENDPOINT", "http://imagine:8800")
    _fake_local_post(monkeypatch, _png_bytes((50, 100, 150)))
    c = _client(app)
    r = c.post(
        "/api/media-library/imagine/generate",
        json={"prompt": "navy and gold poolside backdrop", "aspect": "9:16"},
    )
    assert r.status_code == 200, r.get_json()
    asset = r.get_json()["asset"]
    assert asset["description_parsed"]["imagine"]["provider"] == "local"
    assert iu.count_for_org("club-x") == 1
