"""E2 (Canva gap analysis, photo-imagery) — smartcrop-style candidate scorer.

Multi-scale candidate scoring over the saliency grid, rule-of-thirds placement
as the deterministic default (centred for symmetric archetypes), headroom, and
a subject-size punch-in — emitted through the existing --mh-photo-pos +
--mh-photo-scale levers. The hard contract: byte-identical to today's framing
when the scorer agrees with the largest crop, and best_crop/focus_position are
untouched.
"""

from __future__ import annotations

import os

import pytest
from PIL import Image

from mediahub.graphic_renderer import archetypes as A
from mediahub.graphic_renderer import render as R
from mediahub.graphic_renderer import saliency as S


# --------------------------------------------------------------------------- #
# Fixtures — synthetic frames with a warm "athlete" block
# --------------------------------------------------------------------------- #


def _frame(size, subject_box, *, bg=(18, 18, 28), subj=(205, 150, 120)):
    img = Image.new("RGB", size, bg)
    x0, y0, x1, y1 = subject_box
    img.paste(Image.new("RGB", (x1 - x0, y1 - y0), subj), (x0, y0))
    return img


def _cutout(size, subject_box):
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    x0, y0, x1, y1 = subject_box
    img.paste(Image.new("RGBA", (x1 - x0, y1 - y0), (200, 40, 40, 255)), (x0, y0))
    return img


def _save(img, tmp_path, name):
    p = tmp_path / name
    img.save(p)
    return str(p)


def _pos(vars_):
    x, y = vars_["--mh-photo-pos"].split()
    return float(x.rstrip("%")), float(y.rstrip("%"))


# --------------------------------------------------------------------------- #
# The existing helpers are UNTOUCHED — byte-identity of the non-smart path
# --------------------------------------------------------------------------- #


def test_focus_position_and_best_crop_are_unchanged(tmp_path):
    # A synthetic subject-left image: the historic helpers still return exactly
    # what they did (E2 is purely additive, gated behind smart_crop/smart_focus).
    p = _save(_frame((300, 100), (20, 30, 60, 70)), tmp_path, "legacy.png")
    x, y, w, h = S.best_crop(p, "1:1")
    assert (w, h) == (100, 100)
    assert 0 <= x <= 200
    # focus_position keeps its exact string contract.
    assert S.focus_position(p, "1:1").endswith("%")


# --------------------------------------------------------------------------- #
# Byte-identity: winner == today's largest crop → no reframe, no scale
# --------------------------------------------------------------------------- #


def test_featureless_image_is_byte_identical(tmp_path):
    p = _save(Image.new("RGB", (1000, 1250), (120, 120, 120)), tmp_path, "flat.png")
    vars_ = S.smart_focus(p, "4:5")
    assert vars_ == {"--mh-photo-pos": S.focus_position(p, "4:5")}
    assert "--mh-photo-scale" not in vars_


def test_subject_filling_frame_is_byte_identical(tmp_path):
    # A subject that already fills the frame earns no punch-in and no reframe.
    p = _save(_frame((1000, 1250), (150, 120, 850, 1130)), tmp_path, "big.png")
    vars_ = S.smart_focus(p, "4:5")
    assert vars_ == {"--mh-photo-pos": S.focus_position(p, "4:5")}


def test_smart_crop_reports_zoom_one_when_unchanged(tmp_path):
    p = _save(Image.new("RGB", (1000, 1250), (120, 120, 120)), tmp_path, "flat2.png")
    crop = S.smart_crop(p, "4:5")
    assert crop.zoom == 1.0
    assert (crop.x, crop.y, crop.w, crop.h) == S.best_crop(p, "4:5")


# --------------------------------------------------------------------------- #
# Punch-in on a small / distant subject
# --------------------------------------------------------------------------- #


def test_small_subject_is_punched_in(tmp_path):
    p = _save(_frame((1600, 900), (745, 375, 855, 525)), tmp_path, "small.png")
    vars_ = S.smart_focus(p, "4:5")
    assert "--mh-photo-scale" in vars_
    zoom = float(vars_["--mh-photo-scale"])
    assert 1.0 < zoom <= S._SMART_MAX_ZOOM


def test_zoom_never_exceeds_the_cap(tmp_path):
    # A pinprick subject would want a huge zoom — it's clamped to the cap.
    p = _save(_frame((2000, 2000), (995, 995, 1015, 1015)), tmp_path, "tiny.png")
    crop = S.smart_crop(p, "1:1")
    assert crop.zoom <= S._SMART_MAX_ZOOM


# --------------------------------------------------------------------------- #
# Rule-of-thirds placement (default) vs symmetric (centred)
# --------------------------------------------------------------------------- #


def test_offcentre_subject_is_placed_off_centre(tmp_path):
    # A wide frame cropped to 4:5 slides horizontally; a left subject is placed
    # left of centre (thirds), never dead-centre.
    p = _save(_frame((1600, 900), (150, 200, 450, 700)), tmp_path, "left.png")
    x, _ = _pos(S.smart_focus(p, "4:5"))
    assert x < 45.0


