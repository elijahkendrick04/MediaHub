"""P6.3 Build 2 — web routes: grab-text, mockups, generated-images history."""

from __future__ import annotations

import importlib
import io

import pytest


def _png_bytes(color=(20, 60, 120), size=(400, 500)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def app_env(web_module, tmp_path, monkeypatch):
    for var in (
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "ANTHROPIC_API_KEY",
        "MEDIAHUB_IMAGINE_PROVIDER",
        "MEDIAHUB_IMAGINE_QUOTA_MONTHLY",
    ):
        monkeypatch.delenv(var, raising=False)

    import mediahub.web.secrets_store as ss
    import mediahub.observability.imagine_usage as iu
    import mediahub.media_library.store as st

    importlib.reload(ss)
    importlib.reload(iu)
    st._default_store = st.MediaLibraryStore(
        db_path=tmp_path / "data.db",
        uploads_dir=tmp_path / "uploads_v4" / "media_library",
    )

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-x", display_name="Club X"))
    save_profile(ClubProfile(profile_id="club-y", display_name="Club Y"))

    wm = web_module
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


def _seed(st, tmp_path, profile_id="club-x", **kw):
    from mediahub.media_library.models import MediaAsset

    p = tmp_path / "uploads_v4" / "media_library" / profile_id / "seed.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_png_bytes())
    fields = dict(
        id="", filename="seed.png", path=str(p), type="athlete_action", profile_id=profile_id
    )
    fields.update(kw)
    return st.get_store().save(MediaAsset(**fields))


# --- grab-text --------------------------------------------------------------


def test_grab_text_no_provider_503(app_env):
    app, wm, tmp_path, iu, st = app_env
    a = _seed(st, tmp_path)
    r = _client(app).post(f"/api/media-library/{a.id}/imagine/grab-text", json={})
    assert r.status_code == 503
    assert r.get_json()["error"] == "provider_not_configured"


def test_grab_text_success(app_env, monkeypatch):
    app, wm, tmp_path, iu, st = app_env
    a = _seed(st, tmp_path)
    import mediahub.media_ai.llm as llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    monkeypatch.setattr(llm, "generate_vision", lambda paths, prompt, **k: "GOLD\n100m Fly")
    r = _client(app).post(f"/api/media-library/{a.id}/imagine/grab-text", json={})
    assert r.status_code == 200, r.get_json()
    j = r.get_json()
    assert j["found"] is True
    assert j["blocks"] == ["GOLD", "100m Fly"]


def test_grab_text_cross_org_forbidden(app_env, monkeypatch):
    app, wm, tmp_path, iu, st = app_env
    a = _seed(st, tmp_path, profile_id="club-y")
    import mediahub.media_ai.llm as llm

    monkeypatch.setattr(llm, "is_available", lambda: True)
    r = _client(app, "club-x").post(f"/api/media-library/{a.id}/imagine/grab-text", json={})
    assert r.status_code == 403


# --- mockups ----------------------------------------------------------------


def test_mockup_serves_png(app_env):
    app, wm, tmp_path, iu, st = app_env
    a = _seed(st, tmp_path)
    r = _client(app).post(f"/api/media-library/{a.id}/mockup/poster_wall")
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "image/png"
    assert len(r.data) > 1000


def test_mockup_unknown_template_404(app_env):
    app, wm, tmp_path, iu, st = app_env
    a = _seed(st, tmp_path)
    r = _client(app).post(f"/api/media-library/{a.id}/mockup/nope")
    assert r.status_code == 404
    assert r.get_json()["error"] == "unknown_template"


def test_mockup_cross_org_forbidden(app_env):
    app, wm, tmp_path, iu, st = app_env
    a = _seed(st, tmp_path, profile_id="club-y")
    r = _client(app, "club-x").post(f"/api/media-library/{a.id}/mockup/poster_wall")
    assert r.status_code == 403


def test_mockup_templates_list(app_env):
    app, wm, *_ = app_env
    r = _client(app).get("/api/media-library/mockup-templates")
    assert r.status_code == 200
    ids = {t["id"] for t in r.get_json()["templates"]}
    assert "poster_wall" in ids and "phone_post" in ids


def test_mockup_uses_profile_brand_accent(app_env, monkeypatch):
    """_profile_accent_hex must read the RESOLVED brand kit (manual palette
    included) — the raw brand_kit dict uses ``*_colour`` keys, so the old
    direct ``accent``/``primary`` read missed every profile and mockups were
    never brand-tinted."""
    app, wm, tmp_path, iu, st = app_env
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="club-x",
            display_name="Club X",
            brand_palette_manual={
                "primary": "#0A2540",
                "secondary": "#111111",
                "accent": "#C9A227",
            },
        )
    )
    a = _seed(st, tmp_path)
    seen = {}
    import mediahub.mockups as mk

    real = mk.compose_mockup

    def spy(art, template, accent=None, **kw):
        seen["accent"] = accent
        return real(art, template, accent=accent, **kw)

    monkeypatch.setattr(mk, "compose_mockup", spy)
    r = _client(app).post(f"/api/media-library/{a.id}/mockup/poster_wall")
    assert r.status_code == 200
    # Palette normalisation lowercases hexes — compare case-insensitively.
    assert (seen["accent"] or "").lower() == "#c9a227"


# --- generated-images history ----------------------------------------------


def test_generated_page_empty(app_env):
    app, wm, tmp_path, iu, st = app_env
    r = _client(app).get("/media-library/generated")
    assert r.status_code == 200
    assert b"No AI-generated images yet" in r.data


def test_generated_page_lists_with_provenance(app_env):
    app, wm, tmp_path, iu, st = app_env
    _seed(
        st,
        tmp_path,
        type="ai_generated",
        description_raw="navy poolside backdrop",
        description_parsed={
            "imagine": {
                "operation": "generate",
                "model": "imagen-4.0",
                "prompt": "navy poolside backdrop",
                "digital_source_type": "ai_generated",
                "created_at": "2026-06-18T12:00:00+00:00",
            }
        },
    )
    r = _client(app).get("/media-library/generated")
    assert r.status_code == 200
    body = r.data
    assert b"navy poolside backdrop" in body
    assert b"AI-generated" in body
    assert b"imagen-4.0" in body


def test_generated_page_org_scoped(app_env):
    app, wm, tmp_path, iu, st = app_env
    # An asset for another org must not appear.
    _seed(
        st,
        tmp_path,
        profile_id="club-y",
        type="ai_generated",
        description_raw="secret other-club image",
    )
    r = _client(app, "club-x").get("/media-library/generated")
    assert r.status_code == 200
    assert b"secret other-club image" not in r.data
