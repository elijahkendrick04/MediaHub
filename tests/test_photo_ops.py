"""Tests for media_library.photo_ops — the deterministic non-destructive photo
edit engine (roadmap 1.3).

Strategy mirrors test_photo_adjust.py / test_saliency.py: build small synthetic
images, run the deterministic pixel ops, and assert (a) the maths moves pixels
in the intended direction, (b) alpha is preserved by tone/colour ops and made
deliberately by the mask ops, (c) recipes are serialisable + signed + canonical,
and (d) every op is reproducible run-to-run. No Playwright, no network, no LLM.
"""
from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from mediahub.media_library import photo_ops as po


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _gradient_rgb(size=(64, 64)) -> Image.Image:
    w, h = size
    row = np.linspace(0, 255, w, dtype=np.uint8)
    arr = np.repeat(row[None, :], h, axis=0)
    return Image.fromarray(np.dstack([arr, arr, arr]), "RGB")


def _solid_rgb(size=(32, 32), rgb=(120, 120, 120)) -> Image.Image:
    return Image.new("RGB", size, rgb)


def _cutout_rgba(size=(48, 48)) -> Image.Image:
    w, h = size
    rgb = np.random.default_rng(0).integers(0, 256, (h, w, 3), dtype=np.uint8)
    alpha = np.zeros((h, w), dtype=np.uint8)
    alpha[4 : h - 4, 4 : w - 4] = 255
    alpha[h // 2, :] = 128  # a partial-transparency row
    return Image.fromarray(np.dstack([rgb, alpha]), "RGBA")


def _png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.convert("RGBA" if img.mode == "RGBA" else "RGB").save(buf, "PNG")
    return buf.getvalue()


def _mean_rgb(img: Image.Image):
    return np.asarray(img.convert("RGB"), dtype=np.float64).reshape(-1, 3).mean(axis=0)


def _sat(img: Image.Image) -> float:
    arr = np.asarray(img.convert("RGB"), dtype=np.float64)
    return float((arr.max(axis=2) - arr.min(axis=2)).mean())


def _alpha(img: Image.Image) -> bytes:
    return img.convert("RGBA").getchannel("A").tobytes()


# --------------------------------------------------------------------------- #
# Adjustments
# --------------------------------------------------------------------------- #


def test_warmth_warms_and_cools():
    img = _solid_rgb(rgb=(120, 120, 120))
    warm = _mean_rgb(po.warmth(img, 100))
    cool = _mean_rgb(po.warmth(img, -100))
    assert warm[0] > 120 > warm[2]  # red up, blue down
    assert cool[0] < 120 < cool[2]


def test_tint_green_magenta_axis():
    img = _solid_rgb(rgb=(120, 120, 120))
    mag = _mean_rgb(po.tint(img, 100))
    grn = _mean_rgb(po.tint(img, -100))
    assert mag[1] < 120 and grn[1] > 120


def _ramp(lo, hi, w=64, h=16):
    row = np.linspace(lo, hi, w, dtype=np.uint8)
    arr = np.repeat(row[None, :], h, axis=0)
    return Image.fromarray(np.dstack([arr, arr, arr]), "RGB")


def test_highlights_only_touch_bright_tones():
    img = _ramp(20, 180)  # headroom at the top so the lift isn't clipped away
    out = np.asarray(po.highlights(img, 100).convert("RGB"), np.float64)
    base = np.asarray(img.convert("RGB"), np.float64)
    dark_delta = abs(out[:, 0].mean() - base[:, 0].mean())
    bright_delta = out[:, -1].mean() - base[:, -1].mean()
    assert bright_delta > dark_delta + 8  # the highlight end lifts far more


def test_shadows_only_touch_dark_tones():
    img = _ramp(40, 220)
    out = np.asarray(po.shadows(img, 100).convert("RGB"), np.float64)
    base = np.asarray(img.convert("RGB"), np.float64)
    dark_delta = out[:, 0].mean() - base[:, 0].mean()
    bright_delta = abs(out[:, -1].mean() - base[:, -1].mean())
    assert dark_delta > bright_delta + 8  # the shadow end lifts far more


def test_white_balance_neutralises_a_cast():
    arr = np.zeros((24, 24, 3), np.uint8)
    arr[..., 0] = 80   # red-deficient, blue-heavy "pool" cast
    arr[..., 1] = 120
    arr[..., 2] = 200
    cast = Image.fromarray(arr, "RGB")
    means_before = _mean_rgb(cast)
    means_after = _mean_rgb(po.white_balance(cast, 1.0))
    spread_before = means_before.max() - means_before.min()
    spread_after = means_after.max() - means_after.min()
    assert spread_after < spread_before  # closer to neutral grey


def test_white_balance_zero_is_noop():
    img = _gradient_rgb()
    assert _png_bytes(po.white_balance(img, 0.0)) == _png_bytes(img)


def test_clarity_adds_local_contrast():
    img = _gradient_rgb()
    out = po.clarity(img, 80)
    assert np.asarray(out.convert("RGB"), np.float64).std() >= np.asarray(img.convert("RGB"), np.float64).std() - 1


# --------------------------------------------------------------------------- #
# Effects
# --------------------------------------------------------------------------- #


def test_grayscale_removes_colour():
    img = _solid_rgb(rgb=(200, 60, 40))
    assert _sat(po.grayscale(img, 1.0)) < 2.0
    assert _sat(po.grayscale(img, 0.5)) < _sat(img)


def test_sepia_is_warm_mono():
    img = _solid_rgb(rgb=(120, 120, 120))
    m = _mean_rgb(po.sepia(img, 1.0))
    assert m[0] > m[1] > m[2]  # R > G > B


def test_duotone_maps_to_brand_colours():
    img = _gradient_rgb()
    out = po.duotone(img, shadow="#000080", highlight="#ffd000", amount=1.0).convert("RGB")
    arr = np.asarray(out, np.float64)
    dark = arr[:, 0]   # maps near shadow (navy: blue-heavy)
    light = arr[:, -1]  # maps near highlight (gold: red+green-heavy)
    assert dark[:, 2].mean() > dark[:, 0].mean()
    assert light[:, 0].mean() > light[:, 2].mean()


def test_blur_reduces_detail():
    img = _gradient_rgb()
    before = np.asarray(img.convert("RGB"), np.float64)
    after = np.asarray(po.blur(img, 6).convert("RGB"), np.float64)
    # Horizontal gradient: blur flattens the per-pixel horizontal differences.
    assert np.abs(np.diff(after, axis=1)).mean() < np.abs(np.diff(before, axis=1)).mean()


def test_pixelate_creates_blocks():
    img = _gradient_rgb((64, 64))
    out = po.pixelate(img, 16)
    arr = np.asarray(out.convert("RGB"))
    # Within a 16px block the columns are constant.
    assert np.array_equal(arr[:, 0], arr[:, 5])


def test_glitch_is_deterministic_and_shifts():
    img = _gradient_rgb()
    a = po.glitch(img, 60, seed=3)
    b = po.glitch(img, 60, seed=3)
    assert _png_bytes(a) == _png_bytes(b)
    assert _png_bytes(a) != _png_bytes(img)
    # Different seed → (generally) different result.
    assert _png_bytes(po.glitch(img, 60, seed=7)) != _png_bytes(a)


def test_vignette_darkens_corners_not_centre():
    img = _solid_rgb((64, 64), rgb=(200, 200, 200))
    out = np.asarray(po.vignette(img, 80).convert("RGB"), np.float64)
    assert out[0, 0].mean() < out[32, 32].mean() - 20


def test_opacity_scales_alpha():
    img = _solid_rgb(rgb=(10, 20, 30))
    out = po.opacity(img, 0.5)
    assert out.mode == "RGBA"
    assert 120 <= out.getchannel("A").getpixel((0, 0)) <= 135


def test_golden_hour_and_colour_punch():
    img = _solid_rgb(rgb=(120, 120, 120))
    gh = _mean_rgb(po.golden_hour(img, 1.0))
    assert gh[0] > gh[2]  # warmer
    punch = po.colour_punch(_solid_rgb(rgb=(180, 90, 60)), 100)
    assert _sat(punch) > _sat(_solid_rgb(rgb=(180, 90, 60)))


# --------------------------------------------------------------------------- #
# Geometry
# --------------------------------------------------------------------------- #


def test_crop_fractions_give_expected_size():
    img = _solid_rgb((100, 80))
    out = po.crop(img, 0.1, 0.25, 0.5, 0.5)
    assert out.size == (50, 40)


def test_crop_degenerate_is_noop():
    img = _solid_rgb((40, 40))
    assert po.crop(img, 0, 0, 1, 1).size == img.size
    assert po.crop(img, 0.5, 0.5, 0.0, 0.0).size == img.size


def test_flip_horizontal_and_vertical():
    arr = np.zeros((4, 4, 3), np.uint8)
    arr[0, 0] = (255, 0, 0)
    img = Image.fromarray(arr, "RGB")
    assert po.flip(img, "h").getpixel((3, 0)) == (255, 0, 0)
    assert po.flip(img, "v").getpixel((0, 3)) == (255, 0, 0)


def test_rotate_right_angles_lossless():
    img = _gradient_rgb((40, 20))
    assert po.rotate(img, 90).size == (20, 40)
    assert po.rotate(img, 180).size == (40, 20)
    assert po.rotate(img, 0).size == (40, 20)


def test_rotate_arbitrary_expands():
    img = _solid_rgb((40, 40))
    out = po.rotate(img, 45)
    assert out.size[0] > 40 and out.mode == "RGBA"


def test_resize_modes():
    img = _solid_rgb((100, 50))
    assert po.resize(img, width=50).size == (50, 25)   # aspect preserved
    assert po.resize(img, height=100).size == (200, 100)
    assert po.resize(img, scale=2.0).size == (200, 100)
    assert po.resize(img, width=40, height=40).size == (40, 40)


def test_resize_no_target_is_noop():
    img = _solid_rgb((100, 50))
    assert po.resize(img, width=0, height=0, scale=0).size == (100, 50)


def test_perspective_keeps_size_changes_pixels():
    img = _gradient_rgb()
    out = po.perspective(img, 0.5, 0.0)
    assert out.size == img.size
    assert _png_bytes(out) != _png_bytes(img)
    assert _png_bytes(po.perspective(img, 0, 0)) == _png_bytes(img)


# --------------------------------------------------------------------------- #
# Masks: shape crop, frame, brush, eraser
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("shape", po.SHAPES)
def test_shape_crop_keeps_centre_and_is_rgba(shape):
    img = _solid_rgb((48, 48), rgb=(200, 100, 50))
    out = po.shape_crop(img, shape)
    assert out.mode == "RGBA"
    assert out.getchannel("A").getpixel((24, 24)) > 200  # centre always kept


@pytest.mark.parametrize("shape", ("circle", "oval", "rounded", "triangle", "star", "heart"))
def test_round_shapes_drop_a_corner(shape):
    # A centred square fills a square canvas, so only the non-rectangular shapes
    # carve a corner to transparency.
    out = po.shape_crop(_solid_rgb((48, 48), rgb=(200, 100, 50)), shape)
    assert out.getchannel("A").getpixel((0, 0)) < 128


def test_shape_crop_unknown_is_noop():
    img = _solid_rgb()
    assert po.shape_crop(img, "octagon").size == img.size


def test_frame_draws_border():
    img = _solid_rgb((40, 40), rgb=(10, 10, 10))
    out = po.frame(img, colour="#ffffff", width=0.1)
    assert out.getpixel((0, 0))[:3] == (255, 255, 255)
    assert out.getpixel((20, 20))[:3] == (10, 10, 10)


def test_blur_brush_localises():
    # High-frequency noise so blur visibly changes the painted region (a smooth
    # ramp is invariant under blur and would hide the effect).
    rng = np.random.default_rng(1)
    arr = rng.integers(0, 256, (80, 80, 3), dtype=np.uint8)
    img = Image.fromarray(arr, "RGB")
    out = po.blur_brush(img, [{"cx": 0.25, "cy": 0.5, "r": 0.18}], radius=8, feather=0)
    arr_out = np.asarray(out.convert("RGB"), np.float64)
    arr_in = np.asarray(img.convert("RGB"), np.float64)
    # The painted column band changed; a far column is untouched.
    assert np.abs(arr_out[:, 20] - arr_in[:, 20]).mean() > 2.0
    assert np.abs(arr_out[:, 78] - arr_in[:, 78]).mean() < 0.5


def test_blur_brush_no_stamps_is_noop():
    img = _gradient_rgb()
    assert _png_bytes(po.blur_brush(img, [])) == _png_bytes(img)


def test_eraser_zeroes_alpha_in_region():
    img = _solid_rgb((40, 40), rgb=(50, 60, 70))
    out = po.eraser(img, [{"cx": 0.5, "cy": 0.5, "r": 0.3}], feather=0)
    assert out.mode == "RGBA"
    assert out.getchannel("A").getpixel((20, 20)) == 0
    assert out.getchannel("A").getpixel((0, 0)) == 255


# --------------------------------------------------------------------------- #
# Filter strip
# --------------------------------------------------------------------------- #


def test_filter_intensity_zero_is_identity():
    img = _gradient_rgb()
    assert _png_bytes(po.apply_filter(img, "punchy", 0.0)) == _png_bytes(img)


def test_filter_intensity_full_changes_and_blends():
    img = _gradient_rgb()
    assert _png_bytes(po.apply_filter(img, "punchy", 1.0)) != _png_bytes(img)
    # Half intensity sits between identity and full.
    half = np.asarray(po.apply_filter(img, "vivid", 0.5).convert("RGB"), np.float64)
    full = np.asarray(po.apply_filter(img, "vivid", 1.0).convert("RGB"), np.float64)
    base = np.asarray(img.convert("RGB"), np.float64)
    assert np.abs(half - base).mean() < np.abs(full - base).mean()


def test_mono_filter_desaturates():
    img = _solid_rgb(rgb=(200, 60, 40))
    assert _sat(po.apply_filter(img, "mono", 1.0)) < 5.0


def test_unknown_filter_is_noop():
    img = _gradient_rgb()
    assert _png_bytes(po.apply_filter(img, "nope", 1.0)) == _png_bytes(img)


# --------------------------------------------------------------------------- #
# EditRecipe
# --------------------------------------------------------------------------- #


def test_recipe_canonical_order():
    r = (
        po.EditRecipe()
        .with_op("vignette", {"amount": 30})
        .with_op("brightness", {"factor": 1.1})
        .with_op("crop", {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8})
        .with_op("saturation", {"factor": 1.2})
    )
    # Geometry first, then tone, then effects — regardless of insertion order.
    assert r.op_names() == ["crop", "brightness", "saturation", "vignette"]


def test_with_op_replaces_single_instance():
    r = po.EditRecipe().with_op("brightness", {"factor": 1.1}).with_op("brightness", {"factor": 1.4})
    assert r.op_names() == ["brightness"]
    assert r.steps[0].params["factor"] == 1.4


def test_without_op():
    r = po.EditRecipe().with_op("brightness", {"factor": 1.1}).with_op("contrast", {"factor": 1.2})
    assert r.without_op("brightness").op_names() == ["contrast"]


def test_recipe_serialise_roundtrip_and_signature():
    r = po.EditRecipe.build(
        [("crop", {"x": 0.1, "y": 0.1, "w": 0.8, "h": 0.8}), ("warmth", {"amount": 20})]
    )
    r2 = po.EditRecipe.from_dict(r.to_dict())
    assert r2 == r
    assert r2.signature() == r.signature()
    # Different params → different signature.
    assert po.EditRecipe.build([("warmth", {"amount": 21})]).signature() != po.EditRecipe.build(
        [("warmth", {"amount": 20})]
    ).signature()


def test_recipe_signature_independent_of_insertion_order():
    a = po.EditRecipe().with_op("warmth", {"amount": 10}).with_op("contrast", {"factor": 1.1})
    b = po.EditRecipe().with_op("contrast", {"factor": 1.1}).with_op("warmth", {"amount": 10})
    assert a.signature() == b.signature()


def test_recipe_drops_invalid_op():
    r = po.EditRecipe.build([("brightness", {"factor": 1.2}), ("teleport", {})])
    assert r.op_names() == ["brightness"]


def test_recipe_clamps_out_of_range_params():
    r = po.EditRecipe.build([("brightness", {"factor": 99}), ("warmth", {"amount": 9999})])
    assert r.steps[0].params["factor"] <= 3.0
    assert r.steps[1].params["amount"] <= 100.0


def test_recipe_apply_is_deterministic():
    img = _gradient_rgb()
    r = po.EditRecipe.build(
        [
            ("crop", {"x": 0.05, "y": 0.05, "w": 0.9, "h": 0.9}),
            ("warmth", {"amount": 15}),
            ("contrast", {"factor": 1.1}),
            ("vignette", {"amount": 20}),
        ]
    )
    assert _png_bytes(r.apply(img)) == _png_bytes(r.apply(img))


def test_recipe_noop_apply_bytes_byte_identical():
    raw = _png_bytes(_gradient_rgb())
    assert po.EditRecipe().apply_bytes(raw) == raw


def test_recipe_preserves_alpha_through_multistep():
    img = _cutout_rgba()
    before = _alpha(img)
    r = po.EditRecipe.build(
        [("warmth", {"amount": 30}), ("contrast", {"factor": 1.2}), ("clarity", {"amount": 30})]
    )
    out = r.apply(img)
    assert out.mode == "RGBA"
    assert _alpha(out) == before  # tone ops never shift the mask


def test_recipe_describe():
    r = po.EditRecipe.build([("crop", {"x": 0, "y": 0, "w": 0.5, "h": 0.5}), ("warmth", {"amount": 12})])
    text = " ".join(r.describe())
    assert "crop" in text and "warmth" in text


# --------------------------------------------------------------------------- #
# enhance_auto
# --------------------------------------------------------------------------- #


def test_enhance_auto_is_deterministic_and_canonical():
    img = _gradient_rgb()
    a = po.enhance_auto(img)
    b = po.enhance_auto(img)
    assert a == b
    assert a.op_names() == a.canonical().op_names()
    assert isinstance(a, po.EditRecipe)


def test_enhance_auto_lifts_a_dim_casted_photo():
    arr = np.zeros((40, 40, 3), np.uint8)
    arr[..., 0] = 20   # dim, blue/green cast (pool hall)
    arr[..., 1] = 45
    arr[..., 2] = 70
    dim = Image.fromarray(arr, "RGB")
    recipe = po.enhance_auto(dim)
    names = recipe.op_names()
    assert "white_balance" in names      # corrects the cast
    assert "brightness" in names         # lifts the dim frame
    # And it actually brightens when applied.
    assert _mean_rgb(recipe.apply(dim)).mean() > _mean_rgb(dim).mean()


def test_enhance_auto_strength_zero_is_gentler():
    arr = np.full((40, 40, 3), 30, np.uint8)
    dim = Image.fromarray(arr, "RGB")
    strong = po.enhance_auto(dim, strength=1.0)
    weak = po.enhance_auto(dim, strength=0.0)
    # Zero strength drops the strength-scaled ops (warmth/clarity/saturation).
    assert "warmth" not in weak.op_names()
    assert len(weak.steps) <= len(strong.steps)


# --------------------------------------------------------------------------- #
# Collage composer + profile pictures
# --------------------------------------------------------------------------- #


def test_compose_grid_size_and_determinism():
    imgs = [_solid_rgb(rgb=(i * 40, 0, 0)) for i in range(4)]
    a = po.compose_grid(imgs, layout="grid_2x2", width=200, height=200)
    b = po.compose_grid(imgs, layout="grid_2x2", width=200, height=200)
    assert a.size == (200, 200) and a.mode == "RGB"
    assert _png_bytes(a) == _png_bytes(b)


def test_compose_grid_handles_fewer_images_than_cells():
    out = po.compose_grid([_solid_rgb(rgb=(200, 0, 0)), _solid_rgb(rgb=(0, 200, 0))], layout="grid_2x2")
    assert out.size == (1080, 1080)  # empty cells stay background, no crash


def test_grid_capacity_and_names():
    assert po.grid_capacity("grid_2x2") == 4
    assert po.grid_capacity("grid_3x3") == 9
    assert po.grid_capacity("duo_v") == 2
    assert "grid_2x2" in po.GRID_NAMES


def test_profile_picture_recipe_square_alpha():
    img = _gradient_rgb((400, 300))
    out = po.profile_picture_recipe("avatar_circle").apply(img)
    assert out.size == (512, 512)
    assert out.mode == "RGBA"
    assert out.getchannel("A").getpixel((0, 0)) < 128  # circle drops the corner
