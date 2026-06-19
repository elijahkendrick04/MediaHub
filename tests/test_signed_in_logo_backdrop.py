"""Signed-in brand backdrop — the org's real logo, future-proof for any upload.

Every signed-in page carries a brand backdrop (``.mh-bg-canvas``) that paints
the org's PRIMARY logo as a watermark crest in the bottom-right corner. The
contract that makes it work for WHATEVER a club uploads — a detailed colour
crest, a near-black shield, a wide horizontal lockup — is:

  * it paints the logo's REAL artwork (``background-image`` off the ``?bg=1``
    route, which keys out the background but keeps full colour + internal
    detail), NOT a flat single-tint silhouette that flattens a detailed crest
    to an unrecognisable blob;
  * it sizes with ``background-size: contain``, so any aspect ratio is
    preserved (a wide lockup is never squashed into a square);
  * a soft light halo lifts a near-black logo off the near-black page.

These tests pin that contract and guard against regressing to the old
flat-tint approach, which rendered detailed/thin real logos invisible.
Presentation-only — the deterministic engine and AI surfaces are untouched.
Mirrors the fixture style of ``tests/test_ui_site_wide_effects.py``.
"""

from __future__ import annotations

import re

import pytest
from PIL import Image

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


def _make_org(pid: str, *, brand: str = "#24507f", with_logo: bool = True) -> None:
    """Save a ready org, optionally with a real PNG logo (transparent border so
    the ``?bg=1`` keying produces clean artwork rather than a solid block)."""
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
        im = Image.new("RGBA", (120, 90), (0, 0, 0, 0))  # transparent canvas
        for x in range(20, 100):  # an opaque coloured block = the "artwork"
            for y in range(15, 75):
                im.putpixel((x, y), (40, 120, 200, 255))
        im.save(d / "logo01.png")
        prof.brand_logos = [{"logo_id": "logo01", "mime": "image/png"}]
    save_profile(prof)


def _home(client, pid: str) -> str:
    with client.session_transaction() as s:
        s["active_profile_id"] = pid
    resp = client.get("/", follow_redirects=True)
    assert resp.status_code == 200, f"home → {resp.status_code}"
    return resp.get_data(as_text=True)


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

    # The asset actually serves a real raster logo, not an empty/placeholder.
    asset = client.get(m.group(1))
    assert asset.status_code == 200
    assert asset.headers["Content-Type"].startswith("image/")
    assert len(asset.get_data()) > 0


def test_css_contract_is_future_proof_for_any_logo(client):
    """Aspect preserved + dark-logo lift, and NO regression to the flat tint."""
    _make_org("org-b", brand="#24507f", with_logo=True)
    html = _home(client, "org-b")

    # Any aspect ratio survives (wide lockup / tall shield never squashed).
    assert "background-size: contain" in html
    # A near-black logo still lifts off the near-black page.
    assert "drop-shadow(0 0 16px" in html
    # Stays strictly decorative, behind content.
    assert "pointer-events: none" in html

    # REGRESSION GUARDS — the old flat single-tint silhouette rendered detailed
    # and thin real crests invisible. It must not creep back.
    assert "--mh-bg-tint" not in html
    assert "mask-image:url" not in html


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
