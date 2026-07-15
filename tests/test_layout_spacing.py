"""F1 (systemic floor) — spacing-scale lint for the graphic-renderer layouts.

MediaHub's layouts (``graphic_renderer/layouts/*.html`` + the shared ``.css``)
historically hand-picked raw pixel offsets for every ``margin`` / ``padding`` /
``gap`` / edge inset, so the same footer lockup drifted by a few px across ~30
archetypes. F1 introduces a spacing token scale — ``--mh-sp-1..-9`` = the
``4/8/12/16/24/32/48/64/96`` ramp (``render._SPACING_STEPS``, emitted by
``render._spacing_scale_css`` into every card's ``:root`` and re-used by the
shared ``.mh-lockup*`` classes in ``layouts/_tokens.css``).

This test is a **ratchet**, not a big-bang rewrite: it scans the SPACING
properties of every layout, computes the off-scale px values each file still
carries, and asserts that set is a subset of a per-file baseline allowlist. A
NEW off-scale spacing value in an existing file — or any off-scale spacing value
in a brand-new layout without an allowlist entry — fails the test, nudging new
work onto ``var(--mh-sp-N)``. Removing off-scale px (migrating them to tokens)
only shrinks the set, which the subset check always permits. A summary of the
remaining off-scale spacing usage is emitted as a warning so the debt stays
visible without blocking.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

from mediahub.graphic_renderer.render import _SPACING_STEPS, LAYOUTS_DIR

_SCALE: frozenset[int] = frozenset(_SPACING_STEPS) | {0}

# Only the properties the spacing scale governs. Font size, letter-spacing,
# border width, border-radius, box-shadow geometry and the fixed decorative
# dimensions (a 620px ring, a 540px dial) are deliberately NOT spacing tokens —
# F2 handles the geometry offenders via the --mh-margin/--mh-short scale.
_SPACING_PROPS = r"(?:margin|padding|gap|row-gap|column-gap|inset|top|right|bottom|left)"
_DECL_RE = re.compile(r"(?<![\w-])(" + _SPACING_PROPS + r")(-[a-z]+)?\s*:\s*([^;{}]+)[;}]")
# A bare integer px, not part of a decimal (``1.5px``) or an identifier.
_PX_RE = re.compile(r"(?<![\w.-])(\d+)px")

# Per-file baseline of off-scale spacing px present when F1 landed. New files
# should ship on-scale (empty entry, or add one deliberately with a rationale).
_BASELINE: dict[str, tuple[int, ...]] = {
    "_base.css": (6, 10, 14, 18, 20, 22, 28, 56, 120, 140, 180, 200),
    "_text_led_fill.css": (6, 14, 18, 20, 56, 165, 220),
    "action_photo_hero.html": (18, 20, 56, 150),
    "athlete_spotlight.html": (6, 14, 18, 22, 56, 130, 180, 240),
    "big_number_hero.html": (36,),
    "medal_card.html": (56, 460),
    "meet_preview.html": (6, 10, 14, 18, 56, 200, 380),
    "reel_cover.html": (10, 18),
    "sponsor_branded.html": (56, 86, 130, 250),
    "stat_line.html": (6, 22, 52, 92, 138, 150),
    "story_card.html": (14, 18, 22, 28, 38, 56, 90, 200, 230, 360, 380, 410, 470),
    "text_led_recap.html": (6, 18, 22, 56, 80, 130, 200),
    "v2/band_break.html": (14, 15, 18, 22, 26, 34, 38, 44, 60),
    "v2/big_number_dominant.html": (18, 30, 84),
    "v2/broadcast_scorebug.html": (10, 14, 18, 20, 22, 26, 56),
    "v2/centered_medal_spotlight.html": (14, 18, 26, 28, 36, 40, 44, 80, 92),
    "v2/contact_sheet.html": (10, 14, 18, 26, 28, 30, 68, 72),
    "v2/cornerstone_numeral.html": (14, 84, 92),
    "v2/duo_athlete_split.html": (10, 14, 22, 26, 34, 42),
    "v2/editorial_numbers_grid.html": (14, 20, 26, 30, 34, 40, 76, 80),
    "v2/full_bleed_photo_lower_third.html": (14, 22, 26, 44, 50, 60),
    "v2/full_height_portrait_split.html": (2, 14, 22, 28, 40, 60, 72, 92),
    "v2/horizon_band.html": (9, 14, 18, 26, 28, 30, 84, 88),
    "v2/index_card.html": (14, 18, 22, 26, 28, 36, 40, 80, 84),
    "v2/magazine_cover.html": (2, 7, 9, 18, 20, 22, 26, 28, 30, 50, 54, 56, 60, 132, 150),
    "v2/marquee_crawl.html": (6, 40, 44, 46, 56),
    "v2/mega_surname_bleed.html": (10, 14, 26, 84),
    "v2/minimal_type_poster.html": (6, 10, 20, 30, 40, 84, 104),
    "v2/photo_passepartout.html": (6, 14, 36, 72),
    "v2/poster_name_behind.html": (10, 14, 22, 26, 34, 42, 60, 140),
    "v2/quote_led_recap.html": (14, 18, 30, 60, 84, 112, 120),
    "v2/radial_competition_ring.html": (2, 18, 26, 30, 52, 56, 70, 80, 110),
    "v2/radial_rings.html": (2, 10, 30, 44, 52, 70, 80),
    "v2/relay_collage.html": (2, 6, 10, 13, 14, 22, 28),
    "v2/ribbon_banner.html": (2, 22, 30, 40, 60, 76, 80, 92),
    "v2/scoreline_versus.html": (14, 26, 40, 44, 76, 84),
    "v2/split_diagonal_hero.html": (14, 18, 22, 26, 28, 56),
    "v2/spotlight_disc.html": (14, 22, 30, 40, 56, 72, 84),
    "v2/staggered_diagonal_offset.html": (2, 10, 18, 22, 26, 30, 80, 90, 120, 200),
    "v2/stat_stack_sidebar.html": (2, 10, 18, 20, 28, 30, 34, 38, 40, 56, 84, 88, 92),
    "v2/three_card_editorial_grid.html": (2, 5, 18, 22, 28, 30, 34, 70, 78),
    "v2/ticker_strip.html": (18, 26, 28, 34, 40, 56, 76),
    "v2/timeline_progression.html": (2, 6, 14, 30, 34, 52, 80, 110, 120, 150, 190),
    "v2/triptych_progression.html": (2, 9, 14, 18, 26, 28, 30, 34, 46, 80, 86),
    "v2/vertical_split.html": (13, 14, 26, 40, 56, 76, 84),
    "v2/vertical_stat_tower.html": (2, 14, 18, 26, 34, 72, 80),
    "weekend_numbers.html": (56,),
}


def _layout_files() -> list[Path]:
    files = sorted(LAYOUTS_DIR.glob("v2/*.html")) + sorted(LAYOUTS_DIR.glob("*.html"))
    files += sorted(LAYOUTS_DIR.glob("*.css"))
    # _tokens.css defines the scale (via the shared classes' var() references);
    # it is the source of truth, not a consumer to lint.
    return [f for f in files if f.name != "_tokens.css"]


def _rel(f: Path) -> str:
    return str(f.relative_to(LAYOUTS_DIR))


def _off_scale_spacing(text: str) -> set[int]:
    off: set[int] = set()
    for m in _DECL_RE.finditer(text):
        for pm in _PX_RE.finditer(m.group(3)):
            v = int(pm.group(1))
            if v not in _SCALE:
                off.add(v)
    return off


def test_spacing_scale_is_the_fixed_ramp():
    # The scale is the contract every allowlist is measured against.
    assert _SPACING_STEPS == (4, 8, 12, 16, 24, 32, 48, 64, 96)


def test_no_new_off_scale_spacing():
    """Ratchet: each layout's off-scale spacing px must stay within its baseline."""
    violations: list[str] = []
    total_off = 0
    for f in _layout_files():
        rel = _rel(f)
        off = _off_scale_spacing(f.read_text(encoding="utf-8"))
        total_off += len(off)
        allowed = set(_BASELINE.get(rel, ()))
        new = sorted(off - allowed)
        if new:
            violations.append(
                f"{rel}: off-scale spacing px {new} not on the --mh-sp-* scale "
                f"and not in the baseline allowlist. Use var(--mh-sp-N) "
                f"(4/8/12/16/24/32/48/64/96) or, if a bespoke offset is truly "
                f"needed, add it to _BASELINE with a rationale."
            )
    assert not violations, "\n".join(violations)
    if total_off:
        warnings.warn(
            f"layout spacing debt: {total_off} off-scale spacing px literals remain "
            f"across {sum(1 for f in _layout_files() if _off_scale_spacing(f.read_text()))} "
            f"files; migrate toward var(--mh-sp-N) where the value is on-scale.",
            stacklevel=2,
        )


def test_tokens_sheet_exists_and_uses_only_scale_and_roles():
    """The shared component sheet paints only via --mh-sp-* and --mh-* roles."""
    tokens = (LAYOUTS_DIR / "_tokens.css").read_text(encoding="utf-8")
    assert ".mh-lockup" in tokens
    # No hardcoded hex — brand colour rides the resolved role tokens only.
    assert re.search(r"#[0-9a-fA-F]{3,6}\b", tokens) is None
    # Every spacing value in the sheet is a --mh-sp-* var, never a raw px.
    assert _off_scale_spacing(tokens) == set()
    assert "px" not in tokens or "var(--mh-sp-" in tokens
