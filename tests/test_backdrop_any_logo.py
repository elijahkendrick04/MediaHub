"""Backdrop robustness — ANY uploaded logo sits properly behind, or degrades cleanly.

The signed-in brand backdrop (``.mh-bg-canvas``) must support whatever a club
uploads — any format, colour, shape, or size — and *never* break: no broken-image,
no 404, and crucially no solid ink block (the failure mode where a CSS
``mask-image`` 404s and the browser paints the knockout element's full rectangle).

These tests pin that guarantee end-to-end:

  * many raster formats rasterise to a clean PNG silhouette and the ``?bg=1`` route
    serves them with an explicit image content-type (nosniff-safe);
  * a format we can't rasterise (PDF / corrupt / exotic) makes the ``?bg=1`` route
    serve a TRANSPARENT PIXEL (HTTP 200), never a 404 — so the mask/background
    always loads and the element hides cleanly;
  * the builder picks the first logo that actually yields a paintable silhouette,
    so an unrenderable upload never wins over a usable sibling;
  * colour / shape / size extremes all produce a finite, in-band treatment with no
    exception.

Presentation-only — the deterministic engine and AI surfaces are untouched.
"""

from __future__ import annotations

import io
import re

import pytest
from PIL import Image, ImageDraw

from mediahub.brand import logos as L
from mediahub.web import web as webmod


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("SWIM_CONTENT_PROFILES_DIR", str(tmp_path / "club_profiles"))
    (tmp_path / "club_profiles").mkdir(parents=True, exist_ok=True)
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(webmod, "DATA_DIR", tmp_path, raising=False)
    app = webmod.app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _img(w=240, h=180, *, alpha=True, paint=None) -> Image.Image:
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0) if alpha else (255, 255, 255, 255))
    (paint or _two_tone)(ImageDraw.Draw(im), w, h)
    return im


