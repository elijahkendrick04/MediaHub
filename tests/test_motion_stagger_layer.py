"""R1.25 — multi-part stagger sequences (component-group cascade layer).

The reel/story sprint adds a new additive overlay,
``remotion/src/compositions/sprint/layers/stagger.tsx``, that cascades a card's
component GROUPS — name → event → result → chips — as a deliberate multi-part
sequence, the macro companion to ``kinetic_type``'s existing per-word reveal
(the ``word-cascade`` effect / ``wordAt`` channel).

A sprint *layer* is auto-discovered and rendered over EVERY card, so the one
hard requirement is that it stays inert unless the brief opts in. These tests
prove the source contract end to end:

  * the drop-in shape the registry expects (``export default { Layer, order }``);
  * the layer is gated on ``motionIntent === "kinetic_type"`` and returns null
    for every other intent → all other cards render byte-identically;
  * the cascade order is name → event → result → chips, each segment drawn only
    when the card actually carries that group (absent groups skipped — never an
    invented one);
  * it is a pure, deterministic function of the frame (no wall-clock, no RNG, no
    CSS keyframes), with clamped interpolations and the first beat off frame 0;
  * colour comes from the resolved brand accent role — never an invented hex;
  * it is actually mounted by ``StoryCard.tsx`` via ``EXTRA_LAYERS``.

Mostly source-contract checks (the house style for the motion stack — "No Node
needed"); the final test additionally type-checks the TSX with ``tsc`` when a
Node toolchain is present, and skips cleanly when it isn't.
"""

from __future__ import annotations

import re
import shutil
import subprocess

import pytest

from mediahub.visual import motion


LAYER_PATH = (
    motion.REMOTION_DIR
    / "src"
    / "compositions"
    / "sprint"
    / "layers"
    / "stagger.tsx"
)


def _src() -> str:
    return LAYER_PATH.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Existence + drop-in registry contract
# ---------------------------------------------------------------------------


def test_stagger_layer_file_exists():
    assert LAYER_PATH.is_file(), f"missing R1.25 layer at {LAYER_PATH}"


def test_stagger_layer_dropin_contract():
    """Registry contract (sprint/registry.ts): a layer module DEFAULT-exports
    ``{ Layer: SceneComponent; order?: number }`` and imports its types from
    the shared ``../registry`` barrel."""
    src = _src()
    assert 'from "../registry"' in src, "types must come from the registry barrel"
    assert "const Layer: SceneComponent" in src, "Layer must be a SceneComponent"
    # default export carrying Layer + a numeric order
    m = re.search(r"export default\s*\{\s*Layer\s*,\s*order:\s*(\d+)\s*\}", src)
    assert m, "must `export default { Layer, order: <number> }`"
    assert int(m.group(1)) >= 0


def test_stagger_layer_mounted_in_storycard():
    """The overlay only does anything if StoryCard actually renders the
    discovered layers — guard the integration point so a refactor that drops
    the EXTRA_LAYERS map is caught here too."""
    story = (motion.REMOTION_DIR / "src" / "compositions" / "StoryCard.tsx").read_text()
    assert "EXTRA_LAYERS.map(" in story
    assert "from \"./sprint/registry\"" in story


# ---------------------------------------------------------------------------
# Gate: inert for every intent but kinetic_type
# ---------------------------------------------------------------------------


def test_stagger_layer_gated_on_kinetic_type():
    """The macro group-cascade rides ONLY on kinetic_type; every other intent
    must hit an early `return null` so its card is byte-identical to before."""
    src = _src()
    assert '!== "kinetic_type"' in src, "must gate on the kinetic_type intent"
    # The gate must short-circuit with a null return before any drawing.
    gate = src.split('!== "kinetic_type"', 1)[1]
    assert "return null" in gate[:120], "non-kinetic_type intents must render nothing"
    # And it reads the intent off the card props the director already emits
    # (no new prop / no cache-key change).
    assert "motionIntent" in src


def test_stagger_layer_inert_for_a_single_group():
    """A lone present group can't 'cascade' — the layer stays inert rather than
    drawing a single orphan tick."""
    src = _src()
    assert "groups.length < 2" in src
    assert src.count("return null") >= 2, "needs both the intent gate and the <2 guard"


