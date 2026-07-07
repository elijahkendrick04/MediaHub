"""G1.6 — the texture-layering engine (``graphic_renderer.style_packs``).

The feature: a *layered* surface texture stacks **two** of the closed single-tile
textures and fuses them with a CSS ``background-blend-mode`` (grain+dots,
halftone+weave, …). This suite proves:

* the layered tokens are appended to the ``TEXTURES`` vocabulary, are pack-id
  safe (no ``-``), and resolve to a ``(base_a, base_b, blend)`` recipe;
* the **compositor** paints exactly two tiles fused by the blend mode, at the
  same low-opacity ``mix-blend-mode:overlay`` the single-tile precedent uses —
  so a layered surface is as legibility-safe as one tile, brand-colour-only,
  and deterministic;
* the refactor left every *single*-tile overlay byte-identical;
* the catalog surfaces layered-texture packs (variety reaches output); and
* the motion renderer (``StoryCard.tsx``) mirrors the engine verbatim, so a
  card's video carries the same stacked surface as its still (still↔motion
  parity — the rule this feature must not break).

Pure shaping + source-contract checks: no browser, no Node.
"""

from __future__ import annotations

import re

import pytest

from mediahub.graphic_renderer import archetypes as A
from mediahub.graphic_renderer import style_packs as sp
from mediahub.visual import motion


# The eight layered tokens this engine adds. Pinned here so a silent
# rename/removal in the vocabulary is caught, not absorbed.
LAYERED = (
    "grain_dots",
    "halftone_weave",
    "hatch_grid",
    "crosshatch_grain",
    "dots_scanline",
    "carbon_hatch",
    "chevron_grain",
    "grid_dots",
)

# The legibility-safe blend family: lightening/neutral only, so two faint
# white-on-transparent tiles never fuse into a dark opaque mass over copy.
ALLOWED_BLENDS = {"screen", "lighten", "overlay", "soft-light"}


def _single_textures() -> list[str]:
    return [t for t in sp.TEXTURES if t != "none" and sp.texture_stack(t) is None]


# --------------------------------------------------------------------------- #
# Vocabulary: appended, id-safe, recipe-backed
# --------------------------------------------------------------------------- #


def test_layered_textures_appended_to_vocabulary():
    for t in LAYERED:
        assert t in sp.TEXTURES, f"{t} missing from TEXTURES"
        assert sp.texture_stack(t) is not None, f"{t} has no stack recipe"
    # The single-tile and 'none' tokens are NOT layered.
    assert sp.texture_stack("none") is None
    for t in _single_textures():
        assert sp.texture_stack(t) is None, f"{t} wrongly treated as layered"
    # Unknown / junk → None, never a half-recipe.
    assert sp.texture_stack("totally-bogus") is None
    assert sp.texture_stack("") is None


def test_layered_tokens_are_pack_id_safe():
    # The pack id is "ground-texture-accentGeo-density", split on '-' on both the
    # still and motion sides — a '-' inside a texture token would break the split.
    for t in LAYERED:
        assert "-" not in t, f"{t} contains '-' → breaks the 4-part pack id split"
    pack = sp.normalise_pack(
        ground="vignette", texture="grain_dots", accent_geo="ring", density="bold"
    )
    assert pack.id == "vignette-grain_dots-ring-bold"
    assert len(pack.id.split("-")) == 4, "layered pack id must still split into 4 parts"


def test_stack_recipe_references_valid_distinct_bases():
    singles = set(_single_textures())
    for t in LAYERED:
        base_a, base_b, blend = sp.texture_stack(t)
        assert base_a in singles, f"{t}: base_a {base_a!r} is not a single texture"
        assert base_b in singles, f"{t}: base_b {base_b!r} is not a single texture"
        assert base_a != base_b, f"{t}: a layered texture must stack two *different* tiles"
        assert blend in ALLOWED_BLENDS, f"{t}: blend {blend!r} outside the legibility-safe family"


def test_blend_mode_diversity():
    # "Texture-layering engine ... with blend modes" — plural. Prove the engine
    # actually exercises a range, not one hard-coded mode.
    blends = {sp.texture_stack(t)[2] for t in LAYERED}
    assert len(blends) >= 3, f"only {blends} blend modes used"


def test_every_texture_has_weight_and_label():
    # name()/why()/weight read these dicts — a missing key is a KeyError at render.
    for t in sp.TEXTURES:
        assert t in sp._TEXTURE_W, f"{t} missing a weight"
        assert t in sp._TEXTURE_LABEL, f"{t} missing a label"


