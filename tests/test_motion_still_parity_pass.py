"""Still↔motion PARITY PASS — photo mode, exact filters, data weight, layered scenes.

Covers the four parity-package sections:

  1. **photo-mode mirror** — a "photo"-mode archetype (STILLS-2/M8) sends the
     ORIGINAL photograph and no cutout plane (the remover is never even run);
     "cutout" keeps R1.9; the matte gate outcome is honoured (see also
     tests/test_r1_9_motion_cutout.py's gate tests).
  2. **exact M10 duotone/halftone mirrors** — motion.py passes the still's own
     computed ink hexes / mask tile, and the TSX rebuilds the still's SVG
     filter recipe verbatim; numeric tableValues parity is cross-checked
     against the still's ``_duotone_defs_svg`` for a fixture brand.
  3. **M11 stat chips + PB bars** — the still's selection tables produce the
     motion props; geometry rides the TSX ``StatChipsBlock``; undirected cards
     attach nothing (cache-stable).
  4. **M12 layered scenes** — poster_name_behind / band_break register sprint
     scenes; band_break's bandTopPct/breakSolidPct/breakFadePct props equal
     the still's placement maths for the same alpha mask.

No Node render here — TSX behaviour is validated at the source-contract level
(the suite's established pattern); real renders ride the integration pass.
"""

from __future__ import annotations

import re
import types
from pathlib import Path
from unittest import mock

import pytest

from mediahub.brand.kit import BrandKit
from mediahub.creative_brief.generator import CreativeBrief, generate
from mediahub.graphic_renderer.render import (
    _band_top_fraction,
    _duotone_defs_svg,
    _sticker_outline_css,
    _wash_defs_svg,
    darken,
    resolved_role_vars_for_brief,
)
from mediahub.visual import motion


BRAND = BrandKit(
    profile_id="parity-pass",
    display_name="Parity Pass SC",
    primary_colour="#0E2A47",
    secondary_colour="#C9A227",
    accent_colour="#FFFFFF",
    short_name="PPS",
)


def _card(i: int = 1) -> dict:
    return {
        "id": f"swim-pp-{i}",
        "swim_id": f"swim-pp-{i}",
        "achievement": {
            "swim_id": f"swim-pp-{i}",
            "swimmer_name": f"Swimmer {i}",
            "event_name": "100m Freestyle",
            "result_time": f"1:0{i}.00",
        },
        "meet_name": "Parity Pass Invitational",
    }


def _full_brief(**overrides) -> dict:
    brief = generate(
        {
            "id": "swim-pp-1",
            "post_angle": "confirmed_official_pb",
            "achievement": _card(1)["achievement"],
        },
        None,
        BRAND,
        profile_id="parity-pass",
    )
    d = brief.to_dict()
    d.update(overrides)
    return d


class _SilhouetteRemover:
    """A remover producing a gate-passing bottom-anchored silhouette."""

    def __init__(self) -> None:
        self.calls = 0

    def is_available(self) -> bool:
        return True

    def remove(self, src_path: str, dst_path: str) -> str:
        self.calls += 1
        from PIL import Image, ImageDraw

        im = Image.new("RGBA", (600, 800), (0, 0, 0, 0))
        draw = ImageDraw.Draw(im)
        draw.rectangle([200, 320, 400, 800], fill=(20, 60, 140, 255))
        draw.ellipse([230, 180, 370, 340], fill=(20, 60, 140, 255))
        im.save(dst_path, "PNG")
        return dst_path


@pytest.fixture
def photo_env(tmp_path, monkeypatch):
    """A sourced on-disk photo + silhouette remover, DATA_DIR isolated."""
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    from PIL import Image

    src = tmp_path / "athlete.jpg"
    Image.new("RGB", (600, 800), (20, 60, 140)).save(src, "JPEG")
    asset = types.SimpleNamespace(path=str(src))
    store = types.SimpleNamespace(get=lambda aid: asset)
    remover = _SilhouetteRemover()
    monkeypatch.setattr("mediahub.media_library.store.get_store", lambda: store)
    monkeypatch.setattr("mediahub.media_ai.providers.get_bg_remover", lambda: remover)
    return types.SimpleNamespace(src=src, remover=remover, tmp=tmp_path)


