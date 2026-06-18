"""R1.23 — Dynamic logo sizing + scene-aware animated logo reveal.

The capability ships as an additive sprint overlay
(``src/.../sprint/layers/logo_anim.tsx``) that the layer registry
auto-discovers and ``StoryCard`` renders over every scene. Following the rest
of the motion suite, the TSX is verified as a *source contract* — no Node
needed (real renders stay behind the existing integration gates). The contract:

  * the file exists and registers as a drop-in overlay (default-export
    ``{ Layer, order }`` with ``Layer`` typed as the shared ``SceneComponent``);
  * it sizes the logo with a real ``small / medium / large / auto`` system, and
    ``auto`` reproduces the renderer's own per-scene chip sizes so the animated
    mark coincides with the static chip (one logo on screen, never two);
  * each scene family gets its own entrance, all resolving to the resting
    transform, and the reveal is short enough to finish before the static chip
    fades in (with the ``static`` motion intent skipping the entrance entirely);
  * it only ever draws the real ``brand.logoDataUri`` (brand-locked, fact-exact)
    and renders nothing for a logo-less brand;
  * it stays a pure function of the frame and never edits the shared
    composition (the merge-conflict-free sprint rule).

The shared parity corpus in ``test_motion_v2_parity`` scans every sprint module,
so the existing motion-intent / archetype drift guards now cover this file too.
"""
from __future__ import annotations

import re

from mediahub.visual import motion

_COMPOSITIONS = motion.REMOTION_DIR / "src" / "compositions"
LAYERS_DIR = _COMPOSITIONS / "sprint" / "layers"
LOGO_ANIM = LAYERS_DIR / "logo_anim.tsx"
STORYCARD = _COMPOSITIONS / "StoryCard.tsx"
MEETREEL = _COMPOSITIONS / "MeetReel.tsx"


def _src() -> str:
    return LOGO_ANIM.read_text()


# ---------------------------------------------------------------------------
# Registration / drop-in contract
# ---------------------------------------------------------------------------


def test_layer_file_exists_in_sprint_layers():
    assert LOGO_ANIM.is_file(), "R1.23 builds sprint/layers/logo_anim.tsx"


def test_registers_as_additive_overlay():
    """Drop-in contract (sprint/registry.ts): default-export ``{ Layer, order }``
    with ``Layer`` typed as the shared ``SceneComponent`` and its types pulled
    from the registry (so it lives in one folder, no scene edits)."""
    src = _src()
    assert 'from "../registry"' in src, "must import its types from the registry"
    assert "SceneComponent" in src
    assert re.search(r"const\s+Layer\s*:\s*SceneComponent", src), "Layer: SceneComponent"
    assert re.search(
        r"export\s+default\s*\{\s*Layer\s*,\s*order\s*:\s*\d+", src
    ), "default-export { Layer, order } so the registry discovers it"


def test_layer_lives_under_the_scanned_sprint_tree():
    """The parity corpus scans ``sprint/**/*.{ts,tsx}``; this file sits there,
    so the intent/archetype drift guards automatically extend to it."""
    assert LOGO_ANIM.suffix == ".tsx"
    assert LOGO_ANIM.parent.name == "layers"
    assert LOGO_ANIM.parent.parent.name == "sprint"
    # Raises if the file is not under the scanned sprint subtree.
    LOGO_ANIM.relative_to(_COMPOSITIONS / "sprint")


# ---------------------------------------------------------------------------
# Dynamic sizing — small / medium / large / auto
# ---------------------------------------------------------------------------


def test_dynamic_sizing_vocabulary_is_explicit():
    """The roadmap's sizing vocabulary is real and named in the source, with a
    tier table and an ``auto`` selector."""
    src = _src()
    for tier in ('"small"', '"medium"', '"large"', '"auto"'):
        assert tier in src, tier
    assert "LogoSizeTier" in src
    assert "autoTierFor" in src
    assert "logoBasePx" in src


def test_auto_sizes_match_the_static_chip_sizes():
    """``auto`` must reproduce the renderer's own per-scene logo sizes so the
    animated mark lands exactly on top of the static chip — one logo, never
    two. The set of sizes the overlay can draw must equal the set ``LogoChip``
    uses in StoryCard (110 / 120 / 140)."""
    overlay_sizes = {
        int(n) for n in re.findall(r"(?:small|medium|large):\s*(\d+)", _src())
    }
    assert overlay_sizes == {110, 120, 140}, overlay_sizes

    story = STORYCARD.read_text()
    default_size = int(re.search(r"size\s*=\s*(\d+)\s*\}\)\s*=>", story).group(1))
    explicit = {int(n) for n in re.findall(r"<LogoChip[^>]*size=\{(\d+)\}", story)}
    chip_sizes = explicit | {default_size}
    assert chip_sizes == {110, 120, 140}, chip_sizes
    assert overlay_sizes == chip_sizes, "overlay tiers must match the chip sizes"


