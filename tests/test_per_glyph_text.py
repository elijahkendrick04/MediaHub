"""Per-glyph text reveal — the type-carried intents (kinetic_type / cascade)
can reveal their headline one CHARACTER at a time, not just one word at a time.

Two halves, mirroring the rest of the motion suite:

* Python shaping — the deterministic seed gate that opts a card into glyph
  granularity is fold-only-when-present, so every other card keeps a
  byte-identical prop dict / cache key. Always exercised (no Node needed).
* TSX / TS source contract — the per-glyph channel, its APCA-clamped reveal
  helper, and the KineticLine / KineticWords glyph branch actually exist and are
  frame-pure (no Math.random / Date.now). The still-parity DOM stays byte-
  identical in word mode. Checked as source (the same discipline
  test_motion_style_pack_parity uses).
"""

from __future__ import annotations

from pathlib import Path

from mediahub.motion import compile_remotion
from mediahub.motion.vocabulary import GLYPH_STAGGER_SEC
from mediahub.visual import motion

ROOT = Path(__file__).resolve().parent.parent
REMOTION_SRC = ROOT / "src" / "mediahub" / "remotion" / "src"
STORY_TSX = (REMOTION_SRC / "compositions" / "StoryCard.tsx").read_text()
CASCADE_TS = (REMOTION_SRC / "compositions" / "sprint" / "intents" / "cascade.ts").read_text()
REGISTRY_TS = (REMOTION_SRC / "compositions" / "sprint" / "registry.ts").read_text()
SCENEKIT_TSX = (REMOTION_SRC / "compositions" / "sprint" / "sceneKit.tsx").read_text()
COMPILE_TS = (REMOTION_SRC / "motion" / "compile.ts").read_text()
REEL_FFMPEG = (ROOT / "src" / "mediahub" / "visual" / "reel_ffmpeg.py").read_text()


def _card(name: str = "Kinetic Person", event: str = "100m Free LC") -> dict:
    return {"achievement": {"swimmer_name": name, "event_name": event}}


# ---------------------------------------------------------------------------
# Python — deterministic seed gate (engine decision, never a director field)
# ---------------------------------------------------------------------------


def test_glyph_gate_fires_for_kinetic_intents_on_odd_seed():
    for intent in ("kinetic_type", "cascade"):
        props = motion._card_to_props(_card(), variation_seed=1, brief={"motion_intent": intent})
        assert props.get("textGranularity") == "glyph", intent


def test_glyph_gate_is_off_on_even_seed():
    for intent in ("kinetic_type", "cascade"):
        props = motion._card_to_props(_card(), variation_seed=2, brief={"motion_intent": intent})
        # fold-only-when-present: the key is simply absent, not "word".
        assert "textGranularity" not in props, intent


def test_glyph_gate_never_fires_for_other_intents():
    # Even the odd-seed that would opt a kinetic card in must not touch a
    # count_up / fade_in / bare card — those keep a byte-identical prop dict.
    for intent in ("count_up", "fade_in", "parallax", ""):
        props = motion._card_to_props(_card(), variation_seed=1, brief={"motion_intent": intent})
        assert "textGranularity" not in props, intent or "<default>"


def test_non_gated_card_dict_is_byte_identical_regression():
    """The whole point of fold-only-when-present: a non-opted-in card's prop
    dict has no glyph key, so its sha256 content hash is unchanged."""
    props = motion._card_to_props(_card(), variation_seed=2, brief={"motion_intent": "count_up"})
    assert "textGranularity" not in props
    # Hashing the dict is stable and identical whether or not the glyph feature
    # exists in the codebase, because the key never enters this dict.
    h1 = motion._content_hash({"card": props}, kind="story")
    h2 = motion._content_hash({"card": dict(props)}, kind="story")
    assert h1 == h2


# ---------------------------------------------------------------------------
# Python — explainability axes + honest FFmpeg fallback
# ---------------------------------------------------------------------------


def test_manifest_axes_default_word_and_reflect_glyph():
    plain = motion._card_manifest_axes(motion._card_to_props(_card(), variation_seed=2))
    assert plain["text_granularity"] == "word"
    glyph_props = motion._card_to_props(
        _card(), variation_seed=1, brief={"motion_intent": "kinetic_type"}
    )
    assert motion._card_manifest_axes(glyph_props)["text_granularity"] == "glyph"