COMP = motion.REMOTION_DIR / "src" / "compositions"


def _src(rel: str) -> str:
    return (COMP / rel).read_text()


# ===========================================================================
# 1 — photo-mode mirror
# ===========================================================================


def test_photo_mode_archetype_sends_original_and_no_cutout(photo_env):
    """A "photo"-mode archetype (rectangular window / full-bleed stage) mirrors
    the still: the ORIGINAL photograph rides photoSrc, no cutout plane is sent,
    and the background remover is never even invoked."""
    brief = _full_brief(
        layout_template="full_bleed_photo_lower_third",
        sourced_asset_ids=["a1"],
        photo_treatment="cutout",
    )
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    assert props["photoMode"] == "photo"
    assert props["photoSrc"].startswith("data:image/jpeg;base64,")
    assert props["cutoutSrc"] == ""
    assert photo_env.remover.calls == 0


def test_cutout_mode_archetype_keeps_the_r19_cutout(photo_env):
    brief = _full_brief(
        layout_template="spotlight_disc",
        sourced_asset_ids=["a1"],
        photo_treatment="cutout",
    )
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    assert props["cutoutSrc"].startswith("data:image/png;base64,")
    assert "photoMode" not in props  # cutout/legacy attaches nothing (cache-stable)


def test_archetype_table_beats_a_stale_photo_mode_stamp(photo_env):
    """archetypes.photo_mode(layout_template) is the source of truth — a brief
    whose archetype was regenerated after the stamp was written must follow
    the template that actually renders (caught by a real render: a stale
    'cutout' stamp put a spurious cutout plane on a photo-mode card)."""
    brief = _full_brief(
        layout_template="full_bleed_photo_lower_third",  # photo-mode template…
        photo_mode="cutout",  # …with a stale persisted stamp
        sourced_asset_ids=["a1"],
        photo_treatment="cutout",
    )
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    assert props["photoMode"] == "photo"
    assert props["cutoutSrc"] == ""


def test_photo_mode_stamp_is_the_fallback_for_unresolvable_templates(photo_env):
    """When the template isn't a v2 archetype the persisted stamp decides."""
    brief = _full_brief(
        layout_template="individual_hero",
        photo_mode="photo",
        sourced_asset_ids=["a1"],
        photo_treatment="cutout",
    )
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    assert props["photoMode"] == "photo"
    assert props["cutoutSrc"] == ""


def test_photo_mode_never_attached_without_a_photo():
    props = motion._card_to_props(
        _card(1),
        variation_seed=2,
        brief=_full_brief(layout_template="full_bleed_photo_lower_third"),
        brand_kit=BRAND,
    )
    assert "photoMode" not in props
    props = motion._card_to_props(_card(1), variation_seed=2)
    assert "photoMode" not in props


def test_v1_family_keeps_the_legacy_cutout_path(photo_env):
    """A v1 family name is not a v2 archetype — photo mode stays '' and the
    R1.9 cutout compositing is unchanged (byte-identical prop shape)."""
    brief = _full_brief(
        layout_template="individual_hero",
        sourced_asset_ids=["a1"],
        photo_treatment="cutout",
    )
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    assert "photoMode" not in props
    assert props["cutoutSrc"].startswith("data:image/png;base64,")


def test_cutout_layer_suppresses_photo_mode_and_scene_owned_archetypes():
    src = _src("sprint/layers/cutout.tsx")
    assert 'card.photoMode === "photo"' in src
    assert "poster_name_behind" in src and "band_break" in src


# ===========================================================================
# 2 — exact M10 duotone / halftone mirrors (+ photoScale crop mirror)
# ===========================================================================


def _tsx_table(lo: int, hi: int) -> str:
    """The TSX's tableValues string — `(c/255).toFixed(4)` mirrored exactly."""
    return f"{lo / 255:.4f} {hi / 255:.4f}"