def test_layered_textures_carry_labels_and_weights():
    for t in LAYERED:
        p = sp.normalise_pack(texture=t)
        assert p.weight == 2, f"{t}: layered texture should weigh 2, got {p.weight}"
        assert p.name(), f"{t}: empty name()"
        assert p.why(), f"{t}: empty why()"


# --------------------------------------------------------------------------- #
# The compositor: two tiles, fused by a blend mode, legibility-safe
# --------------------------------------------------------------------------- #


def test_layered_overlay_composites_two_tiles_with_blend():
    for t in LAYERED:
        base_a, base_b, blend = sp.texture_stack(t)
        html = sp.pack_overlay_html(sp.normalise_pack(texture=t), width=1080, height=1350)
        assert html, f"{t}: empty overlay"
        # exactly two tiles referenced and fused with the recipe's blend mode
        assert html.count("url(&quot;") == 2, f"{t}: expected two tiles"
        assert f"background-blend-mode:{blend}" in html, f"{t}: blend {blend} not applied"
        # both base tile sizes appear, comma-joined (two background layers)
        sa, sb = sp._TEX_SIZE[base_a], sp._TEX_SIZE[base_b]
        assert f"background-size:{sa}px {sa}px,{sb}px {sb}px" in html, t
        assert "background-repeat:repeat,repeat" in html, t
        # the composite rides onto the card exactly like the single-tile precedent
        assert "mix-blend-mode:overlay" in html, t
        assert "position:absolute" in html and "pointer-events:none" in html, t


def test_layered_overlay_is_legibility_safe_and_brand_only():
    for t in LAYERED:
        for w, h in ((1080, 1350), (1080, 1920)):
            html = sp.pack_overlay_html(sp.normalise_pack(texture=t), width=w, height=h)
            # low, capped opacity (faint surface, never sits opaque over copy)
            ops = [float(x) for x in re.findall(r"opacity:([0-9.]+)", html)]
            assert ops and all(0 < o <= 0.2 for o in ops), f"{t}: opacity out of safe range {ops}"
            # brand colour only — a raw #hex in an overlay would be a leak
            assert not re.search(r"#[0-9a-fA-F]{3,6}\b", html), f"{t}: raw hex in overlay"


def test_layered_overlay_bold_is_denser_but_still_capped():
    for t in LAYERED:
        std = sp.pack_overlay_html(
            sp.normalise_pack(texture=t, density="standard"), width=1080, height=1350
        )
        bold = sp.pack_overlay_html(
            sp.normalise_pack(texture=t, density="bold"), width=1080, height=1350
        )
        o_std = float(re.search(r"opacity:([0-9.]+)", std).group(1))
        o_bold = float(re.search(r"opacity:([0-9.]+)", bold).group(1))
        assert o_bold > o_std, f"{t}: bold should be denser"
        assert o_bold <= 0.2, f"{t}: bold opacity still capped"


def test_layered_overlay_is_deterministic():
    for t in LAYERED:
        p = sp.normalise_pack(texture=t)
        a = sp.pack_overlay_html(p, width=1080, height=1350)
        b = sp.pack_overlay_html(p, width=1080, height=1350)
        assert a == b, f"{t}: same pack rendered two different overlays"


def test_layered_overlay_distinct_from_each_base():
    # A layered texture must be genuinely composite — not silently one tile.
    for t in LAYERED:
        base_a, base_b, _ = sp.texture_stack(t)
        layered = sp.pack_overlay_html(sp.normalise_pack(texture=t), width=1080, height=1350)
        only_a = sp.pack_overlay_html(sp.normalise_pack(texture=base_a), width=1080, height=1350)
        only_b = sp.pack_overlay_html(sp.normalise_pack(texture=base_b), width=1080, height=1350)
        assert layered != only_a and layered != only_b, f"{t}: not distinct from its bases"


def test_layered_texture_injected_exactly_once():
    # No doubled texture layer in a full pack overlay (ground + texture + accent).
    p = sp.normalise_pack(ground="vignette", texture="halftone_weave", accent_geo="ring")
    html = sp.pack_overlay_html(p, width=1080, height=1350)
    assert html.count("background-blend-mode:") == 1, "layered texture injected more than once"


# --------------------------------------------------------------------------- #
# Regression: the refactor left every single-tile overlay byte-identical
# --------------------------------------------------------------------------- #


