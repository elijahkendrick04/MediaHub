"""Reel scene-mode pack — sprint R1.2.

Three new structurally-distinct motion scenes drop into the auto-discovered
``sprint/scenes/`` seam — ``vertical_split``, ``radial_rings`` and
``marquee_crawl`` — each its OWN file, with zero edits to ``StoryCard.tsx``.
The registry (``sprint/registry.ts``) keys scenes by archetype id and
``StoryCard`` resolves ``EXTRA_SCENES[card.archetype]`` ahead of the built-in
parity-mapped scene, so a card carrying one of these archetypes renders the new
scene.

These are source-contract tests in the house style of
``test_motion_v2_parity.py`` (no Node needed): they pin the drop-in contract,
the three engine non-negotiables every scene inherits (frame-pure, brand-locked,
fact-exact), and that the three scenes are genuinely distinct from each other and
from the built-ins. A gated tail compiles the TSX with ``tsc`` where the Remotion
toolchain is installed.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from mediahub.visual import motion

SPRINT = motion.REMOTION_DIR / "src" / "compositions" / "sprint"
SCENES_DIR = SPRINT / "scenes"
KIT = SPRINT / "sceneKit.tsx"

# The three scenes this sprint item ships, keyed by their still-engine archetype
# id (snake_case, matching the existing archetype vocabulary in StoryCard.tsx).
EXPECTED = {
    "vertical_split": SCENES_DIR / "vertical_split.tsx",
    "radial_rings": SCENES_DIR / "radial_rings.tsx",
    "marquee_crawl": SCENES_DIR / "marquee_crawl.tsx",
}


def _src(path: Path) -> str:
    return path.read_text()


def _strip_comments(src: str) -> str:
    """Drop block + line comments so contract checks never trip on prose."""
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"(?m)//.*$", "", src)
    return src


def _all_scene_sources() -> dict[str, str]:
    return {arch: _src(p) for arch, p in EXPECTED.items()}


# ---------------------------------------------------------------------------
# Drop-in contract
# ---------------------------------------------------------------------------


def test_all_three_scene_files_exist():
    missing = [arch for arch, p in EXPECTED.items() if not p.is_file()]
    assert not missing, f"missing scene files for: {missing}"


def test_each_scene_default_exports_archetype_and_scene():
    """Registry contract (``registry.ts``): each module DEFAULT-exports
    ``{ archetype: string; Scene: SceneComponent }``. The archetype must equal
    the filename stem so the still↔motion key is unambiguous."""
    for arch, path in EXPECTED.items():
        body = _strip_comments(_src(path))
        m = re.search(
            r"export\s+default\s*\{\s*archetype:\s*[\"']([a-z_]+)[\"']\s*,\s*Scene\s*\}",
            body,
        )
        assert m, f"{path.name}: no `export default {{ archetype, Scene }}`"
        assert m.group(1) == arch == path.stem, (
            f"{path.name}: archetype {m.group(1)!r} must match filename stem {path.stem!r}"
        )


def test_scenes_import_types_from_registry_not_storycard():
    """Sprint modules must take their types from the shared ``../registry``
    re-export (the seam's single source), never reach into StoryCard.tsx — that
    is what keeps the drop ISOLATED."""
    for arch, src in _all_scene_sources().items():
        assert 'from "../registry"' in src, f"{arch}: should import types from ../registry"
        assert "StoryCard" not in _strip_comments(src), (
            f"{arch}: a scene must not import from or reference StoryCard.tsx"
        )


def test_scene_switch_in_storycard_is_untouched():
    """R1.2 is 🟢 ISOLATED — new files only. The built-in scene switch and its
    8-mode table stay exactly as they were; the new scenes ride the registry."""
    story = _src(motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx")
    # The override line must still resolve EXTRA_SCENES ahead of the built-ins.
    assert "EXTRA_SCENES[card.archetype" in story
    # And the new archetype ids must NOT have been hand-wired into the built-in
    # switch (that would defeat auto-discovery / make the drop non-isolated).
    switch = story.split("function sceneForArchetype", 1)[1].split("\n}", 1)[0]
    for arch in EXPECTED:
        assert f'"{arch}"' not in switch, (
            f"{arch} must be registered via its own file, not the built-in switch"
        )


# ---------------------------------------------------------------------------
# Engine non-negotiable #1 — frame-pure & deterministic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [KIT, *EXPECTED.values()], ids=lambda p: p.name)
def test_no_nondeterminism_or_css_animation(path):
    """Animation is a pure function of the frame: no wallclock, no RNG, and no
    CSS-driven motion (CSS transitions/keyframes don't render under Remotion and
    would break determinism)."""
    body = _strip_comments(_src(path))
    for banned in (
        "Math.random(",
        "Date.now(",
        "new Date(",
        "performance.now(",
        "@keyframes",
        "animation:",
        "transition:",
        "useState",
        "useEffect",
        "requestAnimationFrame",
    ):
        assert banned not in body, f"{path.name}: banned non-deterministic/CSS construct {banned!r}"


def test_variation_comes_only_from_the_seed():
    """Per-card variety derives solely from ``variationSeed`` (via the kit's
    ``seedPick``) so a card's video stays in lock-step with its still."""
    for arch, src in _all_scene_sources().items():
        if "seedPick(" in src:
            # The kit's seedPick is the only sanctioned variety source.
            assert "variationSeed" in _src(KIT)


def test_motion_is_remotion_interpolation_only():
    """Each scene drives structural motion through Remotion ``interpolate`` and
    the frame from ``ctx`` — the frame-pure house tools, never wallclock."""
    for arch, src in _all_scene_sources().items():
        assert "interpolate(" in src, f"{arch}: expected Remotion interpolate()"
        assert "ctx.frame" in src or "frame," in src or "frame }" in src, (
            f"{arch}: structural motion must read the frame from ctx"
        )


# ---------------------------------------------------------------------------
# Engine non-negotiable #2 — brand-locked colour
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", [KIT, *EXPECTED.values()], ids=lambda p: p.name)
def test_no_hardcoded_hex_colours(path):
    """Colour comes only from the resolved ``ctx.roles`` (ground/surface/accent/
    onGround) or ground-derived alpha scrims — never an invented hex."""
    body = _strip_comments(_src(path))
    hexes = re.findall(r"#[0-9A-Fa-f]{3,8}\b", body)
    assert not hexes, f"{path.name}: hardcoded hex colour(s) {hexes} — use ctx.roles"


def test_scenes_paint_from_resolved_roles():
    for arch, src in _all_scene_sources().items():
        assert "roles.accent" in src or "roles.ground" in src, (
            f"{arch}: must paint from the resolved colour roles"
        )


# ---------------------------------------------------------------------------
# Engine non-negotiable #3 — fact-exact
# ---------------------------------------------------------------------------


def test_marquee_crawl_uses_the_verified_value_not_the_mid_count():
    """A scrolling/crawling number must be the VERIFIED result (``resultFinal``),
    never the mid-count ``result`` display text — a partial time crawling by
    would read as a different result (the same rule the built-in ticker lives by)."""
    src = _src(EXPECTED["marquee_crawl"])
    # The crawl copy is assembled from ctx.resultFinal …
    crawl_assembly = re.search(r"const bits = \[(.*?)\]", src, flags=re.S)
    assert crawl_assembly, "expected a `bits` crawl-copy assembly"
    assert "resultFinal" in crawl_assembly.group(1), "crawl copy must use ctx.resultFinal"
    # `\b` after "result" does not match inside "resultFinal" (both word chars),
    # so this flags only a bare mid-count `ctx.result` in the crawl copy.
    assert not re.search(r"ctx\.result\b", crawl_assembly.group(1)), (
        "crawl copy must NOT use the mid-count ctx.result"
    )


def test_place_ordinal_never_invents_a_placing():
    """The kit's placing helper passes non-numeric values through untouched —
    it never fabricates an ordinal the detector did not produce."""
    kit = _strip_comments(_src(KIT))
    fn = kit.split("export function placeOrdinal", 1)[1].split("\nexport ", 1)[0]
    # Non-numeric input returns the raw (uppercased) string; only a matched
    # /^\d+$/ gets an ordinal suffix.
    assert "match(/^(\\d+)$/)" in fn
    assert "return (place || \"\").trim().toUpperCase()" in fn


def test_scenes_render_only_real_card_fields():
    """Scenes show facts straight from the pre-computed ``ctx`` fields; they must
    not synthesise an achievement, placing or stat of their own."""
    for arch, src in _all_scene_sources().items():
        body = _strip_comments(src)
        # The result shown is the count-up-aware ctx.result (verbatim at rest).
        assert "ctx.result" in body, f"{arch}: must render ctx.result"
        # No string concatenation inventing numbers (e.g. a hardcoded place).
        assert not re.search(r"[\"']\d+(ST|ND|RD|TH)[\"']", body), (
            f"{arch}: must not hardcode a placing"
        )


# ---------------------------------------------------------------------------
# Structural distinctness — the whole point of a "scene-mode pack"
# ---------------------------------------------------------------------------


def test_each_scene_carries_its_distinct_structural_signature():
    """Each scene is structurally distinct (not a recoloured hero): a unique
    composition marker no other scene in the pack uses."""
    srcs = _all_scene_sources()
    # vertical_split — a horizontal seam with a field that RISES (scaleY).
    assert "seamY" in srcs["vertical_split"] and "scaleY(" in srcs["vertical_split"]
    # radial_rings — concentric ring loop + a rotating dashed tick-ring.
    assert "borderRadius:" in srcs["radial_rings"] and "rotate(" in srcs["radial_rings"]
    assert re.search(r"for \(let i = 0; i < ringCount", srcs["radial_rings"])
    # marquee_crawl — a multi-band horizontal crawl (translateX over speeds).
    assert "SPEEDS" in srcs["marquee_crawl"] and "translateX(" in srcs["marquee_crawl"]
    assert "bandCount" in srcs["marquee_crawl"]


def test_signatures_are_mutually_exclusive():
    """The distinct signatures don't leak across files — a hard guard that the
    three really are different scenes, not copies."""
    srcs = _all_scene_sources()
    assert "seamY" not in srcs["radial_rings"] and "seamY" not in srcs["marquee_crawl"]
    assert "ringCount" not in srcs["vertical_split"] and "ringCount" not in srcs["marquee_crawl"]
    assert "SPEEDS" not in srcs["vertical_split"] and "SPEEDS" not in srcs["radial_rings"]


def test_scenes_differ_from_builtin_scene_modes():
    """The new archetype ids are not any of the 8 built-in scene-mode names —
    they extend the vocabulary rather than shadowing a built-in."""
    builtin_modes = {
        "hero", "poster", "lowerThird", "spotlight",
        "grid", "ticker", "split", "magazine",
    }
    assert set(EXPECTED).isdisjoint(builtin_modes)


# ---------------------------------------------------------------------------
# Motion-parity corpus — a registered scene counts as "covered"
# ---------------------------------------------------------------------------


def test_new_archetypes_present_in_motion_source_corpus():
    """The parity scan unions StoryCard.tsx with every sprint module; a scene
    registered for an archetype must therefore appear in that corpus (so the
    still↔motion parity test counts the archetype as executed)."""
    comp = motion.REMOTION_DIR / "src" / "compositions"
    corpus = (comp / "StoryCard.tsx").read_text()
    corpus += "\n".join(
        p.read_text() for p in sorted((comp / "sprint").rglob("*")) if p.suffix in {".ts", ".tsx"}
    )
    for arch in EXPECTED:
        assert f'"{arch}"' in corpus, f"{arch} missing from the motion source corpus"


def test_kit_lives_outside_the_autoscanned_subfolders():
    """The shared kit sits directly under ``sprint/`` (not in a
    ``require.context``-scanned subfolder), so it is never mistaken for a scene
    module by the registry."""
    assert KIT.parent == SPRINT
    scanned = {"intents", "patterns", "accents", "springs", "scenes", "layers", "reel"}
    assert KIT.parent.name not in scanned


# ---------------------------------------------------------------------------
# Gated: the TSX actually compiles where the Remotion toolchain is installed
# ---------------------------------------------------------------------------


def test_new_scene_tsx_typechecks():
    node = shutil.which("node")
    tsc = motion.REMOTION_DIR / "node_modules" / ".bin" / "tsc"
    if not node or not tsc.exists():
        pytest.skip("Remotion toolchain (node + tsc) not installed in this environment")
    proc = subprocess.run(
        [str(tsc), "--noEmit"],
        cwd=str(motion.REMOTION_DIR),
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, f"tsc failed:\n{proc.stdout}\n{proc.stderr}"
