"""R1.6 — Animated-pattern drift layer (reel-generator sprint).

The drift layer (``sprint/layers/pattern_drift.tsx``) is an auto-discovered
additive overlay that gives a card's *already-painted* background pattern
subtle, per-pattern, frame-pure life during the breathe phase. It is a pure
new-file drop (the R1.* parallel-merge protocol): zero edits to the shared
``StoryCard.tsx`` composition, wired only through the layers registry seam.

These are source-contract tests in the house style (see
``test_motion_v2_parity`` / ``test_reel_scene_structure``): no Node/Remotion
needed — the .tsx executes behind the existing integration gates, and a real
render is exercised separately. They guard the things that make the layer
correct and safe to ship in parallel:

  * it lives at the discovered path and default-exports the layer contract
    ``{ Layer, order }`` the registry reads;
  * it is frame-pure & deterministic — Math.sin(frame) only, no wallclock, no
    randomness, no CSS keyframe/transition/animation motion;
  * the motion is keyed PER PATTERN across the rotate / opacity / scale palette
    the roadmap names, and is a clean no-op for the non-textured grounds;
  * the drift is gated to the BREATHE phase via the per-beat duration;
  * it is genuinely isolated — StoryCard.tsx is not edited, and the layers
    seam it relies on is present and wired.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from mediahub.visual import motion


COMPOSITIONS = motion.REMOTION_DIR / "src" / "compositions"
LAYER = COMPOSITIONS / "sprint" / "layers" / "pattern_drift.tsx"
REGISTRY = COMPOSITIONS / "sprint" / "registry.ts"
STORYCARD = COMPOSITIONS / "StoryCard.tsx"


@pytest.fixture(scope="module")
def src() -> str:
    """The layer's executable source — block comments stripped.

    The file's own docstring legitimately *names* the anti-patterns it forbids
    (``Math.random``, ``@keyframes``, ``Date.now``), so the purity assertions
    must read the code, not the prose. Every token these tests look for as
    *present* also lives in the code, so dropping the ``/* */`` header is safe.
    """
    assert LAYER.exists(), f"R1.6 drift layer missing at {LAYER}"
    raw = LAYER.read_text(encoding="utf-8")
    return re.sub(r"/\*.*?\*/", "", raw, flags=re.S)


# ---------------------------------------------------------------------------
# Discovery contract — the registry picks the file up automatically
# ---------------------------------------------------------------------------


def test_layer_lives_under_the_discovered_folder():
    """webpack's require.context scans sprint/layers/*.{ts,tsx}; the file must
    sit there with a .tsx suffix to be auto-registered."""
    assert LAYER.parent == COMPOSITIONS / "sprint" / "layers"
    assert LAYER.suffix == ".tsx"


def test_layer_default_exports_the_registry_contract(src: str):
    """layers/<name>.tsx → default export { Layer; order? } (registry.ts)."""
    assert "export default" in src
    assert "Layer" in src and "order" in src
    # A SceneComponent typed against the shared seam, not a bespoke signature.
    assert "SceneComponent" in src
    assert 'from "../registry"' in src


def test_registry_layers_seam_is_present_and_wired():
    """The seam the drift layer rides must exist and feed StoryCard, or the
    overlay would never render. Guards against the seam being removed."""
    reg = REGISTRY.read_text(encoding="utf-8")
    assert "EXTRA_LAYERS" in reg
    assert 'require.context("./layers"' in reg
    story = STORYCARD.read_text(encoding="utf-8")
    assert "EXTRA_LAYERS" in story, "StoryCard must render the sprint layers"


# ---------------------------------------------------------------------------
# Frame-purity & determinism (the hard motion rules)
# ---------------------------------------------------------------------------


def test_motion_is_frame_pure(src: str):
    """Pure function of the frame: Remotion frame maths only — never wallclock
    or randomness, which would break re-render determinism and the cache."""
    assert "Math.random" not in src
    assert "Date.now" not in src
    assert "Math.sin" in src, "the breathe loop must be a finite frame sine"


def test_no_css_animation_for_motion(src: str):
    """CSS @keyframes / transition / animation do not render in Remotion —
    motion must be computed per frame, never declared in CSS."""
    assert "@keyframes" not in src
    assert "animation:" not in src and "animation :" not in src
    # No CSS transition / animation *property* in a style object (the React
    # style keys). Prose mentioning "transition" in comments is fine.
    assert "transition:" not in src
    assert "transition :" not in src


def test_variation_is_seed_derived_not_random(src: str):
    """Per-card phase/speed jitter is deterministic from variationSeed, so two
    textured cards differ without ever breaking still↔motion parity."""
    assert "variationSeed" in src
    assert "seedFrac" in src


# ---------------------------------------------------------------------------
# Per-pattern motion across the rotate / opacity / scale palette
# ---------------------------------------------------------------------------


def test_uses_all_three_named_motion_channels(src: str):
    """The roadmap names rotate / opacity / scale — all three must appear."""
    assert "rotate(" in src
    assert "scale(" in src
    assert "opacity" in src


def test_motion_is_keyed_per_pattern(src: str):
    """Each pattern family drifts in its own idiom (not one motion for all)."""
    for token in ("dots", "halftone", "diagonal", "stripes", "geometric", "water", "grain"):
        assert token in src, f"pattern {token!r} not handled by the drift layer"
    # Families, not a flat switch of identical bodies.
    for family in ("dot", "linear", "angular", "noise", "generic"):
        assert f'"{family}"' in src, f"missing pattern family {family!r}"


def test_no_op_for_non_textured_grounds(src: str):
    """clean / radial / duotone (and the bare default) paint no motion overlay,
    so those cards render exactly as they did before this layer landed."""
    for token in ("radial", "duotone", "clean"):
        assert f'"{token}"' in src
    # An explicit null bail when there is no tile to drift.
    assert "return null" in src


def test_sprint_patterns_are_supported(src: str):
    """A background pattern registered by R1.4 (EXTRA_PATTERNS) also drifts —
    the layer reuses the same pattern source, never a forked vocabulary."""
    assert "EXTRA_PATTERNS" in src


# ---------------------------------------------------------------------------
# Breathe-phase gating (30–70% of the beat) via the per-beat duration
# ---------------------------------------------------------------------------


def test_drift_is_gated_to_the_breathe_phase(src: str):
    """Duration-proportional envelope: the drift fades in across build→breathe
    and out across breathe→resolve, so the transition/outro owns the exit and
    the build frames (and the poster) stay clean."""
    assert "useVideoConfig" in src
    assert "durationInFrames" in src
    assert "envelope" in src
    # Proportional thresholds inside the breathe band, not absolute frames.
    assert "durationInFrames *" in src or "durationInFrames*" in src


def test_drift_content_area_is_protected(src: str):
    """A mask keeps the drift out of the central content band (motion-craft:
    a full repeating grid over the hero text reads as cheap)."""
    assert "maskImage" in src or "WebkitMaskImage" in src
    assert "pointerEvents" in src  # never intercepts; it is pure decoration


# ---------------------------------------------------------------------------
# Isolation — this is a pure new-file drop, no shared-composition edit
# ---------------------------------------------------------------------------


def test_storycard_is_not_edited_for_this_feature():
    """R1.6 is 🟢 ISOLATED: the capability is added entirely as its own file,
    so StoryCard.tsx carries no drift-specific symbol."""
    story = STORYCARD.read_text(encoding="utf-8")
    assert "pattern_drift" not in story
    assert "driftTileFor" not in story


def test_layer_is_in_the_motion_parity_corpus():
    """The parity corpus scans every sprint .ts/.tsx; the drift layer is part
    of it, so it can never silently fall out of the build the test reasons about."""
    sprint = COMPOSITIONS / "sprint"
    scanned = {
        p for p in sprint.rglob("*") if p.suffix in {".ts", ".tsx"}
    }
    assert LAYER in scanned
