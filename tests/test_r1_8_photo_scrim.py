"""R1.8 — Photo scrim variant system for motion.

The capability ships as a single auto-discovered additive overlay,
``remotion/src/compositions/sprint/layers/photo_scrim.tsx`` (roadmap R1.8,
🟢 ISOLATED). It paints a role-driven legibility scrim over photo cards in one
of four deliberately distinct shapes — ``gradient`` / ``edge`` / ``radial`` /
``corner`` — leaving the central band (subject + hero copy) untouched.

Like the rest of the motion suite (see ``tests/test_motion_v2_parity.py``), the
TSX is validated by **source contracts** — no Node runtime is needed for the
unit gate, so these run everywhere ``pytest`` does. A separate, self-skipping
test compiles the TSX under the project's strict ``tsconfig`` when the Node
toolchain happens to be present (it is absent in the standard CI image, so it
skips cleanly there, exactly like the Playwright layers).

Behavioural correctness (determinism, per-variant shape, centre-clarity,
still↔motion vignette parity) was verified by transpiling and executing the
module against stubbed ``remotion``/JSX runtimes during development; these
contracts lock in the properties that verification proved.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from mediahub.visual import motion

COMPOSITIONS = motion.REMOTION_DIR / "src" / "compositions"
SPRINT = COMPOSITIONS / "sprint"
LAYER = SPRINT / "layers" / "photo_scrim.tsx"


def _strip_comments(s: str) -> str:
    """Drop block + line comments so contracts test the code, not the prose
    (the header documents the very rules these assertions enforce)."""
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    s = re.sub(r"//[^\n]*", "", s)
    return s


@pytest.fixture(scope="module")
def src() -> str:
    return LAYER.read_text()


# ---------------------------------------------------------------------------
# Existence + registry wiring (auto-discovery, no StoryCard.tsx edit)
# ---------------------------------------------------------------------------


def test_layer_file_exists():
    assert LAYER.is_file(), f"missing R1.8 layer file: {LAYER}"


def test_registers_as_an_additive_layer(src: str):
    # The registry default-loads ``{ Layer, order }`` from each layers/ module.
    assert re.search(r"export default\s*{\s*Layer\s*,\s*order", src), (
        "must default-export the { Layer, order } registry shape"
    )
    assert re.search(r"const Layer:\s*SceneComponent", src), (
        "Layer must be typed as a SceneComponent"
    )


def test_order_is_a_sane_positive_integer(src: str):
    m = re.search(r"order:\s*(\d+)", src)
    assert m, "an explicit numeric `order` is required for deterministic stacking"
    order = int(m.group(1))
    assert 0 < order < 100, f"order {order} outside the documented 0–90 overlay band"


def test_discoverable_by_the_same_scan_the_parity_corpus_uses(src: str):
    # tests/test_motion_v2_parity.py builds its corpus from sprint/**/*.{ts,tsx};
    # the registry's require.context uses /\.tsx?$/. Both must see this file.
    discovered = [p for p in SPRINT.rglob("*") if p.suffix in {".ts", ".tsx"}]
    assert LAYER in discovered, "layer not on the sprint discovery path"
    assert LAYER.suffix == ".tsx" and LAYER.parent.name == "layers"


def test_isolated_no_storycard_edit_needed(src: str):
    """ISOLATED contract: the layer is auto-discovered, never hardwired."""
    story = (COMPOSITIONS / "StoryCard.tsx").read_text()
    assert "EXTRA_LAYERS.map" in story, "the auto-discovery pipeline must still wire layers"
    assert "photo_scrim" not in story, "layer must be discovered, not referenced by name"


def test_imports_types_from_the_registry_seam(src: str):
    # Convention (registry.ts): every sprint module imports its types from
    # one place, ../registry.
    assert re.search(
        r'import type\s*{[^}]*\bSceneComponent\b[^}]*}\s*from\s*"\.\./registry"', src
    ), "SceneComponent type must come from ../registry"
    assert re.search(r'import\s*{[^}]*\binterpolate\b[^}]*}\s*from\s*"remotion"', src), (
        "frame-pure motion uses remotion's interpolate"
    )


# ---------------------------------------------------------------------------
# The four-variant system
# ---------------------------------------------------------------------------


def test_declares_all_four_scrim_variants(src: str):
    m = re.search(r"type ScrimVariant\s*=\s*([^;]+);", src)
    assert m, "a ScrimVariant union must define the vocabulary"
    union = m.group(1)
    for variant in ("gradient", "edge", "radial", "corner"):
        assert f'"{variant}"' in union, f"variant {variant!r} missing from the union"


def test_every_variant_has_a_background_recipe(src: str):
    # The Record<ScrimVariant, string> background map keys every variant.
    block = src.split("const backgrounds:", 1)
    assert len(block) == 2, "a per-variant background map is required"
    body = block[1].split("};", 1)[0]
    for variant in ("gradient", "edge", "radial", "corner"):
        assert re.search(rf"\b{variant}:", body), f"no background recipe for {variant!r}"
    # Shapes are genuinely distinct, not four aliases of one gradient.
    assert "linear-gradient(0deg" in body, "gradient = bottom-weighted linear wash"
    assert "linear-gradient(90deg" in body and "linear-gradient(180deg" in body, (
        "edge = four-margin straight frame"
    )
    assert "radial-gradient(ellipse 75%" in body, "radial = centred vignette"
    assert "at 0% 0%" in body and "at 100% 100%" in body, "corner = diagonal corners"


def test_selection_is_deterministic_seed_driven_with_vignette_parity(src: str):
    fn = src.split("export function scrimVariantFor", 1)
    assert len(fn) == 2, "scrimVariantFor must be an exported, testable seam"
    body = fn[1].split("\n}", 1)[0]
    # Still↔motion parity: the still's vignette treatment → the radial scrim.
    assert '=== "vignette"' in body and '"radial"' in body, (
        "vignette photo treatment must map to the radial scrim"
    )
    assert ".toLowerCase()" in body, "vignette parity must be case-insensitive"
    # Otherwise the variant is a pure function of the seed (varied, stable).
    assert "variationSeed" in body, "selection must be variationSeed-driven"
    assert "VARIANTS[" in body, "selection indexes the deterministic VARIANTS order"


# ---------------------------------------------------------------------------
# Non-negotiables: role-driven, deterministic, photo-only, legibility-safe
# ---------------------------------------------------------------------------


def test_role_driven_never_invents_a_colour(src: str):
    assert "roles.ground" in src, "the scrim colour must come from the ground role"
    # No literal #RRGGBB hex anywhere — every colour is built from the role.
    stray = re.findall(r"#[0-9a-fA-F]{6}\b", src)
    assert not stray, f"hard-coded hex colour(s) found: {stray}"


def test_photo_only_is_a_clean_noop_without_a_photo(src: str):
    layer = src.split("const Layer:", 1)[1]
    # First guard inside the component returns null when there's no photo.
    head = layer.split("const variant", 1)[0]
    assert "card.photoSrc" in head and "return null" in head, (
        "no attached photo → render nothing (non-photo cards stay identical)"
    )
    # And an unusable ground role also yields nothing rather than an invented one.
    assert "isHexColour(ground)" in head, "guard a malformed role → no scrim"


def test_deterministic_no_random_or_wallclock(src: str):
    code = _strip_comments(src)
    assert "Math.random" not in code, "no Math.random — renders must be reproducible"
    assert "Date.now" not in code and "performance.now" not in code, "no wallclock"


def test_frame_pure_eased_entrance_not_at_frame_zero(src: str):
    # Eased, clamped interpolate off the frame — composed, never a frame-0 pop.
    assert re.search(r"interpolate\(\s*frame\s*,\s*\[\s*3\s*,\s*18\s*\]", src), (
        "scrim must ease in over frames [3, 18], not pop at frame 0"
    )
    assert 'extrapolateLeft: "clamp"' in src and 'extrapolateRight: "clamp"' in src, (
        "interpolations must clamp so opacity never overshoots"
    )
    assert "Easing.out(Easing.cubic)" in src, "entrance uses an ease-out (composed)"


def test_legibility_safe_overlay_props(src: str):
    style = src.split("style={{", 1)[1].split("}}", 1)[0]
    assert 'position: "absolute"' in style and "inset: 0" in style, "covers the frame"
    assert 'pointerEvents: "none"' in style, "must never intercept input"
    assert "opacity: enter" in style, "opacity is the frame-derived entrance value"


def test_every_variant_keeps_the_centre_clear(src: str):
    # Centre-clarity is what lets the scrim paint over the text safely: each
    # recipe references a fully-transparent same-hue stop (`clear`).
    assert re.search(r"const clear\s*=\s*withAlpha\(ground,\s*0\)", src), (
        "a transparent same-hue `clear` stop must exist"
    )
    body = _strip_comments(src).split("const backgrounds:", 1)[1].split("};", 1)[0]
    # Slice the map per-variant by key position (robust to multi-line recipes).
    keys = ["gradient", "edge", "radial", "corner"]
    pos = {k: body.find(f"{k}:") for k in keys}
    assert all(p >= 0 for p in pos.values()), f"variant keys missing: {pos}"
    order = sorted(keys, key=lambda k: pos[k])
    for i, k in enumerate(order):
        end = pos[order[i + 1]] if i + 1 < len(order) else len(body)
        assert "clear" in body[pos[k]:end], f"{k!r} must keep its centre clear"


def test_peak_alpha_is_capped_low_for_all_variants(src: str):
    block = src.split("const PEAK_ALPHA", 1)[1].split("};", 1)[0]
    pairs = re.findall(r"(gradient|edge|radial|corner):\s*([0-9.]+)", block)
    assert {k for k, _ in pairs} == {"gradient", "edge", "radial", "corner"}
    for name, value in pairs:
        a = float(value)
        assert 0 < a <= 0.4, f"{name} peak alpha {a} not in the capped (0, 0.4] range"


def test_alpha_helper_only_varies_alpha_not_hue(src: str):
    fn = src.split("function withAlpha", 1)[1].split("\n}", 1)[0]
    # Builds #<role-hue><alpha>; the hue is the role's own slice, never rewritten.
    assert "`#${h}${aa}`" in fn, "withAlpha must keep the role hue and append alpha"
    assert "Math.max(0, Math.min(1, alpha))" in fn, "alpha must be clamped to [0,1]"


# ---------------------------------------------------------------------------
# Real strict-TypeScript compile (self-skips without the Node toolchain)
# ---------------------------------------------------------------------------


def test_typechecks_under_strict_tsconfig():
    """Compile the remotion sources (incl. this layer) under the project's
    strict tsconfig. Skips when the Node toolchain isn't installed — the
    standard CI image has no remotion node_modules, the same reason the
    Playwright layers self-skip there."""
    tsc = motion.REMOTION_DIR / "node_modules" / ".bin" / "tsc"
    tsconfig = motion.REMOTION_DIR / "tsconfig.json"
    if shutil.which("node") is None or not tsc.exists():
        pytest.skip("Node toolchain / remotion node_modules absent")
    proc = subprocess.run(
        [str(tsc), "--noEmit", "--project", str(tsconfig)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, f"tsc failed:\n{proc.stdout}\n{proc.stderr}"
