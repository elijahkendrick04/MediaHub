"""Tests for the deterministic text auto-fit helper.

``mediahub.graphic_renderer.autofit`` is pure layout maths: given a string and a
box it returns the largest integer px size at which the text fits. These tests
pin a handful of *golden* values (so an accidental change to the width table is
caught) and assert the structural invariants that must hold regardless of how the
table is tuned — most importantly that the returned size genuinely fits and that
``size + 1`` does not.

Box convention: a deliberately tall box (height = 100_000) isolates the
width constraint, so the result is driven purely by advance-width maths; a short
box exercises the height/line-count constraint.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from mediahub.graphic_renderer import autofit as af

TALL = 100_000  # box height that never binds — isolates the width constraint

# A genuinely long double-barrelled surname (one unbreakable token) and a long
# multi-word name (wraps) — the realistic stressors for a swim result card.
LONG_TOKEN = "Wolajimi-Abubakari"
LONG_MULTIWORD = "Maximilianus Featherstonehaugh"


# --------------------------------------------------------------------------- #
# Independent fit oracle — re-derives "does it fit?" from the public primitives,
# so the invariant checks don't depend on fit_font_px's own internals.
# --------------------------------------------------------------------------- #
def _block_fits(text, size, box_w, box_h, *, font_family, weight, line_height):
    lines = af.wrap_text(text, box_w, size, font_family=font_family, weight=weight)
    if not lines:
        return True
    if len(lines) * size * line_height > box_h + 1e-6:
        return False
    return all(
        af.measure_line_px(ln, size, font_family=font_family, weight=weight) <= box_w + 1e-6
        for ln in lines
    )


# --------------------------------------------------------------------------- #
# Golden values (encode the current deterministic char-width table)
# --------------------------------------------------------------------------- #
def test_golden_width_limited_sizes():
    # Tall box -> width is the only binding constraint.
    assert af.fit_font_px("Cox", 1000, TALL, font_family="Inter", weight=700, max_px=3000) == 542
    assert af.fit_font_px(LONG_TOKEN, 1000, TALL, font_family="Inter", weight=700, max_px=3000) == 112
    # Condensed display face (Anton) packs far more characters per px width.
    assert af.fit_font_px("Cox", 1000, TALL, font_family="Anton", weight=700, max_px=3000) == 904


def test_golden_height_limited_single_line():
    # Wide box, short text, short box -> height caps a single line at box_h/line_height.
    assert af.fit_font_px("Hi", 800, 120, font_family="Inter", weight=700,
                          min_px=8, max_px=400, line_height=1.0) == 120


def test_golden_narrow_vs_wide_box():
    narrow = af.fit_font_px(LONG_TOKEN, 300, TALL, font_family="Inter", weight=700, max_px=3000)
    wide = af.fit_font_px(LONG_TOKEN, 1000, TALL, font_family="Inter", weight=700, max_px=3000)
    assert (narrow, wide) == (33, 112)


# --------------------------------------------------------------------------- #
# Short vs very long swimmer names
# --------------------------------------------------------------------------- #
def test_short_name_fits_larger_than_long_name():
    box_w, box_h = 700, 300
    short = af.fit_font_px("Cox", box_w, box_h, font_family="Anton", weight=700, max_px=400)
    medium = af.fit_font_px("Hannah Cox", box_w, box_h, font_family="Anton", weight=700, max_px=400)
    long_tok = af.fit_font_px(LONG_TOKEN, box_w, box_h, font_family="Anton", weight=700, max_px=400)
    assert short >= medium >= long_tok
    assert short > long_tok  # the headline guarantee: long names shrink to fit


def test_long_multiword_name_wraps_and_fits():
    box_w, box_h = 600, 400
    size, lines = af.fit_text(LONG_MULTIWORD, box_w, box_h,
                              font_family="Anton", weight=700, max_px=400, line_height=1.1)
    assert len(lines) >= 2  # it must wrap to fit a 600px-wide box
    # Reconstruct the original words from the wrapped lines (wrapping only moves
    # word boundaries to line boundaries; it never drops or alters words).
    assert " ".join(lines).split() == LONG_MULTIWORD.split()
    assert _block_fits(LONG_MULTIWORD, size, box_w, box_h,
                       font_family="Anton", weight=700, line_height=1.1)


# --------------------------------------------------------------------------- #
# Core correctness invariant: the returned size fits and size+1 does not
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("text,box_w,box_h,family,weight,lh", [
    ("Cox", 400, 200, "Inter", 400, 1.0),
    ("Hannah Cox", 500, 220, "Inter", 700, 1.2),
    (LONG_TOKEN, 360, 180, "Anton", 700, 1.0),
    (LONG_MULTIWORD, 640, 480, "Inter", 400, 1.25),
    ("100m Freestyle — Personal Best", 520, 300, "Oswald", 600, 1.15),
    ("PB", 240, 240, "JetBrains Mono", 500, 1.0),
])
def test_returned_size_is_the_largest_that_fits(text, box_w, box_h, family, weight, lh):
    size = af.fit_font_px(text, box_w, box_h, font_family=family, weight=weight,
                          min_px=8, max_px=400, line_height=lh)
    assert 8 <= size <= 400
    if size > 8:  # floor may legitimately overflow; above the floor it must fit
        assert _block_fits(text, size, box_w, box_h,
                           font_family=family, weight=weight, line_height=lh)
    if size < 400:  # one px larger must break the fit
        assert not _block_fits(text, size + 1, box_w, box_h,
                               font_family=family, weight=weight, line_height=lh)


# --------------------------------------------------------------------------- #
# Monotonicity: more room never yields a smaller size
# --------------------------------------------------------------------------- #
def test_size_is_monotonic_in_box_width():
    sizes = [
        af.fit_font_px(LONG_TOKEN, w, TALL, font_family="Inter", weight=700, max_px=3000)
        for w in (200, 300, 500, 800, 1200)
    ]
    assert sizes == sorted(sizes)


def test_size_is_monotonic_in_box_height():
    sizes = [
        af.fit_font_px(LONG_MULTIWORD, 500, h, font_family="Inter", weight=400, max_px=400)
        for h in (80, 160, 320, 640)
    ]
    assert sizes == sorted(sizes)


# --------------------------------------------------------------------------- #
# Font-family and weight effects
# --------------------------------------------------------------------------- #
def test_condensed_fits_larger_than_sans_than_mono():
    def fit(fam):
        return af.fit_font_px("Hannah", 600, TALL, font_family=fam, weight=700, max_px=3000)
    assert fit("Anton") > fit("Inter") >= fit("JetBrains Mono")


def test_heavier_weight_never_fits_larger():
    light = af.fit_font_px("Hannah", 600, TALL, font_family="Inter", weight=300, max_px=3000)
    bold = af.fit_font_px("Hannah", 600, TALL, font_family="Inter", weight=900, max_px=3000)
    assert bold <= light


def test_weight_accepts_names_and_numbers():
    assert af.em_width("Hannah", weight="bold") == pytest.approx(af.em_width("Hannah", weight=700))
    assert af.em_width("Hannah", weight="normal") == pytest.approx(af.em_width("Hannah", weight=400))


def test_larger_line_height_never_fits_larger():
    tight = af.fit_font_px("Hannah Cox", 300, 400, font_family="Inter", weight=400,
                           max_px=400, line_height=1.0)
    loose = af.fit_font_px("Hannah Cox", 300, 400, font_family="Inter", weight=400,
                           max_px=400, line_height=2.0)
    assert loose <= tight


# --------------------------------------------------------------------------- #
# Edge cases and bounds
# --------------------------------------------------------------------------- #
def test_empty_text_returns_max():
    assert af.fit_font_px("", 100, 100, max_px=240) == 240
    assert af.fit_font_px("   ", 100, 100, max_px=240) == 240


def test_impossible_fit_returns_floor():
    # A long token in a tiny box cannot fit at any size; return the min_px floor.
    assert af.fit_font_px(LONG_TOKEN, 20, 20, min_px=8, max_px=200) == 8


def test_result_always_within_bounds():
    for mx in (10, 50, 240):
        size = af.fit_font_px("Hannah Cox", 500, 300, min_px=10, max_px=mx)
        assert 10 <= size <= mx


def test_deterministic_across_calls():
    a = af.fit_font_px(LONG_MULTIWORD, 480, 260, font_family="Anton", weight=700, line_height=1.1)
    b = af.fit_font_px(LONG_MULTIWORD, 480, 260, font_family="Anton", weight=700, line_height=1.1)
    assert a == b


@pytest.mark.parametrize("kwargs", [
    {"box_w": 0, "box_h": 100},
    {"box_w": 100, "box_h": -5},
    {"box_w": 100, "box_h": 100, "min_px": 0},
    {"box_w": 100, "box_h": 100, "min_px": 50, "max_px": 20},
])
def test_invalid_geometry_raises(kwargs):
    with pytest.raises(ValueError):
        af.fit_font_px("x", **kwargs)


# --------------------------------------------------------------------------- #
# Wrapping helpers
# --------------------------------------------------------------------------- #
def test_wrap_keeps_every_line_within_box():
    text = "Hannah Cox wins the 100m Freestyle final"
    lines = af.wrap_text(text, 300, 40, font_family="Inter", weight=400)
    assert len(lines) > 1
    for ln in lines:
        assert af.measure_line_px(ln, 40, font_family="Inter", weight=400) <= 300 + 1e-6
    assert " ".join(lines).split() == text.split()


def test_wrap_honours_hard_newlines():
    lines = af.wrap_text("HANNAH COX\n100m FREESTYLE", 10_000, 40)
    assert lines == ["HANNAH COX", "100m FREESTYLE"]


def test_wrap_unbreakable_word_on_its_own_line():
    lines = af.wrap_text(LONG_TOKEN, 50, 40, font_family="Inter", weight=400)
    assert lines == [LONG_TOKEN]  # never hyphenated, even when it overflows


def test_wrap_empty_text_returns_no_lines():
    assert af.wrap_text("", 100, 40) == []
    assert af.wrap_text("   ", 100, 40) == []


def test_fit_text_returns_consistent_size_and_lines():
    size, lines = af.fit_text("Hannah Cox", 300, 400, font_family="Inter", weight=400, max_px=400)
    assert size == af.fit_font_px("Hannah Cox", 300, 400, font_family="Inter", weight=400, max_px=400)
    assert lines == af.wrap_text("Hannah Cox", 300, size, font_family="Inter", weight=400)


# --------------------------------------------------------------------------- #
# Measurement primitives
# --------------------------------------------------------------------------- #
def test_em_width_empty_is_zero():
    assert af.em_width("") == 0.0


def test_measure_line_px_scales_linearly_with_size():
    w100 = af.measure_line_px("Hannah", 100, font_family="Inter", weight=400)
    w200 = af.measure_line_px("Hannah", 200, font_family="Inter", weight=400)
    assert w200 == pytest.approx(2 * w100)
    # table path == em_width * size
    assert w100 == pytest.approx(af.em_width("Hannah", font_family="Inter", weight=400) * 100)


# --------------------------------------------------------------------------- #
# Optional Pillow path (real font metrics) — skipped when no font file present
# --------------------------------------------------------------------------- #
def _find_font_file():
    root = Path(__file__).resolve().parents[1]
    fonts = root / "skills-main" / "skills" / "canvas-design" / "canvas-fonts"
    if fonts.is_dir():
        for ttf in sorted(fonts.glob("*.ttf")):
            return ttf
    return None


def test_pillow_font_path_is_deterministic_and_linear():
    pytest.importorskip("PIL")
    font = _find_font_file()
    if font is None:
        pytest.skip("no .ttf available to exercise the Pillow path")

    w100 = af.measure_line_px("Hannah", 100, font_path=str(font))
    w200 = af.measure_line_px("Hannah", 200, font_path=str(font))
    assert w100 > 0
    assert af.measure_line_px("Hannah", 100, font_path=str(font)) == w100  # deterministic
    assert w200 == pytest.approx(2 * w100, rel=0.02)
    # Real metrics land in the same ballpark as the deterministic table estimate.
    table = af.measure_line_px("Hannah", 100, font_family="Work Sans", weight=400)
    assert w100 == pytest.approx(table, rel=0.20)