def _two_tone(d, w, h):
    d.rectangle([20, 15, w - 20, h - 15], fill=(40, 120, 200, 255))
    d.polygon([(w // 2, 24), (w - 30, h - 24), (30, h - 24)], fill=(232, 150, 60, 255))


def _store_bytes(pid: str, lid: str, ext: str, data: bytes, mime: str) -> dict:
    """Write a raw logo file under the profile's logos dir and return its meta."""
    d = L.logos_dir(pid)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{lid}.{ext}").write_bytes(data)
    return {"logo_id": lid, "mime": mime, "original_filename": f"{lid}.{ext}"}


def _store_img(pid: str, lid: str, ext: str, im: Image.Image, mime: str, fmt: str) -> dict:
    buf = io.BytesIO()
    if fmt in ("JPEG",):  # JPEG can't hold an alpha channel
        im = im.convert("RGB")
    im.save(buf, fmt)
    return _store_bytes(pid, lid, ext, buf.getvalue(), mime)


def _make_org(pid: str, logos: list[dict], *, brand: str = "#24507f", url: str = "") -> None:
    from mediahub.web.club_profile import ClubProfile, save_profile

    prof = ClubProfile(
        profile_id=pid,
        display_name="Any-Logo SC",
        brand_primary=brand,
        brand_capture_status="ok",
    )
    prof.brand_logos = logos
    if url:
        prof.brand_logo_url = url
    save_profile(prof)


def _home(client, pid: str) -> str:
    with client.session_transaction() as s:
        s["active_profile_id"] = pid
    resp = client.get("/", follow_redirects=True)
    assert resp.status_code == 200, f"home → {resp.status_code}"
    return resp.get_data(as_text=True)


def _mark(html: str):
    m = re.search(r'<span class="(mh-bg-mark[^"]*)" style="([^"]+)"', html)
    return (m.group(1), m.group(2)) if m else (None, None)


def _bg_url(style: str) -> str:
    m = re.search(r"(?:background-image|mask-image):url\('([^']+)'\)", style)
    assert m, f"no backdrop asset url in {style!r}"
    return m.group(1)


def _valid_treatment(t: dict) -> None:
    assert t.get("mode") in ("image", "knockout"), t
    op = float(t["opacity"])
    assert 0.0 < op <= 1.0, t
    blur = int(t["blur"])
    assert 8 <= blur <= 28, t  # modest, identifiable band (clamped by the builder too)


# --------------------------------------------------------------------------- #
# format coverage — everything Pillow can open rasterises to a paintable PNG
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "ext,mime,fmt,alpha",
    [
        ("png", "image/png", "PNG", True),
        ("webp", "image/webp", "WEBP", True),
        ("gif", "image/gif", "GIF", True),
        ("jpg", "image/jpeg", "JPEG", False),
        ("bmp", "image/bmp", "BMP", False),
        ("tiff", "image/tiff", "TIFF", True),
        ("ico", "image/vnd.microsoft.icon", "ICO", True),
        ("ppm", "image/x-portable-pixmap", "PPM", False),
        ("tga", "application/octet-stream", "TGA", False),  # octet MIME, still rasterisable
    ],
)
def test_format_rasterises_and_serves_as_image(client, ext, mime, fmt, alpha):
    im = _img(alpha=alpha)
    if fmt == "ICO":
        im = im.resize((64, 64))
    meta = _store_img("org-fmt", f"l_{ext}", ext, im, mime, fmt)
    _make_org("org-fmt", [meta])

    # Silhouette is a real PNG (or SVG); treatment is finite + in-band.
    sil = L.logo_bg_silhouette_path("org-fmt", meta["logo_id"])
    assert sil is not None and sil.suffix.lower() in (".png", ".svg"), ext
    _valid_treatment(L.logo_bg_treatment("org-fmt", meta["logo_id"]))

    # End-to-end: the backdrop renders and its asset serves 200 as a real image.
    html = _home(client, "org-fmt")
    assert 'class="mh-bg-canvas"' in html
    asset = client.get(_bg_url(_mark(html)[1]))
    assert asset.status_code == 200
    assert asset.headers["Content-Type"].startswith("image/")


def test_heic_is_supported_when_plugin_present(client):
    """Apple HEIC (a phone's default export) — supported once pillow_heif is
    registered, which logos.py does at import. Detect by whether the opener got
    registered, not the (version-specific) features flag."""
    if ".heic" not in Image.registered_extensions():
        pytest.skip("pillow_heif/libheif not available in this environment")
    meta = _store_img("org-heic", "l_heic", "heic", _img(), "image/heic", "HEIF")
    _make_org("org-heic", [meta])
    sil = L.logo_bg_silhouette_path("org-heic", "l_heic")
    assert sil is not None and sil.suffix.lower() == ".png"
    asset = client.get(_bg_url(_mark(_home(client, "org-heic"))[1]))
    assert asset.status_code == 200 and asset.headers["Content-Type"].startswith("image/")


def test_svg_logo_serves_as_svg(client):
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        '<circle cx="50" cy="50" r="40" fill="#1e63c8"/></svg>'
    )
    meta = _store_bytes("org-svg", "l_svg", "svg", svg.encode(), "image/svg+xml")
    _make_org("org-svg", [meta])
    asset = client.get(_bg_url(_mark(_home(client, "org-svg"))[1]) )
    assert asset.status_code == 200
    assert "svg" in asset.headers["Content-Type"]


def test_logo_serve_headers_private_and_sandboxed(client):
    """Session-gated logo responses must never be shared-cacheable
    ('private', not 'public'), and every logo/silhouette serve carries
    CSP sandbox so a script-bearing uploaded SVG can't execute on direct
    navigation (global CSP allows 'unsafe-inline')."""
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
        "<script>alert(1)</script>"
        '<circle cx="50" cy="50" r="40" fill="#1e63c8"/></svg>'
    )
    meta = _store_bytes("org-svgx", "l_svgx", "svg", svg.encode(), "image/svg+xml")
    _make_org("org-svgx", [meta])
    with client.session_transaction() as s:
        s["active_profile_id"] = "org-svgx"

    # ?bg silhouette: private cache + sandbox.
    bg = client.get("/organisation/setup/logo/l_svgx?bg=1")
    assert bg.status_code == 200
    assert bg.headers.get("Cache-Control", "").startswith("private"), (
        bg.headers.get("Cache-Control")
    )
    assert bg.headers.get("Content-Security-Policy") == "sandbox"

    # Plain serve (SVG passthrough): sandbox present.
    raw = client.get("/organisation/setup/logo/l_svgx")
    assert raw.status_code == 200
    assert raw.headers.get("Content-Security-Policy") == "sandbox"

    # The sibling per-profile route too.
    raw2 = client.get("/organisation/org-svgx/logo/l_svgx")
    assert raw2.status_code == 200
    assert raw2.headers.get("Content-Security-Policy") == "sandbox"


# --------------------------------------------------------------------------- #
# the never-break guarantee — unrenderable / corrupt → transparent pixel, 200
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "ext,mime,data",
    [
        ("pdf", "application/pdf", b"%PDF-1.4\n%fake pdf, not an image\n"),
        ("png", "image/png", b"\x89PNG\r\n\x1a\nGARBAGE-not-a-real-png"),  # corrupt
        ("jxl", "image/jxl", b"\x00\x00\x00\x0cJXL \r\n\x87\n garbage"),  # can't open
        ("eps", "application/postscript", b"%!PS-Adobe EPSF fake"),  # no ghostscript
        ("png", "image/png", b""),  # zero-byte
    ],
)
def test_unrenderable_logo_serves_transparent_pixel_not_404(client, ext, mime, data):
    meta = _store_bytes("org-bad", "l_bad", ext, data, mime)
    _make_org("org-bad", [meta])

    # The silhouette can't be produced → None (never a raw, un-paintable file).
    assert L.logo_bg_silhouette_path("org-bad", "l_bad") is None

    # The ?bg=1 route must serve a transparent PNG with 200 — NEVER a 404 (which
    # CSS treats as "no mask" → a solid ink block).
    with client.session_transaction() as s:
        s["active_profile_id"] = "org-bad"
    from flask import url_for

    with webmod.app.test_request_context():
        u = url_for("organisation_setup_logo_serve", logo_id="l_bad", bg=1)
    resp = client.get(u)
    assert resp.status_code == 200, ext
    assert resp.headers["Content-Type"] == "image/png"
    body = resp.get_data()
    assert body.startswith(b"\x89PNG"), "must be a real (transparent) PNG"
    # a 1×1 transparent pixel is tiny — proves it's the fallback, not the logo
    assert len(body) < 200


