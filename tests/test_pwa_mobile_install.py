"""Roadmap 1.22 — mobile review/caption/crop polish + install affordance (build 3).

Covers the finishing build of the Mobile PWA:

  * the card inspector (caption box + accent + crop grid) becomes a
    thumb-reachable bottom sheet on phones;
  * a real maskable PNG home-screen icon (192 + 512) installs cleanly where an
    SVG icon doesn't;
  * a first-party install / Add-to-Home-Screen affordance, dismissible and
    standalone-aware.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_CSS = _ROOT / "src" / "mediahub" / "web" / "static" / "theme" / "theme-components.css"
sys.path.insert(0, str(_ROOT))


# ---------------------------------------------------------------------------
# Maskable PNG home-screen icons
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("size", [192, 512])
def test_app_icon_png_renders(client, size):
    r = client.get(f"/icon-{size}.png")
    assert r.status_code == 200
    assert r.mimetype == "image/png"
    from PIL import Image

    im = Image.open(io.BytesIO(r.get_data()))
    assert im.size == (size, size)


def test_app_icon_is_auth_exempt(client):
    """No active org pinned — the icon must still load (the manifest is fetched
    before sign-in)."""
    r = client.get("/icon-192.png")
    assert r.status_code == 200


def test_manifest_lists_maskable_png_icons(client):
    m = client.get("/manifest.webmanifest").get_json(force=True)
    pngs = [i for i in m["icons"] if i.get("type") == "image/png"]
    sizes = {i["sizes"] for i in pngs}
    assert "192x192" in sizes and "512x512" in sizes
    assert any("maskable" in (i.get("purpose") or "") for i in pngs)


# ---------------------------------------------------------------------------
# Install affordance
# ---------------------------------------------------------------------------


def test_install_script_served(client):
    body = client.get("/static/js/pwa-install.js").get_data(as_text=True)
    assert "beforeinstallprompt" in body
    assert "appinstalled" in body
    assert "display-mode: standalone" in body  # never offered once installed
    assert "Add to Home Screen" in body  # iOS fallback hint
    assert "mh_pwa_install_dismissed" in body  # dismissal is remembered


def test_pages_load_install_script(client):
    html = client.get("/").get_data(as_text=True)
    assert "js/pwa-install.js" in html


def test_install_chip_css_present(client):
    html = client.get("/").get_data(as_text=True)
    assert "#mh-install-chip" in html


# ---------------------------------------------------------------------------
# Mobile-first caption / crop: inspector becomes a bottom sheet
# ---------------------------------------------------------------------------


def test_inspector_is_bottom_sheet_on_mobile():
    css = _CSS.read_text(encoding="utf-8")
    # The mobile inspector block rises from the bottom edge with rounded top
    # corners and a grab handle — the bottom-sheet pattern.
    assert "translateY(100%)" in css
    assert "border-radius: 16px 16px 0 0" in css
    assert ".mh-insp-head::before" in css  # grab handle


def test_inspector_mobile_has_large_crop_targets():
    css = _CSS.read_text(encoding="utf-8")
    # Within the 560px block the crop cells grow to a 44px tap target.
    block = css[css.find("@media (max-width: 560px)") :]
    assert ".mh-insp-crop { min-height: 44px; }" in block
