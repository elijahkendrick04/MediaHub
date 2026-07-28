"""Cross-surface parity for the per-keyframe interpolation modes (interp-types).

Three surfaces sample the SAME motion vocabulary and must agree:

* Python ``_sample`` (``value_at``) — the source of truth the still + CSS bake.
* The browser CSS (``compile_css``) — bakes stops from ``value_at``; the fine-grid
  selection must honour a non-bezier interp so a ``hold`` step isn't linearly
  tweened between the {0,1} endpoints only.
* The Remotion TS ``sampleChannel`` — mirrors the Python ``_track_tangents`` /
  ``_hermite_at`` math exactly. Its outputs can't be evaluated from pytest, so
  this file PINS a numeric fixture the TS Hermite math must reproduce byte-for-
  byte (kept in sync by inspection + the type/regen guards).
"""

from __future__ import annotations

import re

import pytest

from mediahub.motion import compile_css
from mediahub.motion import vocabulary as v


def _p(channel, kfs, *, duration=20, photo=False, family="in", loop=False):
    return v.MotionPreset(
        name="synthetic",
        family=family,
        energy="standard",
        direction="none",
        duration_frames=duration,
        channels={channel: tuple(kfs)},
        photo=photo,
        loop=loop,
    )


# ---------------------------------------------------------------------------
# CSS ↔ Python parity (the ADVERSARIAL-VERIFY correction)
# ---------------------------------------------------------------------------


def test_hold_with_linear_easing_forces_fine_grid():
    # The exact case the correction flags: a 2-keyframe hold left at linear
    # easing. Without the interp check _needs_fine_grid returns False and CSS
    # bakes only {0,1}, linearly tweening a step. With the fix it bakes the grid.
    held = _p("opacity", [v.kf(0.0, 0.0, "linear"), v.kf(1.0, 1.0, "linear", interp="hold")])
    stops = compile_css._stops(held)
    assert len(stops) > 2, "hold preset must bake a fine grid, not just the endpoints"
    assert compile_css._needs_fine_grid(held)


def _baked_opacity(block: str) -> dict[float, float]:
    """Parse ``{pct%{...opacity:VAL}}`` pairs out of a @keyframes block."""
    out: dict[float, float] = {}
    for pct, val in re.findall(r"([\d.]+)%\{[^}]*opacity:([\d.]+)", block):
        out[round(float(pct) / 100.0, 5)] = float(val)
    return out


def test_css_baked_hold_stops_equal_value_at():
    # A hold preset: the rendered CSS stops (parsed from the @keyframes block)
    # must equal value_at at each stop — proving CSS bakes the step shape rather
    # than linearly tweening the {0,1} endpoints.
    held = _p("opacity", [v.kf(0.0, 0.0, "linear"), v.kf(0.5, 1.0, "linear", interp="hold")])
    block = compile_css.keyframes_block(held)
    baked = _baked_opacity(block)
    assert baked, "no opacity stops parsed"
    for t, css_val in baked.items():
        assert css_val == pytest.approx(held.value_at("opacity", t), abs=1e-4), t
    # the step is actually present: a plateau at 0 before the jump, 1 after.
    assert baked[0.45] == pytest.approx(0.0)
    assert baked[0.5] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Python ↔ Remotion parity fixture (the TS Hermite math must reproduce these)
# ---------------------------------------------------------------------------
#
# TS `sampleChannel` mirrors `_track_tangents` + `_hermite_at`. Keep these tables
# identical to what the TS produces for the same tokens; a divergence here means
# the two implementations drifted.

_SAMPLE_TS = [0.1, 0.25, 0.4, 0.5, 0.6, 0.75, 0.9]

_CONTINUOUS_KFS = [
    v.kf(0.0, 0.0),
    v.kf(0.25, 8.0, interp="continuous"),
    v.kf(0.75, 3.0, interp="continuous"),
    v.kf(1.0, 5.0, interp="continuous"),
]
_CONTINUOUS_EXPECTED = [3.872, 8.0, 7.34, 6.0, 4.5, 3.0, 3.912]

_AUTO_KFS = [
    v.kf(0.0, 0.0),
    v.kf(0.25, 8.0, interp="auto"),
    v.kf(0.75, 3.0, interp="auto"),
    v.kf(1.0, 5.0, interp="auto"),
]
_AUTO_EXPECTED = [3.968, 8.0, 6.92, 5.5, 4.08, 3.0, 4.008]

_HOLD_KFS = [v.kf(0.0, 0.0), v.kf(0.5, 1.0, interp="hold"), v.kf(1.0, 0.25, interp="hold")]
_HOLD_EXPECTED = [0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]


@pytest.mark.parametrize(
    "kfs, expected",
    [
        (_CONTINUOUS_KFS, _CONTINUOUS_EXPECTED),
        (_AUTO_KFS, _AUTO_EXPECTED),
        (_HOLD_KFS, _HOLD_EXPECTED),
    ],
)
def test_hermite_fixture_pins_cross_engine_values(kfs, expected):
    got = [v._sample(kfs, t) for t in _SAMPLE_TS]
    assert got == pytest.approx(expected, abs=1e-9)


def test_auto_never_exceeds_neighbours_but_continuous_may():
    # auto is overshoot-clamped at extrema; continuous can overshoot. On a track
    # that dips to a trough then rises, continuous undershoots below the trough
    # while auto does not.
    kfs_c = [
        v.kf(0.0, 10.0, interp="continuous"),
        v.kf(0.5, 0.0, interp="continuous"),
        v.kf(1.0, 10.0, interp="continuous"),
    ]
    kfs_a = [
        v.kf(0.0, 10.0, interp="auto"),
        v.kf(0.5, 0.0, interp="auto"),
        v.kf(1.0, 10.0, interp="auto"),
    ]
    pc = _p("translateY", kfs_c)
    pa = _p("translateY", kfs_a)
    auto_min = min(pa.value_at("translateY", i / 40.0) for i in range(41))
    # auto flattens the tangent at the symmetric trough → tangent 0 → no
    # undershoot below 0.
    assert auto_min >= -1e-9
    # (the continuous curve here is also symmetric with a 0 tangent, so this
    # asymmetric case proves the difference)
    kfs_c2 = [
        v.kf(0.0, 10.0, interp="continuous"),
        v.kf(0.5, 0.0, interp="continuous"),
        v.kf(1.0, 6.0, interp="continuous"),
    ]
    pc2 = _p("translateY", kfs_c2)
    cont_min = min(pc2.value_at("translateY", i / 40.0) for i in range(41))
    assert cont_min < -1e-6, "continuous should undershoot below the trough here"
    _ = pc  # keep the symmetric continuous preset referenced for clarity