def test_duotone_props_carry_the_stills_exact_inks(photo_env):
    brief = _full_brief(
        layout_template="full_bleed_photo_lower_third",
        sourced_asset_ids=["a1"],
        photo_treatment="duotone",
    )
    expected_vars = resolved_role_vars_for_brief(CreativeBrief.from_dict(brief), BRAND)
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    assert props["duotoneShadow"] == darken(expected_vars["--mh-primary"], 0.30)
    assert props["duotoneHighlight"] == expected_vars["--mh-accent"]


def test_tsx_duotone_table_values_match_the_still_svg(photo_env):
    """The still's _duotone_defs_svg and the TSX recipe compute identical
    per-channel tableValues for the fixture brand — the two surfaces cannot
    drift because motion.py feeds the TSX the still's own ink hexes."""
    brief = _full_brief(
        layout_template="full_bleed_photo_lower_third",
        sourced_asset_ids=["a1"],
        photo_treatment="duotone",
    )
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    shadow, highlight = props["duotoneShadow"], props["duotoneHighlight"]
    still_svg = _duotone_defs_svg(shadow, highlight)

    def _rgb(h: str) -> tuple[int, int, int]:
        return tuple(int(h.lstrip("#")[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]

    sr, sg, sb = _rgb(shadow)
    hr, hg, hb = _rgb(highlight)
    for chan, table in (
        ("R", _tsx_table(sr, hr)),
        ("G", _tsx_table(sg, hg)),
        ("B", _tsx_table(sb, hb)),
    ):
        assert f'<feFunc{chan} type="table" tableValues="{table}"/>' in still_svg


def test_tsx_carries_the_still_duotone_recipe_verbatim():
    src = _src("sprint/layers/photo_filters.tsx")
    # The still's luminance feColorMatrix constant, sRGB interpolation, and the
    # (c/255).toFixed(4) table ramp.
    assert src.count("0.2126 0.7152 0.0722 0 0") == 3
    assert 'colorInterpolationFilters="sRGB"' in src
    assert "toFixed(4)" in src
    assert "feComponentTransfer" in src and "feFuncR" in src
    # Exact mirrors take over BEFORE the legacy approximation (never stacked).
    grade_fn = src.split("export function photoGradeFilterFor", 1)[1]
    assert grade_fn.index("photoExactGradeFor") < grade_fn.index("baseStackFor")


def test_halftone_tile_matches_the_stills_decoration_maths(photo_env):
    brief = _full_brief(
        layout_template="full_bleed_photo_lower_third",
        sourced_asset_ids=["a1"],
        photo_treatment="halftone",
        decoration_strength=0.8,
    )
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    assert props["halftoneTile"] == int(round(14 + 18 * 0.8))  # 14–32px dots
    assert "duotoneShadow" not in props


def test_tsx_halftone_mirrors_the_still_mask_geometry():
    src = _src("sprint/layers/photo_filters.tsx")
    # The still's held grade + the style-pack dot geometry (two offset circles
    # at (6,17)/22 of the tile, radii 0.42/0.30) — render._halftone_mask_tile_uri.
    assert "grayscale(1) contrast(1.18) brightness(0.98)" in src
    assert "6) / 22" in src and "17) / 22" in src
    assert "* 0.42" in src and "* 0.30" in src
    assert "maskImage" in src and "maskSize" in src


def test_untreated_cards_attach_no_filter_props(photo_env):
    brief = _full_brief(
        layout_template="full_bleed_photo_lower_third",
        sourced_asset_ids=["a1"],
        photo_treatment="cutout",
    )
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    for key in (
        "duotoneShadow",
        "duotoneHighlight",
        "halftoneTile",
        "stickerInk",
        "stickerRadius",
        "washTint",
        "washMix",
    ):
        assert key not in props


# ===========================================================================
# B5 — die-cut sticker contour (render._sticker_outline_css)
# ===========================================================================


def test_sticker_props_carry_the_stills_ink_and_radius(photo_env):
    """A sticker-treated card on a CUTOUT-mode archetype passes the resolved
    on-ground ink and the exact radius the still computed
    (round(min(w,h)·(0.003 + 0.004·strength))), so the TSX rebuilds the same
    8-direction contour the still painted on img.athlete-cutout."""
    brief = _full_brief(
        layout_template="spotlight_disc",  # cutout-mode → a real silhouette
        sourced_asset_ids=["a1"],
        photo_treatment="sticker",
        decoration_strength=0.8,
    )
    expected_vars = resolved_role_vars_for_brief(CreativeBrief.from_dict(brief), BRAND)
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    assert props["cutoutSrc"].startswith("data:image/png;base64,")  # cutout exists
    assert props["stickerInk"] == expected_vars["--mh-on-primary"]
    # Story cut is 1080×1920 → min(w,h)=1080; radius = round(1080·(0.003+0.004·0.8)).
    assert props["stickerRadius"] == max(3, int(round(1080 * (0.003 + 0.004 * 0.8))))
    # The still's CSS uses the SAME radius maths on its own 1080-min geometry:
    # the (dx, dy) = (r, 0) axis shadow renders "<r>px 0px 0 <ink>".
    still_css = _sticker_outline_css(1080, 1350, 0.8)
    assert f"{props['stickerRadius']}px 0px 0 var(--mh-on-primary)" in still_css


def test_sticker_needs_a_real_cutout(photo_env):
    """A photo-mode archetype has no alpha silhouette — the still's cutout_ok
    gate skips the sticker (a full-bleed rectangle would paint a box halo), so
    no sticker props attach on the motion side either."""
    brief = _full_brief(
        layout_template="full_bleed_photo_lower_third",  # photo-mode → no cutout
        sourced_asset_ids=["a1"],
        photo_treatment="sticker",
    )
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    assert props["cutoutSrc"] == ""
    assert "stickerInk" not in props and "stickerRadius" not in props


def test_tsx_sticker_contour_mirrors_the_still_eight_directions():
    """The TSX stickerContourFilter builds the identical 8-direction zero-blur
    drop-shadow stack (±r on axes, ±d on diagonals, d = round(r·0.7071)) that
    render._sticker_outline_css paints, in the passed on-ground ink."""
    src = _src("sprint/layers/photo_filters.tsx")
    assert "export function stickerContourFilter" in src
    # Eight offsets: the four axis pairs and the four diagonals.
    for pair in (
        "[r, 0]",
        "[-r, 0]",
        "[0, r]",
        "[0, -r]",
        "[d, d]",
        "[d, -d]",
        "[-d, d]",
        "[-d, -d]",
    ):
        assert pair in src
    # Same diagonal-offset maths as the still (r·0.7071, floored at 2).
    assert "r * 0.7071" in src and "Math.max(2" in src
    # Zero-blur drop-shadow in the passed ink; gated on a real cutout.
    assert "drop-shadow(${dx}px ${dy}px 0 ${ink})" in src
    assert "!card.cutoutSrc" in src
    # cutout.tsx applies it, replacing the grounded depth shadow (like exactGrade).
    cut = _src("sprint/layers/cutout.tsx")
    assert "stickerContourFilter(card)" in cut
    assert "exactGrade ||\n            sticker ||" in cut


def test_photo_scale_mirrors_the_stills_crop_intent(photo_env):
    from mediahub.graphic_renderer.render import _crop_intent_vars

    brief = _full_brief(
        layout_template="full_bleed_photo_lower_third",
        sourced_asset_ids=["a1"],
        photo_treatment="cutout",
        crop_intent="tight_portrait",
    )
    expected = _crop_intent_vars("tight_portrait", photo_env.src, None, 1080, 1920)
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    assert props["photoScale"] == float(expected["--mh-photo-scale"])


def test_photo_scale_absent_for_noop_intents(photo_env):
    brief = _full_brief(
        layout_template="full_bleed_photo_lower_third",
        sourced_asset_ids=["a1"],
        photo_treatment="cutout",
        crop_intent="full_bleed",
    )
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    assert "photoScale" not in props


def test_paint_sites_multiply_crop_scale_into_the_camera():
    for rel, marker in (
        ("StoryCard.tsx", "const PhotoLayer"),
        ("sprint/sceneKit.tsx", "export const PhotoFill"),
    ):
        block = _src(rel).split(marker, 1)[1]
        assert "cropScale" in block, rel
        assert "transformOrigin" in block, rel


# ===========================================================================
# 3 — stat chips + PB bars (M11 mirror)
# ===========================================================================

_CHIP_FACTS = dict(
    secondary_stats=["pb_delta", "placing", "split_time"],
    hero_stat_options={
        "pb_delta": "−0.42s on PB",
        "placing": "2nd place",
        "split_time": "split 29.87",
    },
)


def test_stat_chips_mirror_the_still_selection():
    brief = _full_brief(layout_template="editorial_numbers_grid", **_CHIP_FACTS)
    brief["text_layers"]["hero_stat"] = "−0.42s on PB"  # the hero line's own fact
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    # pb_delta is the hero line → skipped; values label-trimmed exactly like
    # render._chip_value ("2nd place" → "2nd", "split 29.87" → "29.87").
    assert props["statChips"] == [
        {"label": "Place", "value": "2nd"},
        {"label": "Split", "value": "29.87"},
    ]
    expected_vars = resolved_role_vars_for_brief(CreativeBrief.from_dict(brief), BRAND)
    assert props["statInk"] == expected_vars["--mh-on-surface"]
    # The chip boxes' hairline is the still's own --mh-outline, passed — the
    # TSX never re-derives it from a colour literal (brand-locked rule).
    assert props["roleOutline"] == expected_vars["--mh-outline"]


def test_stat_chips_only_for_the_data_led_archetypes():
    brief = _full_brief(layout_template="magazine_cover", **_CHIP_FACTS)
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    for key in ("statChips", "statInk", "pbBars", "roleOutline"):
        assert key not in props


def test_pb_bars_mirror_the_still_proportional_maths():
    brief = _full_brief(layout_template="editorial_numbers_grid", **_CHIP_FACTS)
    brief["text_layers"]["prev_pb_time"] = "1:02.50"
    brief["text_layers"]["result_value"] = "1:01.80"
    brief["text_layers"]["hero_stat"] = "−0.42s on PB"
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    bars = props["pbBars"]
    assert bars["prev"] == "1:02.50" and bars["now"] == "1:01.80"
    assert bars["nowPct"] == round(61.80 / 62.50 * 100.0, 1)
    # The delta already IS the hero line → the caption is the axis note alone.
    assert bars["caption"] == "bars proportional to real times"


def test_pb_bars_caption_prepends_the_delta_when_not_the_hero_line():
    brief = _full_brief(layout_template="editorial_numbers_grid", **_CHIP_FACTS)
    brief["text_layers"]["prev_pb_time"] = "1:02.50"
    brief["text_layers"]["result_value"] = "1:01.80"
    brief["text_layers"]["hero_stat"] = "2nd place"
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    assert props["pbBars"]["caption"] == "−0.42s on PB · bars proportional to real times"


def test_pb_bars_never_render_on_unverifiable_times():
    brief = _full_brief(layout_template="editorial_numbers_grid", **_CHIP_FACTS)
    brief["text_layers"]["prev_pb_time"] = "1:01.00"
    brief["text_layers"]["result_value"] = "1:01.80"  # SLOWER — no comparison
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    assert "pbBars" not in props


def test_stat_chips_block_mirrors_the_still_geometry():
    src = _src("sprint/sceneKit.tsx")
    block = src.split("export const StatChipsBlock", 1)[1]
    # Continuity grammar: 1px outline chip, 18/24 padding, Inter 700 17px
    # .22em label in accent, JetBrains Mono 700 30px tnum value, row gap 14.
    assert "1px solid ${outline}" in block
    assert "18 * ts" in block and "24 * ts" in block
    assert "0.22em" in block and "17 * ts" in block
    assert "'JetBrains Mono'" in block and "tabular-nums" in block and "30 * ts" in block
    assert "14 * ts" in block
    # PB bars: 26px tall, 15px labels at .18em, honest full-width PREVIOUS.
    assert "26 * ts" in block and "15 * ts" in block and "0.18em" in block
    assert "100.0" in block
    # Skips cleanly — undirected cards render nothing.
    assert re.search(r"if \(chips\.length === 0 && !bars\)\s*\{\s*return null", block)


def test_chip_bearing_scenes_render_the_block():
    story = _src("StoryCard.tsx")
    assert story.count("<StatChipsBlock ctx={ctx} />") >= 2  # grid + triptych split
    assert "<StatChipsBlock ctx={ctx} />" in _src("sprint/scenes/timeline_progression.tsx")


# ===========================================================================
# 4 — the layered-archetype scenes (M12 twins)
# ===========================================================================


def test_band_break_props_equal_the_still_band_maths(photo_env, tmp_path):
    brief = _full_brief(
        layout_template="band_break",
        sourced_asset_ids=["a1"],
        photo_treatment="cutout",
    )
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    assert props["cutoutSrc"].startswith("data:image/png;base64,")
    # Recompute from the SAME cut the props were built from.
    _, cut_path = motion._cutout_for_brief(brief)
    assert cut_path is not None
    band_top = _band_top_fraction(Path(cut_path), 1080, 1920)
    assert band_top is not None
    assert props["bandTopPct"] == round(band_top * 100, 1)
    solid = max(0.0, min(0.97, (band_top + 0.015 - 0.14) / 0.86))
    fade = min(0.99, solid + 0.055)
    assert props["breakSolidPct"] == round(solid * 100, 1)
    assert props["breakFadePct"] == round(fade * 100, 1)


def test_band_props_absent_without_a_gated_cutout(photo_env, monkeypatch):
    brief = _full_brief(
        layout_template="band_break",
        sourced_asset_ids=["a1"],
        photo_treatment="cutout",
    )
    with mock.patch.object(motion, "_cutout_for_brief", return_value=("", None)):
        props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    for key in ("bandTopPct", "breakSolidPct", "breakFadePct", "decorationStrength"):
        assert key not in props


def test_poster_name_behind_attaches_the_surface_ink(photo_env):
    brief = _full_brief(
        layout_template="poster_name_behind",
        sourced_asset_ids=["a1"],
        photo_treatment="cutout",
        decoration_strength=0.9,
    )
    props = motion._card_to_props(_card(1), variation_seed=2, brief=brief, brand_kit=BRAND)
    expected_vars = resolved_role_vars_for_brief(CreativeBrief.from_dict(brief), BRAND)
    assert props["roleOnSurface"] == expected_vars["--mh-on-surface"]
    assert props["decorationStrength"] == 0.9


@pytest.mark.parametrize("name", ["poster_name_behind", "band_break"])
def test_layered_scene_registers_and_is_frame_pure(name):
    src = _src(f"sprint/scenes/{name}.tsx")
    assert re.search(r"export default \{\s*archetype:\s*\"%s\",\s*Scene\s*\}" % name, src)
    assert 'from "../registry"' in src
    assert "Math.random(" not in src and "Date.now(" not in src and "new Date(" not in src
    # Motion-craft guardrails: first animation off frame 0, ≥3 distinct easings.
    assert "3 + (durationInFrames - 3)" in src
    easings = set(re.findall(r"Easing\.(?:in|out|inOut)\(Easing\.\w+\)", src))
    assert len(easings) >= 3, f"{name} needs ≥3 distinct easings, has {easings}"
    assert "spring({" in src  # the result chip's snap_in_then_settle
    # Matte-gate grace: the original-photo fallback path exists.
    assert "photoFlat" in src


def test_band_break_scene_uses_the_python_computed_stops():
    src = _src("sprint/scenes/band_break.tsx")
    assert "card.bandTopPct" in src
    assert "card.breakSolidPct" in src and "card.breakFadePct" in src
    # ONE cutout painted twice: both planes share the contain-fit stage plane.
    assert src.count("stagePlane") >= 3  # definition + body + head
    assert "bottom center" in src and '"contain"' in src


def test_poster_scene_carries_the_depth_treatment_maths():
    src = _src("sprint/scenes/poster_name_behind.tsx")
    # render._cutout_depth_filter: 10+14s / 24+30s lift, 8+22s accent glow.
    assert "10 + 14 * s" in src and "24 + 30 * s" in src and "8 + 22 * s" in src
    assert "0.18 + 0.2 * s" in src
    # The cutout's ambient push stays ≤1.03 and there is no saliency pan.
    assert "1.03" in src
