"""G1.27 — interactive brief/design editor ("Studio").

Three tiers, matching the repo convention (cf. test_template_catalog /
test_v8_graphic_renderer):

* **Pure helper** — the Flask-free ``mediahub.web.design_editor``: vocabulary
  exposure, parameter coercion (the trust boundary), brief construction,
  explainability, the editor body HTML, and the security guarantees (injection
  in palette/text/archetype/pack/roles can never reach the renderer or break the
  page). No browser, no request.
* **Routes (browser-stubbed)** — ``GET /studio`` + ``POST /api/studio/render``
  with the single Playwright path stubbed, so the real brief→HTML pipeline runs
  but no Chromium is needed: response shape, coercion, caching, the honest
  render-unavailable error, and CSRF-exemption by content-type.
* **Real render** — one end-to-end render, skipped when Playwright/Chromium is
  absent, proving the live preview genuinely produces a valid PNG.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest

from mediahub.creative_brief.generator import CreativeBrief
from mediahub.graphic_renderer import archetypes as A
from mediahub.graphic_renderer import style_packs as SP
from mediahub.web import design_editor as DE


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch()
                browser.close()
                return True
            except Exception:
                return False
    except Exception:
        return False


_STUB_PNG = b"\x89PNG\r\n\x1a\n" + b"studio-stub"


# =========================================================================== #
# Tier 1 — pure helper
# =========================================================================== #


def test_vocabulary_is_sourced_from_the_engine():
    v = DE.vocabulary()
    # archetypes mirror the live v2 catalog exactly (no drift)
    assert [a["value"] for a in v["archetypes"]] == A.list_archetypes()
    assert len(v["archetypes"]) >= 6
    # every lever vocabulary matches style_packs (the renderer's source of truth)
    assert [g["value"] for g in v["grounds"]] == list(SP.GROUNDS)
    assert [t["value"] for t in v["textures"]] == list(SP.TEXTURES)
    assert [a["value"] for a in v["accent_geos"]] == list(SP.ACCENT_GEOS)
    assert [d["value"] for d in v["densities"]] == list(SP.DENSITIES)
    assert [r["value"] for r in v["token_roles"]] == list(A.TOKEN_ROLES)
    # every archetype option carries a human label + a structural summary string
    for a in v["archetypes"]:
        assert a["label"] and isinstance(a["summary"], str)


def test_default_archetype_is_a_real_archetype():
    assert DE.default_archetype() in A.list_archetypes()


def test_formats_are_the_supported_aspect_ratios():
    ids = [fid for fid, _, _ in DE.FORMATS]
    assert ids == ["feed_portrait", "feed_square", "story"]
    # landscape is intentionally NOT offered (extended ratios are unbuilt G1.3)
    assert "landscape" not in ids
    for _, _, (w, h) in DE.FORMATS:
        assert w >= 1080 and h >= 1080


def test_coerce_defaults_are_all_renderer_safe():
    p = DE.coerce_params({})
    assert p.archetype == DE.default_archetype()
    assert p.format_id == DE.DEFAULT_FORMAT
    # the default pack is the bare, catalog-valid pack
    assert SP.style_pack_from_id(p.pack_id) is not None
    assert p.pack_eased is False
    assert p.palette == DE.DEFAULT_PALETTE
    assert set(p.text) == {k for k, *_ in DE.TEXT_FIELDS}
    assert p.role_assignment == {}
    assert p.full is False


def test_coerce_rejects_out_of_vocabulary_archetype_and_format():
    p = DE.coerce_params({"archetype": "evil; }body{display:none", "format": "billboard"})
    assert p.archetype == DE.default_archetype()
    assert p.format_id == DE.DEFAULT_FORMAT


def test_coerce_normalises_out_of_vocabulary_pack_levers():
    p = DE.coerce_params(
        {"pack": {"ground": "explode", "texture": "dots", "accent_geo": "ring", "density": "????"}}
    )
    pack = SP.style_pack_from_id(p.pack_id)
    assert pack is not None  # always catalog-valid
    assert pack.ground == "flat"  # bad ground -> default
    assert pack.texture == "dots"  # good lever preserved
    assert pack.density == "standard"  # bad density -> default


def test_coerce_eases_over_cap_pack_to_nearest_catalog_pack():
    # vignette(2)+dots(1)+corner_ticks(1)=4 ; Bold caps at 3 -> must ease.
    p = DE.coerce_params(
        {
            "pack": {
                "ground": "vignette",
                "texture": "dots",
                "accent_geo": "corner_ticks",
                "density": "bold",
            }
        }
    )
    assert p.pack_eased is True
    pack = SP.style_pack_from_id(p.pack_id)
    assert pack is not None
    # eased to Standard but kept all three decorative levers
    assert (pack.ground, pack.texture, pack.accent_geo, pack.density) == (
        "vignette",
        "dots",
        "corner_ticks",
        "standard",
    )


def test_coerce_within_cap_pack_is_not_eased():
    p = DE.coerce_params(
        {
            "pack": {
                "ground": "vignette",
                "texture": "dots",
                "accent_geo": "corner_ticks",
                "density": "standard",
            }
        }
    )
    assert p.pack_eased is False


@pytest.mark.parametrize(
    "ground,texture,accent_geo,density",
    [
        ("vignette", "halftone", "frame", "bold"),  # weight 6 — heaviest
        ("edge_frame", "carbon", "corner_arc", "bold"),
        ("spotlight", "crosshatch", "ring", "standard"),
        ("twotone", "chevron", "corner_blocks", "bold"),
    ],
)
def test_any_lever_combination_resolves_to_a_catalog_pack(ground, texture, accent_geo, density):
    # The renderer's catalog lookup must never silently drop the pack: every
    # resolved id is guaranteed to be in the catalog.
    p = DE.coerce_params(
        {"pack": {"ground": ground, "texture": texture, "accent_geo": accent_geo, "density": density}}
    )
    assert SP.style_pack_from_id(p.pack_id) is not None


def test_coerce_palette_validates_hex_and_rejects_injection():
    p = DE.coerce_params(
        {
            "palette": {
                "primary": "#1A2B3C",  # valid 6-digit
                "secondary": "#abc",  # valid 3-digit
                "accent": "url(javascript:alert(1))",  # injection -> default
            }
        }
    )
    assert p.palette["primary"] == "#1A2B3C"
    assert p.palette["secondary"] == "#abc"
    assert p.palette["accent"] == DE.DEFAULT_PALETTE["accent"]
    # other non-hex shapes also rejected
    for bad in ("red", "123456", "#12", "#12345", "#1234567", "#GGG", "; }", ""):
        q = DE.coerce_params({"palette": {"primary": bad}})
        assert q.palette["primary"] == DE.DEFAULT_PALETTE["primary"], bad


def test_coerce_text_is_capped_and_whitespace_collapsed():
    caps = {k: cap for k, _, _, cap in DE.TEXT_FIELDS}
    p = DE.coerce_params(
        {
            "text": {
                "athlete_surname": "X" * 500,
                "event_name": "  200m\n\n  Freestyle   ",
                "result_value": 12345,  # non-string -> ""
            }
        }
    )
    assert len(p.text["athlete_surname"]) == caps["athlete_surname"]
    assert p.text["event_name"] == "200m Freestyle"
    assert p.text["result_value"] == ""


def test_coerce_roles_keeps_only_valid_token_roles():
    p = DE.coerce_params(
        {"roles": {"ground": "secondary", "accent": "evil_role", "surface": "primary", "bogus": "x"}}
    )
    assert p.role_assignment == {"ground": "secondary", "surface": "primary"}


def test_coerce_non_dict_yields_defaults():
    for raw in (None, [], "nonsense", 42):
        p = DE.coerce_params(raw)
        assert p.archetype == DE.default_archetype()
        assert p.palette == DE.DEFAULT_PALETTE


def test_size_is_half_native_for_preview_and_native_for_full():
    prev = DE.coerce_params({"format": "story", "full": False})
    full = DE.coerce_params({"format": "story", "full": True})
    assert full.size == (1080, 1920)
    assert prev.size == (540, 960)
    # square + portrait too
    assert DE.coerce_params({"format": "feed_square", "full": True}).size == (1080, 1080)
    assert DE.coerce_params({"format": "feed_portrait", "full": True}).size == (1080, 1350)


def test_signature_is_stable_and_change_sensitive():
    a = DE.coerce_params({"archetype": "big_number_dominant", "text": {"result_value": "1.0"}})
    b = DE.coerce_params({"archetype": "big_number_dominant", "text": {"result_value": "1.0"}})
    c = DE.coerce_params({"archetype": "big_number_dominant", "text": {"result_value": "2.0"}})
    assert a.signature() == b.signature()
    assert a.signature() != c.signature()
    # full vs preview are different cache entries
    assert DE.coerce_params({"full": True}).signature() != DE.coerce_params({"full": False}).signature()


def test_build_brief_is_a_renderable_photoless_brief():
    p = DE.coerce_params(
        {
            "archetype": "mega_surname_bleed",
            "pack": {"ground": "vignette", "texture": "dots", "accent_geo": "ring", "density": "standard"},
            "palette": {"primary": "#0E5BFF", "secondary": "#101820", "accent": "#FFD24A"},
            "text": {"athlete_surname": "HUGHES", "result_value": "2:08.41"},
            "roles": {"ground": "secondary"},
        }
    )
    brief = DE.build_brief_from_params(p)
    assert isinstance(brief, CreativeBrief)
    assert brief.layout_template == "mega_surname_bleed"
    assert brief.style_pack == p.pack_id
    assert brief.palette == {"primary": "#0E5BFF", "secondary": "#101820", "accent": "#FFD24A"}
    assert brief.colour_role_assignment == {"ground": "secondary"}
    assert brief.image_treatment == "no-photo"  # never fabricates a person
    assert brief.text_layers["athlete_surname"] == "HUGHES"
    # round-trips through the persisted form like any pipeline brief
    assert CreativeBrief.from_dict(brief.to_dict()) is not None


def test_explain_reports_resolved_roles_pack_and_archetype():
    p = DE.coerce_params(
        {"archetype": "big_number_dominant", "palette": {"primary": "#11332E", "accent": "#F2C14E"}}
    )
    e = DE.explain(p)
    vars_ = {r["var"] for r in e["roles"]}
    assert vars_ == {
        "--mh-primary",
        "--mh-surface",
        "--mh-accent",
        "--mh-secondary",
        "--mh-on-primary",
        "--mh-on-surface",
        "--mh-outline",
    }
    # the resolved ground is exactly the chosen primary; every role hex is real
    by_var = {r["var"]: r["hex"] for r in e["roles"]}
    assert by_var["--mh-primary"] == "#11332E"
    assert all(h.startswith("#") or h.startswith("rgba") for h in by_var.values())
    assert e["archetype"]["name"] == "big_number_dominant"
    assert e["pack"]["name"]  # human label present
    assert e["width"] and e["height"]


def test_explain_flags_illegible_role_swap_via_the_compliance_gate():
    # Push every slot to the accent role — a same-hue ground/headline collapse the
    # APCA gate will reject, so the brand defaults stand and the user is told.
    p = DE.coerce_params(
        {
            "palette": {"primary": "#101820", "secondary": "#101820", "accent": "#101820"},
            "roles": {"ground": "accent", "surface": "accent", "headline": "accent", "accent": "accent"},
        }
    )
    e = DE.explain(p)
    assert any("legible" in n.lower() for n in e["notices"])


def test_explain_flags_eased_pack():
    p = DE.coerce_params(
        {"pack": {"ground": "vignette", "texture": "halftone", "accent_geo": "frame", "density": "bold"}}
    )
    e = DE.explain(p)
    assert p.pack_eased is True
    assert any("eased" in n.lower() for n in e["notices"])


def test_editor_body_contains_every_control():
    body = DE.render_editor_body(
        render_url="/api/studio/render", gallery_url="/templates", make_url="/make"
    )
    # the live-render endpoint + the structural anchors the JS controller needs
    assert "/api/studio/render" in body
    for anchor in (
        'id="mh-studio"',
        'id="mh-studio-config"',
        "data-studio-canvas",
        "data-studio-img",
        'data-studio="archetype"',
        'data-studio="ground"',
        'data-studio="texture"',
        'data-studio="accent_geo"',
        'data-studio="density"',
        'data-studio="format"',
        'data-studio-hex="primary"',
        'data-studio-text="athlete_surname"',
        'data-studio-action="download"',
    ):
        assert anchor in body, anchor
    # every archetype is selectable
    for name in A.list_archetypes():
        assert f'value="{name}"' in body


def test_editor_body_controls_have_exactly_one_binding_attr():
    # Each <select> must carry exactly one JS binding hook — a duplicate
    # data-studio attribute is invalid HTML and double-binds the controller.
    import re

    body = DE.render_editor_body(render_url="/r", gallery_url="/g", make_url="/m")
    for tag in re.findall(r"<select[^>]*>", body):
        assert tag.count("data-studio=") <= 1, tag
    # the four role selects bind via data-studio-role only (never data-studio)
    role_selects = re.findall(r"<select[^>]*data-studio-role[^>]*>", body)
    assert len(role_selects) == len(DE._ROLE_SLOTS)
    for tag in role_selects:
        assert "data-studio=" not in tag
    # each main control is bound exactly once
    for ctrl in ("archetype", "ground", "texture", "accent_geo", "density", "format"):
        assert len(re.findall(r'data-studio="' + ctrl + r'"', body)) == 1, ctrl


def test_editor_body_seeds_palette_from_brand_kit():
    body = DE.render_editor_body(
        render_url="/r",
        gallery_url="/g",
        make_url="/m",
        palette={"primary": "#123456", "secondary": "#abcdef", "accent": "#0F0F0F"},
    )
    assert 'value="#123456"' in body
    assert 'value="#abcdef"' in body
    # an invalid seed colour falls back to the default, never injected raw
    body2 = DE.render_editor_body(
        render_url="/r", gallery_url="/g", make_url="/m", palette={"primary": "</script><x>"}
    )
    assert "</script><x>" not in body2
    assert f'value="{DE.DEFAULT_PALETTE["primary"]}"' in body2


def test_editor_body_embedded_json_cannot_break_out_of_script():
    # The embedded config escapes "<" so no value can close the <script> tag early.
    body = DE.render_editor_body(render_url="/r", gallery_url="/g", make_url="/m")
    open_tag = '<script type="application/json" id="mh-studio-config">'
    i = body.index(open_tag) + len(open_tag)
    payload = body[i : body.index("</script>", i)]
    assert "<" not in payload  # no raw "<" → cannot contain "</script>"
    json.loads(payload)  # and the payload is still valid JSON
    # the escaper would neutralise a "<" if one ever reached the config
    assert DE._safe_json({"x": "</script><b>"}) == '{"x": "\\u003c/script>\\u003cb>"}'


# =========================================================================== #
# Tier 2 — routes, with the Playwright path stubbed
# =========================================================================== #


@pytest.fixture()
def client():
    from mediahub.web.web import create_app

    app = create_app()
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture(autouse=True)
def _clear_studio_cache():
    from mediahub.web.web import _studio_render_cache

    _studio_render_cache.clear()
    yield
    _studio_render_cache.clear()


@pytest.fixture()
def stub_render(monkeypatch):
    """Stub the single Playwright screenshot so the real brief→HTML pipeline runs
    without Chromium. Captures the rendered HTML for assertions."""
    import mediahub.graphic_renderer.render as R

    cap: dict = {}

    def _fake_png(html, output_path, size):
        cap["html"] = html
        cap["size"] = size
        Path(output_path).write_bytes(_STUB_PNG)
        return len(_STUB_PNG)

    monkeypatch.setattr(R, "render_html_to_png", _fake_png)
    return cap


def test_get_studio_page_ok(client):
    r = client.get("/studio")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert 'id="mh-studio"' in html
    assert "/api/studio/render" in html
    assert ">Studio<" in html  # nav link


def test_render_api_returns_png_and_explainability(client, stub_render):
    req = {
        "archetype": "big_number_dominant",
        "format": "feed_square",
        "pack": {"ground": "spotlight", "texture": "grid", "accent_geo": "frame", "density": "standard"},
        "palette": {"primary": "#11332E", "secondary": "#0B1F1B", "accent": "#F2C14E"},
        "text": {"athlete_surname": "OKAFOR", "result_value": "24.91", "achievement_label": "CLUB RECORD"},
    }
    r = client.post("/api/studio/render", json=req)
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    assert d["image"].startswith("data:image/png;base64,")
    raw = base64.b64decode(d["image"].split(",", 1)[1])
    assert raw == _STUB_PNG
    meta = d["meta"]
    assert meta["archetype"]["name"] == "big_number_dominant"
    assert any(role["var"] == "--mh-accent" and role["hex"] == "#F2C14E" for role in meta["roles"])
    # the stub captured the REAL assembled HTML — preview size + chosen colours rode in
    assert stub_render["size"] == (540, 540)
    assert "#11332E" in stub_render["html"]
    assert "{{" not in stub_render["html"]


def test_render_api_coerces_garbage_and_still_renders(client, stub_render):
    r = client.post(
        "/api/studio/render",
        json={"archetype": 12345, "format": "evil", "pack": "notadict", "palette": "x", "text": None},
    )
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    assert d["meta"]["archetype"]["name"] == DE.default_archetype()


def test_render_api_handles_empty_and_non_json_body(client, stub_render):
    r = client.post("/api/studio/render", data=b"", content_type="application/json")
    assert r.status_code == 200 and r.get_json()["ok"] is True
    # a non-JSON content type still coerces to defaults (request.get_json silent)
    r2 = client.post("/api/studio/render", data=b"garbage", content_type="text/plain")
    assert r2.status_code == 200 and r2.get_json()["ok"] is True


def test_render_api_escapes_injection_in_text(client, stub_render):
    r = client.post(
        "/api/studio/render",
        json={"text": {"athlete_surname": "<script>alert(1)</script>", "result_value": "<img src=x>"}},
    )
    assert r.status_code == 200
    html = stub_render["html"]
    # the renderer HTML-escapes layer text, so no raw tag reaches the canvas
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html or "&lt;img" in html


def test_render_api_caches_identical_requests(client, stub_render):
    calls = {"n": 0}
    import mediahub.graphic_renderer.render as R

    orig = R.render_html_to_png

    def _counting(html, output_path, size):
        calls["n"] += 1
        return orig(html, output_path, size)

    R.render_html_to_png = _counting
    try:
        req = {"archetype": "big_number_dominant", "text": {"result_value": "1.23"}}
        a = client.post("/api/studio/render", json=req).get_json()
        b = client.post("/api/studio/render", json=req).get_json()
    finally:
        R.render_html_to_png = orig
    assert a["image"] == b["image"]
    assert calls["n"] == 1  # second served from cache, no re-render


def test_render_api_honest_error_when_browser_unavailable(client, monkeypatch):
    import mediahub.graphic_renderer.render as R

    def _boom(html, output_path, size):
        raise RuntimeError("Playwright not installed: chromium missing")

    monkeypatch.setattr(R, "render_html_to_png", _boom)
    r = client.post("/api/studio/render", json={"archetype": "big_number_dominant"})
    assert r.status_code == 503
    d = r.get_json()
    assert d["ok"] is False
    assert d["error"] == "render_unavailable"
    assert "image" not in d  # never fabricates a preview


def test_render_api_is_csrf_exempt_by_content_type(client, stub_render):
    # JSON content-type is CSRF-exempt even with enforcement on (a cross-site
    # form can't set application/json) — so the editor needs no token.
    client.application.config["ENFORCE_CSRF"] = True
    try:
        r = client.post("/api/studio/render", json={"archetype": "big_number_dominant"})
        assert r.status_code == 200 and r.get_json()["ok"] is True
    finally:
        client.application.config["ENFORCE_CSRF"] = False


def test_render_api_full_flag_renders_native_size(client, stub_render):
    client.post("/api/studio/render", json={"format": "feed_portrait", "full": True})
    assert stub_render["size"] == (1080, 1350)


# =========================================================================== #
# Tier 3 — one real render (skipped without Chromium)
# =========================================================================== #


@pytest.mark.skipif(not _have_playwright(), reason="Playwright/Chromium not available")
def test_real_render_produces_a_valid_png(client):
    req = {
        "archetype": "big_number_dominant",
        "format": "feed_square",
        "pack": {"ground": "vignette", "texture": "dots", "accent_geo": "corner_ticks", "density": "standard"},
        "palette": {"primary": "#0E5BFF", "secondary": "#101820", "accent": "#FFD24A"},
        "text": {"athlete_surname": "HUGHES", "result_value": "2:08.41", "achievement_label": "NEW PB"},
    }
    r = client.post("/api/studio/render", json=req)
    assert r.status_code == 200
    d = r.get_json()
    assert d["ok"] is True
    raw = base64.b64decode(d["image"].split(",", 1)[1])
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"  # a genuine PNG
    assert len(raw) > 2000  # a real card, not a 1×1 placeholder
    assert d["render_ms"] >= 0
