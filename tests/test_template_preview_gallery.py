"""G1.26 — the live archetype × style-pack preview gallery ("Template studio").

Covers the pure ``mediahub.web.template_preview_gallery`` helper (state
validation, pack filtering, pagination, the self-contained schematic fallback,
and the body renderer) and the two routes it powers — the ``/templates/preview``
page and the ``/templates/preview/thumb/<archetype>/<pack_id>`` live-thumbnail
endpoint (with the render path stubbed so the suite needs no browser). The
gallery renders the *existing* catalog only (archetypes × style packs); these
tests pin that contract: every knob is validated, junk can never 500 or escape
the cache dir, a render failure degrades to an honest schematic, and the two
gallery surfaces cross-link.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mediahub.graphic_renderer import archetypes as A
from mediahub.graphic_renderer import style_packs as SP
from mediahub.web import template_preview_gallery as G


# A >100-byte PNG-ish blob so the route's cache-validity check (size > 100)
# accepts the stubbed render and serves the second request from cache.
_FAKE_PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 256


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def app(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("MEDIAHUB_GEN_V2", "1")
    monkeypatch.delenv("STRIPE_SECRET_KEY", raising=False)
    from mediahub.web.web import create_app

    application = create_app()
    application.config["TESTING"] = True
    if not application.secret_key:
        application.secret_key = "test-secret"
    return application


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def clean_preview_cache():
    """Wipe the disk preview cache around a test.

    ``web.DATA_DIR`` is fixed at import, so the on-disk cache would otherwise
    bleed between tests in a session (a prior render masking a later one). Thumb
    tests that assert on render counts / failure use this for a clean slate.
    """
    import shutil

    import mediahub.web.web as wm

    cache = wm.DATA_DIR / "template_previews"
    shutil.rmtree(cache, ignore_errors=True)
    yield cache
    shutil.rmtree(cache, ignore_errors=True)


@pytest.fixture
def stub_render(monkeypatch):
    """Stub render_brief so route tests need no Chromium. Counts calls."""
    import mediahub.graphic_renderer.render as R

    calls = {"n": 0}

    def _fake(brief, *, output_dir, size, brand_kit=None, skip_cutout=False, **kw):
        calls["n"] += 1
        p = Path(output_dir) / f"render_{calls['n']}.png"
        p.write_bytes(_FAKE_PNG)

        class _V:
            file_path = str(p)

        class _Res:
            visual = _V()
            html = ""
            png_bytes = len(_FAKE_PNG)

        return _Res()

    monkeypatch.setattr(R, "render_brief", _fake)
    return calls


def _thumb_url(archetype, pack_id, hero=False):
    base = f"/templates/preview/thumb/{archetype}/{pack_id}"
    return base + "?hero=1" if hero else base


def _default_state():
    return G.normalise_state({})


# Count studio tiles via the anchor (so JS string refs can't inflate the count).
_TILE_RE = re.compile(r'<a class="mh-tpv-tile\b')


def _tiles(html: str) -> int:
    return len(_TILE_RE.findall(html))


# ---------------------------------------------------------------------------
# Validators + defaults
# ---------------------------------------------------------------------------


def test_default_archetype_and_pack_are_catalog_members():
    assert G.default_archetype() in A.list_archetypes()
    assert SP.style_pack_from_id(G.default_pack()) is not None
    # The default pack is the bare (undecorated) one.
    assert SP.style_pack_from_id(G.default_pack()).is_bare


def test_valid_archetype_coercion():
    real = A.list_archetypes()[0]
    assert G.valid_archetype(real) == real
    assert G.valid_archetype("  " + real + "  ".strip()) == real
    assert G.valid_archetype("nonsense_zzz") == G.default_archetype()
    assert G.valid_archetype(None) == G.default_archetype()
    assert G.valid_archetype("") == G.default_archetype()


def test_valid_pack_coercion():
    pid = SP.pick_style_pack(7).id
    assert G.valid_pack(pid) == pid
    assert G.valid_pack("totally-bogus") == G.default_pack()
    assert G.valid_pack(None) == G.default_pack()
    # A path-traversal-y value can never resolve to a real pack.
    assert G.valid_pack("../../etc/passwd") == G.default_pack()


@pytest.mark.parametrize(
    "kind,good,vocab",
    [
        ("ground", "vignette", SP.GROUNDS),
        ("texture", "halftone", SP.TEXTURES),
        ("accent", "ring", SP.ACCENT_GEOS),
        ("density", "bold", SP.DENSITIES),
    ],
)
def test_valid_lever(kind, good, vocab):
    assert good in vocab  # guard the fixture itself
    assert G.valid_lever(kind, good) == good
    assert G.valid_lever(kind, good.upper()) == good
    assert G.valid_lever(kind, "nope") == G.ANY
    assert G.valid_lever(kind, None) == G.ANY
    assert G.valid_lever("unknown_kind", good) == G.ANY


def test_lever_label():
    assert G.lever_label("corner_ticks") == "Corner Ticks"
    assert G.lever_label("bold") == "Bold"
    assert G.lever_label(G.ANY) == "Any"


# ---------------------------------------------------------------------------
# Pack filtering + pagination
# ---------------------------------------------------------------------------


def test_filter_packs_any_returns_whole_catalog():
    assert len(G.filter_packs()) == SP.style_pack_count()


def test_filter_packs_narrows_by_each_lever():
    only_bold = G.filter_packs(density="bold")
    assert only_bold and all(p.density == "bold" for p in only_bold)
    vign = G.filter_packs(ground="vignette")
    assert vign and all(p.ground == "vignette" for p in vign)
    assert len(vign) < SP.style_pack_count()
    # Combined filters intersect.
    both = G.filter_packs(ground="vignette", density="bold")
    assert all(p.ground == "vignette" and p.density == "bold" for p in both)


def test_filter_packs_impossible_combo_is_empty():
    # A heavy ground + heavy texture + heavy accent + bold exceeds the coherence
    # cap, so the catalog never contains it.
    assert G.filter_packs(
        ground="edge_frame", texture="carbon", accent="frame", density="bold"
    ) == []


def test_filters_active():
    assert not G.filters_active(G.ANY, G.ANY, G.ANY, G.ANY)
    assert G.filters_active("vignette", G.ANY, G.ANY, G.ANY)
    assert G.filters_active(G.ANY, G.ANY, G.ANY, "bold")


def test_paginate_clamps_and_slices():
    seq = list(range(100))
    p1 = G.paginate(seq, 1, per=12)
    assert p1.page == 1 and p1.total == 100 and len(p1.items) == 12
    assert p1.start == 1 and p1.end == 12 and p1.pages == 9
    # Page beyond the end clamps to the last page.
    last = G.paginate(seq, 999, per=12)
    assert last.page == last.pages == 9
    assert last.end == 100 and len(last.items) == 100 - 12 * 8
    # Page below 1 clamps to 1.
    assert G.paginate(seq, 0, per=12).page == 1
    assert G.paginate(seq, -5, per=12).page == 1


def test_paginate_empty_sequence():
    p = G.paginate([], 3, per=12)
    assert p.total == 0 and p.pages == 1 and p.page == 1 and p.items == []
    assert p.start == 0 and p.end == 0


# ---------------------------------------------------------------------------
# State normalisation
# ---------------------------------------------------------------------------


def test_normalise_state_defaults():
    st = G.normalise_state({})
    assert st.archetype == G.default_archetype()
    assert st.pack == G.default_pack()
    assert st.category == "all"
    assert st.ground == st.texture == st.accent == st.density == G.ANY
    assert st.page == 1


def test_normalise_state_validates_everything():
    st = G.normalise_state(
        {
            "archetype": "garbage",
            "pack": "garbage",
            "category": "<script>",
            "ground": "vignette",
            "texture": "garbage",
            "accent": "ring",
            "density": "bold",
            "page": "4",
        }
    )
    assert st.archetype == G.default_archetype()  # junk coerced
    assert st.pack == G.default_pack()
    assert st.category == "all"  # junk category → all
    assert st.ground == "vignette" and st.accent == "ring" and st.density == "bold"
    assert st.texture == G.ANY  # junk lever → any
    assert st.page == 4


def test_normalise_state_bad_page_is_one():
    assert G.normalise_state({"page": "not-a-number"}).page == 1
    assert G.normalise_state({"page": "-3"}).page == 1


# ---------------------------------------------------------------------------
# Self-contained schematic fallback
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", A.list_archetypes())
def test_standalone_schematic_is_self_contained(name):
    svg = G.standalone_schematic_svg(name)
    assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
    assert 'viewBox="0 0 120 150"' in svg
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg  # standalone (img-loadable)
    # Inline <style> bakes the theme colours in so it renders without page CSS.
    assert "<style>" in svg and ".gd{fill:" in svg
    assert 'role="img"' in svg and "aria-label=" in svg


# ---------------------------------------------------------------------------
# render_studio_body — pure HTML, no request
# ---------------------------------------------------------------------------


def _body(state=None):
    return G.render_studio_body(
        studio_url="/templates/preview",
        gallery_url="/templates",
        make_url="/make",
        thumb_url=_thumb_url,
        state=state or _default_state(),
    )


def test_body_has_both_rails_and_featured():
    html = _body()
    assert "Every archetype" in html
    assert "Every style pack" in html
    assert "Pinned template" in html
    # 1 featured + 20 archetypes + PER_DEFAULT packs.
    assert _tiles(html) == len(A.list_archetypes()) + G.PER_DEFAULT
    # The featured (eager) hero image uses the hero size param.
    assert "?hero=1" in html


def test_body_archetype_rail_has_every_archetype():
    html = _body()
    for name in A.list_archetypes():
        assert _thumb_url(name, G.default_pack()) in html


def test_body_pins_are_marked():
    arch = A.list_archetypes()[3]
    pack = SP.pick_style_pack(9).id
    st = G.normalise_state({"archetype": arch, "pack": pack})
    html = _body(st)
    # The pinned archetype + pinned pack tiles carry the pinned class + badge.
    assert "is-pinned" in html
    assert html.count("mh-tpv-pin-badge") >= 1
    # The featured panel shows the pinned slugs.
    assert f">{arch}</code>" in html or arch in html
    assert pack in html


def test_body_category_filter_hides_non_matching_archetypes():
    st = G.normalise_state({"category": "photo"})
    html = _body(st)
    entries = __import__(
        "mediahub.web.template_gallery", fromlist=["gallery_entries"]
    ).gallery_entries()
    n_photo = sum(1 for e in entries if e["category"] == "photo")
    # All archetype tiles stay in the DOM (client filter), non-photo hidden.
    n_hidden = html.count("mh-tpv-tile is-hidden")
    assert n_hidden == len(A.list_archetypes()) - n_photo


def test_body_pack_rail_paginates():
    st = G.normalise_state({"page": "2"})
    html = _body(st)
    assert "Page 2 of" in html
    # Prev is a live link on page 2; the pager is present.
    assert "mh-tpv-pager" in html
    assert "rel=\"prev\"" in html


def test_body_lever_filter_renders_selects_with_current_value():
    st = G.normalise_state({"ground": "vignette", "density": "bold"})
    html = _body(st)
    # The selected lever options are marked selected.
    assert re.search(r'<option value="vignette" selected>', html)
    assert re.search(r'<option value="bold" selected>', html)
    # A "clear filters" affordance shows when a filter is active.
    assert "Clear filters" in html


def test_body_empty_pack_rail_shows_reset():
    st = G.normalise_state(
        {"ground": "edge_frame", "texture": "carbon", "accent": "frame", "density": "bold"}
    )
    html = _body(st)
    assert "No style packs match these filters" in html
    assert "Clear filters" in html or "Clear filters</a>" in html


def test_body_links_back_to_schematic_gallery():
    html = _body()
    assert 'href="/templates"' in html
    assert "schematic template gallery" in html


def test_body_surfaces_honest_totals():
    html = _body()
    n_templates = SP.style_pack_count() * len(A.list_archetypes())
    assert f"{n_templates:,}" in html
    assert f"{SP.style_pack_count():,}" in html


def test_body_heading_order_valid():
    """Hero h1 → section h2s; exactly one h1."""
    html = _body()
    i_h1 = html.find("<h1")
    i_h2 = html.find("<h2")
    assert i_h1 != -1 and i_h2 != -1 and i_h1 < i_h2
    assert html.count("<h1") == 1


def test_body_escapes_thumb_urls():
    def evil_thumb(a, p, hero=False):
        return '/x"><img onerror=alert(1)>'

    html = G.render_studio_body(
        studio_url="/templates/preview",
        gallery_url="/templates",
        make_url="/make",
        thumb_url=evil_thumb,
        state=_default_state(),
    )
    assert "onerror=alert(1)>" not in html  # the raw payload was escaped
    assert "&gt;" in html or "&#34;" in html


def test_query_preserves_state_and_resets_page_on_filter():
    st = G.normalise_state(
        {"archetype": A.list_archetypes()[0], "pack": SP.pick_style_pack(3).id, "page": "5"}
    )
    # Pinning a different archetype preserves the pack + page.
    q = G._query(st, archetype=A.list_archetypes()[1])
    assert f"archetype={A.list_archetypes()[1]}" in q
    assert "page=5" in q
    # Changing a filter resets the page (caller passes page=1).
    q2 = G._query(st, ground="vignette", page=1)
    assert "ground=vignette" in q2 and "page=5" not in q2


# ---------------------------------------------------------------------------
# /templates/preview page route
# ---------------------------------------------------------------------------


def test_studio_route_renders(client):
    r = client.get("/templates/preview")
    assert r.status_code == 200
    assert r.mimetype == "text/html"
    html = r.get_data(as_text=True)
    assert "Template previews" in html
    assert "Every archetype" in html and "Every style pack" in html
    assert _tiles(html) == len(A.list_archetypes()) + G.PER_DEFAULT


def test_studio_route_nav_highlights_templates(client):
    html = client.get("/templates/preview").get_data(as_text=True)
    assert re.search(r'href="/templates"[^>]*class="active"', html)


def test_studio_route_honours_pins_and_filters(client):
    arch = A.list_archetypes()[2]
    r = client.get(f"/templates/preview?archetype={arch}&ground=vignette&page=2")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    # Pinned archetype's thumb (with the default bare pack) is the featured img.
    assert arch in html
    assert re.search(r'<option value="vignette" selected>', html)
    assert "Page 2 of" in html


def test_studio_route_junk_params_do_not_500(client):
    r = client.get("/templates/preview?archetype=%3Cscript%3E&pack=zzz&category=zzz&page=abc")
    assert r.status_code == 200
    html = r.get_data(as_text=True)
    assert "<script>alert" not in html
    # Junk coerced to defaults — the gallery still renders both rails.
    assert "Every archetype" in html and "Every style pack" in html


def test_schematic_gallery_links_to_studio(client):
    html = client.get("/templates").get_data(as_text=True)
    assert 'href="/templates/preview"' in html
    assert "See live preview thumbnails" in html


# ---------------------------------------------------------------------------
# /templates/preview/thumb route (render stubbed)
# ---------------------------------------------------------------------------


def test_thumb_renders_and_caches(client, stub_render, clean_preview_cache):
    url = "/templates/preview/thumb/big_number_dominant/flat-none-none-standard"
    r = client.get(url)
    assert r.status_code == 200 and r.mimetype == "image/png"
    assert r.get_data() == _FAKE_PNG
    assert stub_render["n"] == 1
    # Second request is served from the disk cache — no second render.
    r2 = client.get(url)
    assert r2.status_code == 200 and r2.mimetype == "image/png"
    assert stub_render["n"] == 1
    assert "max-age" in r2.headers.get("Cache-Control", "")
    # Exactly one cache file was written for this template+size.
    assert len(list(clean_preview_cache.rglob("*.png"))) == 1


def test_thumb_hero_size_is_separate_cache_entry(client, stub_render, clean_preview_cache):
    base = "/templates/preview/thumb/big_number_dominant/flat-none-none-standard"
    client.get(base)
    client.get(base + "?hero=1")
    # Different size → a distinct render + distinct cache file.
    assert stub_render["n"] == 2
    assert len(list(clean_preview_cache.rglob("*.png"))) == 2


def test_thumb_junk_coerces_and_still_returns_image(client, stub_render, clean_preview_cache):
    r = client.get("/templates/preview/thumb/NOT_A_REAL_ARCH/not-a-real-pack")
    assert r.status_code == 200 and r.mimetype == "image/png"
    assert stub_render["n"] == 1


def test_thumb_falls_back_to_schematic_on_render_failure(client, monkeypatch, clean_preview_cache):
    import mediahub.graphic_renderer.render as R

    def _boom(*a, **k):
        raise RuntimeError("no browser")

    monkeypatch.setattr(R, "render_brief", _boom)
    r = client.get("/templates/preview/thumb/split_diagonal_hero/vignette-dots-corner_ticks-bold")
    assert r.status_code == 200
    assert r.mimetype == "image/svg+xml"
    body = r.get_data(as_text=True)
    assert body.startswith("<svg") and ".gd{fill:" in body  # self-contained schematic


def test_thumb_falls_back_to_schematic_when_renderer_busy(client, monkeypatch, clean_preview_cache):
    # Simulate the render gate being saturated → honest schematic, never a 500.
    import mediahub.web.web as wm

    @wm.contextlib.contextmanager
    def _busy(*a, **k):
        raise wm._RenderBusy("preview")
        yield  # pragma: no cover

    monkeypatch.setattr(wm, "_render_slot", _busy)
    r = client.get("/templates/preview/thumb/magazine_cover/flat-grain-none-standard")
    assert r.status_code == 200 and r.mimetype == "image/svg+xml"


def test_thumb_does_not_write_cache_on_failure(client, monkeypatch, clean_preview_cache):
    import mediahub.graphic_renderer.render as R

    monkeypatch.setattr(R, "render_brief", lambda *a, **k: (_ for _ in ()).throw(RuntimeError()))
    client.get("/templates/preview/thumb/index_card/flat-none-none-standard")
    pngs = list(clean_preview_cache.rglob("*.png")) if clean_preview_cache.exists() else []
    assert pngs == []  # a failed render leaves no poisoned cache entry
