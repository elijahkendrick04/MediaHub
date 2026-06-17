"""G1.14 — WebP/AVIF output + render quality profiles (fast/standard/high DPR).

Covers the G1.14 encode step added to ``graphic_renderer/render.py``:

* The three quality profiles (``fast``/``standard``/``high``) and how they map
  to screenshot DPR + per-format encoder settings.
* ``MEDIAHUB_RENDER_QUALITY`` selection + the back-compatible
  ``MEDIAHUB_RENDER_DPR`` override (the historic DPR tests still hold — see
  ``test_v8_render_upgrades.py``).
* Output-format resolution from an explicit name or the output suffix, and the
  honest ``RenderEncodeError`` for an unknown/uninstallable codec.
* ``_encode_image`` producing genuinely-correct PNG/WebP/AVIF/JPEG bytes.
* Real end-to-end renders (Playwright-gated) to each format + via ``render_brief``.

The pure-Python tests run everywhere; the live-render tests skip when
Playwright/Chromium isn't available, exactly like the sibling render tests.
"""
from __future__ import annotations

import hashlib
import sys
from io import BytesIO
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mediahub.graphic_renderer import render as render_mod
from mediahub.graphic_renderer.render import (
    QualityProfile,
    RenderEncodeError,
    _coerce_profile,
    _dpr_render,
    _encode_image,
    _pil_can_encode,
    _quality_profile,
    _resolve_image_format,
    _ENCODE_FORMATS,
    _FORMAT_EXTENSIONS,
    _QUALITY_PROFILES,
)

PIL_Image = render_mod.Image


# ---------------------------------------------------------------------------
# Format signature helpers (independent of Pillow's own format detection)
# ---------------------------------------------------------------------------

def _magic(data: bytes) -> str:
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "PNG"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    if data[4:8] == b"ftyp":
        return "AVIF"  # ISO-BMFF container (AVIF box)
    if data[:3] == b"\xff\xd8\xff":
        return "JPEG"
    return "UNKNOWN"


# ---------------------------------------------------------------------------
# Quality profiles
# ---------------------------------------------------------------------------

def test_three_profiles_exist_and_only_those():
    assert set(_QUALITY_PROFILES) == {"fast", "standard", "high"}


def test_profile_dprs_ascend():
    assert _QUALITY_PROFILES["fast"].dpr == 1
    assert _QUALITY_PROFILES["standard"].dpr == 2
    assert _QUALITY_PROFILES["high"].dpr == 3


def test_standard_profile_matches_historic_default():
    # The historic render was DPR 2 with an optimised PNG — `standard` must
    # reproduce that so today's posts stay byte-identical.
    std = _QUALITY_PROFILES["standard"]
    assert std.dpr == 2
    assert std.png_optimize is True


def test_profile_encoder_quality_ascends_fast_to_high():
    f, s, h = (_QUALITY_PROFILES[k] for k in ("fast", "standard", "high"))
    assert f.webp_quality < s.webp_quality < h.webp_quality
    assert f.avif_quality < s.avif_quality < h.avif_quality
    # fast skips the slow PNG zlib pass; standard/high pay for it.
    assert f.png_optimize is False and s.png_optimize and h.png_optimize


def test_quality_profile_is_frozen():
    with pytest.raises(Exception):
        _QUALITY_PROFILES["standard"].dpr = 9  # type: ignore[misc]


def test_quality_profile_lookup_by_name():
    assert _quality_profile("fast").name == "fast"
    assert _quality_profile("HIGH").name == "high"  # case-insensitive
    assert _quality_profile("  standard  ").name == "standard"  # trims


def test_unknown_profile_falls_back_to_standard():
    assert _quality_profile("nonsense").name == "standard"
    assert _quality_profile("").name == "standard"