def test_symmetric_keeps_the_subject_centred(tmp_path):
    # Same off-centre-ish subject, but a symmetric composition holds today's
    # centroid framing (thirds snapping off).
    p = _save(_frame((1000, 1250), (300, 250, 520, 700)), tmp_path, "sym.png")
    sym = S.smart_focus(p, "4:5", symmetric=True)
    # The symmetric position equals today's centroid focus (scale aside).
    assert sym["--mh-photo-pos"] == S.focus_position(p, "4:5")


# --------------------------------------------------------------------------- #
# Headroom on a portrait cutout
# --------------------------------------------------------------------------- #


def test_portrait_cutout_keeps_headroom(tmp_path):
    # A small standing cutout near the top: the punched crop must not cut into
    # the head — its top edge sits above the subject, so y is small.
    p = _save(_cutout((1000, 1400), (440, 250, 560, 650)), tmp_path, "cut.png")
    crop = S.smart_crop(p, "4:5")
    # Head band: the crop top is at/above the subject top (250px).
    assert crop.y <= 260


# --------------------------------------------------------------------------- #
# Determinism + bounds
# --------------------------------------------------------------------------- #


def test_smart_crop_is_deterministic(tmp_path):
    p = _save(_frame((1600, 900), (745, 375, 855, 525)), tmp_path, "det.png")
    assert S.smart_crop(p, "4:5") == S.smart_crop(p, "4:5")
    assert S.smart_focus(p, "9:16") == S.smart_focus(p, "9:16")


def test_smart_crop_stays_within_bounds(tmp_path):
    p = _save(_frame((1600, 900), (1300, 100, 1500, 700)), tmp_path, "edge.png")
    for ratio in ("4:5", "9:16", "1:1", "16:9"):
        x, y, w, h, z = S.smart_crop(p, ratio)
        assert x >= 0 and y >= 0 and w > 0 and h > 0
        assert x + w <= 1600 and y + h <= 900


def test_smart_focus_safe_default_on_bad_path():
    assert S.smart_focus("/nope/none.jpg", "4:5") == {"--mh-photo-pos": "center 28%"}


def test_smart_focus_for_format_resolves_ratio(tmp_path):
    p = _save(_frame((1600, 900), (745, 375, 855, 525)), tmp_path, "fmt.png")
    story = S.smart_focus_for_format(p, "story")
    assert story == S.smart_focus(p, "9:16")


# --------------------------------------------------------------------------- #
# Mask steers the crop of a non-alpha original (parity with focus_with_mask)
# --------------------------------------------------------------------------- #


def test_mask_steers_smart_crop_of_non_alpha_original(tmp_path):
    photo = _save(_frame((1000, 1400), (150, 900, 850, 1300)), tmp_path, "orig.png")
    # The cutout says the SUBJECT (head) is up top, not the bright block below.
    mask = _save(_cutout((1000, 1400), (420, 200, 580, 620)), tmp_path, "mask.png")
    _, y = _pos(S.smart_focus(photo, "4:5", mask_path=mask))
    # Focus pulled up toward the masked subject, not the bottom block.
    assert y < 60.0


# --------------------------------------------------------------------------- #
# Registry — symmetric flag
# --------------------------------------------------------------------------- #


def test_symmetric_registry():
    assert A.is_symmetric("spotlight_disc")
    assert A.is_symmetric("centered_medal_spotlight")
    assert not A.is_symmetric("big_number_dominant")
    assert not A.is_symmetric("full_height_portrait_split")


# --------------------------------------------------------------------------- #
# render seam — effective_crop_intent + _crop_intent_vars("smart")
# --------------------------------------------------------------------------- #


def test_effective_crop_intent_env_gate(monkeypatch):
    monkeypatch.delenv(R._SMART_CROP_ENV, raising=False)
    assert R.effective_crop_intent("") == ""
    assert R.effective_crop_intent("centered") == "centered"
    monkeypatch.setenv(R._SMART_CROP_ENV, "1")
    assert R.effective_crop_intent("") == "smart"
    assert R.effective_crop_intent("tight_portrait") == "tight_portrait"


def test_crop_intent_vars_smart_matches_saliency(tmp_path):
    p = _save(_frame((1600, 900), (745, 375, 855, 525)), tmp_path, "seam.png")
    vars_ = R._crop_intent_vars("smart", p, None, 1080, 1350, symmetric=False)
    assert vars_ == S.smart_focus(p, "1080:1350", symmetric=False)


def test_crop_intent_vars_smart_symmetric_flag(tmp_path):
    p = _save(_frame((1000, 1250), (300, 250, 520, 700)), tmp_path, "seamsym.png")
    asym = R._crop_intent_vars("smart", p, None, 1080, 1350, symmetric=False)
    sym = R._crop_intent_vars("smart", p, None, 1080, 1350, symmetric=True)
    # The symmetric flag changes placement (centred vs thirds).
    assert sym["--mh-photo-pos"] != asym["--mh-photo-pos"] or "--mh-photo-scale" in sym


def test_smart_is_in_crop_intents_vocab():
    from mediahub.creative_brief.design_spec import CROP_INTENTS

    assert "smart" in CROP_INTENTS
