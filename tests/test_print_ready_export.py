"""Roadmap 1.20 Build C — print-ready export: PDF/X (pdfx.py) + orchestrator (engine.py).

The pure builders (PDF/X definition + Ghostscript argv, the print-page HTML, the
geometry and colour-mode downgrade) are tested directly; the Chromium PDF render
and the Ghostscript hops are monkeypatched so the orchestration logic — preflight
gating, caching, honest colour downgrade, manifest — runs with no binaries.
"""

from __future__ import annotations

import io

import pytest

from PIL import Image

from mediahub.print_ready import engine as ENG
from mediahub.print_ready import pdfx as PX
from mediahub.print_ready import products as P
from mediahub.print_ready.engine import PrintRequest


def _png(w: int, h: int, colour=(255, 255, 255)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (w, h), colour).save(buf, format="PNG")
    return buf.getvalue()


# ===========================================================================
# pdfx.py — pure builders + honest unavailability
# ===========================================================================


def test_pdfx_definition_declares_output_intent_and_version():
    ps = PX.pdfx_definition_ps(icc_profile_path="/icc/CoatedFOGRA39.icc", title="Club poster")
    assert "PDF/X-3:2002" in ps
    assert "/GTS_PDFX" in ps and "OutputIntent" in ps
    assert "(/icc/CoatedFOGRA39.icc) (r) file" in ps
    assert "(Club poster)" in ps


def test_pdfx_definition_escapes_postscript_specials():
    ps = PX.pdfx_definition_ps(icc_profile_path="/x.icc", title="Gala (2026) \\ tour")
    assert "Gala \\(2026\\) \\\\ tour" in ps


def test_pdfx_definition_supports_x1a():
    ps = PX.pdfx_definition_ps(icc_profile_path="/x.icc", standard="PDF/X-1a")
    assert "PDF/X-1a:2003" in ps


def test_ghostscript_pdfx_args_are_cmyk_and_ordered(tmp_path):
    src, dps, out = tmp_path / "in.pdf", tmp_path / "d.ps", tmp_path / "out.pdf"
    args = PX.ghostscript_pdfx_args(
        "gs", src_pdf=src, def_ps=dps, out_pdf=out, icc_profile="/x.icc"
    )
    assert args[0] == "gs"
    assert "-dPDFX" in args
    assert "-sColorConversionStrategy=CMYK" in args
    assert "-dProcessColorModel=/DeviceCMYK" in args
    assert "-sOutputICCProfile=/x.icc" in args
    # the definition .ps must precede the source pdf
    assert args.index(str(dps)) < args.index(str(src))
    assert f"-sOutputFile={out}" in args


def test_resolve_icc_profile_prefers_explicit_then_env(tmp_path, monkeypatch):
    prof = tmp_path / "my.icc"
    prof.write_bytes(b"icc")
    assert PX.resolve_icc_profile(str(prof)) == str(prof)
    monkeypatch.setenv("MEDIAHUB_PRINT_ICC_PROFILE", str(prof))
    assert PX.resolve_icc_profile() == str(prof)


