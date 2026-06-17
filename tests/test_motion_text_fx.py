"""R1.11 — On-video text-effect library (`sprint/layers/text_fx.tsx`).

The reel/story text-effect overlay: glow · outline · 3D-shadow · stroke-animate ·
blur-to-focus, added as a single auto-discovered additive layer with NO edits to
`StoryCard.tsx` or the shared scene components.

These are source-contract tests (the same no-Node approach the rest of the motion
suite uses — see ``test_motion_v2_parity``): they assert the layer honours the
sprint registry drop-in contract and the motion-craft "hard bounds" — frame-pure,
deterministic, brand-exact, legacy-safe. One extra test runs the real TypeScript
compiler when the Remotion toolchain is present, and skips cleanly when it isn't.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from mediahub.visual import motion

LAYER = (
    motion.REMOTION_DIR
    / "src"
    / "compositions"
    / "sprint"
    / "layers"
    / "text_fx.tsx"
)

# The five effects the roadmap names, as the canonical in-code tokens.
EFFECTS = ("glow", "outline", "shadow3d", "stroke_animate", "blur_to_focus")


@pytest.fixture(scope="module")
def src() -> str:
    assert LAYER.is_file(), f"R1.11 layer missing at {LAYER}"
    return LAYER.read_text()


def _strip_comments(text: str) -> str:
    """TSX with /* */ and // comments removed, so "forbidden token" checks read
    the executable code, not the prose that documents what the code avoids."""
    no_block = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//[^\n]*", "", no_block)


@pytest.fixture(scope="module")
def code(src: str) -> str:
    return _strip_comments(src)


# ---------------------------------------------------------------------------
# Registry drop-in contract (auto-discovery)
# ---------------------------------------------------------------------------


def test_layer_lives_in_the_auto_discovered_layers_folder():
    # registry.ts enumerates ./layers via require.context; a file here is picked
    # up with no StoryCard.tsx edit.
    assert LAYER.parent.name == "layers"
    assert LAYER.parent.parent.name == "sprint"


def test_layer_default_exports_the_registry_shape(src: str):
    # The contract: layers/<name>.tsx default-exports { Layer; order? }.
    assert re.search(r"export\s+default\s*{\s*Layer\s*,\s*order", src), (
        "must default-export { Layer, order } so EXTRA_LAYERS discovers it"
    )
    assert "SceneComponent" in src, "Layer must be typed as the registry SceneComponent"
    # The registry filters on `m.Layer`; the sort uses a numeric `order`.
    assert re.search(r"order:\s*\d+", src)


def test_registry_consumes_layer_modules():
    """Guard the seam itself: registry.ts must still discover ./layers and the
    composition must still render EXTRA_LAYERS. Otherwise this file is inert."""
    reg = (motion.REMOTION_DIR / "src" / "compositions" / "sprint" / "registry.ts").read_text()
    assert 'require.context("./layers"' in reg
    assert "EXTRA_LAYERS" in reg
    story = (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text()
    assert "EXTRA_LAYERS.map" in story, "StoryCard must render the discovered layers"


# ---------------------------------------------------------------------------
# Library completeness — every named effect is implemented, not just listed
# ---------------------------------------------------------------------------


def test_every_named_effect_is_implemented(src: str):
    for fx in EFFECTS:
        assert f'"{fx}"' in src, f"effect {fx!r} missing from the effect union"
        assert f'case "{fx}"' in src, f"effect {fx!r} has no execution branch"


def test_roadmap_names_are_traceable(src: str):
    # The hyphenated roadmap spellings appear (in comments) so a reader can map
    # the roadmap line to the code.
    for name in ("3D-shadow", "stroke-animate", "blur-to-focus"):
        assert name in src, f"roadmap name {name!r} not traceable in the source"


def test_all_five_effects_are_reachable_from_the_brief(src: str):
    """Each effect must be selectable from a real brief axis (mood or accent) —
    a library nothing can pick is dead code."""
    # Pull the mood→fx and accent→fx maps and assert their union covers all five.
    reachable = set(re.findall(r':\s*"(\w+)"', src))
    for fx in EFFECTS:
        assert fx in reachable, f"effect {fx!r} is not mapped from any mood/accent"


# ---------------------------------------------------------------------------
# Hard bound 1 + 2 — pure function of the frame, deterministic
# ---------------------------------------------------------------------------


def test_animation_is_frame_pure(src: str):
    # Frame-driven via Remotion interpolate over ctx.frame, eased + clamped.
    assert "interpolate(" in src
    assert "ctx.frame" in src
    assert "Easing" in src
    assert 'extrapolateRight: "clamp"' in src or "extrapolateRight:" in src


def test_no_css_animation_primitives(code: str):
    # CSS @keyframes / transition / animation don't render under Remotion — the
    # motion must come from per-frame React re-render, not the stylesheet.
    lowered = code.lower()
    assert "@keyframes" not in lowered
    assert "transition:" not in lowered
    assert "animation:" not in lowered
    assert "animation-" not in lowered


def test_deterministic_no_wallclock_or_random(code: str):
    assert "Math.random" not in code
    assert "Date.now" not in code
    assert "performance.now" not in code


# ---------------------------------------------------------------------------
# Hard bound 3/4 — brand-exact colours, no invented hex
# ---------------------------------------------------------------------------


def test_colours_come_from_resolved_roles(src: str):
    assert "roles.ground" in src
    assert "roles.accent" in src


def test_no_invented_brand_hex(code: str):
    """No literal brand colour — only the universal black/white safety net the
    rest of StoryCard.tsx also uses is allowed."""
    hexes = set(re.findall(r"#[0-9a-fA-F]{6}\b", code))
    stray = hexes - {"#000000", "#FFFFFF"}
    assert not stray, f"invented brand hex literal(s): {stray}"


# ---------------------------------------------------------------------------
# Hard bound 5 — legacy-safe: restraint / brief-less cards render unchanged
# ---------------------------------------------------------------------------


def test_restraint_and_briefless_resolve_to_none(src: str):
    # neutral / minimal / stoic are explicitly off; the catch-all returns "none".
    for mood in ("neutral", "minimal", "stoic"):
        assert f'"{mood}"' in src, f"restraint mood {mood!r} not handled"
    assert '"none"' in src
    # An effect of "none" renders nothing (the overlay is invisible for legacy).
    assert "return null" in src
    assert re.search(r'effect\s*===\s*"none"', src)


def test_none_is_not_in_the_active_effect_maps(src: str):
    """"none" must be reached by *falling through* the maps, never by mapping a
    mood to it — otherwise a typo'd map entry could silently disable an effect."""
    map_block = src.split("function chooseEffect", 1)[0]
    # The MOOD_FX / ACCENT_FX object literals must not contain a "none" value.
    assert re.search(r':\s*"none"', map_block) is None


