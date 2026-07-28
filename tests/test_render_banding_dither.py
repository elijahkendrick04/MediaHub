"""render-banding-dither — a deterministic ordered-dither debanding layer.

Covers the still side (the static Bayer data-URI, its mean-preserving property,
the opt-in render hook, the registered ``dither`` background token) and the
motion parity signal (a card's ``dither`` prop rides the still's opt-in). The
default render stays byte-identical: with no ``dither`` token neither the hook
nor the prop fires.
"""

from __future__ import annotations

import base64
import re
from types import SimpleNamespace

from mediahub.graphic_renderer import render
from mediahub.graphic_renderer.sprint_hooks import RenderHookCtx
from mediahub.graphic_renderer.sprint_hooks import dither_bg


# ---------------------------------------------------------------------------
# The static Bayer tile
# ---------------------------------------------------------------------------


def _greys(uri: str) -> list[int]:
    """Pull the per-cell grey values out of the data-URI SVG tile."""
    m = re.search(r"base64,([A-Za-z0-9+/=]+)", uri)
    assert m, f"expected a base64 data URI, got {uri!r}"
    svg = base64.b64decode(m.group(1)).decode()
    return [int(r) for (r, _g, _b) in re.findall(r"fill='rgb\((\d+),(\d+),(\d+)\)'", svg)]


def test_dither_uri_is_byte_stable_across_calls():
    a = render._dither_pattern_data_uri()
    b = render._dither_pattern_data_uri()
    assert a == b, "the dither tile must be a pure constant (deterministic)"
    assert a.startswith('url("data:image/svg+xml;base64,')


def test_dither_uri_carries_no_randomness_source():
    uri = render._dither_pattern_data_uri()
    svg = base64.b64decode(re.search(r"base64,([A-Za-z0-9+/=]+)", uri).group(1)).decode()
    # A genuine ordered dither — no turbulence filter, no RNG, no clock.
    for banned in ("feTurbulence", "random", "Date", "filter"):
        assert banned not in svg, f"ordered dither must not contain {banned!r}"


def test_dither_tile_is_64_cells_of_grey():
    greys = _greys(render._dither_pattern_data_uri())
    assert len(greys) == 64, "an 8x8 Bayer tile has 64 cells"


def test_dither_is_mean_preserving_neutral_grey():
    """The tile's average grey is EXACTLY 128 (neutral under mix-blend overlay),
    so compositing it over a fill leaves the field's average colour unchanged —
    no APCA text/bg pair can cross its floor."""
    greys = _greys(render._dither_pattern_data_uri())
    assert sum(greys) == 128 * len(greys)
    assert sum(greys) / len(greys) == 128.0


def test_dither_amplitude_is_low():
    """Every cell stays within ±amplitude of neutral — a ~±1/255 perturbation,
    far too small to shift legibility, big enough to break 8-bit banding."""
    greys = _greys(render._dither_pattern_data_uri())
    for g in greys:
        assert abs(g - 128) <= render._DITHER_AMPLITUDE


# ---------------------------------------------------------------------------
# The registered ``dither`` background token (correction b: no water fallthrough)
# ---------------------------------------------------------------------------


def test_dither_token_resolves_to_clean_ground_not_water():
    """A bare ``dither`` ground must NOT fall through to the busy water tile —
    the dither wants a smooth big fill to deband."""
    assert render._background_pattern_for("dither") == render._bg_clean_data_uri()
    assert render._background_pattern_for("dither") != render._water_pattern_data_uri()


# ---------------------------------------------------------------------------
# The opt-in render hook (correction a: a SEPARATE standalone token)
# ---------------------------------------------------------------------------

_HTML_V1 = (
    '<html><body><div class="canvas">'
    '<div class="bg-gradient"></div>'
    '<div class="bg-noise"></div>'
    "<main>card</main></div></body></html>"
)
_HTML_V2 = "<html><body><div><main>card</main></div></body></html>"


def _ctx(brief, *, is_v2=False):
    return RenderHookCtx(
        brief=brief,
        width=1080,
        height=1350,
        family="big_number_dominant",
        format_name="feed_portrait",
        is_v2=is_v2,
    )


def _brief(background_style=""):
    return SimpleNamespace(background_style=background_style)


def test_hook_byte_identical_without_token():
    for style in ("", "water", "gradient_mesh", "gradient_mesh:radial", "halftone"):
        out = dither_bg.apply(_HTML_V1, _ctx(_brief(style)))
        assert out == _HTML_V1, f"style={style!r} must not inject the dither layer"


def test_hook_does_not_collide_with_mesh_mode_suffix():
    """The separate opt-in never fires off a mesh ``:mode`` — only the standalone
    ``dither`` base token triggers it, so the two contracts can't clash."""
    out = dither_bg.apply(_HTML_V1, _ctx(_brief("gradient_mesh:conic")))
    assert out == _HTML_V1


def test_hook_injects_overlay_on_v1_after_bg_noise():
    out = dither_bg.apply(_HTML_V1, _ctx(_brief("dither")))
    assert out != _HTML_V1
    assert 'class="bg-dither mh-dither-v1"' in out
    assert "data-mh-dither" in out
    assert "mix-blend-mode:overlay" in out
    # placed directly after the ground/noise layer, not above content
    assert out.index('class="bg-dither') < out.index("<main>")


def test_hook_injects_overlay_on_v2_body_level():
    out = dither_bg.apply(_HTML_V2, _ctx(_brief("dither"), is_v2=True))
    assert out != _HTML_V2
    assert 'class="bg-dither mh-dither-v2"' in out
    assert out.rstrip().endswith("</body></html>")


def test_hook_is_deterministic():
    a = dither_bg.apply(_HTML_V1, _ctx(_brief("dither")))
    b = dither_bg.apply(_HTML_V1, _ctx(_brief("dither")))
    assert a == b