def _old_single_texture_div(texture: str, bold: bool) -> str:
    """The pre-G1.6 inline single-tile overlay, reproduced verbatim."""
    tile = sp._TEX_TILES[texture]
    size = sp._TEX_SIZE[texture]
    opacity = (0.16 if bold else 0.10) if texture != "grain" else (0.18 if bold else 0.12)
    return (
        '<div style="position:absolute;inset:0;z-index:6;pointer-events:none;'
        f"background-image:url(&quot;{tile}&quot;);background-size:{size}px {size}px;"
        f'background-repeat:repeat;opacity:{opacity};mix-blend-mode:overlay;"></div>'
    )


def test_single_texture_overlay_unchanged_by_refactor():
    # A flat/none pack isolates the texture layer, so the whole overlay is just
    # the texture div — compare byte-for-byte against the old formula.
    for t in _single_textures():
        for density, bold in (("standard", False), ("bold", True)):
            got = sp.pack_overlay_html(
                sp.normalise_pack(texture=t, density=density), width=1080, height=1350
            )
            assert got == _old_single_texture_div(t, bold), f"{t}/{density}: single overlay drifted"
            assert "background-blend-mode" not in got, f"{t}: single must not carry a blend"


# --------------------------------------------------------------------------- #
# Catalog: layered-texture packs exist, round-trip, and reach selection
# --------------------------------------------------------------------------- #


def test_catalog_includes_layered_texture_packs_and_roundtrips():
    layered_packs = [p for p in sp.list_style_packs() if sp.texture_stack(p.texture)]
    assert len(layered_packs) >= 50, f"only {len(layered_packs)} layered-texture packs"
    for p in (layered_packs[0], layered_packs[len(layered_packs) // 2], layered_packs[-1]):
        assert sp.style_pack_from_id(p.id) == p, f"{p.id}: did not round-trip"
    # The widened vocabulary keeps the catalog well past its floors.
    assert sp.style_pack_count() > 1000
    assert len(A.list_archetypes()) * sp.style_pack_count() > 10000


def test_layered_textures_reach_deterministic_selection():
    # The seeded per-card picker must actually surface layered surfaces, or the
    # engine would be dead weight. Sweep a pack's worth of cards.
    picked = {sp.pick_style_pack_for_card(f"swim-{i}").texture for i in range(400)}
    assert picked & set(LAYERED), "no card ever drew a layered texture"


# --------------------------------------------------------------------------- #
# Still↔motion parity: StoryCard.tsx mirrors the engine verbatim
# --------------------------------------------------------------------------- #


def _story_src() -> str:
    return (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text()


def test_layered_textures_mirrored_in_storycard():
    src = _story_src()
    assert "PACK_TEXTURE_STACKS" in src, "motion side has no layered-texture recipe"
    assert "backgroundBlendMode" in src, "motion side never applies a blend mode"
    for t in LAYERED:
        # accepted by parseStylePack (in the PACK_TEXTURES set) AND executed
        assert f'"{t}"' in src, f"{t} not mirrored in StoryCard.tsx"


def test_storycard_stack_recipes_match_python():
    """Drift guard: the motion compositor's recipes must equal the still's, or a
    card's video would stack different tiles / a different blend than its still."""
    src = _story_src()
    block = src.split("PACK_TEXTURE_STACKS", 1)[1].split("};", 1)[0]
    pairs = re.findall(
        r'"(\w+)":\s*\["([\w-]+)",\s*"([\w-]+)",\s*"([\w-]+)"\]',
        block,
    )
    tsx = {tok: (a, b, blend) for tok, a, b, blend in pairs}
    assert tsx == dict(sp._TEXTURE_STACKS), "TSX stack recipes drifted from style_packs"


def test_storycard_accepts_layered_texture_ids():
    # Every layered token must be in the motion PACK_TEXTURES set, or
    # parseStylePack rejects the pack id and the video loses the still's surface.
    src = _story_src()
    tex_set = src.split("const PACK_TEXTURES = new Set([", 1)[1].split("]);", 1)[0]
    for t in LAYERED:
        assert f'"{t}"' in tex_set, f"{t} not accepted by motion parseStylePack"


@pytest.mark.parametrize("token", LAYERED)
def test_storycard_base_tiles_and_sizes_exist_for_each_stack(token):
    # The motion compositor reuses base tiles by name — every base a layered
    # token references must have a tile fn + a size on the motion side too.
    src = _story_src()
    base_a, base_b, _ = sp.texture_stack(token)
    for base in (base_a, base_b):
        assert f'case "{base}":' in src, f"{base}: no packTextureImage branch in StoryCard.tsx"
        assert re.search(rf"\b{base}:\s*\d+", src), f"{base}: no PACK_TEX_SIZE in StoryCard.tsx"