def test_quality_profile_env_default(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_RENDER_QUALITY", raising=False)
    assert _quality_profile().name == "standard"


def test_quality_profile_env_selection(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_QUALITY", "high")
    assert _quality_profile().name == "high"
    monkeypatch.setenv("MEDIAHUB_RENDER_QUALITY", "fast")
    assert _quality_profile().name == "fast"


def test_coerce_profile_accepts_name_object_or_none(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_RENDER_QUALITY", raising=False)
    assert _coerce_profile("fast").name == "fast"
    obj = _QUALITY_PROFILES["high"]
    assert _coerce_profile(obj) is obj
    assert _coerce_profile(None).name == "standard"
    assert _coerce_profile("").name == "standard"


# ---------------------------------------------------------------------------
# DPR resolution — profile-driven, but explicit env still wins (back-compat)
# ---------------------------------------------------------------------------

def test_profile_drives_default_dpr(monkeypatch):
    monkeypatch.delenv("MEDIAHUB_RENDER_DPR", raising=False)
    monkeypatch.setenv("MEDIAHUB_RENDER_QUALITY", "high")
    assert _dpr_render() == 3
    monkeypatch.setenv("MEDIAHUB_RENDER_QUALITY", "fast")
    assert _dpr_render() == 1


def test_explicit_dpr_overrides_profile(monkeypatch):
    # The ops override must beat the profile, even a "high" one.
    monkeypatch.setenv("MEDIAHUB_RENDER_QUALITY", "high")
    monkeypatch.setenv("MEDIAHUB_RENDER_DPR", "2")
    assert _dpr_render() == 2


def test_blank_explicit_dpr_uses_profile(monkeypatch):
    monkeypatch.setenv("MEDIAHUB_RENDER_QUALITY", "fast")
    monkeypatch.setenv("MEDIAHUB_RENDER_DPR", "")  # blank = unset
    assert _dpr_render() == 1


# ---------------------------------------------------------------------------
# Output-format resolution
# ---------------------------------------------------------------------------

def test_format_map_covers_webp_and_avif():
    assert _ENCODE_FORMATS[".webp"] == "WEBP"
    assert _ENCODE_FORMATS[".avif"] == "AVIF"
    assert _ENCODE_FORMATS[".png"] == "PNG"
    assert _ENCODE_FORMATS[".jpg"] == "JPEG"
    assert _ENCODE_FORMATS[".jpeg"] == "JPEG"


def test_format_extension_roundtrip():
    for suffix, pil in _ENCODE_FORMATS.items():
        ext = _FORMAT_EXTENSIONS[pil]
        # the canonical extension re-resolves to the same Pillow format
        assert _ENCODE_FORMATS["." + ext] == pil


def test_resolve_format_from_suffix():
    assert _resolve_image_format(None, "/tmp/x.webp") == "WEBP"
    assert _resolve_image_format(None, "/tmp/x.avif") == "AVIF"
    assert _resolve_image_format(None, "/tmp/x.png") == "PNG"
    assert _resolve_image_format(None, Path("/tmp/x.JPG")) == "JPEG"


def test_resolve_format_unknown_suffix_defaults_png():
    # Historic behaviour: anything we don't recognise writes PNG.
    assert _resolve_image_format(None, "/tmp/x") == "PNG"
    assert _resolve_image_format(None, "/tmp/x.bmp") == "PNG"


def test_resolve_format_explicit_wins_over_suffix():
    assert _resolve_image_format("webp", "/tmp/x.png") == "WEBP"
    assert _resolve_image_format(".AVIF", "/tmp/x.png") == "AVIF"
    assert _resolve_image_format("PNG", "/tmp/x.webp") == "PNG"


def test_resolve_format_unknown_explicit_raises():
    with pytest.raises(RenderEncodeError):
        _resolve_image_format("tiff", "/tmp/x")
    with pytest.raises(RenderEncodeError):
        _resolve_image_format("gif", "/tmp/x.png")


def test_render_encode_error_is_runtime_error():
    assert issubclass(RenderEncodeError, RuntimeError)


# ---------------------------------------------------------------------------
# _pil_can_encode
# ---------------------------------------------------------------------------

@pytest.mark.skipif(PIL_Image is None, reason="Pillow not installed")
def test_pil_can_encode_png_jpeg_always():
    assert _pil_can_encode("PNG") is True
    assert _pil_can_encode("JPEG") is True


@pytest.mark.skipif(PIL_Image is None, reason="Pillow not installed")
def test_pil_can_encode_webp_avif_present_in_this_build():
    # The dev/CI image ships Pillow with both codecs; if a deployment lacks one
    # the encode step raises RenderEncodeError (see test below) rather than lying.
    assert _pil_can_encode("WEBP") is True
    assert _pil_can_encode("AVIF") is True


# ---------------------------------------------------------------------------
# _encode_image — genuine format bytes + profile effects
# ---------------------------------------------------------------------------

def _sample_image():
    img = PIL_Image.new("RGBA", (160, 120), (10, 37, 64, 255))
    for x in range(0, 160, 6):
        for y in range(0, 120, 6):
            img.putpixel((x, y), (255, 210, 74, 255))
    return img


@pytest.mark.skipif(PIL_Image is None, reason="Pillow not installed")
@pytest.mark.parametrize("pil_format", ["PNG", "WEBP", "AVIF", "JPEG"])
def test_encode_image_produces_correct_magic(pil_format):
    data = _encode_image(_sample_image(), pil_format, _quality_profile("standard"))
    assert _magic(data) == pil_format
    # And Pillow can re-open it at the original size.
    reopened = PIL_Image.open(BytesIO(data))
    assert reopened.format == pil_format
    assert reopened.size == (160, 120)


@pytest.mark.skipif(PIL_Image is None, reason="Pillow not installed")
def test_encode_image_jpeg_flattens_alpha():
    # RGBA in → a valid JPEG (which has no alpha channel) out, no exception.
    data = _encode_image(_sample_image(), "JPEG", _quality_profile("standard"))
    reopened = PIL_Image.open(BytesIO(data))
    assert reopened.format == "JPEG"
    assert reopened.mode in ("RGB", "L")


@pytest.mark.skipif(PIL_Image is None, reason="Pillow not installed")
def test_encode_image_profile_changes_webp_bytes():
    img = _sample_image()
    fast = _encode_image(img, "WEBP", _quality_profile("fast"))
    high = _encode_image(img, "WEBP", _quality_profile("high"))
    # Different quality/method → different bytes (anti-shortcut), both valid WebP.
    assert fast != high
    assert _magic(fast) == "WEBP" and _magic(high) == "WEBP"


@pytest.mark.skipif(PIL_Image is None, reason="Pillow not installed")
def test_encode_image_honest_error_when_codec_missing(monkeypatch):
    # Simulate a Pillow build without AVIF: the encode step must raise, never
    # silently fall back to a different format on disk.
    monkeypatch.setattr(
        render_mod, "_pil_can_encode", lambda fmt: fmt not in ("AVIF",)
    )
    with pytest.raises(RenderEncodeError):
        _encode_image(_sample_image(), "AVIF", _quality_profile("standard"))
    # WEBP still fine under the same monkeypatch.
    assert _magic(_encode_image(_sample_image(), "WEBP", _quality_profile("standard"))) == "WEBP"


# ---------------------------------------------------------------------------
# Live renders (Playwright-gated)
# ---------------------------------------------------------------------------

def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright  # noqa

        with sync_playwright() as p:
            try:
                browser = p.chromium.launch(args=["--no-sandbox"])
                browser.close()
                return True
            except Exception:
                return False
    except Exception:
        return False


_PLAYWRIGHT = _have_playwright()

_SAMPLE_HTML = (
    "<html><head><style>body{margin:0}"
    ".c{width:100vw;height:100vh;background:linear-gradient(135deg,#0A2540,#FFD24A);"
    "display:flex;align-items:center;justify-content:center;color:#fff;"
    "font:700 40px sans-serif}</style></head>"
    "<body><div class='c'>G1.14</div></body></html>"
)


@pytest.mark.skipif(not _PLAYWRIGHT, reason="Playwright/Chromium not available")
@pytest.mark.parametrize("ext,expect", [("png", "PNG"), ("webp", "WEBP"), ("avif", "AVIF"), ("jpg", "JPEG")])
def test_render_html_to_png_writes_each_format(tmp_path, monkeypatch, ext, expect):
    monkeypatch.delenv("MEDIAHUB_RENDER_DPR", raising=False)
    from mediahub.graphic_renderer.render import render_html_to_png

    out = tmp_path / f"card.{ext}"
    n = render_html_to_png(_SAMPLE_HTML, out, (320, 240), quality="standard")
    data = out.read_bytes()
    assert n == len(data)
    assert _magic(data) == expect
    img = PIL_Image.open(BytesIO(data))
    assert img.format == expect
    assert img.size == (320, 240)


@pytest.mark.skipif(not _PLAYWRIGHT, reason="Playwright/Chromium not available")
def test_render_html_explicit_format_overrides_suffix(tmp_path):
    # Suffix says .png, but we explicitly ask for WebP — the bytes must be WebP.
    from mediahub.graphic_renderer.render import render_html_to_png

    out = tmp_path / "mislabelled.png"
    render_html_to_png(_SAMPLE_HTML, out, (256, 256), image_format="webp")
    assert _magic(out.read_bytes()) == "WEBP"


@pytest.mark.skipif(not _PLAYWRIGHT, reason="Playwright/Chromium not available")
def test_webp_smaller_than_png_same_render(tmp_path):
    from mediahub.graphic_renderer.render import render_html_to_png

    png = tmp_path / "a.png"
    webp = tmp_path / "a.webp"
    render_html_to_png(_SAMPLE_HTML, png, (512, 512), quality="standard")
    render_html_to_png(_SAMPLE_HTML, webp, (512, 512), quality="standard")
    # WebP should compress this gradient card well below the PNG.
    assert webp.stat().st_size < png.stat().st_size


@pytest.mark.skipif(not _PLAYWRIGHT, reason="Playwright/Chromium not available")
def test_quality_profiles_change_png_bytes(tmp_path, monkeypatch):
    # fast (DPR 1) vs high (DPR 3) must yield different PNGs (anti-shortcut),
    # both exactly the target size.
    monkeypatch.delenv("MEDIAHUB_RENDER_DPR", raising=False)
    from mediahub.graphic_renderer.render import render_html_to_png

    fast = tmp_path / "fast.png"
    high = tmp_path / "high.png"
    render_html_to_png(_SAMPLE_HTML, fast, (300, 300), quality="fast")
    render_html_to_png(_SAMPLE_HTML, high, (300, 300), quality="high")
    assert PIL_Image.open(fast).size == (300, 300)
    assert PIL_Image.open(high).size == (300, 300)
    h_fast = hashlib.sha256(fast.read_bytes()).hexdigest()
    h_high = hashlib.sha256(high.read_bytes()).hexdigest()
    assert h_fast != h_high


# ---------------------------------------------------------------------------
# Live renders via render_brief (the public high-level API)
# ---------------------------------------------------------------------------

def _render_brief_for_test():
    from mediahub.brand.kit import BrandKit
    from mediahub.creative_brief.generator import generate as gen_brief
    from mediahub.media_requirements.evaluator import EvaluationResult

    bk = BrandKit(
        profile_id="test",
        display_name="Test Swim Club",
        primary_colour="#0E5BFF",
        secondary_colour="#101820",
        short_name="TSC",
    )
    ev = EvaluationResult(
        content_item_id="ci-1",
        content_type="achievement_card_individual",
        status="ready",
        suggested_layout="individual_hero",
        matched={},
        missing_required=[],
        missing_optional=[],
        recommended_action="render",
        confidence_tier="high",
        confidence_label="NEW PB",
        explain="ok",
    )
    item = {
        "id": "ci-1",
        "post_angle": "individual_pb",
        "achievement": {
            "swimmer_name": "Eira Hughes",
            "event_name": "200m Freestyle",
            "result_time": "2:08.41",
        },
    }
    return gen_brief(item, ev, bk, profile_id="test", meet_name="Manchester Open"), bk


@pytest.mark.skipif(not _PLAYWRIGHT, reason="Playwright/Chromium not available")
def test_render_brief_default_is_png(tmp_path, monkeypatch):
    monkeypatch.delenv("MEDIAHUB_RENDER_DPR", raising=False)
    from mediahub.graphic_renderer.render import render_brief

    brief, bk = _render_brief_for_test()
    res = render_brief(
        brief, output_dir=tmp_path, size=(540, 675),
        format_name="feed_portrait", brand_kit=bk,
    )
    assert res.visual.file_path.endswith("feed_portrait.png")
    assert _magic(Path(res.visual.file_path).read_bytes()) == "PNG"


@pytest.mark.skipif(not _PLAYWRIGHT, reason="Playwright/Chromium not available")
@pytest.mark.parametrize("fmt,ext,magic", [("webp", "webp", "WEBP"), ("avif", "avif", "AVIF")])
def test_render_brief_webp_avif_output(tmp_path, monkeypatch, fmt, ext, magic):
    monkeypatch.delenv("MEDIAHUB_RENDER_DPR", raising=False)
    from mediahub.graphic_renderer.render import render_brief

    brief, bk = _render_brief_for_test()
    res = render_brief(
        brief, output_dir=tmp_path, size=(540, 675),
        format_name="feed_portrait", brand_kit=bk, image_format=fmt, quality="fast",
    )
    assert res.visual.file_path.endswith(f"feed_portrait.{ext}")
    data = Path(res.visual.file_path).read_bytes()
    assert _magic(data) == magic
    assert res.png_bytes == len(data)
    img = PIL_Image.open(BytesIO(data))
    assert img.size == (540, 675)