def test_ffmpeg_manifests_declare_per_glyph_unsupported():
    # Both the story and the reel FFmpeg manifests degrade honestly.
    assert REEL_FFMPEG.count('"text_granularity": "per-glyph-unsupported-on-engine"') == 2


def test_revisions_bumped_for_shared_kineticline_change():
    # Bumped again by range-selectors (glyph reveal ORDER × SHAPE now varies).
    assert motion.STORY_COMPOSITION_REVISION == "5"
    assert motion.REEL_COMPOSITION_REVISION == "8"


# ---------------------------------------------------------------------------
# Token bundle — the glyph cadence is tokenised (single source of truth)
# ---------------------------------------------------------------------------


def test_token_bundle_exposes_glyph_stagger():
    bundle = compile_remotion.token_bundle()
    assert bundle["text"]["glyphStaggerSec"] == round(GLYPH_STAGGER_SEC, 6)
    ts = compile_remotion.export_ts()
    assert "text: { glyphStaggerSec: number };" in ts
    assert '"glyphStaggerSec"' in ts


# ---------------------------------------------------------------------------
# TSX / TS source contract
# ---------------------------------------------------------------------------


def test_animchannels_has_required_glyph_channel():
    assert "glyphAt: (index: number, total: number) => { y: number; opacity: number };" in STORY_TSX
    # base + static both set the identity glyph so every intent inherits it.
    assert STORY_TSX.count("glyphAt: identityGlyph") == 2
    assert "const identityGlyph = () => ({ y: 0, opacity: 1 });" in STORY_TSX


def test_kinetic_type_drives_the_glyph_channel():
    assert "glyphRevealAt(i, total, frame, fps, seed, mood)," in STORY_TSX


def test_kineticline_word_mode_preserved_and_glyph_branch_added():
    # Word mode keeps the exact per-word span (kernNumeric + 0.28em gap).
    assert "{kernNumeric(w)}" in STORY_TSX
    # Glyph branch: per-word wrapper kept, characters split onto glyphAt.
    assert "if (perGlyph) {" in STORY_TSX
    assert "const a = anim.glyphAt(base + ci, lineTotal);" in STORY_TSX
    # All six call sites thread the flag from the card.
    assert STORY_TSX.count('perGlyph={ctx.card.textGranularity === "glyph"}') == 6


def test_scenekit_kineticwords_mirrors_glyph_split():
    assert 'ctx.card.textGranularity === "glyph"' in SCENEKIT_TSX
    assert "const a = ctx.anim.glyphAt(base + ci, lineTotal);" in SCENEKIT_TSX


def test_intentprogram_threads_seed_and_dispatch_passes_it():
    # The corrected shared-type change: cascade could not read the seed before.
    assert "seed?: number," in REGISTRY_TS
    assert "extra(frame, fps, durationInFrames, mood, base, stagger, seed)" in STORY_TSX
    assert "seed = 0," in CASCADE_TS
    assert "glyphRevealAt(i, total, frame, fps, seed, mood)," in CASCADE_TS


def test_glyph_reveal_helper_is_frame_pure_and_apca_clamped():
    # Frame-pure: seeded integer mix, never Math.random / Date.now (the call
    # forms — the explanatory comment names them, so match the invocation).
    assert "Math.random(" not in COMPILE_TS
    assert "Date.now(" not in COMPILE_TS
    assert "new Date(" not in COMPILE_TS
    # Reads the tokenised cadence, never a hard-coded constant.
    assert "MOTION_TOKENS.text.glyphStaggerSec" in COMPILE_TS
    # APCA-safety: the per-glyph start is CLAMPED so the last glyph resolves
    # within the absolute budget regardless of glyph count.
    assert "GLYPH_BUDGET_SEC" in COMPILE_TS
    assert "const maxStart = Math.max(0, fps * GLYPH_BUDGET_SEC - revealFrames);" in COMPILE_TS
    assert "Math.min((rank + jitter) * staggerSec * fps, maxStart)" in COMPILE_TS