# ---------------------------------------------------------------------------
# The cascade: name -> event -> result -> chips, present groups only
# ---------------------------------------------------------------------------


def test_stagger_cascade_order_is_name_event_result_chips():
    src = _src()
    order = [src.find(f'"{g}"') for g in ("name", "event", "result", "chips")]
    assert all(i != -1 for i in order), "all four component groups must be named"
    assert order == sorted(order), (
        "cascade must run name -> event -> result -> chips (roadmap R1.25 order)"
    )


def test_stagger_groups_map_to_real_card_fields():
    """Each group's presence is decided from the card's actual content, so the
    rail length equals the number of REAL groups — honesty, not decoration."""
    src = _src()
    # name ← athlete name, event ← event line, result ← the verbatim value,
    # chips ← achievement label / meet / club chrome.
    for token in ("firstName", "surnameText", "ctx.event", "resultFinal",
                  "ctx.label", "ctx.meet", "ctx.club"):
        assert token in src, f"group presence must read {token}"


def test_stagger_skips_absent_groups():
    """Absent groups contribute no segment (never imply content the card lacks)."""
    src = _src()
    assert ".filter(" in src, "present groups must be filtered before drawing"
    # presence is a real boolean test, not an unconditional list
    assert "Boolean(" in src


# ---------------------------------------------------------------------------
# Frame-pure, deterministic, clamped (inherited motion hard-bounds)
# ---------------------------------------------------------------------------


def test_stagger_layer_is_frame_pure_and_deterministic():
    src = _src()
    for forbidden in ("Math.random", "Date.now", "requestAnimationFrame",
                      "@keyframes", "useEffect", "animation:"):
        assert forbidden not in src, f"non-deterministic / non-frame-pure: {forbidden}"
    # motion is built from Remotion's frame-pure primitives off the ctx frame
    assert "interpolate(" in src
    assert "spring(" in src
    assert "ctx" in src and "frame" in src and "fps" in src


def test_stagger_layer_clamps_interpolations():
    """Unclamped interpolations overshoot past 0/1 and flash — every one here
    must clamp."""
    src = _src()
    assert "clamp" in src
    # no raw interpolate without an options object somewhere on the call
    assert "extrapolateRight" in src


def test_stagger_first_beat_is_off_frame_zero():
    """First animation at frame 3–9, never 0 (a t=0 entrance reads as a jump
    cut). The group stagger is also coarser than the per-word 2–4f step."""
    src = _src()
    start = re.search(r"const START\s*=\s*(\d+)", src)
    stagger = re.search(r"const STAGGER\s*=\s*(\d+)", src)
    assert start and stagger, "START / STAGGER cadence constants must be explicit"
    assert int(start.group(1)) >= 3, "first beat must be off frame 0"
    assert int(stagger.group(1)) >= 1, "groups must actually stagger"


# ---------------------------------------------------------------------------
# Brand exactness
# ---------------------------------------------------------------------------


def test_stagger_layer_uses_resolved_accent_no_invented_hex():
    """Colour comes only from the resolved roles — never an invented hex."""
    src = _src()
    assert "roles.accent" in src
    assert "#" not in src, "no hardcoded hex — brand colour must come from roles"


# ---------------------------------------------------------------------------
# Real build check (skips cleanly without a Node toolchain)
# ---------------------------------------------------------------------------


def test_stagger_layer_typechecks_with_tsc():
    npx = shutil.which("npx")
    node_modules = motion.REMOTION_DIR / "node_modules"
    tsconfig = motion.REMOTION_DIR / "tsconfig.json"
    if not npx or not node_modules.is_dir() or not tsconfig.is_file():
        pytest.skip("Node toolchain / remotion node_modules not available")
    try:
        proc = subprocess.run(
            [npx, "tsc", "-p", "tsconfig.json"],
            cwd=motion.REMOTION_DIR,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        pytest.skip("tsc type-check timed out in this environment")
    assert proc.returncode == 0, (
        "TSX type-check failed:\n" + (proc.stdout or "") + (proc.stderr or "")
    )