# ---------------------------------------------------------------------------
# Self-contained hook — no scene edits, no cross-card bleed
# ---------------------------------------------------------------------------


def test_self_contained_has_hook_with_unique_id(src: str):
    # Reaches the card root via :has() on a per-instance marker; useId keeps two
    # cards in one reel from sharing a selector.
    assert ":has(" in src
    assert "data-mh-textfx" in src
    assert "useId(" in src


def test_does_not_edit_shared_scene_components(src: str):
    # The overlay must not import or re-implement a scene — it only augments.
    for scene in ("HeroScene", "PosterScene", "SpotlightScene", "SCENES"):
        assert scene not in src, f"text_fx must not reach into {scene}"


# ---------------------------------------------------------------------------
# Self-hosted fonts (defence in depth alongside test_self_hosted_fonts.py)
# ---------------------------------------------------------------------------


def test_no_font_cdn_or_new_family(code: str):
    lowered = code.lower()
    for bad in ("googleapis", "gstatic", "@import", "@font-face", "fontfamily", "font-family"):
        assert bad not in lowered, f"text_fx must not touch fonts/CDN ({bad!r})"


# ---------------------------------------------------------------------------
# Real build gate — typecheck with the actual compiler when it's available
# ---------------------------------------------------------------------------


def test_layer_typechecks_with_tsc_when_toolchain_present():
    tsc = motion.REMOTION_DIR / "node_modules" / ".bin" / "tsc"
    if not tsc.exists() or shutil.which("node") is None:
        pytest.skip("Remotion node toolchain not installed in this environment")
    proc = subprocess.run(
        [str(tsc), "--noEmit"],
        cwd=str(motion.REMOTION_DIR),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, f"tsc failed:\n{proc.stdout}\n{proc.stderr}"
