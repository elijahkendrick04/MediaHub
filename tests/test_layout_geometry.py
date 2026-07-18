"""F2 (systemic floor) — geometry context tokens + offender migration.

F2 publishes a per-canvas geometry context — ``--mh-short`` / ``--mh-margin`` /
``--mh-gutter`` / ``--mh-col`` (``render._geometry_scale_css``) — and migrates
the worst frozen-pixel offenders to ``calc()`` off it: the
``centered_medal_spotlight`` 620px ring, the ``radial_competition_ring`` 540px
dial, the ``stat_stack_sidebar`` 320px rail and the ``split_diagonal_hero`` 690px
wedge. The coefficients are exact integer ratios of the 1080 short edge, so
every certified 1080-wide format (portrait 1080×1350 and story 1080×1920 both
have ``min(w,h)==1080``) renders byte-identical — proven by a render-diff in the
build — while a smaller canvas scales the whole geometry down together.
"""

from __future__ import annotations

import re
from fractions import Fraction

from mediahub.graphic_renderer.render import (
    LAYOUTS_DIR,
    _geometry_scale_css,
    _round8,
)


def test_round8_snaps_to_module():
    assert _round8(0.06 * 1080) == 64  # 64.8 → 64
    assert _round8(0.02 * 1080) == 24  # 21.6 → 24
    assert _round8(0) == 0
    assert _round8(26) == 24  # 26 → 3.25 → 3*8
    assert _round8(30) == 32  # 30 → 3.75 → 4*8


def test_geometry_context_at_certified_formats():
    portrait = _geometry_scale_css(1080, 1350)
    story = _geometry_scale_css(1080, 1920)
    landscape = _geometry_scale_css(1920, 1080)
    # All three certified formats share short==1080, so the geometry is identical
    # — the guarantee that makes the offender migration byte-identical.
    assert portrait == story == landscape
    assert "--mh-short:1080px;" in portrait
    assert "--mh-margin:64px;" in portrait
    assert "--mh-gutter:24px;" in portrait
    assert "--mh-col:calc((var(--mh-short) - var(--mh-margin) * 2) / 12);" in portrait


def test_geometry_context_scales_on_smaller_canvas():
    small = _geometry_scale_css(540, 675)
    assert "--mh-short:540px;" in small
    assert "--mh-margin:32px;" in small  # round8(0.06*540)=round8(32.4)=32
    assert "--mh-gutter:8px;" in small  # round8(0.02*540)=round8(10.8)=8


# The exact-ratio coefficients each offender was migrated to, and the px they
# must reproduce at the 1080 short edge.
_OFFENDER_RATIOS = {
    "centered_medal_spotlight.html": [(Fraction(31, 54), 620)],
    "radial_competition_ring.html": [
        (Fraction(1, 2), 540),  # --rr-dial
        (Fraction(41, 45), 492),  # tickmask, relative to the dial
        (Fraction(113, 135), 452),  # ring
        (Fraction(97, 135), 388),  # core
    ],
    "stat_stack_sidebar.html": [(Fraction(8, 27), 320)],
    "split_diagonal_hero.html": [(Fraction(23, 36), 690)],
}


def test_offender_coefficients_are_exact_at_1080():
    # The dial ratios are relative to --rr-dial (itself 1080/2=540), so the inner
    # rings resolve against 540, not 1080.
    for f, ratios in _OFFENDER_RATIOS.items():
        base = 1080
        for ratio, expected in ratios:
            if f == "radial_competition_ring.html" and ratio != Fraction(1, 2):
                base = 540
            assert base * ratio == expected, f"{f}: {ratio} * {base} != {expected}"


def test_offenders_reference_the_geometry_var():
    for f in _OFFENDER_RATIOS:
        raw = (LAYOUTS_DIR / "v2" / f).read_text(encoding="utf-8")
        assert "var(--mh-short" in raw, f"{f} no longer references --mh-short"
        # No hardcoded hex crept in with the migration.
        assert re.search(r"#[0-9a-fA-F]{3,6}\b", raw) is None, f"{f} has a hex literal"


def test_migrated_dimensions_are_no_longer_raw_px():
    # The frozen px counts are gone (replaced by calc), so a regression back to a
    # hardcoded ring/dial/rail/wedge size is caught.
    checks = {
        "centered_medal_spotlight.html": "620px",
        "stat_stack_sidebar.html": "320px",
        "split_diagonal_hero.html": "690px",
    }
    comment_re = re.compile(r"/\*.*?\*/", re.DOTALL)
    for f, needle in checks.items():
        raw = comment_re.sub("", (LAYOUTS_DIR / "v2" / f).read_text(encoding="utf-8"))
        assert needle not in raw, f"{f} still hardcodes {needle!r} in a declaration"