def test_unrenderable_logo_falls_back_to_the_brand_wash(client):
    """A club whose ONLY logo is unrenderable still gets a tasteful backdrop: the
    soft brand-coloured wash (better than nothing), with NO crest mark — and never
    a broken asset or a solid ink block."""
    meta = _store_bytes("org-onlybad", "l_bad", "pdf", b"%PDF-1.4 not an image", "application/pdf")
    _make_org("org-onlybad", [meta], brand="#24507f")  # brand colour, no website logo
    html = _home(client, "org-onlybad")
    classes, _style = _mark(html)
    assert classes is None  # the PDF can't be painted → no crest mark
    assert 'class="mh-bg-canvas"' in html  # but the canvas + brand wash render
    assert 'class="mh-bg-wash"' in html
    assert "--mh-bg-brand:#24507f" in html


def test_builder_picks_a_renderable_logo_over_an_unrenderable_sibling(client):
    """Given a usable PNG and an unrenderable PDF, the backdrop uses the PNG."""
    bad = _store_bytes("org-mix", "l_pdf", "pdf", b"%PDF-1.4 nope", "application/pdf")
    good = _store_img("org-mix", "l_png", "png", _img(200, 200), "image/png", "PNG")
    _make_org("org-mix", [bad, good])  # bad listed first

    html = _home(client, "org-mix")
    classes, style = _mark(html)
    assert classes, "a backdrop should render from the usable PNG"
    url = _bg_url(style)
    assert "l_png" in url and "l_pdf" not in url
    asset = client.get(url)
    assert asset.status_code == 200 and asset.headers["Content-Type"].startswith("image/")


# --------------------------------------------------------------------------- #
# colour extremes — all map to a finite, visible treatment
# --------------------------------------------------------------------------- #
def _solid(colour):
    def paint(d, w, h):
        m = max(1, min(w, h) // 8)  # relative margin so tiny canvases stay valid
        d.ellipse([m, m, w - m, h - m], fill=colour)

    return paint


@pytest.mark.parametrize(
    "name,paint",
    [
        ("white", _solid((255, 255, 255, 255))),
        ("black", _solid((0, 0, 0, 255))),
        ("near-black-navy", _solid((10, 16, 30, 255))),
        ("neon", _solid((10, 255, 60, 255))),
        ("mid-grey", _solid((128, 128, 128, 255))),
        ("two-tone-bright", _two_tone),
    ],
)
def test_colour_extremes_give_a_finite_visible_treatment(client, name, paint):
    meta = _store_img(f"org-col-{name}", "l", "png", _img(paint=paint), "image/png", "PNG")
    _make_org(f"org-col-{name}", [meta])
    _valid_treatment(L.logo_bg_treatment(f"org-col-{name}", "l"))
    # And it renders end-to-end without error.
    assert 'class="mh-bg-canvas"' in _home(client, f"org-col-{name}")


# --------------------------------------------------------------------------- #
# shape / size extremes — no exception, finite treatment, bounded work
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "w,h,paint",
    [
        (1200, 60, _two_tone),  # extreme wide wordmark
        (60, 1200, _two_tone),  # extreme tall lockup
        (8, 8, _solid((40, 120, 200, 255))),  # tiny favicon
        (4000, 4000, _solid((40, 120, 200, 255))),  # huge (must be thumbnailed)
        (400, 6, lambda d, w, h: d.rectangle([0, 2, w, 4], fill=(40, 120, 200, 255))),  # 1px-thin line
    ],
)
def test_shape_and_size_extremes_do_not_break(client, w, h, paint):
    pid = f"org-shape-{w}x{h}"
    meta = _store_img(pid, "l", "png", _img(w, h, paint=paint), "image/png", "PNG")
    _make_org(pid, [meta])
    # No exception, finite in-band treatment.
    _valid_treatment(L.logo_bg_treatment(pid, "l"))
    # Renders, centred, and its asset serves as an image.
    html = _home(client, pid)
    _classes, style = _mark(html)
    assert "left:50%" in style and "top:50%" in style
    asset = client.get(_bg_url(style))
    assert asset.status_code == 200 and asset.headers["Content-Type"].startswith("image/")


def test_one_pixel_tall_silhouette_does_not_raise(tmp_path):
    """A silhouette trimmed to 1px in a dimension makes np.diff empty (→ NaN). The
    treatment must guard this and return a finite, in-band result, never raise."""
    sil = tmp_path / "line_bg.png"
    im = Image.new("RGBA", (400, 1), (0, 0, 0, 0))
    for x in range(0, 400, 3):  # a dashed 1-px line → real ink, height 1
        im.putpixel((x, 0), (40, 120, 200, 255))
    im.save(sil)
    t = L._treatment_for_silhouette(sil)
    _valid_treatment(t)
