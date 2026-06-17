"""Tests for graphic_renderer.photo_adjust — the deterministic, server-side
photo adjustment stack (roadmap G1.25).

Strategy mirrors test_saliency.py: build small synthetic images, run the
deterministic PIL recipes over them, and assert (a) the maths moves pixels in
the intended direction, (b) a cutout's alpha mask is preserved *exactly*,
(c) the default is a no-op / byte-identical, and (d) every recipe is
reproducible run-to-run. No Playwright, no network, no LLM.
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from mediahub.graphic_renderer import photo_adjust as pa


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _gradient_rgb(size=(64, 64)) -> Image.Image:
    """A horizontal 0→255 luminance ramp — real tonal range to push around."""
    w, h = size
    row = np.linspace(0, 255, w, dtype=np.uint8)
    arr = np.repeat(row[None, :], h, axis=0)
    return Image.fromarray(np.dstack([arr, arr, arr]), "RGB")


def _colour_rgb(size=(32, 32), rgb=(160, 90, 60)) -> Image.Image:
    return Image.new("RGB", size, rgb)


def _cutout_rgba(size=(32, 32)) -> Image.Image:
    """A subject block with a graded alpha border — a realistic cutout mask."""
    w, h = size
    rgb = np.random.default_rng(0).integers(0, 256, (h, w, 3), dtype=np.uint8)
    alpha = np.zeros((h, w), dtype=np.uint8)
    alpha[4 : h - 4, 4 : w - 4] = 255
    alpha[h // 2, :] = 128  # a partial-transparency row, to be sure it survives
    return Image.fromarray(np.dstack([rgb, alpha]), "RGBA")


def _alpha_bytes(img: Image.Image) -> bytes:
    return img.getchannel("A").tobytes()


def _mean(img: Image.Image) -> float:
    return float(np.asarray(img.convert("RGB"), dtype=np.float64).mean())


def _std(img: Image.Image) -> float:
    return float(np.asarray(img.convert("RGB"), dtype=np.float64).std())


def _saturation_mean(img: Image.Image) -> float:
    arr = np.asarray(img.convert("RGB"), dtype=np.float64)
    return float((arr.max(axis=2) - arr.min(axis=2)).mean())


# --------------------------------------------------------------------------- #
# Presets
# --------------------------------------------------------------------------- #


def test_all_presets_present_and_valid():
    assert set(pa.PRESETS) >= {"none", "natural", "crisp", "punchy", "vivid", "editorial", "soft"}
    for name, recipe in pa.PRESETS.items():
        assert isinstance(recipe, pa.PhotoRecipe)
        # Every step in every preset is a known, valid op.
        assert all(s.valid for s in recipe.steps), name


def test_none_preset_is_a_real_noop():
    assert pa.PRESETS["none"].is_noop()
    assert not pa.PRESETS["punchy"].is_noop()


def test_preset_names_are_resolvable_and_exclude_none():
    assert "none" not in pa.PRESET_NAMES
    for name in pa.PRESET_NAMES:
        assert pa.get_preset(name) is not None


@pytest.mark.parametrize("name", ["natural", "crisp", "punchy", "vivid", "editorial", "soft"])
def test_get_preset_case_insensitive(name):
    assert pa.get_preset(name.upper()) is pa.PRESETS[name]
    assert pa.get_preset(f"  {name} ") is pa.PRESETS[name]


def test_get_preset_unknown_is_none():
    assert pa.get_preset("totally-made-up") is None
    assert pa.get_preset("") is None


# --------------------------------------------------------------------------- #
# Recipe model — build / serialise / signature
# --------------------------------------------------------------------------- #


def test_recipe_roundtrip_and_signature_stability():
    r = pa.PRESETS["editorial"]
    again = pa.PhotoRecipe.from_dict(r.to_dict())
    assert again is not None
    assert again == r
    assert again.signature() == r.signature()


def test_signature_depends_on_steps_not_name():
    a = pa.PhotoRecipe.build("alpha", [("contrast", {"factor": 1.2})])
    b = pa.PhotoRecipe.build("beta", [("contrast", {"factor": 1.2})])
    c = pa.PhotoRecipe.build("alpha", [("contrast", {"factor": 1.3})])
    assert a.signature() == b.signature()  # name is irrelevant to the effect
    assert a == b
    assert a.signature() != c.signature()  # different params → different effect
    assert hash(a) == hash(b) and hash(a) != hash(c)


def test_recipe_describe_is_human_readable():
    desc = pa.PRESETS["punchy"].describe()
    assert desc == ["contrast ×1.12", "saturation ×1.15", "sharpen ×0.8 (r=2, t=3)"]


def test_invalid_steps_are_dropped_on_construction():
    r = pa.PhotoRecipe.build("mix", [("contrast", {"factor": 1.1}), ("bogus_op", {})])
    assert [s.op for s in r.steps] == ["contrast"]


def test_from_dict_is_tolerant():
    assert pa.PhotoRecipe.from_dict(None) is None
    assert pa.PhotoRecipe.from_dict("nope") is None
    # Unknown ops inside are filtered; the recipe still builds.
    r = pa.PhotoRecipe.from_dict({"name": "x", "steps": [{"op": "zzz"}, {"op": "contrast"}]})
    assert r is not None and [s.op for s in r.steps] == ["contrast"]


# --------------------------------------------------------------------------- #
# Param coercion / clamping
# --------------------------------------------------------------------------- #


def test_params_are_clamped_into_range():
    step = pa.AdjustStep("contrast", {"factor": 999.0})
    assert step.params["factor"] == pa._BOUNDS["contrast"][1]
    step2 = pa.AdjustStep("contrast", {"factor": -5.0})
    assert step2.params["factor"] == pa._BOUNDS["contrast"][0]


def test_unknown_params_dropped_defaults_filled():
    step = pa.AdjustStep("sharpen", {"amount": 1.0, "nonsense": 5})
    assert set(step.params) == {"amount", "radius", "threshold"}


def test_nan_param_falls_back_to_low_bound():
    step = pa.AdjustStep("brightness", {"factor": float("nan")})
    assert step.params["factor"] == pa._BOUNDS["brightness"][0]


# --------------------------------------------------------------------------- #
# Primitives — direction of effect
# --------------------------------------------------------------------------- #


def test_contrast_increases_and_decreases_spread():
    img = _gradient_rgb()
    base = _std(img)
    assert _std(pa.contrast(img, 1.5)) > base
    assert _std(pa.contrast(img, 0.5)) < base


def test_contrast_identity_is_unchanged():
    img = _gradient_rgb()
    assert pa.contrast(img, 1.0).tobytes() == img.tobytes()


def test_saturation_zero_is_greyscale_and_high_is_vivid():
    img = _colour_rgb()
    grey = pa.saturation(img, 0.0)
    arr = np.asarray(grey.convert("RGB"))
    # Greyscale ⇒ R == G == B everywhere.
    assert np.array_equal(arr[..., 0], arr[..., 1]) and np.array_equal(arr[..., 1], arr[..., 2])
    assert _saturation_mean(pa.saturation(img, 1.6)) > _saturation_mean(img)


def test_brightness_lighter_and_darker():
    img = _colour_rgb()
    assert _mean(pa.brightness(img, 1.4)) > _mean(img)
    assert _mean(pa.brightness(img, 0.6)) < _mean(img)


def test_sharpen_zero_is_noop_and_positive_changes_pixels():
    # Sharpening acts on edges/detail, so use a textured image (a smooth ramp has
    # no high-frequency content for an unsharp mask to amplify).
    noise = np.random.default_rng(7).integers(0, 256, (48, 48, 3), dtype=np.uint8)
    img = Image.fromarray(noise, "RGB")
    assert pa.sharpen(img, 0.0).tobytes() == img.tobytes()
    assert pa.sharpen(img, 1.5).tobytes() != img.tobytes()


def test_levels_maps_endpoints_and_identity_is_noop():
    img = _gradient_rgb((256, 4))  # one pixel per input value across the row
    out = np.asarray(pa.levels(img, black=50, white=200, gamma=1.0).convert("RGB"))[0, :, 0]
    # Anything at/below the black point clamps to 0; at/above white clamps to 255.
    assert out[50] == 0
    assert out[200] == 255
    assert out[0] == 0 and out[255] == 255
    # The midpoint of [50,200] (=125) lands near mid-grey at gamma 1.
    assert 120 <= int(out[125]) <= 135
    # Identity is a true no-op.
    assert pa.levels(img, 0, 255, 1.0).tobytes() == img.tobytes()


def test_levels_degenerate_window_is_noop():
    img = _gradient_rgb()
    assert pa.levels(img, black=200, white=100).tobytes() == img.tobytes()


def test_auto_contrast_stretches_low_contrast_image():
    arr = np.full((16, 16, 3), 110, dtype=np.uint8)
    arr[:, 8:] = 150  # narrow 110–150 band
    img = Image.fromarray(arr, "RGB")
    out = np.asarray(pa.auto_contrast(img, cutoff=0.0).convert("RGB"))
    assert out.min() == 0 and out.max() == 255  # stretched to the full range


# --------------------------------------------------------------------------- #
# Alpha preservation — the cutout-mask guarantee
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "fn",
    [
        lambda im: pa.sharpen(im, 1.5),
        lambda im: pa.contrast(im, 1.4),
        lambda im: pa.saturation(im, 1.5),
        lambda im: pa.brightness(im, 1.2),
        lambda im: pa.levels(im, 10, 240, 0.9),
        lambda im: pa.auto_contrast(im, 0.5),
    ],
)
def test_primitive_preserves_alpha_exactly(fn):
    cut = _cutout_rgba()
    before = _alpha_bytes(cut)
    out = fn(cut)
    assert out.mode == "RGBA"
    assert _alpha_bytes(out) == before  # mask byte-identical


def test_recipe_preserves_alpha_exactly():
    cut = _cutout_rgba()
    before = _alpha_bytes(cut)
    out = pa.adjust_image(cut, "punchy")
    assert out.mode == "RGBA"
    assert _alpha_bytes(out) == before


def test_la_and_palette_alpha_modes_round_trip():
    # LA (greyscale + alpha)
    la = Image.new("LA", (16, 16), (120, 200))
    out_la = pa.adjust_image(la, "crisp")
    assert out_la.mode == "RGBA"
    # P with transparency
    p = Image.new("P", (16, 16))
    p.info["transparency"] = 0
    out_p = pa.adjust_image(p, "crisp")
    assert out_p.mode in ("RGBA", "RGB")


def test_grayscale_and_rgb_modes_do_not_raise():
    assert pa.adjust_image(Image.new("L", (8, 8), 100), "punchy").mode in ("RGB", "RGBA")
    assert pa.adjust_image(_colour_rgb(), "punchy").mode == "RGB"


# --------------------------------------------------------------------------- #
# adjust_image — no-op + determinism
# --------------------------------------------------------------------------- #


def test_adjust_image_noop_returns_unchanged():
    img = _colour_rgb()
    assert pa.adjust_image(img, None) is img
    assert pa.adjust_image(img, "none") is img
    assert pa.adjust_image(img, pa.PRESETS["none"]) is img


def test_adjust_image_is_deterministic():
    img = _gradient_rgb()
    a = pa.adjust_image(img, "editorial").tobytes()
    b = pa.adjust_image(img, "editorial").tobytes()
    assert a == b


def test_adjust_image_unknown_string_recipe_is_noop():
    img = _colour_rgb()
    assert pa.adjust_image(img, "does-not-exist") is img


# --------------------------------------------------------------------------- #
# adjust_bytes / adjust_to_data_uri
# --------------------------------------------------------------------------- #


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _jpeg_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=95)
    return buf.getvalue()


def test_adjust_bytes_noop_is_byte_identical():
    raw = _png_bytes(_colour_rgb())
    assert pa.adjust_bytes(raw, None) == raw
    assert pa.adjust_bytes(raw, "none") == raw


def test_adjust_bytes_produces_a_decodable_image():
    raw = _png_bytes(_gradient_rgb())
    out = pa.adjust_bytes(raw, "punchy")
    assert out != raw
    with Image.open(io.BytesIO(out)) as im:
        im.load()
        assert im.size == (64, 64)


def test_adjust_bytes_jpeg_source_stays_jpeg_rgba_stays_png():
    jpeg = _jpeg_bytes(_colour_rgb())
    out_j = pa.adjust_bytes(jpeg, "crisp")
    with Image.open(io.BytesIO(out_j)) as im:
        assert im.format == "JPEG"
    rgba = _png_bytes(_cutout_rgba())
    out_p = pa.adjust_bytes(rgba, "crisp")
    with Image.open(io.BytesIO(out_p)) as im:
        assert im.format == "PNG" and im.mode == "RGBA"


def test_adjust_to_data_uri_noop_passthrough_matches_source(tmp_path):
    raw = _png_bytes(_colour_rgb())
    p = tmp_path / "x.png"
    p.write_bytes(raw)
    uri = pa.adjust_to_data_uri(str(p), None)
    assert uri.startswith("data:image/png;base64,")
    assert base64.b64decode(uri.split(",", 1)[1]) == raw


def test_adjust_to_data_uri_matches_render_img_to_data_uri_for_noop(tmp_path):
    """The wiring contract: a no-op adjust inline equals the renderer's plain
    inline byte-for-byte, so an un-requested recipe never changes a render."""
    from mediahub.graphic_renderer.render import _img_to_data_uri

    p = tmp_path / "photo.jpg"
    p.write_bytes(_jpeg_bytes(_colour_rgb()))
    assert pa.adjust_to_data_uri(str(p), None) == _img_to_data_uri(p)


def test_adjust_to_data_uri_applies_recipe_from_path(tmp_path):
    p = tmp_path / "photo.png"
    p.write_bytes(_png_bytes(_gradient_rgb()))
    uri = pa.adjust_to_data_uri(str(p), "vivid")
    decoded = base64.b64decode(uri.split(",", 1)[1])
    assert decoded != p.read_bytes()


def test_adjust_to_data_uri_accepts_bytes_and_image():
    img = _gradient_rgb()
    raw = _png_bytes(img)
    assert pa.adjust_to_data_uri(raw, "crisp").startswith("data:image/")
    assert pa.adjust_to_data_uri(img, "crisp").startswith("data:image/png")


def test_adjust_to_data_uri_rgba_is_png_mime():
    uri = pa.adjust_to_data_uri(_png_bytes(_cutout_rgba()), "crisp")
    assert uri.startswith("data:image/png;base64,")


# --------------------------------------------------------------------------- #
# recipe_for — resolution + precedence (the byte-identical-by-default contract)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("legacy", ["cutout", "vignette", "duotone", "halftone", "frame", "no-photo"])
def test_legacy_treatments_resolve_to_none(monkeypatch, legacy):
    monkeypatch.delenv(pa.ENV_VAR, raising=False)
    assert pa.recipe_for(treatment=legacy) is None


def test_recipe_for_default_is_none(monkeypatch):
    monkeypatch.delenv(pa.ENV_VAR, raising=False)
    assert pa.recipe_for() is None


def test_recipe_for_explicit_and_treatment_tokens(monkeypatch):
    monkeypatch.delenv(pa.ENV_VAR, raising=False)
    assert pa.recipe_for(explicit="punchy").name == "punchy"
    assert pa.recipe_for(treatment="crisp").name == "crisp"


def test_recipe_for_env_default(monkeypatch):
    monkeypatch.setenv(pa.ENV_VAR, "editorial")
    assert pa.recipe_for().name == "editorial"
    assert pa.recipe_for(env=False) is None  # env can be ignored


def test_recipe_for_precedence_explicit_over_treatment_over_env(monkeypatch):
    monkeypatch.setenv(pa.ENV_VAR, "soft")
    assert pa.recipe_for(explicit="punchy", treatment="vivid").name == "punchy"
    assert pa.recipe_for(treatment="vivid").name == "vivid"
    assert pa.recipe_for().name == "soft"


def test_recipe_for_none_token_forces_off_past_env(monkeypatch):
    monkeypatch.setenv(pa.ENV_VAR, "punchy")
    r = pa.recipe_for(explicit="none")
    assert r is not None and r.is_noop()  # explicit "none" overrides the env default


def test_is_enabled_tracks_env(monkeypatch):
    monkeypatch.delenv(pa.ENV_VAR, raising=False)
    assert pa.is_enabled() is False
    monkeypatch.setenv(pa.ENV_VAR, "punchy")
    assert pa.is_enabled() is True
    monkeypatch.setenv(pa.ENV_VAR, "garbage")
    assert pa.is_enabled() is False


# --------------------------------------------------------------------------- #
# Render-wiring contract (no Playwright needed)
# --------------------------------------------------------------------------- #


def test_render_brief_resolves_no_recipe_for_default_brief(monkeypatch):
    """A default brief (photo_treatment='cutout') with no env set must resolve
    to None — the guarantee that today's renders are byte-identical."""
    monkeypatch.delenv(pa.ENV_VAR, raising=False)
    assert pa.recipe_for(explicit="", treatment="cutout") is None