def test_resolve_icc_profile_none_when_absent(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_PRINT_ICC_PROFILE", raising=False)
    monkeypatch.setattr(PX, "_CANDIDATE_PROFILES", ())
    assert PX.resolve_icc_profile() is None


def test_export_pdfx_honest_when_unavailable(tmp_path, monkeypatch):
    src = tmp_path / "in.pdf"
    src.write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(PX, "_gs_binary", lambda: None)  # no Ghostscript
    with pytest.raises(PX.PdfXUnavailable):
        PX.export_pdfx(src, tmp_path / "out.pdf")


def test_export_pdfx_missing_source_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        PX.export_pdfx(tmp_path / "nope.pdf")


def test_pdfx_available_requires_both_gs_and_profile(tmp_path, monkeypatch):
    prof = tmp_path / "p.icc"
    prof.write_bytes(b"icc")
    monkeypatch.setattr(PX, "_gs_binary", lambda: "/usr/bin/gs")
    assert PX.pdfx_available(str(prof)) is True
    monkeypatch.setattr(PX, "_gs_binary", lambda: None)
    assert PX.pdfx_available(str(prof)) is False


# ===========================================================================
# engine.py — geometry + HTML
# ===========================================================================


def test_geometry_for_paper_product_has_bleed_and_marks():
    poster = P.product_for("poster_a3")
    geom = ENG.geometry_for_placement(poster, poster.primary_placement)
    assert geom.trim_w_mm == pytest.approx(297.0)
    assert geom.trim_h_mm == pytest.approx(420.0)
    assert geom.bleed_mm == 3.0 and geom.mark_len_mm > 0
    # media box = trim + 2*(bleed + mark slug)
    assert geom.media_w_mm > geom.trim_w_mm


def test_geometry_for_merch_has_no_marks():
    tee = P.product_for("club_tee")
    geom = ENG.geometry_for_placement(tee, tee.placement("front"))
    assert geom.bleed_mm == 0.0 and geom.mark_len_mm == 0.0
    assert geom.media_w_mm == pytest.approx(geom.trim_w_mm)


def test_bleed_override_is_honoured():
    poster = P.product_for("poster_a3")
    geom = ENG.geometry_for_placement(poster, poster.primary_placement, bleed_mm=5.0)
    assert geom.bleed_mm == 5.0


def test_raster_html_has_image_and_marks_for_paper():
    poster = P.product_for("poster_a3")
    geom = ENG.geometry_for_placement(poster, poster.primary_placement)
    html = ENG.build_raster_print_html("data:image/png;base64,AAAA", geom, info_label="X")
    assert 'class="art"' in html and "data:image/png;base64,AAAA" in html
    assert "<svg" in html  # crop marks / colour bar furniture present
    assert f"{ENG._f(geom.media_w_mm)}mm" in html


def test_raster_html_has_no_marks_for_merch():
    tee = P.product_for("club_tee")
    geom = ENG.geometry_for_placement(tee, tee.placement("front"))
    html = ENG.build_raster_print_html("data:image/png;base64,AAAA", geom)
    assert "<svg" not in html and 'class="marks"' not in html


# ===========================================================================
# engine.py — colour-mode honest downgrade
# ===========================================================================


def test_colour_mode_rgb_is_a_noop(tmp_path):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    used, note = ENG._apply_colour_mode(pdf, "rgb", title="t")
    assert used == "rgb" and note == ""


def test_colour_mode_cmyk_downgrades_to_rgb_without_ghostscript(tmp_path, monkeypatch):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")

    def _boom(*a, **k):
        raise ENG.CmykUnavailable("no gs")

    monkeypatch.setattr(ENG, "cmyk_convert_pdf", _boom)
    used, note = ENG._apply_colour_mode(pdf, "cmyk", title="t")
    assert used == "rgb" and "CMYK unavailable" in note


def test_colour_mode_pdfx_downgrades_through_cmyk_to_rgb(tmp_path, monkeypatch):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(ENG, "export_pdfx", lambda *a, **k: (_ for _ in ()).throw(PX.PdfXUnavailable("x")))
    monkeypatch.setattr(ENG, "cmyk_convert_pdf", lambda *a, **k: (_ for _ in ()).throw(ENG.CmykUnavailable("y")))
    used, note = ENG._apply_colour_mode(pdf, "pdfx", title="t")
    assert used == "rgb" and "PDF/X and CMYK unavailable" in note


def test_colour_mode_pdfx_success(tmp_path, monkeypatch):
    pdf = tmp_path / "a.pdf"
    pdf.write_bytes(b"%PDF")
    monkeypatch.setattr(ENG, "export_pdfx", lambda *a, **k: pdf)
    used, note = ENG._apply_colour_mode(pdf, "pdfx", title="t")
    assert used == "pdfx" and note == ""


# ===========================================================================
# engine.py — build_profile
# ===========================================================================


def test_build_profile_merges_image_and_design():
    req = PrintRequest(
        artwork=_png(400, 300, (12, 37, 64)),
        product_slug="poster_a3",
        design={"background": "#FFFFFF", "primary": "#0A2540"},
        min_text_px=42,
        full_bleed=True,
    )
    prof = ENG.build_profile(req.artwork, req)
    assert prof.width_px == 400 and prof.height_px == 300
    assert prof.paper_colour == "#FFFFFF"
    assert "#0A2540" in prof.ink_colours
    assert prof.min_text_px == 42 and prof.full_bleed is True


# ===========================================================================
# engine.py — prepare_print orchestration (render monkeypatched)
# ===========================================================================


@pytest.fixture
def stub_render(monkeypatch):
    """Replace the Chromium PDF render with a stub that writes a tiny PDF."""
    calls = {"n": 0}

    def _fake(html, out, **kw):
        calls["n"] += 1
        from pathlib import Path

        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_bytes(b"%PDF-1.4 stub")
        return Path(out)

    monkeypatch.setattr(ENG, "render_html_to_pdf", _fake)
    return calls


def test_prepare_print_blocks_on_preflight_error(tmp_path, stub_render):
    # a 100×65 image on a business card is far below print resolution → error
    req = PrintRequest(artwork=_png(100, 65), product_slug="business_card")
    res = ENG.prepare_print(req, out_dir=tmp_path)
    assert res.blocked and not res.rendered
    assert res.pdf_path is None
    assert not res.preflight.ok
    assert stub_render["n"] == 0  # never rendered
    assert res.manifest["preflight"]["counts"]["error"] >= 1


def test_prepare_print_force_overrides_block(tmp_path, stub_render):
    req = PrintRequest(artwork=_png(100, 65), product_slug="business_card", force=True)
    res = ENG.prepare_print(req, out_dir=tmp_path)
    assert res.rendered and res.pdf_path is not None and res.pdf_path.exists()
    assert stub_render["n"] == 1


def test_prepare_print_renders_clean_artwork_and_writes_manifest(tmp_path, stub_render):
    poster = P.product_for("poster_a3")
    spec = poster.primary_placement.format
    req = PrintRequest(
        artwork=_png(spec.width, spec.height, (10, 37, 64)),
        product_slug="poster_a3",
        full_bleed=True,
        min_text_px=400,
    )
    res = ENG.prepare_print(req, out_dir=tmp_path)
    assert res.rendered and res.pdf_path.exists()
    assert res.colour_mode_used == "rgb"
    # manifest sidecar written
    assert res.pdf_path.with_suffix(".json").exists()
    assert res.manifest["product"] == "poster_a3"
    assert res.manifest["trim_mm"] == [297.0, 420.0]


def test_prepare_print_caches_identical_requests(tmp_path, stub_render):
    poster = P.product_for("poster_a3")
    spec = poster.primary_placement.format
    req = PrintRequest(
        artwork=_png(spec.width, spec.height, (10, 37, 64)),
        product_slug="poster_a3",
        full_bleed=True,
        min_text_px=400,
    )
    first = ENG.prepare_print(req, out_dir=tmp_path)
    second = ENG.prepare_print(req, out_dir=tmp_path)
    assert first.pdf_path == second.pdf_path
    assert second.from_cache is True
    assert stub_render["n"] == 1  # second served from cache, not re-rendered


def test_cache_hit_reports_recorded_downgrade_not_requested_mode(tmp_path, stub_render, monkeypatch):
    """CMYK unavailable → the cold render honestly downgrades to RGB with a
    note. A later identical request must never claim colour_mode_used='cmyk'
    for that RGB file: the recorded downgrade is treated as a miss (so a
    later-installed toolchain re-converts) and the result stays honest."""

    def _no_cmyk(*a, **k):
        raise ENG.CmykUnavailable("no ghostscript")

    monkeypatch.setattr(ENG, "cmyk_convert_pdf", _no_cmyk)
    poster = P.product_for("poster_a3")
    spec = poster.primary_placement.format
    req = PrintRequest(
        artwork=_png(spec.width, spec.height, (10, 37, 64)),
        product_slug="poster_a3",
        full_bleed=True,
        min_text_px=400,
        colour_mode="cmyk",
    )
    first = ENG.prepare_print(req, out_dir=tmp_path)
    assert first.colour_mode_used == "rgb"
    assert "CMYK unavailable" in first.note

    second = ENG.prepare_print(req, out_dir=tmp_path)
    assert second.colour_mode_used == "rgb"  # never 'cmyk' for an RGB file
    assert "CMYK unavailable" in second.note
    assert second.manifest["colour_mode_used"] == "rgb"
    assert second.from_cache is False  # downgrade recorded → honest re-render
    assert stub_render["n"] == 2


def test_prepare_print_unknown_product_and_mode_raise(tmp_path):
    with pytest.raises(ValueError):
        ENG.prepare_print(PrintRequest(artwork=_png(10, 10), product_slug="nope"), out_dir=tmp_path)
    with pytest.raises(ValueError):
        ENG.prepare_print(
            PrintRequest(artwork=_png(10, 10), product_slug="poster_a3", colour_mode="xyz"),
            out_dir=tmp_path,
        )


def test_prepare_print_double_sided_placement_selectable(tmp_path, stub_render):
    tee = P.product_for("club_tee")
    spec = tee.placement("back").format
    req = PrintRequest(
        artwork=_png(spec.width, spec.height, (10, 37, 64)),
        product_slug="club_tee",
        placement_slug="back",
        full_bleed=True,
        min_text_px=400,
    )
    res = ENG.prepare_print(req, out_dir=tmp_path)
    assert res.rendered and res.placement_slug == "back"
