"""Signed-in brand backdrop — the org's real logo, auto-balanced for any upload.

Every signed-in page carries a brand backdrop (``.mh-bg-canvas``) that paints
the org's PRIMARY logo as a watermark crest CENTRED behind the content. The
contract that makes it work — and look professional — for WHATEVER a club
uploads (a bright filled badge, a near-black line crest, a wide lockup) is:

  * it paints the logo's REAL artwork (``background-image`` off the ``?bg=1``
    route, which keeps full colour + detail), NOT a flat single-tint silhouette
    that flattens a detailed crest to an unrecognisable blob;
  * ``background-size: contain`` preserves any aspect ratio (no squashing);
  * a per-logo *adaptive treatment* (``logo_bg_treatment``) sets opacity /
    brightness / saturation / halo inline, so a bright, dense crest is toned
    down (never dazzles) while a dark, faint one is lifted (never vanishes) —
    both landing at a similar, tasteful presence.

These tests pin that contract, prove the auto-balance, and guard against
regressing to the old flat-tint approach. Presentation-only — the deterministic
engine and AI surfaces are untouched. Mirrors ``tests/test_ui_site_wide_effects``.
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


def _default_paint(d: ImageDraw.ImageDraw, w: int, h: int) -> None:
    d.rectangle([20, 15, w - 20, h - 15], fill=(40, 120, 200, 255))


def _make_org(
    pid: str,
    *,
    brand: str = "#24507f",
    with_logo: bool = True,
    logo_paint: Optional[Painter] = None,
) -> None:
    """Save a ready org, optionally with a real PNG logo (transparent border so
    the ``?bg=1`` keying produces clean artwork)."""
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
        im = Image.new("RGBA", (240, 180), (0, 0, 0, 0))  # transparent canvas
        (logo_paint or _default_paint)(ImageDraw.Draw(im), 240, 180)
        im.save(d / "logo01.png")
        prof.brand_logos = [{"logo_id": "logo01", "mime": "image/png"}]
    save_profile(prof)


def _home(client, pid: str) -> str:
    with client.session_transaction() as s:
        s["active_profile_id"] = pid
    resp = client.get("/", follow_redirects=True)
    assert resp.status_code == 200, f"home → {resp.status_code}"
    return resp.get_data(as_text=True)


def _mark_style(html: str) -> str:
    m = re.search(r'<span class="mh-bg-mark" style="([^"]+)"', html)
    assert m, "backdrop crest mark not found"
    return m.group(1)


def _mark_opacity(style: str) -> float:
    m = re.search(r"--op:([0-9.]+)", style)
    assert m, f"inline --op not found in {style!r}"
    return float(m.group(1))


def test_backdrop_paints_the_real_logo_artwork(client):
    """One watermark crest, painted as the logo's real image off ?bg=1."""
    _make_org("org-a", brand="#24507f", with_logo=True)
    html = _home(client, "org-a")

    assert 'class="mh-bg-canvas"' in html
    assert "aria-hidden" in html  # decorative — hidden from the a11y tree
    assert html.count('class="mh-bg-mark"') == 1  # a single, confident crest

    m = re.search(r"background-image:url\('([^']+)'\)", html)
    assert m, "crest must be painted via background-image (real artwork)"
    assert "bg=1" in m.group(1), "must use the colour-preserving ?bg=1 silhouette"

    asset = client.get(m.group(1))
    assert asset.status_code == 200
    assert asset.headers["Content-Type"].startswith("image/")
    assert len(asset.get_data()) > 0


def test_css_contract_is_future_proof_for_any_logo(client):
    """Centred, aspect-preserved, adaptively treated — and no flat-tint regress."""
    _make_org("org-b", brand="#24507f", with_logo=True)
    html = _home(client, "org-b")
    style = _mark_style(html)

    # Centred behind the content.
    assert "left:50%" in style and "top:50%" in style
    # Any aspect ratio survives (wide lockup / tall shield never squashed).
    assert "background-size: contain" in html
    # Per-logo adaptive treatment is applied inline.
    assert "--op:" in style
    assert "filter:" in style and "brightness(" in style and "drop-shadow(" in style
    # Stays strictly decorative, behind content.
    assert "pointer-events: none" in html

    # REGRESSION GUARDS — the old flat single-tint silhouette rendered detailed
    # and thin real crests invisible. It must not creep back: the logo is never
    # painted through a tint mask.
    assert "--mh-bg-tint" not in html
    assert "mask-image:url('" not in html
    assert "-webkit-mask-image:url('" not in html


def test_bright_and_dark_logos_balance_to_similar_presence(client):
    """The core auto-balance: a heavy bright logo sits BELOW a faint dark one."""

    def bright(d, w, h):  # dense, saturated, opaque block → high visual weight
        d.rectangle([8, 8, w - 8, h - 8], fill=(40, 120, 230, 255))

    def dark(d, w, h):  # a few thin near-black strokes → low visual weight
        for x in range(24, w - 16, 26):
            d.line([x, 18, x, h - 18], fill=(15, 21, 33, 255), width=3)

    _make_org("org-bright", brand="#1659c8", logo_paint=bright)
    _make_org("org-dark", brand="#0e5c3a", logo_paint=dark)

    op_bright = _mark_opacity(_mark_style(_home(client, "org-bright")))
    op_dark = _mark_opacity(_mark_style(_home(client, "org-dark")))

    assert op_bright < op_dark, (
        f"bright/dense logo (op={op_bright}) should be toned down below the "
        f"faint dark logo (op={op_dark})"
    )


def test_no_brand_colour_drops_the_wash_but_keeps_the_crest(client):
    _make_org("org-c", brand="", with_logo=True)
    html = _home(client, "org-c")
    assert 'class="mh-bg-canvas"' in html
    assert 'class="mh-bg-mark"' in html
    assert 'class="mh-bg-wash"' not in html  # no colour → no ambient wash


def test_no_logo_means_no_backdrop(client):
    _make_org("org-d", brand="#24507f", with_logo=False)
    html = _home(client, "org-d")
    assert 'class="mh-bg-canvas"' not in html
