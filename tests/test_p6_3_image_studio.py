"""Roadmap 1.2 — the generative-imagery **studio** UI (mask-brush + edit family).

Two layers:

* **Flask-free module tests** on ``mediahub.web.image_studio`` — structure, the
  edit-family op vocabulary, style options sourced from the seam, XSS-escaping of
  the (parsed-metadata) asset label, URL wiring, and the honest provider-off note.
* **Flask route tests** on ``/media-library/<asset_id>/studio`` — gating, tenancy
  (404 / cross-org 403), a happy render, the library / generated-page entry-point
  links, and the brushed-``mask_b64`` contract round-tripping through the shipped
  asset-op route via the in-house local backend (stubbed — nothing hits a network).
"""

from __future__ import annotations

import io

import pytest


def _png_bytes(color=(10, 20, 30), size=(24, 18)):
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, format="PNG")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Flask-free module tests
# ---------------------------------------------------------------------------


def _body(**over):
    from mediahub.web import image_studio as s

    kw = dict(
        asset_id="abc123",
        asset_label="Eira Hughes",
        asset_type="athlete_action",
        asset_url="/api/media-library/abc123/file",
        info_url="/api/media-library/imagine/info",
        op_url_base="/api/media-library/abc123/imagine/" + s.OP_SENTINEL,
        grab_text_url="/api/media-library/abc123/imagine/grab-text",
        subject_lift_url="/api/media-library/abc123/imagine/subject-lift",
        cutout_url="/api/media-library/abc123/cutout",
        studio_url_base="/media-library/" + s.ASSET_SENTINEL + "/studio",
        file_url_base="/api/media-library/" + s.ASSET_SENTINEL + "/file",
        back_url="/media-library",
        gen_history_url="/media-library/generated",
        width=1200,
        height=800,
    )
    kw.update(over)
    return s.render_studio_body(**kw)


def test_studio_ops_cover_the_edit_family():
    from mediahub.web import image_studio as s

    # The headline 1.2 vocabulary plus the deterministic / vision ops.
    for op in ("edit", "remove", "expand", "upscale", "style_match", "similar"):
        assert op in s.STUDIO_OPS
    assert "subject_lift" in s.STUDIO_OPS and "grab_text" in s.STUDIO_OPS
    # STUDIO_OPS stays in lock-step with the rendered panels.
    assert s.STUDIO_OPS == tuple(op for op, _, _, _ in s.TOOL_PANELS)


def test_body_has_canvas_and_brush_controls():
    body = _body()
    assert 'id="mh-st-overlay"' in body  # the mask-brush canvas
    assert 'id="mh-st-img"' in body
    for ctl in ("mh-st-brush", "mh-st-erase", "mh-st-clear", "mh-st-size"):
        assert f'id="{ctl}"' in body


def test_body_has_a_panel_and_apply_for_each_op():
    from mediahub.web import image_studio as s

    body = _body()
    for op in s.STUDIO_OPS:
        assert f'data-panel="{op}"' in body
        assert f'data-op="{op}"' in body


def test_body_escapes_asset_label_against_xss():
    # The label is parsed/AI metadata — it must never reach markup unescaped.
    body = _body(asset_label="Eira <script>alert(1)</script>")
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body


def test_body_wires_every_passed_url():
    from mediahub.web import image_studio as s

    body = _body()
    assert "/api/media-library/imagine/info" in body
    assert "/api/media-library/abc123/file" in body
    assert "/api/media-library/abc123/imagine/grab-text" in body
    # The op + result sentinels survive into the JS config for client rewrite.
    assert s.OP_SENTINEL in body
    assert s.ASSET_SENTINEL in body


def test_style_options_sourced_from_the_seam():
    from mediahub.media_ai.imagine_providers.styles import DEFAULT_STYLE, STYLE_PRESETS

    body = _body()
    # Every curated preset is offered, and the seam default is pre-selected.
    for style in STYLE_PRESETS:
        assert f'value="{style}"' in body
    assert f'value="{DEFAULT_STYLE}" selected' in body


