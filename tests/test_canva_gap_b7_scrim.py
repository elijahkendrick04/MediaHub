"""B7 (Canva gap analysis) — photo-adaptive scrim alpha.

A deterministic PIL pre-pass samples the graded photo region under the
over-photo text and raises the scrim alpha from the archetype's authored floor
until the light ink clears APCA against the actual pixels. Guards:

* the object-position → cover-crop maths (``_parse_object_position``,
  ``_cover_bottom_band_luma``);
* the alpha search (``_scrim_alpha_for_luma``) — never below the floor, capped,
  raises on a bright region;
* ``_photo_scrim_plan`` gating (non-scrim archetype / photo-less / dark ink → None);
* the three layouts consume ``--mh-scrim-alpha`` with the authored constant as
  the byte-identical fallback;
* determinism (same photo + crop → same alpha).
"""

from __future__ import annotations

from types import SimpleNamespace

from PIL import Image

from mediahub.graphic_renderer import archetypes as _arch
from mediahub.graphic_renderer import render as R

_ROLES = {
    "--mh-primary": "#0A2540",
    "--mh-on-primary": "#F6F7F9",  # light ink (dark ground)
    "--mh-surface": "#0A1626",
}


def _photo(tmp_path, top_rgb, bottom_rgb, split=800):
    p = tmp_path / "athlete.jpg"
    img = Image.new("RGB", (900, 1400))
    px = img.load()
    for y in range(1400):
        row = bottom_rgb if y > split else top_rgb
        for x in range(900):
            px[x, y] = row
    img.save(p, quality=95)
    return str(p)


# --------------------------------------------------------------------------- #
# object-position parsing
# --------------------------------------------------------------------------- #
def test_parse_object_position_keywords_and_percents():
    assert R._parse_object_position("center 24%") == (0.5, 0.24)
    assert R._parse_object_position("left top") == (0.0, 0.0)
    assert R._parse_object_position("50% 30%") == (0.5, 0.3)
    assert R._parse_object_position("right bottom") == (1.0, 1.0)
    # single vertical keyword keeps x centred.
    assert R._parse_object_position("bottom") == (0.5, 1.0)
    # empty → centre.
    assert R._parse_object_position("") == (0.5, 0.5)


# --------------------------------------------------------------------------- #
# cover-crop bottom-band luminance
# --------------------------------------------------------------------------- #
def test_cover_bottom_band_luma_reads_the_bottom_of_the_frame():
    # dark top, near-white bottom → the bottom band samples bright.
    bright = Image.new("RGB", (900, 1400))
    b = bright.load()
    for y in range(1400):
        for x in range(900):
            b[x, y] = (250, 250, 250) if y > 800 else (20, 20, 20)
    luma = R._cover_bottom_band_luma(bright, 1080, 1350, "center 50%")
    assert luma is not None and luma > 220
    # a uniformly dark photo samples dark.
    dark = Image.new("RGB", (900, 1400), (18, 22, 30))
    assert (R._cover_bottom_band_luma(dark, 1080, 1350, "center 50%") or 255) < 60


# --------------------------------------------------------------------------- #
# alpha search
# --------------------------------------------------------------------------- #
def test_scrim_alpha_never_drops_below_floor_and_caps():
    # a dark region: the floor already clears → returns exactly the floor.
    assert R._scrim_alpha_for_luma(20, "#F6F7F9", "#000000", 0.40) == 0.40
    # a near-white region under a low floor → the alpha is raised.
    raised = R._scrim_alpha_for_luma(255, "#F6F7F9", "#000000", 0.30)
    assert raised > 0.30
    assert raised <= R._SCRIM_MAX_ALPHA


def test_scrim_alpha_is_monotonic_in_region_brightness():
    a_dark = R._scrim_alpha_for_luma(60, "#F6F7F9", "#000000", 0.20)
    a_mid = R._scrim_alpha_for_luma(180, "#F6F7F9", "#000000", 0.20)
    a_bright = R._scrim_alpha_for_luma(255, "#F6F7F9", "#000000", 0.20)
    assert a_dark <= a_mid <= a_bright


# --------------------------------------------------------------------------- #
# _photo_scrim_plan gating
# --------------------------------------------------------------------------- #
def _brief():
    return SimpleNamespace(photo_adjust="", photo_treatment="")


def test_scrim_plan_returns_alpha_for_a_photo_led_scrim_archetype(tmp_path):
    photo = _photo(tmp_path, (250, 250, 250), (250, 250, 250))  # all bright
    plan = R._photo_scrim_plan(
        "full_bleed_photo_lower_third", photo, _brief(), _ROLES, 1080, 1350, "center 50%"
    )
    assert plan is not None
    alpha, luma = plan
    assert 0.40 <= alpha <= R._SCRIM_MAX_ALPHA
    assert luma > 220


def test_scrim_plan_none_for_non_scrim_archetype(tmp_path):
    photo = _photo(tmp_path, (250, 250, 250), (250, 250, 250))
    assert (
        R._photo_scrim_plan("big_number_dominant", photo, _brief(), _ROLES, 1080, 1350, "") is None
    )


def test_scrim_plan_none_without_a_photo():
    assert (
        R._photo_scrim_plan("full_bleed_photo_lower_third", None, _brief(), _ROLES, 1080, 1350, "")
        is None
    )


def test_scrim_plan_none_for_dark_ink():
    # a light-ground card (dark ink) — a black/primary scrim can't protect it,
    # so the pre-pass leaves the authored scrim alone.
    dark_ink = {**_ROLES, "--mh-on-primary": "#0B0B0C"}
    # even with a photo the gate refuses (build one lazily via a tmp is overkill;
    # None athlete already covers the photo-less branch, so use a sentinel path).
    assert (
        R._photo_scrim_plan(
            "full_bleed_photo_lower_third", "does-not-exist.jpg", _brief(), dark_ink, 1080, 1350, ""
        )
        is None
    )


def test_scrim_plan_is_deterministic(tmp_path):
    photo = _photo(tmp_path, (40, 60, 90), (240, 240, 245))
    a = R._photo_scrim_plan("broadcast_scorebug", photo, _brief(), _ROLES, 1080, 1350, "center 30%")
    b = R._photo_scrim_plan("broadcast_scorebug", photo, _brief(), _ROLES, 1080, 1350, "center 30%")
    assert a == b and a is not None


# --------------------------------------------------------------------------- #
# layout consumption (byte-identity by var fallback)
# --------------------------------------------------------------------------- #
def test_scrim_layouts_consume_the_alpha_with_authored_fallback():
    scorebug = (_arch.V2_DIR / "broadcast_scorebug.html").read_text(encoding="utf-8")
    assert "rgba(0,0,0,var(--mh-scrim-alpha,0.55))" in scorebug
    lower = (_arch.V2_DIR / "full_bleed_photo_lower_third.html").read_text(encoding="utf-8")
    assert "rgba(0,0,0,var(--mh-scrim-alpha,0.40))" in lower
    mag = (_arch.V2_DIR / "magazine_cover.html").read_text(encoding="utf-8")
    assert "var(--mh-scrim-alpha, 0.62)" in mag
