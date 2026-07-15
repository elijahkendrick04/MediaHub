"""F5 (systemic floor) — render-time floor.

Covers the four render-time guards:
  * ``--force-color-profile=srgb`` is on the Chromium launch args and folded into
    the PNG cache salt (a flag change ages out stale cache entries).
  * ICC→sRGB normalisation at the inline seam — byte-identical for a profile-less
    or already-sRGB photo, converting only a genuinely off-sRGB source.
  * the raise-on-missing-font gate (RenderError) and its kill switch.
  * the photo upscale guard + native crop-zoom clamp record explainability notes
    (browser-gated).
"""

from __future__ import annotations

import io

import pytest

from mediahub.graphic_renderer import render as R
from mediahub.graphic_renderer import render_cache as C

Image = pytest.importorskip("PIL.Image")


# ---- colour profile flag + cache salt -----------------------------------


def test_force_color_profile_on_launch_args():
    assert "--force-color-profile=srgb" in R._CHROMIUM_LAUNCH_ARGS


def test_launch_args_folded_into_cache_salt(monkeypatch):
    # The launch-args salt reflects the actual flag list …
    assert "--force-color-profile=srgb" in C._launch_args_salt()

    # … and changing the flags changes the renderer-generation salt (so a deploy
    # that toggles the colour-profile flag invalidates pre-change cache entries).
    C._salt_cache = None
    base = C._renderer_generation()
    monkeypatch.setattr(R, "_CHROMIUM_LAUNCH_ARGS", ["--no-sandbox"])
    C._salt_cache = None
    changed = C._renderer_generation()
    C._salt_cache = None
    assert base != changed


# ---- ICC → sRGB normalisation (inline seam) -----------------------------


def _png_bytes(color=(120, 30, 200), icc=None):
    im = Image.new("RGB", (8, 8), color)
    buf = io.BytesIO()
    if icc is not None:
        im.save(buf, "PNG", icc_profile=icc)
    else:
        im.save(buf, "PNG")
    return buf.getvalue()


def test_profileless_photo_is_byte_identical():
    raw = _png_bytes()
    assert R._srgb_normalised_bytes(raw, "png") == raw


def test_non_raster_is_byte_identical():
    raw = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    assert R._srgb_normalised_bytes(raw, "svg") == raw


def test_already_srgb_profile_is_byte_identical():
    ImageCms = pytest.importorskip("PIL.ImageCms")
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    # confirm the built-in sRGB profile is recognised as sRGB by description
    desc = ImageCms.getProfileDescription(ImageCms.createProfile("sRGB")).lower()
    if "srgb" not in desc:
        pytest.skip("platform littlecms sRGB profile lacks an 'sRGB' description")
    raw = _png_bytes(icc=srgb)
    assert R._srgb_normalised_bytes(raw, "png") == raw


def test_inline_seam_uses_srgb_salt(monkeypatch, tmp_path):
    # _img_to_data_uri must domain-separate the F5 normalisation from any pre-F5
    # encode of the same file via the "srgb" cache salt.
    p = tmp_path / "photo.png"
    p.write_bytes(_png_bytes())
    seen = {}

    def _fake(path, loader, *, salt=""):
        seen["salt"] = salt
        return loader(path)

    monkeypatch.setattr(R._render_cache, "asset_data_uri", _fake)
    R._img_to_data_uri(p)
    assert seen["salt"] == "srgb"


# ---- font-strict gate ---------------------------------------------------


def test_render_error_type():
    assert issubclass(R.RenderError, RuntimeError)


def test_font_strict_default_on_and_kill_switch(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_RENDER_FONT_STRICT", raising=False)
    assert R._font_strict_enabled() is True
    monkeypatch.setenv("MEDIAHUB_RENDER_FONT_STRICT", "0")
    assert R._font_strict_enabled() is False


# ---- browser-gated: font miss raises, upscale note recorded -------------


def _chromium_ok():
    try:
        from playwright.sync_api import sync_playwright  # noqa: F401
    except Exception:
        return False
    return True


@pytest.mark.skipif(not _chromium_ok(), reason="chromium/playwright unavailable")
def test_missing_font_raises_render_error(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_CACHE", "0")
    monkeypatch.setenv("MEDIAHUB_RENDER_FONT_STRICT", "1")
    # Visible text in a family that has no @font-face and is not a system font →
    # the floor sweep sees it fall back and raises rather than shipping the lie.
    # A self-hosted @font-face whose file cannot load (a missing woff2) is the
    # real failure: the family is declared, referenced by text, but errors — so
    # the text silently falls back and the floor sweep must catch it.
    html = (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        "@font-face{font-family:'BrokenBrandFace';"
        "src:url('file:///nonexistent-mediahub-face.woff2') format('woff2');}"
        "</style></head>"
        "<body style=\"margin:0;font-family:'BrokenBrandFace'\">"
        "<div style='font-size:80px'>HELLO WORLD</div></body></html>"
    )
    with pytest.raises(R.RenderError):
        R.render_html_to_png(html, tmp_path / "x.png", (400, 400))


@pytest.mark.skipif(not _chromium_ok(), reason="chromium/playwright unavailable")
def test_font_strict_off_allows_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_CACHE", "0")
    monkeypatch.setenv("MEDIAHUB_RENDER_FONT_STRICT", "0")
    # A self-hosted @font-face whose file cannot load (a missing woff2) is the
    # real failure: the family is declared, referenced by text, but errors — so
    # the text silently falls back and the floor sweep must catch it.
    html = (
        "<!doctype html><html><head><meta charset='utf-8'><style>"
        "@font-face{font-family:'BrokenBrandFace';"
        "src:url('file:///nonexistent-mediahub-face.woff2') format('woff2');}"
        "</style></head>"
        "<body style=\"margin:0;font-family:'BrokenBrandFace'\">"
        "<div style='font-size:80px'>HELLO WORLD</div></body></html>"
    )
    # kill switch on → no raise, a PNG is produced
    n = R.render_html_to_png(html, tmp_path / "x.png", (400, 400))
    assert n > 0


@pytest.mark.skipif(not _chromium_ok(), reason="chromium/playwright unavailable")
def test_low_res_photo_records_upscale_note(tmp_path, monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_CACHE", "0")
    # A 60px-wide source painted into a full-bleed slot upscales far past native.
    photo = tmp_path / "tiny.png"
    Image.new("RGB", (60, 60), (200, 40, 40)).save(photo)
    html = (
        "<!doctype html><html><head><meta charset='utf-8'></head>"
        "<body style='margin:0'>"
        f"<img src='{photo.as_uri()}' style='width:400px;height:400px;object-fit:cover'>"
        "</body></html>"
    )
    out = tmp_path / "card.png"
    R.render_html_to_png(html, out, (400, 400))
    notes = out.with_suffix(out.suffix + R._RENDER_NOTES_SUFFIX)
    # The sidecar is consumed by render_brief, but render_html_to_png leaves it in
    # place; assert the floor sweep wrote an upscale note.
    import json

    data = json.loads(notes.read_text("utf-8"))
    assert any("upscaled" in n for n in data), data
