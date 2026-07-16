"""D7-structural (Canva gap analysis) — vertical spine archetype + skew slab.

Rotated/vertical type was absent from MediaHub — every glyph in all archetypes
was horizontal. This adds a full-height vertical-rl surname spine
(poster_spine) with a vertical-aware autofit, and a broadcast-angled skew_slab
ACCENT_GEOS motif. Both mirror on the motion side.
"""

from __future__ import annotations

from pathlib import Path

from mediahub.graphic_renderer import archetypes as A
from mediahub.graphic_renderer import style_packs as sp

_ROOT = Path(A.__file__).parent
_TSX = _ROOT.parents[0] / "remotion" / "src" / "compositions" / "StoryCard.tsx"


# --- skew_slab motif -------------------------------------------------------


def test_skew_slab_registered_and_capped():
    assert "skew_slab" in sp.ACCENT_GEOS
    assert sp._ACCENT_W["skew_slab"] == 2
    assert "skew_slab" in sp._ACCENT_LABEL


def test_skew_slab_is_brand_locked_and_angled():
    html = sp._accent_geometry_html("skew_slab", 1080, 1350, bold=True)
    assert "skewX(-12deg)" in html
    assert "var(--mh-accent)" in html
    assert "z-index:4" in html
    import re

    assert not re.search(r"#[0-9a-f]{3,6}", html.lower())


def test_skew_slab_executed_on_motion_side():
    src = _TSX.read_text()
    assert 'case "skew_slab"' in src
    assert "skewX(-12deg)" in src


# --- poster_spine archetype + vertical fit --------------------------------


def test_spine_archetype_registered_type_led():
    assert "poster_spine" in A.list_archetypes()
    # No photo slot → type-led.
    assert "poster_spine" not in A.photo_archetypes()


def test_spine_layout_uses_vertical_writing_mode():
    raw = (_ROOT / "layouts" / "v2" / "poster_spine.html").read_text()
    assert "writing-mode: vertical-rl" in raw
    assert "--mh-fit-spine-px" in raw
    # Brand-locked: no hardcoded decorative hex.
    import re

    hexes = set(re.findall(r"#[0-9A-Fa-f]{3,6}", raw))
    assert hexes == set(), f"unexpected hardcoded hex: {hexes}"


def test_spine_notes_and_catalog_line():
    notes = _ROOT / "layouts" / "v2" / "poster_spine.notes.md"
    assert notes.exists()
    assert "the director should pick" in notes.read_text().lower()
    assert A.director_note("poster_spine")


def test_vertical_fit_swaps_the_axes():
    from mediahub.graphic_renderer.render import _fit_one_line_px

    # A TALL, NARROW rail (the spine geometry): the horizontal fit is crushed by
    # the narrow width; the vertical fit — the run travels DOWN the tall height —
    # sizes large (capped only by the rail width). The axis swap is what makes
    # a rotated spine fill its rail instead of shrinking to a strip.
    kw = dict(font_family="Anton", weight=400, min_px=10, max_px=2000)
    horizontal = _fit_one_line_px("WESTHUIZEN", 200, 1000, **kw)
    vertical = _fit_one_line_px("WESTHUIZEN", 200, 1000, vertical=True, **kw)
    assert horizontal != vertical
    # Horizontal is width-capped (~200/ew); vertical is width-capped as the SIZE
    # but length-fed by the tall height, so it is far larger.
    assert vertical > horizontal
    assert vertical <= 200  # the rotated glyph height can't exceed the rail width


def test_spine_motion_scene_mapping():
    src = _TSX.read_text()
    assert '"poster_spine"' in src