def test_end_to_end_determinism_bytes(monkeypatch):
    raw = _png_bytes(_gradient_rgb())
    assert pa.adjust_bytes(raw, "punchy") == pa.adjust_bytes(raw, "punchy")


# --------------------------------------------------------------------------- #
# Real-render integration (Playwright-gated) — the recipe must propagate into
# the actual rendered PNG, and the default (no env) render must be unchanged.
# --------------------------------------------------------------------------- #


def _have_playwright() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            try:
                b = p.chromium.launch()
                b.close()
                return True
            except Exception:
                return False
    except Exception:
        return False


def _photo_on_disk(tmp_path) -> str:
    """A colourful, detailed photo so an adjustment visibly moves pixels."""
    rng = np.random.default_rng(3)
    base = rng.integers(40, 220, (480, 360, 3), dtype=np.uint8)
    base[120:360, 90:270] = [200, 60, 50]  # a strong colour block (the "subject")
    p = tmp_path / "action.jpg"
    Image.fromarray(base, "RGB").save(p, "JPEG", quality=95)
    return str(p)


@pytest.mark.skipif(not _have_playwright(), reason="Playwright/Chromium not available")
def test_recipe_propagates_into_render_and_default_is_unchanged(tmp_path, monkeypatch):
    from mediahub.brand.kit import BrandKit
    from mediahub.creative_brief.generator import generate as gen_brief
    from mediahub.graphic_renderer.render import render_brief
    from mediahub.media_requirements.evaluator import EvaluationResult

    brand = BrandKit(
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
        suggested_layout="action_photo_hero",
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
    photo = _photo_on_disk(tmp_path)

    def _render(out_sub: str):
        brief = gen_brief(item, ev, brand, profile_id="test", meet_name="Open")
        brief.layout_template = "action_photo_hero"
        brief.photo_treatment = "cutout"  # a non-preset → no implicit adjustment
        res = render_brief(
            brief,
            output_dir=tmp_path / out_sub,
            size=(1080, 1350),
            format_name="feed_portrait",
            athlete_path=photo,
            brand_kit=brand,
            skip_cutout=True,
        )
        return Path(res.visual.file_path).read_bytes()

    # Default: no env → un-adjusted. Same render twice = byte-identical PNG.
    monkeypatch.delenv(pa.ENV_VAR, raising=False)
    base_a = _render("base_a")
    base_b = _render("base_b")
    assert base_a[:8] == b"\x89PNG\r\n\x1a\n"
    assert base_a == base_b  # deterministic, unchanged default path

    # With the env recipe set, the baked-in photo differs → the PNG differs.
    monkeypatch.setenv(pa.ENV_VAR, "punchy")
    adjusted = _render("adjusted")
    assert adjusted != base_a
