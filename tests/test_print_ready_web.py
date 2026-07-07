"""Roadmap 1.20 Build D — the print web surface.

Exercises the print routes the way the g117 print tests do: a tmp DATA_DIR, two
orgs and a run on disk, multi-tenant isolation. The card-render (Chromium) and
the PDF colour hops aren't needed here — the testable route logic is auth,
product resolution, the deterministic preflight, the no-design gate and the
catalogue/capability surface.
"""

from __future__ import annotations

import importlib
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest


def _run_payload(run_id: str, profile_id: str) -> dict:
    return {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Spring Open", "start_date": "2026-06-06", "swimmers": {}, "results": []},
        "cards": [],
        "recognition_report": {"ranked_achievements": []},
    }


@pytest.fixture
def web_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs_v4"))
    monkeypatch.setenv("UPLOADS_DIR", str(tmp_path / "uploads_v4"))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    monkeypatch.delenv("MEDIAHUB_FULFILMENT_PROVIDER", raising=False)
    for sub in ("runs_v4", "uploads_v4", "club_profiles"):
        (tmp_path / sub).mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import mediahub.web.club_profile as cp
    import mediahub.web.web as wm

    importlib.reload(cp)
    importlib.reload(wm)
    from mediahub.web.club_profile import ClubProfile, save_profile

    save_profile(
        ClubProfile(
            profile_id="org-alpha",
            display_name="Org Alpha",
            club_codes=["ALPH"],
            brand_primary="#0E5BFF",
            brand_secondary="#101820",
        )
    )
    save_profile(ClubProfile(profile_id="org-beta", display_name="Org Beta"))

    run_id = "run-print-" + uuid.uuid4().hex[:8]
    (tmp_path / "runs_v4" / f"{run_id}.json").write_text(json.dumps(_run_payload(run_id, "org-alpha")))
    conn = wm._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name)"
        " VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Spring Open", "spring.hy3"),
    )
    conn.commit()
    conn.close()

    app = wm.create_app()
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield {"client": c, "run_id": run_id, "tmp_path": tmp_path}


def _pin(client, profile_id):
    r = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert r.status_code == 200, r.get_json()


# ---------------------------------------------------------------------------
# Capability / catalogue surface
# ---------------------------------------------------------------------------


def test_print_products_catalogue(web_env):
    c = web_env["client"]
    _pin(c, "org-alpha")
    r = c.get("/api/print/products")
    assert r.status_code == 200
    body = r.get_json()
    fams = {g["family"] for g in body["families"]}
    assert {"paper", "apparel", "drinkware", "accessory"} <= fams
    assert set(body["capabilities"]) >= {"cmyk", "pdfx", "colour_modes"}
    assert body["fulfilment"]["enabled"] is False


def test_print_fulfilment_status_honest(web_env):
    c = web_env["client"]
    _pin(c, "org-alpha")
    r = c.get("/api/print/fulfilment")
    assert r.status_code == 200
    assert r.get_json()["enabled"] is False


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------


def test_print_center_page_renders(web_env):
    c = web_env["client"]
    _pin(c, "org-alpha")
    r = c.get("/print")
    assert r.status_code == 200
    assert b"Print" in r.data and b"merch" in r.data.lower()