def test_honest_provider_off_note_is_present():
    # The note that explains *why* the AI tools may be off is always in the
    # markup (the JS hides it once a provider is confirmed) — honest, no fake.
    # Env-var instructions only appear for the dev operator (customers can't
    # set env vars on a hosted deployment).
    body = _body(dev_operator=True)
    assert "MEDIAHUB_IMAGINE_LOCAL_ENDPOINT" in body
    assert "No image generator is configured" in body


def test_dims_render_when_known_and_omit_when_not():
    assert "1200&times;800" in _body(width=1200, height=800)
    out = _body(width=0, height=0)
    assert "&times;" not in out


# ---------------------------------------------------------------------------
# Flask route tests
# ---------------------------------------------------------------------------


@pytest.fixture
def app_env(app, web_module, tmp_path, monkeypatch):
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

    import mediahub.observability.imagine_usage as iu
    import mediahub.media_library.store as st

    # imagine_usage captures DB_PATH from DATA_DIR at import; the old reload
    # recomputed it per test. Repoint it surgically at this test's isolated
    # data.db so the per-org usage ledger the route writes and the assertions
    # read stay isolated (the shared web fixtures don't touch this module).
    monkeypatch.setattr(iu, "DB_PATH", tmp_path / "data.db")
    st._default_store = st.MediaLibraryStore(
        db_path=tmp_path / "data.db",
        uploads_dir=tmp_path / "uploads_v4" / "media_library",
    )

    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(ClubProfile(profile_id="club-x", display_name="Club X"))
    save_profile(ClubProfile(profile_id="club-y", display_name="Club Y"))

    return app, web_module, tmp_path, iu, st


def _client(app, profile_id="club-x"):
    c = app.test_client()
    with c.session_transaction() as s:
        s["active_profile_id"] = profile_id
    return c


def _seed_asset(st, tmp_path, profile_id="club-x", asset_type="athlete_action", **over):
    from mediahub.media_library.models import MediaAsset

    p = tmp_path / "uploads_v4" / "media_library" / profile_id / "seed.png"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(_png_bytes())
    kw = dict(
        id="", filename="seed.png", path=str(p), type=asset_type, profile_id=profile_id
    )
    kw.update(over)
    return st.get_store().save(MediaAsset(**kw))


def test_studio_gated_by_imagine_flag(app_env, monkeypatch):
    app, wm, tmp_path, iu, st = app_env
    a = _seed_asset(st, tmp_path)
    monkeypatch.setattr(wm, "_imagine_ok", False)
    c = _client(app)
    r = c.get(f"/media-library/{a.id}/studio")
    assert r.status_code == 503


def test_studio_not_found(app_env):
    app, wm, *_ = app_env
    c = _client(app)
    r = c.get("/media-library/nope/studio")
    assert r.status_code == 404


def test_studio_forbidden_cross_org(app_env):
    app, wm, tmp_path, iu, st = app_env
    a = _seed_asset(st, tmp_path, profile_id="club-y")
    c = _client(app, "club-x")
    r = c.get(f"/media-library/{a.id}/studio")
    assert r.status_code == 403


def test_studio_happy_render_without_provider(app_env):
    # With no image provider configured the page still renders (capabilities are
    # probed client-side) and shows the honest provider-off note — never a fake.
    app, wm, tmp_path, iu, st = app_env
    a = _seed_asset(st, tmp_path)
    c = _client(app)
    r = c.get(f"/media-library/{a.id}/studio")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="mh-st-overlay"' in html
    assert "/api/media-library/imagine/info" in html
    assert f"/api/media-library/file/{a.id}" in html
    # Customer session: honest note, without operator env-var instructions.
    assert 'id="mh-st-providernote"' in html
    assert "aren&rsquo;t enabled on this deployment" in html
    assert "MEDIAHUB_IMAGINE_LOCAL_ENDPOINT" not in html


def test_studio_renders_with_local_backend(app_env, monkeypatch):
    app, wm, tmp_path, iu, st = app_env
    monkeypatch.setenv("MEDIAHUB_IMAGINE_LOCAL_ENDPOINT", "http://imagine:8800")
    a = _seed_asset(st, tmp_path)
    c = _client(app)
    r = c.get(f"/media-library/{a.id}/studio")
    assert r.status_code == 200
    # The op route base (with the operation sentinel) is wired for the JS.
    from mediahub.web import image_studio as s

    assert s.OP_SENTINEL in r.get_data(as_text=True)


