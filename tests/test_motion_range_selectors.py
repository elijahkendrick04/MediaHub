"""Range selectors — the seeded ORDER × SHAPE vocabulary that drives the
per-glyph reveal (the After-Effects Range-Selector analog).

A per-glyph reveal is an ORDER (how glyphs are ranked for staggering: index /
reverse / centre-out / seeded scatter) crossed with a SHAPE (how that ramp is
eased: linear / ease_in / ease_out / ease_in_out). The vocabulary lives in a
pure, frame-pure module (`sprint/rangeSelector.ts`) and is wired into the
per-glyph channel (`motion/compile.ts` `glyphRevealAt`) for the two type-carried
intents. Depends on the per-glyph channel (per-char-text), already committed.

Source-contract tested — the same discipline the rest of the motion suite uses
(no JS runner in the tree). The frame-purity / seed-only-entropy / identity-
default guarantees are asserted against the real module source, and the byte-
identity of the default path is pinned by the shape of `selectorRank`.
"""

from __future__ import annotations

from pathlib import Path

from mediahub.visual import motion

ROOT = Path(__file__).resolve().parent.parent
REMOTION_SRC = ROOT / "src" / "mediahub" / "remotion" / "src"
RANGE_TS = (REMOTION_SRC / "compositions" / "sprint" / "rangeSelector.ts").read_text()
COMPILE_TS = (REMOTION_SRC / "motion" / "compile.ts").read_text()
STORY_TSX = (REMOTION_SRC / "compositions" / "StoryCard.tsx").read_text()
CASCADE_TS = (REMOTION_SRC / "compositions" / "sprint" / "intents" / "cascade.ts").read_text()


# ---------------------------------------------------------------------------
# Module exists and exports the order × shape vocabulary
# ---------------------------------------------------------------------------


def test_range_selector_module_exports_order_and_shape_vocabulary():
    assert 'export type RangeOrder = "index" | "reverse" | "center_out" | "seeded";' in RANGE_TS
    assert 'export type RangeShape = "linear" | "ease_in" | "ease_out" | "ease_in_out";' in RANGE_TS
    # The public surface the channel + tests rely on.
    for fn in (
        "export function orderRank(",
        "export function applyShape(",
        "export function selectorRank(",
        "export function rangeSelectorPhase(",
        "export function selectRangeFor(",
        "export function seededPermutation(",
    ):
        assert fn in RANGE_TS, fn


def test_default_selector_is_index_linear_identity():
    # The identity-ramp guarantee: the DEFAULT pair is {index, linear}.
    assert (
        "export const IDENTITY_SELECTOR: { order: RangeOrder; shape: RangeShape } = {" in RANGE_TS
    )
    assert 'order: "index",' in RANGE_TS
    assert 'shape: "linear",' in RANGE_TS
    # Restraint moods explicitly return the identity selector (stay plain).
    assert "return { ...IDENTITY_SELECTOR };" in RANGE_TS
    assert "/(calm|stoic|precise|minimal|composed|weighty)/" in RANGE_TS


def test_identity_order_returns_raw_index_for_byte_identity():
    # orderRank("index") MUST return the raw index (no clamp / normalize), so the
    # per-glyph channel's identity path is byte-for-byte the plain index ramp.
    assert 'if (order === "index") {' in RANGE_TS
    assert "return index; // raw" in RANGE_TS
    # selectorRank keeps the exact integer rank for a linear shape (no float
    # round-trip that could perturb the identity bytes).
    assert 'if (shape === "linear") {' in RANGE_TS
    assert "return rank;" in RANGE_TS


# ---------------------------------------------------------------------------
# Frame-purity — the only entropy is variationSeed (no wall clock / randomness)
# ---------------------------------------------------------------------------


def test_range_selector_is_frame_pure_no_randomness():
    assert "Math.random(" not in RANGE_TS
    assert "Date.now(" not in RANGE_TS
    assert "new Date(" not in RANGE_TS
    # performance.now() is another wall-clock leak — must not appear either.
    assert "performance.now(" not in RANGE_TS


def test_seeded_permutation_is_driven_by_the_seed():
    # A self-contained xmur3 -> mulberry32 Fisher-Yates permutation; the seed is
    # the sole input, so the shuffle is stable across every render of the frame.
    assert "function xmur3(seed: number): number {" in RANGE_TS
    assert "function mulberry32(a: number): () => number {" in RANGE_TS
    assert "const rand = mulberry32(xmur3(seed));" in RANGE_TS
    # Fisher-Yates swap loop.
    assert "for (let i = arr.length - 1; i > 0; i--) {" in RANGE_TS


def test_shape_uses_remotion_easing():
    assert 'import { Easing } from "remotion";' in RANGE_TS
    assert "Easing.in(Easing.cubic)(x)" in RANGE_TS
    assert "Easing.out(Easing.cubic)(x)" in RANGE_TS
    assert "Easing.inOut(Easing.cubic)(x)" in RANGE_TS


# ---------------------------------------------------------------------------
# Wiring — the per-glyph channel flows through the selector for both intents
# ---------------------------------------------------------------------------


def test_glyph_channel_routes_through_the_range_selector():
    # compile.ts imports + calls the vocabulary; the default selector collapses
    # to the raw index so the identity path stays byte-identical.
    assert (
        'import { selectRangeFor, selectorRank } from "../compositions/sprint/rangeSelector";'
        in COMPILE_TS
    )
    assert "const { order, shape } = selectRangeFor(seed, mood);" in COMPILE_TS
    assert "const rank = selectorRank(i, total, seed, order, shape);" in COMPILE_TS
    assert "Math.min((rank + jitter) * staggerSec * fps, maxStart)" in COMPILE_TS


def test_both_type_intents_thread_total_and_mood_into_the_channel():
    # kinetic_type (StoryCard) and cascade (sprint intent) both feed the glyph's
    # (index, total) + card mood into the shared reveal so the ordering can vary.
    assert "glyphRevealAt(i, total, frame, fps, seed, mood)," in STORY_TSX
    assert "glyphRevealAt(i, total, frame, fps, seed, mood)," in CASCADE_TS


# ---------------------------------------------------------------------------
# Determinism contract — the identity selector reproduces the plain index ramp
# ---------------------------------------------------------------------------


def test_identity_selector_reproduces_plain_index_ramp_contract():
    """Python-level determinism assertion (string/contract): the identity
    selector's rank is the raw glyph index, so `(rank + jitter) * staggerSec *
    fps` is the exact pre-selector expression. This is what keeps a restraint-
    mood glyph card byte-identical to the per-glyph reveal that shipped before
    range-selectors — the sole reason the identity path needs no re-render."""
    # orderRank("index") -> raw index; selectorRank(linear) -> that rank verbatim.
    assert "return index; // raw" in RANGE_TS
    assert "const rank = orderRank(index, total, order, seed);" in RANGE_TS
    # The channel multiplies rank (== index on identity) by the tokenised cadence.
    assert "Math.min((rank + jitter) * staggerSec * fps, maxStart)" in COMPILE_TS


# ---------------------------------------------------------------------------
# Revision bump — a shipping (glyph-opted) intent's output changed
# ---------------------------------------------------------------------------


def test_composition_revisions_bumped_for_range_selectors():
    assert motion.STORY_COMPOSITION_REVISION == "5"
    assert motion.REEL_COMPOSITION_REVISION == "8"