def test_coincides_with_the_static_chip_slot():
    """Same slot as the StoryCard ``LogoChip`` (top 100·ts, right min(80, 6%))
    so the animated mark overlaps the static one exactly at rest."""
    layer = _src()
    assert "Math.round(100 * ts)" in layer
    assert "Math.min(80, width * 0.06)" in layer
    story = STORYCARD.read_text()
    assert "Math.round(100 * ts)" in story
    assert "Math.min(80, width * 0.06)" in story


# ---------------------------------------------------------------------------
# Scene-aware entrance + ghost-free timing
# ---------------------------------------------------------------------------


def test_scene_aware_entrance_per_family():
    """A distinct entrance per scene family (the roadmap's 'scene-aware
    entrance'), built from a progress that decays to the resting transform."""
    src = _src()
    assert "entranceFor" in src
    for mode in (
        "hero",
        "poster",
        "lowerThird",
        "spotlight",
        "grid",
        "ticker",
        "split",
        "magazine",
    ):
        assert mode in src, mode
    # Offsets are scaled by ``inv = 1 - e`` (slides) or grow with ``e`` (scale),
    # so every entrance resolves to identity (dx=dy=0, scale=1) as e→1.
    assert "1 - e" in src


def test_reveal_timing_is_ghost_free_and_not_a_jump_cut():
    """The reveal must (a) open a few frames in, never at frame 0 — a t=0
    entrance reads as a jump cut (motion-craft, 0.1–0.3s) — and (b) complete
    before the earliest static-chip fade (the snap_in_then_settle intent's
    chipOpacity starts at fps*0.6 in StoryCard), so the overlay and the chip
    never read as two logos. The ``static`` motion intent skips the entrance so
    it coincides with the always-on chip from frame 0."""
    src = _src()
    start = re.search(r"REVEAL_START_SEC\s*=\s*([0-9.]+)", src)
    end = re.search(r"REVEAL_END_SEC\s*=\s*([0-9.]+)", src)
    assert start and end, "reveal start/end constants must exist"
    assert 0.1 <= float(start.group(1)) <= 0.3, "entrance must not start at frame 0"
    assert float(end.group(1)) <= 0.55, "reveal must finish before the chip fades in"
    assert float(start.group(1)) < float(end.group(1))
    assert '"static"' in src
    assert "isStatic" in src


# ---------------------------------------------------------------------------
# Brand-locked, deterministic, non-invasive
# ---------------------------------------------------------------------------


def test_only_draws_the_real_brand_logo():
    """Brand-locked + fact-exact: the only thing ever drawn is the operator's
    own ``brand.logoDataUri``; a logo-less brand renders nothing (byte-identical
    to before the overlay landed)."""
    src = _src()
    assert "brand.logoDataUri" in src
    assert re.search(r"if\s*\(\s*!brand\.logoDataUri\s*\)", src), "guard logo-less brands"
    assert "return null" in src


def test_pure_function_of_the_frame():
    """Deterministic — no wall-clock or randomness — so renders stay
    byte-identical and the motion cache key remains valid."""
    src = _src()
    assert "Math.random" not in src
    assert "Date.now" not in src and "new Date" not in src
    assert "frame" in src and "fps" in src


def test_does_not_edit_the_shared_composition():
    """Sprint contract: a capability is its own file, with NO edit to
    StoryCard.tsx / MeetReel.tsx (so parallel sessions never conflict). The
    overlay reaches the screen only through the existing registry seam."""
    story = STORYCARD.read_text()
    reel = MEETREEL.read_text()
    assert "logo_anim" not in story
    assert "logo_anim" not in reel
    assert "EXTRA_LAYERS" in story, "the registry seam StoryCard renders must stay"


def test_overlay_reaches_both_story_and_reel():
    """R1.23 is a reel-sprint item: the reel renders each beat THROUGH
    ``StoryCard``, so the overlay rides onto every reel card as well as the
    standalone story card."""
    story = STORYCARD.read_text()
    reel = MEETREEL.read_text()
    assert "EXTRA_LAYERS.map" in story
    assert "<StoryCard" in reel


def test_no_cdn_font_creep():
    """Belt-and-suspenders with test_self_hosted_fonts: the overlay must not
    introduce a CDN font or a webfont loader on the reel surface."""
    src = _src()
    for needle in ("googleapis", "gstatic", "@remotion/google-fonts", "@fontsource"):
        assert needle not in src, needle