def test_library_page_links_to_studio(app_env):
    app, wm, tmp_path, iu, st = app_env
    a = _seed_asset(st, tmp_path)
    c = _client(app)
    r = c.get("/media-library")
    assert r.status_code == 200
    assert f"/media-library/{a.id}/studio" in r.get_data(as_text=True)


def test_generated_page_links_to_studio(app_env):
    app, wm, tmp_path, iu, st = app_env
    a = _seed_asset(st, tmp_path, asset_type="ai_generated")
    c = _client(app)
    r = c.get("/media-library/generated")
    assert r.status_code == 200
    assert f"/media-library/{a.id}/studio" in r.get_data(as_text=True)


def _fake_local_post_capturing(monkeypatch, png, captured):
    """Patch requests.post to capture the JSON body and return ``png``."""
    import base64

    import requests

    class _R:
        status_code = 200
        headers = {"Content-Type": "application/json"}
        text = ""

        @staticmethod
        def json():
            return {"images": [base64.b64encode(png).decode()]}

    def _post(url, json=None, headers=None, timeout=None):
        captured["json"] = json or {}
        captured["url"] = url
        return _R()

    monkeypatch.setattr(requests, "post", _post)


def test_studio_edit_forwards_the_brushed_mask(app_env, monkeypatch):
    # The studio's core contract: a brushed mask (base64 PNG) posted to the
    # shipped asset-op route reaches the provider as a non-empty mask, and the
    # result is a provenance-stamped composite asset.
    app, wm, tmp_path, iu, st = app_env
    monkeypatch.setenv("MEDIAHUB_IMAGINE_LOCAL_ENDPOINT", "http://imagine:8800")
    a = _seed_asset(st, tmp_path)
    captured: dict = {}
    _fake_local_post_capturing(monkeypatch, _png_bytes((90, 90, 90)), captured)

    import base64

    mask_b64 = base64.b64encode(_png_bytes((255, 255, 255))).decode()
    c = _client(app)
    r = c.post(
        f"/api/media-library/{a.id}/imagine/edit",
        json={"instruction": "remove the bin behind the podium", "mask_b64": mask_b64},
    )
    assert r.status_code == 200, r.get_json()
    assert captured["url"].endswith("/edit")
    assert captured["json"].get("mask"), "the brushed mask was not forwarded to the provider"
    asset = r.get_json()["asset"]
    assert asset["description_parsed"]["imagine"]["operation"] == "edit"
    assert iu.count_for_org("club-x") == 1


def test_studio_remove_requires_no_instruction(app_env, monkeypatch):
    app, wm, tmp_path, iu, st = app_env
    monkeypatch.setenv("MEDIAHUB_IMAGINE_LOCAL_ENDPOINT", "http://imagine:8800")
    a = _seed_asset(st, tmp_path)
    captured: dict = {}
    _fake_local_post_capturing(monkeypatch, _png_bytes((5, 5, 5)), captured)
    import base64

    c = _client(app)
    r = c.post(
        f"/api/media-library/{a.id}/imagine/remove",
        json={"mask_b64": base64.b64encode(_png_bytes((255, 255, 255))).decode()},
    )
    assert r.status_code == 200, r.get_json()
    assert captured["json"].get("mask")


def test_provider_note_hides_env_var_copy_from_customers():
    """Hosted-SaaS customers cannot set env vars: the no-provider note must not
    show operator instructions unless the session is the dev operator."""
    customer = _body()
    assert "MEDIAHUB_IMAGINE_LOCAL_ENDPOINT" not in customer
    assert "aren&rsquo;t enabled on this deployment" in customer

    operator = _body(dev_operator=True)
    assert "MEDIAHUB_IMAGINE_LOCAL_ENDPOINT" in operator
    # On-server naming rule: the backend is never described as "local".
    assert "in-house local model" not in operator