def test_print_run_tool_page_access(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    ok = c.get(f"/print/{run_id}")
    assert ok.status_code == 200
    assert b"pr-product" in ok.data and b"print_center.js" in ok.data
    # cross-org cannot open the tool
    _pin(c, "org-beta")
    assert c.get(f"/print/{run_id}").status_code == 404


# ---------------------------------------------------------------------------
# Preflight (deterministic, no render)
# ---------------------------------------------------------------------------


def test_preflight_returns_report(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{run_id}/card/c1/preflight?product=poster_a3")
    assert r.status_code == 200
    body = r.get_json()
    assert body["product"] == "poster_a3"
    assert "ok" in body and "violations" in body and "summary" in body


def test_preflight_unknown_product_400(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{run_id}/card/c1/preflight?product=spaceship")
    assert r.status_code == 400


def test_preflight_cross_org_404(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-beta")
    r = c.post(f"/api/runs/{run_id}/card/c1/preflight?product=poster_a3")
    assert r.status_code == 404


def test_preflight_placement_selectable(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{run_id}/card/c1/preflight?product=club_tee&placement=back")
    assert r.status_code == 200
    assert r.get_json()["placement"] == "back"


# ---------------------------------------------------------------------------
# Print + mockup gating (no Chromium needed — the no-design path returns first)
# ---------------------------------------------------------------------------


def test_print_no_design_returns_409(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{run_id}/card/c1/print?product=poster_a3")
    assert r.status_code == 409
    assert r.get_json()["error"] == "no_design"


def test_print_bad_colour_mode_400(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{run_id}/card/c1/print?product=poster_a3&colour=neon")
    assert r.status_code == 400


def test_print_unknown_product_400(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{run_id}/card/c1/print?product=nope")
    assert r.status_code == 400


def test_print_cross_org_404(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-beta")
    r = c.post(f"/api/runs/{run_id}/card/c1/print?product=poster_a3")
    assert r.status_code == 404


def test_merch_mockup_no_design_409(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    r = c.post(f"/api/runs/{run_id}/card/c1/merch-mockup?product=club_tee")
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Print success path (render_brief + the Chromium PDF hop mocked, like the
# sibling reformat suite) — 200 PDF, 422 preflight block, force=1 override
# ---------------------------------------------------------------------------


_PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _seed_brief(tmp_path: Path, run_id: str, card_id: str = "c1") -> None:
    from mediahub.creative_brief.generator import CreativeBrief

    bdir = tmp_path / "runs_v4" / run_id / "briefs"
    bdir.mkdir(parents=True, exist_ok=True)
    brief = CreativeBrief(
        id="cb_print1",
        content_item_id=card_id,
        profile_id="org-alpha",
        achievement_summary="New PB",
        objective="celebrate",
        primary_hook="NEW PB",
        confidence_label="NEW PB",
        tone="hype",
        layout_template="split_diagonal_hero",
        inspiration_pattern_id="x",
        image_treatment="cutout",
        text_hierarchy=[],
        brand_instructions="b",
        sponsor_instructions=None,
        sourced_asset_ids=[],
        safety_notes=[],
        why_this_design="because",
        text_layers={"athlete_full_name": "Alice Lee"},
        palette={"primary": "#A30D2D", "secondary": "#000000", "accent": "#FFFFFF"},
        format_priority=["story"],
    )
    (bdir / f"{brief.id}.json").write_text(json.dumps(brief.to_dict(), default=str))


def _fake_render_brief_factory(fixed_size=None):
    """A render_brief stub writing a solid PNG at the requested (or fixed) size."""
    from PIL import Image

    captured = {}

    def _fake(brief, *, output_dir, size, format_name, **kw):
        captured["brief"] = brief
        captured["size"] = size
        captured["format_name"] = format_name
        out = Path(output_dir)
        out.mkdir(parents=True, exist_ok=True)
        png = out / f"{format_name}.png"
        Image.new("RGB", fixed_size or size, (163, 13, 45)).save(png, format="PNG")
        visual = SimpleNamespace(file_path=str(png), id="v1", format_name=format_name)
        return SimpleNamespace(visual=visual)

    return _fake, captured


def _fake_render_html_to_pdf(html, out, **kw):
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_bytes(_PDF_BYTES)


def test_print_success_serves_pdf(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    _seed_brief(web_env["tmp_path"], run_id)
    fake, captured = _fake_render_brief_factory()  # renders at the print canvas → dpi met
    with mock.patch("mediahub.graphic_renderer.render.render_brief", fake), \
         mock.patch("mediahub.print_ready.engine.render_html_to_pdf", _fake_render_html_to_pdf):
        r = c.post(f"/api/runs/{run_id}/card/c1/print?product=poster_a3")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.headers["Content-Type"].startswith("application/pdf")
    assert "poster_a3-c1-rgb.pdf" in r.headers.get("Content-Disposition", "")
    assert r.data.startswith(b"%PDF")
    # the card was re-laid at the product's print canvas (A3 @ 150 dpi)
    assert captured["size"] == (1754, 2480)


def test_print_cmyk_downgrade_names_file_for_achieved_mode(web_env):
    """A Ghostscript-less deployment downgrades cmyk→rgb: the download must be
    named for the mode actually ACHIEVED and carry the honest headers, never a
    '…-cmyk.pdf' that is really RGB."""
    from mediahub.graphic_renderer.print_export import CmykUnavailable

    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    _seed_brief(web_env["tmp_path"], run_id)
    fake, _captured = _fake_render_brief_factory()
    with mock.patch("mediahub.graphic_renderer.render.render_brief", fake), \
         mock.patch("mediahub.print_ready.engine.render_html_to_pdf", _fake_render_html_to_pdf), \
         mock.patch(
             "mediahub.print_ready.engine.cmyk_convert_pdf",
             side_effect=CmykUnavailable("Ghostscript is not installed"),
         ):
        r = c.post(f"/api/runs/{run_id}/card/c1/print?product=poster_a3&colour=cmyk")
    assert r.status_code == 200, r.get_data(as_text=True)
    assert r.headers["X-Print-Colour-Requested"] == "cmyk"
    assert r.headers["X-Print-Colour-Used"] == "rgb"
    assert "Ghostscript" in r.headers.get("X-Print-Note", "")
    cd = r.headers.get("Content-Disposition", "")
    assert "-rgb.pdf" in cd and "-cmyk.pdf" not in cd


def test_print_caps_line_names_the_missing_piece(web_env):
    """/print's PDF/X capability line blames the piece actually missing:
    Ghostscript absent → 'needs Ghostscript', not 'needs an ICC profile'."""
    import mediahub.graphic_renderer.print_export as gpe
    import mediahub.print_ready.pdfx as pdfx

    c = web_env["client"]
    _pin(c, "org-alpha")
    with mock.patch.object(gpe, "ghostscript_available", return_value=False), \
         mock.patch.object(pdfx, "pdfx_available", return_value=False):
        page = c.get("/print")
    assert b"needs Ghostscript" in page.data
    assert b"needs an ICC profile" not in page.data
    with mock.patch.object(gpe, "ghostscript_available", return_value=True), \
         mock.patch.object(pdfx, "pdfx_available", return_value=False):
        page = c.get("/print")
    assert b"needs an ICC profile" in page.data


def test_print_tool_force_checkbox_names_the_real_gate(web_env):
    """Warnings never block an export — only errors do — so the force
    checkbox says 'blocking errors', not 'warnings'."""
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    page = c.get(f"/print/{run_id}")
    assert b"export despite blocking errors" in page.data
    assert b"export despite warnings" not in page.data


def test_preflight_palette_only_before_render_then_artwork_after(web_env):
    """Before any render, preflight honestly says it only checked the palette;
    once the card's print artwork is cached, it proofs the actual pixels."""
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    _seed_brief(web_env["tmp_path"], run_id)
    pre = c.post(f"/api/runs/{run_id}/card/c1/preflight?product=poster_a3").get_json()
    assert pre["checked"] == "palette"
    assert "alette-only" in pre["note"]
    # Render the print artwork (mocked Chromium/PDF hops), then re-proof.
    fake, _captured = _fake_render_brief_factory()
    with mock.patch("mediahub.graphic_renderer.render.render_brief", fake), \
         mock.patch("mediahub.print_ready.engine.render_html_to_pdf", _fake_render_html_to_pdf):
        assert c.post(f"/api/runs/{run_id}/card/c1/print?product=poster_a3").status_code == 200
        post = c.post(f"/api/runs/{run_id}/card/c1/preflight?product=poster_a3").get_json()
    assert post["checked"] == "artwork"
    assert "note" not in post


def test_print_art_cache_invalidates_on_brief_edit(web_env):
    """The print_art cache key folds the brief's content: editing the stored
    design (same layout template) must re-render, never print stale artwork."""
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    _seed_brief(web_env["tmp_path"], run_id)
    calls = []
    fake, _captured = _fake_render_brief_factory()

    def counting_fake(*a, **kw):
        calls.append(1)
        return fake(*a, **kw)

    with mock.patch("mediahub.graphic_renderer.render.render_brief", counting_fake), \
         mock.patch("mediahub.print_ready.engine.render_html_to_pdf", _fake_render_html_to_pdf):
        assert c.post(f"/api/runs/{run_id}/card/c1/print?product=poster_a3").status_code == 200
        assert len(calls) == 1
        # unchanged brief → cache hit, no second render
        assert c.post(f"/api/runs/{run_id}/card/c1/print?product=poster_a3").status_code == 200
        assert len(calls) == 1
        # edit the persisted brief (headline change, same layout_template)
        bpath = web_env["tmp_path"] / "runs_v4" / run_id / "briefs" / "cb_print1.json"
        bdict = json.loads(bpath.read_text())
        bdict["primary_hook"] = "CLUB RECORD"
        bpath.write_text(json.dumps(bdict, default=str))
        assert c.post(f"/api/runs/{run_id}/card/c1/print?product=poster_a3").status_code == 200
        assert len(calls) == 2  # the edit re-rendered


def test_dark_artwork_paper_sampled_not_forced_white(web_env):
    """The route's design palette no longer asserts white paper, so
    build_profile keeps the paper colour sampled from the actual (dark-first)
    artwork — contrast/ink checks proof the real ground, not '#FFFFFF'."""
    import io as _io

    from PIL import Image

    from mediahub.print_ready.engine import PrintRequest, build_profile

    buf = _io.BytesIO()
    Image.new("RGB", (400, 400), (10, 24, 32)).save(buf, format="PNG")
    art = buf.getvalue()
    # The same design mapping web.py's _brand_palette now builds (no background)
    design = {"primary": "#0E5BFF", "secondary": "#101820", "accent": "#FFD700"}
    prof = build_profile(
        art,
        PrintRequest(artwork=art, product_slug="poster_a3", placement_slug="front", design=design),
    )
    assert prof.paper_colour.upper() != "#FFFFFF"


def test_brand_palette_source_has_no_hardcoded_white_background():
    import mediahub.web.web as wm

    src = Path(wm.__file__).read_text(encoding="utf-8")
    assert '"background": "#FFFFFF"' not in src


def test_content_builder_links_the_print_tool(web_env):
    """The per-meet print tool is reachable beside the pack's export actions."""
    from mediahub.workflow.status import CardStatus
    from mediahub.workflow.store import WorkflowStore

    c = web_env["client"]
    run_id = web_env["run_id"]
    tmp_path = web_env["tmp_path"]
    _pin(c, "org-alpha")
    # A pack page with one approved card so the builder body (not the empty
    # state) renders. The run payload needs a ranked achievement to approve.
    rpath = tmp_path / "runs_v4" / f"{run_id}.json"
    run = json.loads(rpath.read_text())
    run["recognition_report"]["ranked_achievements"] = [
        {
            "rank": 1,
            "id": "c1",
            "achievement": {
                "swim_id": "c1",
                "swimmer_name": "Alice Lee",
                "event": "100 Free",
                "headline": "New PB",
            },
        }
    ]
    rpath.write_text(json.dumps(run))
    ws = WorkflowStore(tmp_path / "runs_v4")
    ws.set_status(run_id, "c1", CardStatus.APPROVED)
    page = c.get(f"/pack/{run_id}")
    assert page.status_code == 200
    assert f"/print/{run_id}".encode() in page.data


def test_print_preflight_blocked_422_then_force_overrides(web_env):
    c = web_env["client"]
    run_id = web_env["run_id"]
    _pin(c, "org-alpha")
    _seed_brief(web_env["tmp_path"], run_id)
    # a 100×100 artwork on an A3 poster is ~8 dpi → blocking resolution error
    fake, _captured = _fake_render_brief_factory(fixed_size=(100, 100))
    with mock.patch("mediahub.graphic_renderer.render.render_brief", fake), \
         mock.patch("mediahub.print_ready.engine.render_html_to_pdf", _fake_render_html_to_pdf):
        blocked = c.post(f"/api/runs/{run_id}/card/c1/print?product=poster_a3")
        forced = c.post(f"/api/runs/{run_id}/card/c1/print?product=poster_a3&force=1")
    assert blocked.status_code == 422
    body = blocked.get_json()
    assert body["error"] == "preflight_blocked"
    assert body["preflight"]["ok"] is False
    assert body["preflight"]["counts"]["error"] >= 1
    assert any(v["code"] == "resolution_low" for v in body["preflight"]["violations"])
    # the human override still exports, honestly carrying the same report
    assert forced.status_code == 200, forced.get_data(as_text=True)
    assert forced.headers["Content-Type"].startswith("application/pdf")
    assert forced.data.startswith(b"%PDF")
