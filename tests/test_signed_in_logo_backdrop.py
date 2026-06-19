"""Signed-in brand backdrop — the org's logo, future-proof for any upload.

Every signed-in page carries a brand backdrop (``.mh-bg-canvas``) that paints
the org's PRIMARY logo as a watermark crest CENTRED behind the content. To stay
recognisable, professional, and readable for WHATEVER a club uploads, the
deterministic ``logo_bg_treatment`` analysis picks one of two modes:

  * **image** — a COLOURFUL logo is painted as its real artwork
    (``background-image`` off the ``?bg=1`` route, which keeps full colour +
    detail), with a per-logo opacity / brightness / saturation / halo so it
    never dazzles and never vanishes — keeping the club's colour;
  * **knockout** — a MONOCHROME logo (black / navy / grey / white / single ink)
    or an SVG we can't rasterise to measure is painted as its SHAPE in one
    light, brand-tinted ink via a CSS mask — guaranteed to read on the
    near-black page, with nothing lost since the logo was already one colour.

These tests pin the contract for both modes, prove the auto-balance, prove the
hard cases that used to fail (pure-black, SVG), and guard against regressing to
the old flat single-tint approach. Presentation-only — the deterministic engine
and AI surfaces are untouched. Mirrors ``tests/test_ui_site_wide_effects.py``.
"""

from __future__ import annotations

import re
from typing import Callable, Optional

import pytest
from PIL import Image, ImageDraw

from mediahub.web import web as webmod

Painter = Callable[[ImageDraw.ImageDraw, int, int], None]


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


