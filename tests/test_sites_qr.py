"""Microsite engine (roadmap 1.16) — build 3: the brand-safe QR generator."""

from __future__ import annotations

import pytest

from mediahub.sites import qr


@pytest.fixture(autouse=True)
def _data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    return tmp_path


def test_segno_available():
    assert qr.is_available() is True


def test_brand_colors_contrast_guard():
    # navy on white clears the scanner-safe bar → kept
    dark, light = qr.brand_qr_colors({"--mh-primary": "#0A2540"})
    assert dark == "#0A2540" and light == "#FFFFFF"
    # a low-contrast brand (gold on white) falls back to black for scannability
    dark2, _ = qr.brand_qr_colors({"--mh-primary": "#FFB81C"})
    assert dark2 == "#000000"
    # explicit override that fails contrast is also rejected
    dark3, _ = qr.brand_qr_colors({}, dark="#EEEEEE")
    assert dark3 == "#000000"


def test_qr_svg_uses_brand_dark():
    svg = qr.qr_svg("https://x.example/site/abc", role_vars={"--mh-primary": "#0A2540"})
    assert svg.lstrip().startswith("<svg")
    assert "0A2540" in svg.upper()


def test_qr_png_and_pdf_bytes():
    png = qr.qr_png("https://x.example", role_vars={"--mh-primary": "#0A2540"})
    assert png[:4] == b"\x89PNG"
    pdf = qr.qr_pdf("https://x.example")
    assert pdf[:5] == b"%PDF-"


def test_export_qr_is_cached_and_typed():
    a, mime = qr.export_qr("https://x.example/abc", "png", role_vars={"--mh-primary": "#0A2540"})
    b, _ = qr.export_qr("https://x.example/abc", "png", role_vars={"--mh-primary": "#0A2540"})
    assert a == b  # content-addressed cache hit → identical bytes
    assert mime == "image/png"
    svg, smime = qr.export_qr("https://x.example/abc", "svg")
    assert smime == "image/svg+xml" and svg.lstrip().startswith(b"<svg")
    _pdf, pmime = qr.export_qr("https://x.example/abc", "pdf")
    assert pmime == "application/pdf"


def test_unknown_format_defaults_png():
    _b, mime = qr.export_qr("https://x.example", "bogus")
    assert mime == "image/png"
