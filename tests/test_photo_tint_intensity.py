"""E3 (Canva gap analysis, photo-imagery) — tint_overlay op + recipe intensity.

The filter-preset upgrade: a brand-derived colour cast (the Clarendon signature
that unifies shadow hues) plus one intensity knob that lerps every op toward
identity, clamped to a house band and auto-lowered on already-punchy sources.

Deterministic pure-function coverage: the op, the lerp, the resolver, the
signature folds, and the byte-identical-when-absent contract.
"""

from __future__ import annotations

import io

import pytest
from PIL import Image

import mediahub.graphic_renderer.photo_adjust as pa


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def _photo(seed: int = 0) -> Image.Image:
    """A mid-grey RGB photo with a little structure (not flat)."""
    img = Image.new("RGB", (48, 48), (120, 120, 120))
    for y in range(48):
        for x in range(0, 48, 2):
            img.putpixel((x, y), (150 + (seed % 5) * 3, 90, 70))
    return img


def _rgba(seed: int = 0) -> Image.Image:
    img = _photo(seed).convert("RGBA")
    # a diagonal transparent wedge — the mask under test
    for y in range(48):
        for x in range(48):
            if x + y < 24:
                img.putpixel((x, y), (0, 0, 0, 0))
    return img


def _bytes_of(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --------------------------------------------------------------------------- #
# tint_overlay primitive
# --------------------------------------------------------------------------- #


def test_tint_overlay_changes_pixels_when_engaged():
    src = _photo()
    out = pa.tint_overlay(src, hex="#0E5BFF", opacity=0.3, mode="soft_light")
    assert list(out.getdata()) != list(src.getdata())


def test_tint_overlay_noop_on_empty_hex_or_zero_opacity():
    src = _photo()
    assert list(pa.tint_overlay(src, hex="", opacity=0.3).getdata()) == list(src.getdata())
    assert list(pa.tint_overlay(src, hex="#123456", opacity=0.0).getdata()) == list(src.getdata())
    # A non-hex string is rejected by the parser → no-op (never an invented colour).
    assert list(pa.tint_overlay(src, hex="rebeccapurple", opacity=0.3).getdata()) == list(
        src.getdata()
    )


def test_tint_overlay_preserves_alpha_exactly():
    src = _rgba()
    out = pa.tint_overlay(src, hex="#0E5BFF", opacity=0.4, mode="overlay")
    assert out.mode == "RGBA"
    assert list(out.getchannel("A").getdata()) == list(src.getchannel("A").getdata())


def test_tint_overlay_opacity_is_bounded():
    # opacity above the house cap is clamped, never a full colour flood.
    src = _photo()
    capped = pa.tint_overlay(src, hex="#FF0000", opacity=5.0)
    half = pa.tint_overlay(src, hex="#FF0000", opacity=0.5)
    assert list(capped.getdata()) == list(half.getdata())


@pytest.mark.parametrize("mode", ["soft_light", "overlay", "multiply", "screen"])
def test_tint_overlay_modes_all_run(mode):
    src = _photo()
    out = pa.tint_overlay(src, hex="#0E5BFF", opacity=0.3, mode=mode)
    assert out.size == src.size and out.mode == "RGB"


def test_tint_overlay_is_deterministic():
    src = _photo()
    a = pa.tint_overlay(src, hex="#0E5BFF", opacity=0.3, mode="soft_light")
    b = pa.tint_overlay(src, hex="#0E5BFF", opacity=0.3, mode="soft_light")
    assert list(a.getdata()) == list(b.getdata())


# --------------------------------------------------------------------------- #
# AdjustStep coercion for the new op
# --------------------------------------------------------------------------- #


def test_tint_step_coerces_and_is_valid():
    step = pa.AdjustStep("tint_overlay", {"hex": "#0e5bff", "opacity": 2.0, "mode": "bogus"})
    assert step.valid
    assert step.params["hex"] == "#0E5BFF"  # canonicalised upper
    assert step.params["opacity"] == 0.5  # clamped to the house cap
    assert step.params["mode"] == "soft_light"  # unknown mode → house default


def test_tint_step_bad_hex_becomes_empty_and_noops():
    step = pa.AdjustStep("tint_overlay", {"hex": "not-a-hex", "opacity": 0.3})
    assert step.params["hex"] == ""
    src = _photo()
    assert list(step.apply(src).getdata()) == list(src.getdata())


# --------------------------------------------------------------------------- #
# Intensity lerp
# --------------------------------------------------------------------------- #


def test_intensity_one_is_byte_identical_to_absent():
    src = _photo()
    base = pa.PRESETS["punchy"]
    full = pa.PhotoRecipe(name="punchy", steps=base.steps, intensity=1.0)
    assert list(pa.adjust_image(src, base).getdata()) == list(pa.adjust_image(src, full).getdata())


def test_intensity_zero_lerps_ops_to_near_identity():
    src = _photo()
    recipe = pa.PhotoRecipe(name="punchy", steps=pa.PRESETS["punchy"].steps, intensity=0.0)
    out = pa.adjust_image(src, recipe)
    # Every factor/opacity op lerped to identity, sharpen amount → 0. The result
    # is the source (auto_contrast isn't in punchy, so nothing survives at t=0).
    assert list(out.getdata()) == list(src.getdata())


def test_intensity_scales_effect_monotonically():
    src = _photo()
    steps = (pa.AdjustStep("saturation", {"factor": 2.0}),)

    def _mean_sat(img):
        hsv = img.convert("HSV")
        return sum(hsv.getdata(band=1)) / (img.width * img.height)

    low = pa.adjust_image(src, pa.PhotoRecipe("s", steps, intensity=0.4))
    high = pa.adjust_image(src, pa.PhotoRecipe("s", steps, intensity=0.8))
    full = pa.adjust_image(src, pa.PhotoRecipe("s", steps, intensity=1.0))
    assert _mean_sat(low) < _mean_sat(high) < _mean_sat(full)


def test_intensity_clamped_into_zero_one_by_dataclass():
    assert pa.PhotoRecipe("x", (), intensity=5.0).intensity == 1.0
    assert pa.PhotoRecipe("x", (), intensity=-3.0).intensity == 0.0


# --------------------------------------------------------------------------- #
# resolve_recipe
# --------------------------------------------------------------------------- #


def test_resolve_adds_tint_only_to_tint_slot_presets():
    tinted = pa.resolve_recipe("punchy", tint_hex="#0E5BFF")
    assert [s.op for s in tinted.steps][-1] == "tint_overlay"
    # editorial declares no tint slot → untouched (byte-identical base object).
    assert pa.resolve_recipe("editorial", tint_hex="#0E5BFF") is pa.PRESETS["editorial"]


def test_resolve_without_tint_or_intensity_returns_base_object():
    assert pa.resolve_recipe("punchy") is pa.PRESETS["punchy"]


def test_resolve_unknown_preset_is_none():
    assert pa.resolve_recipe("does-not-exist", tint_hex="#0E5BFF") is None


def test_resolve_intensity_clamped_to_house_band():
    lo, hi = pa.HOUSE_INTENSITY_BAND
    assert pa.resolve_recipe("punchy", intensity=0.05).intensity == lo
    assert pa.resolve_recipe("punchy", intensity=0.99).intensity == hi


def test_resolve_autolowers_intensity_on_punchy_source():
    lo, hi = pa.HOUSE_INTENSITY_BAND
    punchy_source = {"std": 90.0, "sat": 0.8}
    calm = pa.resolve_recipe("punchy", intensity=0.8, measured={"std": 20.0, "sat": 0.2})
    hot = pa.resolve_recipe("punchy", intensity=0.8, measured=punchy_source)
    assert hot.intensity < calm.intensity
    assert lo <= hot.intensity <= hi


def test_resolve_tint_hex_must_be_a_real_colour():
    # A garbage hex is dropped, so no tint step is appended (no invented colour).
    r = pa.resolve_recipe("punchy", tint_hex="periwinkle")
    assert "tint_overlay" not in [s.op for s in r.steps]
    assert r is pa.PRESETS["punchy"]


# --------------------------------------------------------------------------- #
# Signature folds — cache correctness
# --------------------------------------------------------------------------- #


def test_base_preset_signatures_unchanged_by_the_upgrade():
    # Full-strength, tint-free recipes keep their historic step-only signature.
    for name in ("natural", "crisp", "punchy", "vivid", "editorial", "soft"):
        r = pa.PRESETS[name]
        assert r.signature() == r.__class__(name="x", steps=r.steps).signature()


def test_signature_folds_tint_and_intensity():
    base = pa.PRESETS["punchy"]
    tinted = pa.resolve_recipe("punchy", tint_hex="#0E5BFF")
    dimmed = pa.resolve_recipe("punchy", intensity=0.6)
    both = pa.resolve_recipe("punchy", tint_hex="#0E5BFF", intensity=0.6)
    sigs = {base.signature(), tinted.signature(), dimmed.signature(), both.signature()}
    assert len(sigs) == 4  # every distinct (preset, tint, intensity) is distinct

    # Two different tint hexes never collide.
    other = pa.resolve_recipe("punchy", tint_hex="#FF3300")
    assert other.signature() != tinted.signature()


def test_intensity_roundtrips_through_dict():
    r = pa.resolve_recipe("punchy", tint_hex="#0E5BFF", intensity=0.6)
    again = pa.PhotoRecipe.from_dict(r.to_dict())
    assert again is not None
    assert again.intensity == r.intensity
    assert again.signature() == r.signature()


def test_full_strength_recipe_serialises_without_intensity_key():
    # Byte-identical persisted shape for a recipe that doesn't move intensity.
    assert "intensity" not in pa.PRESETS["punchy"].to_dict()


# --------------------------------------------------------------------------- #
# recipe_for byte-identity contract
# --------------------------------------------------------------------------- #


def test_recipe_for_without_tint_or_intensity_is_unchanged(monkeypatch):
    monkeypatch.delenv(pa.ENV_VAR, raising=False)
    assert pa.recipe_for(explicit="punchy") is pa.PRESETS["punchy"]
    assert pa.recipe_for(explicit="nope") is None


def test_recipe_for_applies_tint_when_requested():
    r = pa.recipe_for(explicit="punchy", tint_hex="#0E5BFF")
    assert "tint_overlay" in [s.op for s in r.steps]


def test_adjust_bytes_tinted_recipe_is_deterministic():
    src = _bytes_of(_photo())
    r = pa.resolve_recipe("punchy", tint_hex="#0E5BFF", intensity=0.6)
    assert pa.adjust_bytes(src, r) == pa.adjust_bytes(src, r)