def _colourful_paint(d: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """Two distinct hues → high colourfulness → image mode."""
    d.rectangle([20, 15, w - 20, h - 15], fill=(40, 120, 200, 255))
    d.polygon([(w // 2, 24), (w - 30, h - 24), (30, h - 24)], fill=(232, 130, 40, 255))


def _mono_dark_paint(d: ImageDraw.ImageDraw, w: int, h: int) -> None:
    """A single near-black ink → low colourfulness → knockout mode."""
    d.ellipse([20, 20, w - 20, h - 20], outline=(16, 26, 44, 255), width=8)
    d.polygon(
        [(w // 2 - 40, h - 50), (w // 2, 40), (w // 2 + 40, h - 50)],
        outline=(16, 26, 44, 255),
        width=6,
    )


_COLOURFUL_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<circle cx="50" cy="50" r="42" fill="none" stroke="#1e63c8" stroke-width="6"/>'
    '<circle cx="50" cy="50" r="28" fill="#d8a23a"/></svg>'
)


def _make_org(
    pid: str,
    *,
    brand: str = "#24507f",
    with_logo: bool = True,
    logo_paint: Optional[Painter] = None,
    svg_text: Optional[str] = None,
) -> None:
    from mediahub.brand import logos as L
    from mediahub.web.club_profile import ClubProfile, save_profile

    prof = ClubProfile(
        profile_id=pid,
        display_name="Backdrop SC",
        brand_primary=(brand or ""),
        brand_capture_status="ok",
    )
    if with_logo:
        d = L.logos_dir(pid)
        d.mkdir(parents=True, exist_ok=True)
        if svg_text is not None:
            (d / "logo01.svg").write_text(svg_text)
            prof.brand_logos = [{"logo_id": "logo01", "mime": "image/svg+xml"}]
        else:
            im = Image.new("RGBA", (240, 180), (0, 0, 0, 0))  # transparent canvas
            (logo_paint or _colourful_paint)(ImageDraw.Draw(im), 240, 180)
            im.save(d / "logo01.png")
            prof.brand_logos = [{"logo_id": "logo01", "mime": "image/png"}]
    save_profile(prof)


def _home(client, pid: str) -> str:
    with client.session_transaction() as s:
        s["active_profile_id"] = pid
    resp = client.get("/", follow_redirects=True)
    assert resp.status_code == 200, f"home → {resp.status_code}"
    return resp.get_data(as_text=True)


def _mark(html: str) -> tuple[str, str]:
    """Return (class_list, inline_style) of the single backdrop crest mark."""
    m = re.search(r'<span class="(mh-bg-mark[^"]*)" style="([^"]+)"', html)
    assert m, "backdrop crest mark not found"
    return m.group(1), m.group(2)


def _opacity(style: str) -> float:
    m = re.search(r"--op:([0-9.]+)", style)
    assert m, f"inline --op not found in {style!r}"
    return float(m.group(1))


def test_colourful_logo_is_painted_as_real_artwork(client):
    """A colourful logo → image mode: its real artwork off ?bg=1, never masked."""
    _make_org("org-a", brand="#24507f", with_logo=True)  # default = colourful
    html = _home(client, "org-a")
    classes, style = _mark(html)

    assert 'class="mh-bg-canvas"' in html
    assert "aria-hidden" in html
    assert html.count("mh-bg-mark mh-bg-mark--img") == 1  # one image-mode crest
    assert "mh-bg-mark--ko" not in classes

    m = re.search(r"background-image:url\('([^']+)'\)", style)
    assert m, "colourful logo must be painted via background-image (real artwork)"
    assert "bg=1" in m.group(1)
    assert "mask-image" not in style  # a colourful logo is NEVER flattened to a tint mask

    asset = client.get(m.group(1))
    assert asset.status_code == 200
    assert asset.headers["Content-Type"].startswith("image/")


def test_css_contract_is_future_proof(client):
    """Centred, aspect-preserved, adaptively treated — and no flat-tint regress."""
    _make_org("org-b", brand="#24507f", with_logo=True)
    html = _home(client, "org-b")
    _classes, style = _mark(html)

    assert "left:50%" in style and "top:53%" in style  # centred
    assert "background-size: contain" in html  # any aspect ratio survives
    assert "--op:" in style  # adaptive opacity, inline
    # Blur is a FIXED CSS rule, not an inline per-logo value — so a bad adaptive
    # number can never void the filter and leave one logo sharp.
    assert "filter: blur(16px)" in html
    assert "blur" not in style  # never inline
    # Still, not animated (no drift/breathe/orbit).
    assert "mh-bg-drift" not in html and "mh-bg-wash-orbit" not in html
    assert "pointer-events: none" in html
    # Both modes exist in the stylesheet, with a guaranteed-readable knockout ink.
    assert ".mh-bg-mark--img" in html and ".mh-bg-mark--ko" in html
    assert "--mh-bg-ink" in html
    # REGRESSION GUARD — the old flat single-tint silhouette is gone for good.
    assert "--mh-bg-tint" not in html


def test_monochrome_logo_uses_a_readable_knockout(client):
    """A near-black mono logo → knockout: its shape in a light brand-tinted ink."""
    _make_org("org-mono", brand="#10243f", with_logo=True, logo_paint=_mono_dark_paint)
    html = _home(client, "org-mono")
    classes, style = _mark(html)

    assert "mh-bg-mark--ko" in classes  # knockout, not image
    assert "background-image" not in style
    # Painted as the logo's shape via a CSS mask, tinted by the light ink.
    assert re.search(r"mask-image:url\('[^']*bg=1[^']*'\)", style)
    assert "--mh-bg-ink: #" in html or "--mh-bg-ink:#" in html


def test_unmeasurable_svg_takes_the_safe_knockout_path(client):
    """An SVG (no rasteriser to measure) → safe light knockout, never invisible."""
    _make_org("org-svg", brand="#1e63c8", with_logo=True, svg_text=_COLOURFUL_SVG)
    html = _home(client, "org-svg")
    classes, style = _mark(html)

    assert "mh-bg-mark--ko" in classes
    assert "mask-image:url(" in style
    assert "background-image" not in style


def test_heavy_logo_is_toned_down_relative_to_a_faint_one(client):
    """The auto-balance: a dense colourful logo sits BELOW a sparse one."""

    def dense(d, w, h):  # fills its box → high visual weight
        d.rectangle([6, 6, w - 6, h - 6], fill=(40, 120, 220, 255))
        d.polygon([(w // 2, 12), (w - 12, h - 12), (12, h - 12)], fill=(235, 135, 40, 255))

    def sparse(d, w, h):  # a few thin strokes → low visual weight
        for x in range(26, w - 16, 30):
            d.line([x, 16, x, h - 16], fill=(40, 120, 220, 255), width=3)
        d.line([20, h // 2, w - 20, h // 2], fill=(235, 135, 40, 255), width=3)

    _make_org("org-dense", brand="#1659c8", logo_paint=dense)
    _make_org("org-sparse", brand="#1659c8", logo_paint=sparse)

    op_dense = _opacity(_mark(_home(client, "org-dense"))[1])
    op_sparse = _opacity(_mark(_home(client, "org-sparse"))[1])
    assert (
        op_dense < op_sparse
    ), f"dense logo (op={op_dense}) should be toned down below the sparse one (op={op_sparse})"


def test_no_brand_colour_drops_the_wash_but_keeps_the_crest(client):
    _make_org("org-c", brand="", with_logo=True)
    html = _home(client, "org-c")
    assert 'class="mh-bg-canvas"' in html
    assert "mh-bg-mark" in html
    assert 'class="mh-bg-wash"' not in html  # no colour → no ambient wash


def test_no_logo_means_no_backdrop(client):
    _make_org("org-d", brand="#24507f", with_logo=False)
    html = _home(client, "org-d")
    assert 'class="mh-bg-canvas"' not in html


def test_backdrop_falls_back_to_website_captured_logo(client):
    """No uploaded logo but a captured website logo → the backdrop still shows,
    painted from the first-party MIRROR of that logo. This is what makes it work
    no matter which profile is selected, not only ones that uploaded a file."""
    from mediahub.web.club_profile import ClubProfile, save_profile

    prof = ClubProfile(
        profile_id="org-cap",
        display_name="Captured SC",
        brand_primary="#1e63c8",
        brand_capture_status="ok",
    )
    prof.brand_logo_url = "https://example.com/logo.png"  # captured, not uploaded
    save_profile(prof)

    html = _home(client, "org-cap")
    classes, style = _mark(html)
    assert 'class="mh-bg-canvas"' in html
    # Painted from the mirror serve route's ?bg=1 silhouette of the captured logo.
    assert "brand-logo?bg=1" in style
    # No network in the render path: the treatment is the neutral knockout until
    # the silhouette has been produced by the serve route on first request.
    assert "mh-bg-mark--ko" in classes


def test_nan_opacity_is_sanitised_and_blur_survives(client, monkeypatch):
    """Regression for the "one logo wasn't blurred" bug: an older build could
    cache a NaN opacity. It must not reach the CSS (an inline NaN would void the
    calc()), and the blur — now a fixed CSS rule — must still apply regardless."""
    import mediahub.brand.logos as L

    monkeypatch.setattr(
        L, "logo_bg_treatment", lambda *a, **k: {"mode": "image", "opacity": float("nan")}
    )
    _make_org("org-nan", brand="#24507f", with_logo=True)
    html = _home(client, "org-nan")
    _classes, style = _mark(html)

    assert "nan" not in style.lower()  # the NaN never reaches the markup
    m = re.search(r"--op:([0-9.]+)", style)
    assert m and 0.0 <= float(m.group(1)) <= 1.0  # sanitised to a finite opacity
    assert "filter: blur(16px)" in html  # blur is a fixed CSS rule, unaffected
