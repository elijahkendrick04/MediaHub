"""Tests for the G1.17 print-production pipeline.

G1.17 expands ``graphic_renderer.print_export`` (W.12) with a real
print-production path: trim/bleed/crop marks + CMYK-aware export. The pure
logic (geometry, CMYK colour science, the SVG furniture, the HTML wrapper, the
honest Ghostscript-absent path) runs everywhere. The real Playwright
print-to-PDF renders are skipped when Chromium isn't installed (same
convention as tests/test_print_export.py / tests/test_v8_graphic_renderer.py).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest

from mediahub.graphic_renderer.print_export import (
    CmykUnavailable,
    PrintGeometry,
    build_certificate_html,
    build_certificate_print_html,
    build_poster_print_html,
    cmyk_convert_pdf,
    cmyk_percent,
    cmyk_separations,
    cmyk_to_hex,
    cmyk_to_rgb,
    export_certificate_print_pdf,
    export_poster_print_pdf,
    format_cmyk,
    geometry_for,
    ghostscript_available,
    print_furniture_svg,
    rgb_to_cmyk,
    to_print_production,
)

BRAND = {"primary": "#0E5BFF", "secondary": "#101820", "accent": "#FFD24A"}


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


_PLAYWRIGHT = pytest.mark.skipif(not _have_playwright(), reason="Playwright/Chromium not available")
_GHOSTSCRIPT = pytest.mark.skipif(not ghostscript_available(), reason="Ghostscript not installed")


def _cert_html(**overrides) -> str:
    kwargs = dict(
        swimmer_name="Eira Hughes",
        event_label="200m Freestyle",
        time_str="2:08.41",
        achievement_headline="Personal Best Certificate",
        meet_name="Welsh Winter Open 2026",
        meet_date="7 June 2026",
        club_name="Test Swim Club",
        brand=BRAND,
        detail_line="2.3 seconds faster than her previous best.",
    )
    kwargs.update(overrides)
    return build_certificate_print_html(**kwargs)


def _poster_html(**overrides) -> str:
    kwargs = dict(
        title="The Weekend in Numbers",
        meet_name="Welsh Winter Open 2026",
        stat_lines=[("PBs", "14"), ("Medals", "6")],
        highlight_rows=[
            {"swimmer": "Swimmer 1", "event": "50m Free", "time": "29.9", "note": "PB"}
        ],
        club_name="Test Swim Club",
        brand=BRAND,
    )
    kwargs.update(overrides)
    return build_poster_print_html(**kwargs)


# ---------------------------------------------------------------------------
# Print geometry
# ---------------------------------------------------------------------------


class TestPrintGeometry:
    def test_a4_media_box_is_trim_plus_two_margins(self):
        g = geometry_for("A4", bleed_mm=3, mark_len_mm=4)
        assert (g.trim_w_mm, g.trim_h_mm) == (210.0, 297.0)
        assert g.margin_mm == 7.0  # bleed + mark_len
        assert g.media_w_mm == 210 + 14
        assert g.media_h_mm == 297 + 14

    def test_landscape_swaps_dimensions(self):
        p = geometry_for("A4")
        ls = geometry_for("A4", landscape=True)
        assert (ls.trim_w_mm, ls.trim_h_mm) == (p.trim_h_mm, p.trim_w_mm)

    def test_paper_name_is_case_insensitive(self):
        assert geometry_for("a4").trim_w_mm == geometry_for("A4").trim_w_mm

    def test_unknown_paper_raises(self):
        with pytest.raises(ValueError):
            geometry_for("Quarto")

    def test_bleed_rectangle_sits_one_bleed_inside_the_margin(self):
        g = geometry_for("A4", bleed_mm=3, mark_len_mm=4)
        # The bled background starts mark_len in from the media edge ...
        assert g.bleed_rect_left_mm == 4.0  # margin - bleed == mark_len
        # ... and is the trim grown by one bleed on every side.
        assert g.bleed_rect_w_mm == 210 + 6
        assert g.bleed_rect_h_mm == 297 + 6
        # The trim box sits a full margin in.
        assert g.trim_left_mm == g.margin_mm == 7.0

    def test_zero_trim_raises(self):
        with pytest.raises(ValueError):
            PrintGeometry(trim_w_mm=0, trim_h_mm=100)

    def test_negative_bleed_raises(self):
        with pytest.raises(ValueError):
            PrintGeometry(trim_w_mm=100, trim_h_mm=100, bleed_mm=-1)

    def test_frozen(self):
        g = geometry_for("A4")
        with pytest.raises(Exception):
            g.bleed_mm = 5  # type: ignore[misc]


# ---------------------------------------------------------------------------
# CMYK colour science
# ---------------------------------------------------------------------------


class TestCmykMath:
    @pytest.mark.parametrize(
        "hex_colour,expected",
        [
            ("#FFFFFF", (0.0, 0.0, 0.0, 0.0)),  # white = no ink
            ("#000000", (0.0, 0.0, 0.0, 1.0)),  # black = pure K
            ("#FF0000", (0.0, 1.0, 1.0, 0.0)),  # red
            ("#00FF00", (1.0, 0.0, 1.0, 0.0)),  # green
            ("#0000FF", (1.0, 1.0, 0.0, 0.0)),  # blue
            ("#00FFFF", (1.0, 0.0, 0.0, 0.0)),  # cyan
            ("#FF00FF", (0.0, 1.0, 0.0, 0.0)),  # magenta
            ("#FFFF00", (0.0, 0.0, 1.0, 0.0)),  # yellow
        ],
    )
    def test_known_conversions(self, hex_colour, expected):
        assert rgb_to_cmyk(hex_colour) == expected

    def test_accepts_three_digit_and_no_hash(self):
        assert rgb_to_cmyk("#fff") == (0.0, 0.0, 0.0, 0.0)
        assert rgb_to_cmyk("000000") == (0.0, 0.0, 0.0, 1.0)

    @pytest.mark.parametrize("bad", ["", "#12", "#GGGGGG", "nope", None])
    def test_invalid_hex_raises(self, bad):
        with pytest.raises(ValueError):
            rgb_to_cmyk(bad)  # type: ignore[arg-type]

    def test_round_trip_is_lossless(self):
        for r in range(0, 256, 17):
            for g in range(0, 256, 51):
                for b in range(0, 256, 85):
                    hx = f"#{r:02X}{g:02X}{b:02X}"
                    rr, gg, bb = cmyk_to_rgb(*rgb_to_cmyk(hx))
                    assert abs(rr - r) <= 1 and abs(gg - g) <= 1 and abs(bb - b) <= 1

    def test_cmyk_to_rgb_clamps_out_of_range(self):
        assert cmyk_to_rgb(-1, 0, 0, 0) == (255, 255, 255)
        assert cmyk_to_rgb(2, 2, 2, 2) == (0, 0, 0)

    def test_format_and_percent(self):
        assert format_cmyk(*rgb_to_cmyk("#FF0000")) == "C0 M100 Y100 K0"
        assert cmyk_percent("#000000") == (0, 0, 0, 100)
        assert cmyk_to_hex(0, 0, 0, 1) == "#000000"
        assert cmyk_to_hex(1, 0, 0, 0) == "#00FFFF"


class TestSeparations:
    def test_brand_roles_plus_fixed_inks(self):
        rows = cmyk_separations(BRAND)
        roles = [r["role"] for r in rows]
        assert "primary" in roles and "accent" in roles
        assert roles[-2:] == ["ink", "paper"]  # always appended last
        prim = next(r for r in rows if r["role"] == "primary")
        assert prim["hex"] == "#0E5BFF"
        assert isinstance(prim["cmyk"], tuple) and len(prim["cmyk"]) == 4
        assert prim["label"].startswith("C")

    def test_empty_brand_still_describes_paper_and_ink(self):
        rows = cmyk_separations({})
        assert [r["role"] for r in rows] == ["ink", "paper"]

    def test_dedupes_by_hex(self):
        rows = cmyk_separations({"primary": "#0E5BFF", "secondary": "#0e5bff"})
        hexes = [r["hex"] for r in rows]
        assert hexes.count("#0E5BFF") == 1

    def test_invalid_hex_is_skipped(self):
        rows = cmyk_separations({"primary": "not-a-colour", "accent": "#FFD24A"})
        roles = [r["role"] for r in rows]
        assert "primary" not in roles and "accent" in roles


# ---------------------------------------------------------------------------
# Printer's-marks furniture (SVG)
# ---------------------------------------------------------------------------


class TestFurnitureSvg:
    def test_well_formed_svg_with_media_box(self):
        g = geometry_for("A4")
        svg = print_furniture_svg(g, brand=BRAND)
        assert svg.startswith("<svg") and svg.rstrip().endswith("</svg>")
        assert 'viewBox="0 0 224 311"' in svg
        assert 'width="224mm"' in svg and 'height="311mm"' in svg

    def test_eight_crop_mark_lines(self):
        svg = print_furniture_svg(geometry_for("A4"), crop_marks=True, registration=False)
        assert svg.count("<line") == 8  # two perpendicular marks per corner

    def test_crop_marks_stay_within_the_media_box(self):
        import re

        g = geometry_for("A4")
        svg = print_furniture_svg(g, registration=False, colour_bar=False, info=False)
        coords = [float(v) for v in re.findall(r'(?:x|y)\d="([\d.]+)"', svg)]
        assert coords and max(coords) <= max(g.media_w_mm, g.media_h_mm) + 0.01
        assert min(coords) >= -0.01

    def test_toggles_remove_pieces(self):
        g = geometry_for("A4")
        none = print_furniture_svg(
            g, crop_marks=False, registration=False, colour_bar=False, info=False
        )
        assert "<line" not in none and "<circle" not in none and "<text" not in none
        with_marks = print_furniture_svg(g, registration=True, info=True)
        assert "<circle" in with_marks  # registration targets
        assert "<text" in with_marks  # info label

    def test_colour_bar_has_process_and_brand_swatches(self):
        svg = print_furniture_svg(geometry_for("A4"), brand=BRAND, colour_bar=True)
        # Four process patches (C/M/Y/K) are derived via cmyk_to_hex, plus brand.
        assert cmyk_to_hex(1, 0, 0, 0) in svg  # cyan
        assert "#0E5BFF" in svg  # brand primary swatch

    def test_info_label_is_escaped(self):
        svg = print_furniture_svg(geometry_for("A4"), info_label="<script>x</script>")
        assert "<script>" not in svg and "&lt;script&gt;" in svg

    def test_deterministic(self):
        g = geometry_for("A4")
        assert print_furniture_svg(g, brand=BRAND) == print_furniture_svg(g, brand=BRAND)


# ---------------------------------------------------------------------------
# Bleed wrapper
# ---------------------------------------------------------------------------


class TestToPrintProduction:
    def _trim(self) -> str:
        return build_certificate_html(
            swimmer_name="Eira Hughes",
            event_label="200m Freestyle",
            time_str="2:08.41",
            achievement_headline="New Personal Best",
            meet_name="Welsh Open",
            meet_date="7 June 2026",
            club_name="Test SC",
            brand=BRAND,
        )

    def test_wraps_with_media_box_bleed_and_marks(self):
        g = PrintGeometry(trim_w_mm=210, trim_h_mm=296, bleed_mm=3, mark_len_mm=4)
        out = to_print_production(self._trim(), g, bleed_bg="#FDFBF6", brand=BRAND)
        assert "@page { size: 224mm 310mm" in out  # 210+14 x 296+14
        assert "mh-print-marks" in out
        assert "body::before" in out  # the bled-background rectangle
        assert "#FDFBF6" in out  # bleed colour applied

    def test_artwork_is_preserved_unmodified(self):
        g = PrintGeometry(trim_w_mm=210, trim_h_mm=296)
        trim = self._trim()
        out = to_print_production(trim, g)
        assert "Eira Hughes" in out and "200m Freestyle" in out and "2:08.41" in out
        # The original trim doc is untouched (no marks injected into the source).
        assert "mh-print-marks" not in trim

    def test_no_unfilled_placeholders(self):
        g = PrintGeometry(trim_w_mm=210, trim_h_mm=296)
        out = to_print_production(self._trim(), g)
        assert "{{" not in out and "}}" not in out

    def test_self_hosted_fonts_survive(self):
        g = PrintGeometry(trim_w_mm=210, trim_h_mm=296)
        out = to_print_production(self._trim(), g)
        assert "fonts.googleapis.com" not in out and "gstatic" not in out
        assert "file://" in out and ".woff2" in out

    def test_idempotent(self):
        g = PrintGeometry(trim_w_mm=210, trim_h_mm=296)
        once = to_print_production(self._trim(), g)
        assert to_print_production(once, g) == once

    def test_escaping_preserved_through_wrap(self):
        trim = build_certificate_html(
            swimmer_name='<script>alert("x")</script>',
            event_label="E",
            time_str="T",
            achievement_headline="H",
            meet_name="M",
            meet_date="D",
            club_name="C",
            brand=BRAND,
        )
        out = to_print_production(trim, PrintGeometry(trim_w_mm=210, trim_h_mm=296))
        assert "<script>" not in out and "&lt;script&gt;" in out

    def test_custom_sheet_selector(self):
        html = "<html><head></head><body><div class='card-root'>hi</div></body></html>"
        out = to_print_production(
            html, PrintGeometry(trim_w_mm=100, trim_h_mm=100), sheet_selector=".card-root"
        )
        assert ".card-root {" in out and "mh-print-marks" in out


# ---------------------------------------------------------------------------
# Print-production builders
# ---------------------------------------------------------------------------


class TestPrintBuilders:
    def test_certificate_print_html(self):
        html = _cert_html()
        assert "mh-print-marks" in html
        assert "{{" not in html and "}}" not in html
        assert "Eira Hughes" in html
        assert "@page { size: 224mm 310mm" in html
        assert "PB CERTIFICATE" in html  # info label

    def test_poster_print_html_has_layered_bleed(self):
        html = _poster_html()
        assert "mh-print-marks" in html
        assert "{{" not in html
        # Layered bleed bg (branded top strip / ink bottom / paper) for the
        # edge-to-edge masthead + footer bands.
        assert "linear-gradient" in html
        assert "#0E5BFF" in html  # brand primary in the top bleed strip

    def test_certificate_print_escapes_injection(self):
        html = _cert_html(swimmer_name="<b>x</b>")
        assert "<b>x</b>" not in html and "&lt;b&gt;x&lt;/b&gt;" in html

    def test_crop_marks_can_be_disabled(self):
        # The crop-mark group is uniquely flagged with stroke-linecap="butt"
        # (registration crosshairs use their own group), so toggling crop marks
        # off removes that group while the overlay container stays.
        on = _cert_html(crop_marks=True)
        off = _cert_html(crop_marks=False)
        assert "mh-print-marks" in on and "mh-print-marks" in off
        assert 'stroke-linecap="butt"' in on
        assert 'stroke-linecap="butt"' not in off


# ---------------------------------------------------------------------------
# DeviceCMYK conversion — honest when Ghostscript is absent
# ---------------------------------------------------------------------------


class TestCmykConvert:
    def test_missing_source_raises_filenotfound(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            cmyk_convert_pdf(tmp_path / "nope.pdf")

    def test_honest_error_without_ghostscript(self, tmp_path, monkeypatch):
        import mediahub.graphic_renderer.print_export as pe

        monkeypatch.setattr(pe, "_gs_binary", lambda: None)
        src = tmp_path / "in.pdf"
        src.write_bytes(b"%PDF-1.4\n%fake\n")
        assert pe.ghostscript_available() is False
        with pytest.raises(CmykUnavailable):
            pe.cmyk_convert_pdf(src)

    @_GHOSTSCRIPT
    @_PLAYWRIGHT
    def test_real_devicecmyk_conversion(self, tmp_path):
        out = tmp_path / "cert.pdf"
        export_certificate_print_pdf(
            out,
            cmyk=True,
            swimmer_name="Eira Hughes",
            event_label="200m Freestyle",
            time_str="2:08.41",
            achievement_headline="New PB",
            meet_name="Welsh Open",
            meet_date="7 June 2026",
            club_name="Test SC",
            brand=BRAND,
        )
        data = out.read_bytes()
        assert data[:5] == b"%PDF-"
        assert b"DeviceCMYK" in data or b"/CMYK" in data


# ---------------------------------------------------------------------------
# Real Playwright print-to-PDF renders (media box must be bleed-expanded)
# ---------------------------------------------------------------------------


def _assert_real_pdf(path: Path):
    assert path.exists()
    data = path.read_bytes()
    assert data[:5] == b"%PDF-"
    assert len(data) > 5 * 1024, f"suspiciously small PDF: {len(data)} bytes"


def _page_size_pt(path: Path):
    try:
        from pypdf import PdfReader
    except Exception:
        return None
    box = PdfReader(str(path)).pages[0].mediabox
    return float(box.width), float(box.height)


@_PLAYWRIGHT
def test_render_certificate_print_pdf(tmp_path):
    out = tmp_path / "cert_print.pdf"
    export_certificate_print_pdf(
        out,
        swimmer_name="Eira Hughes",
        event_label="200m Freestyle",
        time_str="2:08.41",
        achievement_headline="New Personal Best",
        meet_name="Welsh Open",
        meet_date="7 June 2026",
        club_name="Test SC",
        brand=BRAND,
    )
    _assert_real_pdf(out)
    assert not list(tmp_path.glob("*.render.html"))  # throwaway cleaned up
    size = _page_size_pt(out)
    if size is not None:
        # 224mm x 310mm in points (1mm = 72/25.4 pt), tolerance ±2pt.
        assert abs(size[0] - 224 * 72 / 25.4) < 2
        assert abs(size[1] - 310 * 72 / 25.4) < 2


@_PLAYWRIGHT
def test_render_poster_print_pdf(tmp_path):
    out = tmp_path / "poster_print.pdf"
    export_poster_print_pdf(
        out,
        title="The Weekend in Numbers",
        meet_name="Welsh Open",
        stat_lines=[("PBs", "14"), ("Medals", "6")],
        highlight_rows=[{"swimmer": "A", "event": "50 Free", "time": "29.9", "note": "PB"}],
        club_name="Test SC",
        brand=BRAND,
    )
    _assert_real_pdf(out)


@_PLAYWRIGHT
def test_custom_bleed_changes_media_box(tmp_path):
    out = tmp_path / "cert_bleed5.pdf"
    export_certificate_print_pdf(
        out,
        bleed_mm=5,
        swimmer_name="A",
        event_label="E",
        time_str="T",
        achievement_headline="H",
        meet_name="M",
        meet_date="D",
        club_name="C",
        brand=BRAND,
    )
    _assert_real_pdf(out)
    size = _page_size_pt(out)
    if size is not None:
        # 210 + 2*(5+4) = 228mm wide, 296 + 18 = 314mm tall.
        assert abs(size[0] - 228 * 72 / 25.4) < 2
        assert abs(size[1] - 314 * 72 / 25.4) < 2


# ---------------------------------------------------------------------------
# Web surface — CMYK separations endpoint + print-mode guards
# ---------------------------------------------------------------------------


def _run_payload(run_id: str, profile_id: str) -> dict:
    return {
        "run_id": run_id,
        "profile_id": profile_id,
        "meet": {"name": "Spring Open", "start_date": "2026-06-06", "swimmers": {}, "results": []},
        "cards": [],
        "recognition_report": {"ranked_achievements": []},
    }


@pytest.fixture
def web_env(web_module, client):
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

    run_id = "run-g117-" + uuid.uuid4().hex[:8]
    (web_module.RUNS_DIR / f"{run_id}.json").write_text(
        json.dumps(_run_payload(run_id, "org-alpha"))
    )
    conn = web_module._db()
    conn.execute(
        "INSERT OR REPLACE INTO runs (id, created_at, status, profile_id, meet_name, file_name)"
        " VALUES (?, datetime('now'), 'done', ?, ?, ?)",
        (run_id, "org-alpha", "Spring Open", "spring.hy3"),
    )
    conn.commit()
    conn.close()

    return {"client": client, "run_id": run_id}


def _pin(client, profile_id):
    r = client.post("/api/organisation/active", data={"profile_id": profile_id})
    assert r.status_code == 200, r.get_json()


class TestCmykSeparationsRoute:
    def test_returns_separations_geometry_and_gs_flag(self, web_env):
        c = web_env["client"]
        _pin(c, "org-alpha")
        r = c.get(f"/pack/{web_env['run_id']}/print/separations.json")
        assert r.status_code == 200
        body = r.get_json()
        assert body["colour_mode"].startswith("CMYK")
        assert body["geometry"]["bleed_mm"] == 3.0
        assert body["geometry"]["media_mm"] == [224.0, 311.0]
        assert isinstance(body["ghostscript_available"], bool)
        roles = [row["role"] for row in body["separations"]]
        assert "primary" in roles and "ink" in roles and "paper" in roles
        prim = next(row for row in body["separations"] if row["role"] == "primary")
        assert prim["hex"] == "#0E5BFF"

    def test_cross_org_is_404(self, web_env):
        c = web_env["client"]
        _pin(c, "org-beta")
        assert c.get(f"/pack/{web_env['run_id']}/print/separations.json").status_code == 404


class TestPrintModeCertificateRoute:
    def test_print_param_still_honest_with_no_approved_cards(self, web_env):
        c = web_env["client"]
        _pin(c, "org-alpha")
        r = c.get(f"/pack/{web_env['run_id']}/certificates.zip?print=1&bleed=4")
        assert r.status_code == 200
        assert b"No approved cards yet" in r.data

    def test_print_param_cross_org_404(self, web_env):
        c = web_env["client"]
        _pin(c, "org-beta")
        assert c.get(f"/pack/{web_env['run_id']}/certificates.zip?print=1").status_code == 404

    def test_mid_run_cmyk_failure_ships_rgb_zip_with_note(self, web_env, monkeypatch):
        """If Ghostscript errors mid-run, the intact RGB print PDFs still ship
        as a 200 zip with a CMYK-NOTE.txt naming the fallback — never a 500."""
        import io
        import os
        import zipfile

        c = web_env["client"]
        _pin(c, "org-alpha")
        run_id = web_env["run_id"]
        runs_dir = Path(os.environ["RUNS_DIR"])
        payload = json.loads((runs_dir / f"{run_id}.json").read_text())
        payload["recognition_report"]["ranked_achievements"] = [
            {
                "rank": 1,
                "quality_band": "elite",
                "priority": 0.9,
                "safe_to_post": {"level": "safe", "reason": "ok"},
                "achievement": {
                    "swim_id": "swim-1",
                    "swimmer_name": "Maya Patel",
                    "event": "100m Freestyle",
                    "headline": "New PB",
                    "raw_facts": {"time": "59.99"},
                },
            }
        ]
        (runs_dir / f"{run_id}.json").write_text(json.dumps(payload))
        from mediahub.workflow.status import CardStatus
        from mediahub.workflow.store import WorkflowStore

        WorkflowStore(runs_dir).set_status(run_id, "swim-1", CardStatus.APPROVED)

        import mediahub.graphic_renderer.print_export as pe

        def fake_export(output_path, *, cmyk=False, **kw):
            # The real function renders the RGB PDF first, then converts —
            # so on a CMYK failure the RGB file is already on disk.
            Path(output_path).write_bytes(b"%PDF-1.4 fake rgb")
            if cmyk:
                raise pe.CmykUnavailable("Ghostscript CMYK conversion failed: boom")
            return Path(output_path)

        monkeypatch.setattr(pe, "ghostscript_available", lambda: True)
        monkeypatch.setattr(pe, "export_certificate_print_pdf", fake_export)

        r = c.get(f"/pack/{run_id}/certificates.zip?print=1&cmyk=1")
        assert r.status_code == 200
        zf = zipfile.ZipFile(io.BytesIO(r.data))
        names = zf.namelist()
        assert any(n.endswith(".pdf") for n in names)
        assert "certificates/CMYK-NOTE.txt" in names
        note = zf.read("certificates/CMYK-NOTE.txt").decode()
        assert "failed at run time" in note and "Maya-Patel" in note
